from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .experience import ExperienceRecord, ExperienceStatus, SQLiteExperienceStore, TrustClass
from .experience_compiler import ExperienceCompiler
from .experience_portability import (
    export_experience_bundle,
    import_experience_bundle,
)
from .experience_runtime import (
    AgentEventKind,
    AgentExperienceEvent,
    AgentExperienceRuntime,
    OutcomeVerification,
    VerificationSource,
)
from .memory_firewall import FirewallContext, MemoryFirewall, MemoryFirewallPolicy


WORKSPACE_IDENTITY_SCHEMA = "wavemind.workspace_identity.v1"
WORKSPACE_CONFIG_SCHEMA = "wavemind.workspace_config.v1"
WORKSPACE_BUNDLE_SCHEMA = "wavemind.workspace_experience_bundle.v1"
WORKSPACE_RUNBOOK_SCHEMA = "wavemind.workspace_runbook.v1"
WORKSPACE_PACKET_SCHEMA = "wavemind.workspace_experience_packet.v1"

_SLUG_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_PRIVATE_PARTS = {".codex", ".claude", "claude"}
_ATTACHMENT_CONTENT_LIMIT_BYTES = 256 * 1024


@dataclass(frozen=True)
class WorkspaceIdentity:
    workspace_id: str
    tenant_id: str
    user_id: str
    project_root: str
    project_fingerprint: str
    fingerprint_source: dict[str, Any]
    namespace: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema": WORKSPACE_IDENTITY_SCHEMA, **asdict(self)}


@dataclass(frozen=True)
class WorkspaceConfig:
    identity: WorkspaceIdentity
    config_path: str
    memory_db_path: str
    experience_db_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": WORKSPACE_CONFIG_SCHEMA,
            "identity": self.identity.as_dict(),
            "config_path": self.config_path,
            "memory_db_path": self.memory_db_path,
            "experience_db_path": self.experience_db_path,
        }


@dataclass(frozen=True)
class WorkspaceEvent:
    id: str
    run_id: str
    kind: AgentEventKind
    sequence: int
    payload: dict[str, Any]
    session_id: str | None = None
    task_id: str | None = None
    parent_event_id: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    occurred_at: float | None = None

    def to_runtime_event(self, identity: WorkspaceIdentity) -> AgentExperienceEvent:
        return AgentExperienceEvent(
            id=self.id,
            namespace=identity.namespace,
            run_id=self.run_id,
            session_id=self.session_id,
            task_id=self.task_id,
            kind=self.kind,
            sequence=self.sequence,
            occurred_at=float(self.occurred_at if self.occurred_at is not None else time.time()),
            parent_event_id=self.parent_event_id,
            tool_name=self.tool_name,
            duration_ms=self.duration_ms,
            payload=_normalize_workspace_payload(self.payload, Path(identity.project_root)),
        )


class WorkspacePathError(ValueError):
    pass


def resolve_workspace_identity(
    root: str | Path,
    *,
    workspace_id: str,
    tenant_id: str = "local",
    user_id: str = "local",
    allow_private_root: bool = False,
) -> WorkspaceIdentity:
    if not str(workspace_id or "").strip():
        raise ValueError("workspace_id must not be empty")
    project_root = _safe_project_root(root, allow_private_root=allow_private_root)
    fingerprint_source = _project_fingerprint_source(project_root)
    project_fingerprint = _sha256(fingerprint_source)
    namespace = ":".join(
        (
            "workspace",
            _slug(tenant_id),
            _slug(user_id),
            _slug(workspace_id),
            project_fingerprint[:16],
        )
    )
    return WorkspaceIdentity(
        workspace_id=str(workspace_id),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        project_root=str(project_root),
        project_fingerprint=project_fingerprint,
        fingerprint_source=fingerprint_source,
        namespace=namespace,
    )


def initialize_workspace(
    root: str | Path,
    *,
    workspace_id: str,
    tenant_id: str = "local",
    user_id: str = "local",
    force: bool = False,
    allow_private_root: bool = False,
) -> WorkspaceConfig:
    identity = resolve_workspace_identity(
        root,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        allow_private_root=allow_private_root,
    )
    project_root = Path(identity.project_root)
    state_dir = project_root / ".wavemind"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "workspace.json"
    if config_path.exists() and not force:
        return load_workspace_config(config_path)
    config = WorkspaceConfig(
        identity=identity,
        config_path=str(config_path),
        memory_db_path=str(state_dir / "wavemind.sqlite3"),
        experience_db_path=str(state_dir / "experience.sqlite3"),
    )
    config_path.write_text(
        json.dumps(config.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return config


def load_workspace_config(
    path_or_root: str | Path,
    *,
    allow_private_root: bool = False,
) -> WorkspaceConfig:
    config_path = _resolve_workspace_config_path(
        path_or_root,
        allow_private_root=allow_private_root,
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("schema") != WORKSPACE_CONFIG_SCHEMA:
        raise ValueError("unsupported workspace config schema")
    identity_payload = dict(payload.get("identity") or {})
    if identity_payload.get("schema") != WORKSPACE_IDENTITY_SCHEMA:
        raise ValueError("unsupported workspace identity schema")
    identity_payload.pop("schema", None)
    return WorkspaceConfig(
        identity=WorkspaceIdentity(**identity_payload),
        config_path=str(config_path),
        memory_db_path=str(payload["memory_db_path"]),
        experience_db_path=str(payload["experience_db_path"]),
    )


class WorkspaceExperienceManager:
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.identity = config.identity
        self.store = SQLiteExperienceStore(config.experience_db_path)
        self.compiler = ExperienceCompiler(
            self.store,
            MemoryFirewall(
                MemoryFirewallPolicy(
                    namespace=self.identity.namespace,
                    policy_id="workspace-experience",
                    require_consent_for_user_data=False,
                )
            ),
        )
        self.runtime = AgentExperienceRuntime(self.compiler)

    @classmethod
    def open(cls, path_or_root: str | Path) -> "WorkspaceExperienceManager":
        return cls(load_workspace_config(path_or_root))

    def close(self) -> None:
        self.store.close()

    def start_run(
        self,
        *,
        query: str,
        objective: str,
        domain: str = "workspace",
        task_type: str = "task",
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        tools: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        token_budget: int = 400,
        top_k: int = 3,
        canary: bool = False,
    ) -> dict[str, Any]:
        if run_id:
            existing_events = self.runtime.events(
                namespace=self.identity.namespace,
                run_id=run_id,
            )
            if existing_events:
                first = existing_events[0]
                run_started = next(
                    (
                        event
                        for event in existing_events
                        if event.kind is AgentEventKind.RUN_STARTED
                    ),
                    None,
                )
                task_started = next(
                    (
                        event
                        for event in existing_events
                        if event.kind is AgentEventKind.TASK_STARTED
                    ),
                    None,
                )
                same_request = (
                    run_started is not None
                    and task_started is not None
                    and (session_id is None or first.session_id == session_id)
                    and (task_id is None or first.task_id == task_id)
                    and run_started.payload.get("objective") == objective
                    and task_started.payload.get("domain") == domain
                    and task_started.payload.get("task_type") == task_type
                )
                if not same_request:
                    raise ValueError("run_id already exists with a different payload")
                decision = next(
                    (
                        item
                        for item in self.runtime.injection_decisions(
                            namespace=self.identity.namespace,
                            limit=1000,
                        )
                        if item.get("run_id") == run_id
                    ),
                    {
                        "inject": False,
                        "reason": "no_applicable_verified_experience",
                        "confidence": None,
                        "packet": None,
                        "source_tool_result_refs": [],
                    },
                )
                applied = [
                    str(item["experience_id"])
                    for item in (decision.get("packet") or {}).get("items", [])
                    if isinstance(item, dict) and item.get("experience_id")
                ]
                return {
                    "schema": "wavemind.workspace_run.v1",
                    "identity": self.identity.as_dict(),
                    "run_id": run_id,
                    "session_id": first.session_id,
                    "task_id": first.task_id,
                    "namespace": self.identity.namespace,
                    "intervention": decision,
                    "applied_experience_ids": applied,
                    "next_sequence": self.runtime.next_sequence(
                        namespace=self.identity.namespace,
                        run_id=run_id,
                    ),
                    "idempotent_replay": True,
                }
        intervention = self.runtime.decide(
            query,
            namespace=self.identity.namespace,
            run_id=run_id,
            task_id=task_id,
            domains=(domain,),
            task_types=(task_type,),
            tools=tuple(tools),
            token_budget=token_budget,
            top_k=top_k,
            canary=canary,
        )
        applied = (
            tuple(item.experience_id for item in intervention.packet.items)
            if intervention.inject and intervention.packet is not None
            else ()
        )
        handle = self.runtime.begin_run(
            namespace=self.identity.namespace,
            objective=objective,
            domain=domain,
            task_type=task_type,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            metadata={
                "workspace_identity": self.identity.as_dict(),
                "declared_tools": list(dict.fromkeys(str(tool) for tool in tools)),
                **dict(metadata or {}),
            },
            applied_experience_ids=applied,
        )
        return {
            "schema": "wavemind.workspace_run.v1",
            "identity": self.identity.as_dict(),
            "run_id": handle.run_id,
            "session_id": handle.session_id,
            "task_id": handle.task_id,
            "namespace": self.identity.namespace,
            "intervention": intervention.as_dict(),
            "applied_experience_ids": list(applied),
            "next_sequence": self.runtime.next_sequence(
                namespace=self.identity.namespace,
                run_id=handle.run_id,
            ),
            "idempotent_replay": False,
        }

    def capture_event(self, event: WorkspaceEvent) -> dict[str, Any]:
        prepared = event
        if prepared.occurred_at is None:
            existing_time = next(
                (
                    stored.occurred_at
                    for stored in self.runtime.events(
                        namespace=self.identity.namespace,
                        run_id=prepared.run_id,
                    )
                    if stored.id == prepared.id
                ),
                None,
            )
            if existing_time is not None:
                prepared = WorkspaceEvent(
                    id=prepared.id,
                    run_id=prepared.run_id,
                    kind=prepared.kind,
                    sequence=prepared.sequence,
                    payload=prepared.payload,
                    session_id=prepared.session_id,
                    task_id=prepared.task_id,
                    parent_event_id=prepared.parent_event_id,
                    tool_name=prepared.tool_name,
                    duration_ms=prepared.duration_ms,
                    occurred_at=existing_time,
                )
        result = self.runtime.capture(prepared.to_runtime_event(self.identity))
        return {"inserted": result.inserted, "event": result.event.as_dict()}

    def verify_run(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: VerificationSource | str,
        verifier: str,
        success: bool,
        score: float | None = None,
        reference: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        applied_experience_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        verification = OutcomeVerification(
            evidence_id=evidence_id,
            source=VerificationSource(source),
            verifier=verifier,
            success=success,
            score=score,
            reference=reference,
            metadata=dict(metadata or {}),
        )
        return self.runtime.finalize_external_run(
            namespace=self.identity.namespace,
            run_id=run_id,
            verification=verification,
            applied_experience_ids=applied_experience_ids,
        ).as_dict()

    def cancel_run(
        self,
        *,
        run_id: str,
        evidence_id: str,
        verifier: str = "operator",
        reason: str = "cancelled",
    ) -> dict[str, Any]:
        events = self.runtime.events(namespace=self.identity.namespace, run_id=run_id)
        if not events:
            raise KeyError(run_id)
        self.capture_event(
            WorkspaceEvent(
                id=f"{run_id}:cancelled",
                run_id=run_id,
                session_id=events[-1].session_id,
                task_id=events[-1].task_id,
                kind=AgentEventKind.ERROR,
                sequence=self.runtime.next_sequence(
                    namespace=self.identity.namespace,
                    run_id=run_id,
                ),
                payload={
                    "message": reason,
                    "error_code": "run_cancelled",
                    "cancelled": True,
                },
            )
        )
        return self.verify_run(
            run_id=run_id,
            evidence_id=evidence_id,
            source=VerificationSource.OPERATOR,
            verifier=verifier,
            success=False,
            score=0.0,
            metadata={"cancelled": True, "reason": reason},
        )

    def packet(
        self,
        query: str,
        *,
        domain: str = "workspace",
        task_type: str = "task",
        tools: Sequence[str] = (),
        token_budget: int = 400,
        top_k: int = 3,
    ) -> dict[str, Any]:
        decision = self.runtime.decide(
            query,
            namespace=self.identity.namespace,
            domains=(domain,),
            task_types=(task_type,),
            tools=tuple(tools),
            token_budget=token_budget,
            top_k=top_k,
        )
        excluded = self._excluded_experience(query)
        return {
            "schema": WORKSPACE_PACKET_SCHEMA,
            "identity": self.identity.as_dict(),
            "namespace": self.identity.namespace,
            "query": query,
            "abstain": not decision.inject,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "packet": decision.packet.as_dict() if decision.packet else None,
            "selected_citations": (
                list(decision.packet.citations)
                if decision.packet is not None and decision.inject
                else []
            ),
            "excluded": excluded,
        }

    def review_queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        records: list[ExperienceRecord] = []
        for status in (ExperienceStatus.SHADOW, ExperienceStatus.CANARY):
            records.extend(
                self.store.list(
                    namespace=self.identity.namespace,
                    status=status,
                    include_expired=True,
                    limit=limit,
                )
            )
        return [
            {
                "experience": record.as_dict(),
                "runbook": runbook_from_experience(
                    record,
                    evidence_count=self.store.candidate_validation_summary(
                        record.id
                    ).validation_count,
                ),
                "diff": self.semantic_diff(record),
            }
            for record in records[:limit]
        ]

    def approve(self, experience_id: str, *, evidence_id: str, score: float = 1.0) -> str:
        return self.runtime.approve(
            experience_id,
            namespace=self.identity.namespace,
            evidence_id=evidence_id,
            score=score,
        )

    def edit_and_approve(
        self,
        experience_id: str,
        *,
        evidence_id: str,
        title: str | None = None,
        content: str | None = None,
        reason: str = "operator edited and approved",
        score: float = 1.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.store.get(experience_id)
        if current is None:
            raise KeyError(experience_id)
        edited_payload = {
            "source_id": experience_id,
            "title": title if title is not None else current.title,
            "content": content if content is not None else current.content,
            "metadata": dict(metadata or {}),
        }
        edited_id = f"exp_edit_{_sha256(edited_payload)[:24]}"
        replacement = replace(
            current,
            id=edited_id,
            title=edited_payload["title"],
            content=edited_payload["content"],
            trust=TrustClass.VERIFIED_OPERATOR,
            status=ExperienceStatus.CANARY,
            metadata={
                **dict(current.metadata),
                "operator_edit": True,
                "edit_reason": reason,
                **edited_payload["metadata"],
            },
        )
        promoted = self.store.supersede(experience_id, replacement, reason=reason)
        status = self.approve(promoted.id, evidence_id=evidence_id, score=score)
        refreshed = self.store.get(promoted.id)
        return {
            "schema": "wavemind.workspace_edit_approval.v1",
            "source_experience_id": experience_id,
            "experience_id": promoted.id,
            "status": status,
            "experience": refreshed.as_dict() if refreshed else promoted.as_dict(),
            "runbook": runbook_from_experience(
                refreshed or promoted,
                evidence_count=self.store.candidate_validation_summary(
                    promoted.id
                ).validation_count,
            ),
        }

    def reject(self, experience_id: str, *, reason: str) -> dict[str, Any]:
        return self.runtime.reject(
            experience_id,
            namespace=self.identity.namespace,
            reason=reason,
        ).as_dict()

    def rollback(self, experience_id: str, *, reason: str) -> dict[str, Any]:
        return self.runtime.rollback(
            experience_id,
            namespace=self.identity.namespace,
            reason=reason,
        ).as_dict()

    def protected_delete(
        self,
        experience_id: str,
        *,
        reason: str,
        confirmation: str,
    ) -> bool:
        expected = f"delete:{experience_id}"
        if confirmation != expected:
            raise ValueError(f"protected deletion requires confirmation {expected!r}")
        return self.compiler.delete(
            experience_id,
            reason=reason,
            context=FirewallContext(
                namespace=self.identity.namespace,
                actor="operator",
                actor_trust=TrustClass.VERIFIED_OPERATOR,
                operator_override=True,
                consent_token="operator-approved",
            ),
        )

    def export_bundle(self) -> dict[str, Any]:
        payload = {
            "schema": WORKSPACE_BUNDLE_SCHEMA,
            "identity": self.identity.as_dict(),
            "experience_bundle": export_experience_bundle(
                self.store,
                namespace=self.identity.namespace,
            ),
        }
        payload["content_sha256"] = _sha256(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        return payload

    def import_bundle(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if payload.get("schema") != WORKSPACE_BUNDLE_SCHEMA:
            raise ValueError("unsupported workspace experience bundle schema")
        expected = str(payload.get("content_sha256") or "")
        actual = _sha256({key: value for key, value in payload.items() if key != "content_sha256"})
        if expected != actual:
            raise ValueError("workspace experience bundle checksum mismatch")
        identity = dict(payload.get("identity") or {})
        if identity.get("namespace") != self.identity.namespace:
            raise ValueError("workspace bundle namespace does not match this workspace")
        report = import_experience_bundle(self.store, payload["experience_bundle"])
        return {
            "schema": "wavemind.workspace_experience_import.v1",
            "identity": self.identity.as_dict(),
            "parity": report.parity,
            "record_count": report.record_count,
            "trajectory_count": report.trajectory_count,
            "validation_count": report.validation_count,
            "inserted_records": report.inserted_records,
            "inserted_trajectories": report.inserted_trajectories,
        }

    def semantic_diff(self, record: ExperienceRecord) -> str:
        active = self.store.list(
            namespace=self.identity.namespace,
            kind=record.kind,
            status=ExperienceStatus.ACTIVE,
            limit=100,
        )
        comparable = next(
            (
                item
                for item in active
                if item.id != record.id
                and set(item.applicability.task_types)
                == set(record.applicability.task_types)
            ),
            None,
        )
        before = (comparable.content if comparable else "").splitlines()
        after = record.content.splitlines()
        return "\n".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=comparable.id if comparable else "empty",
                tofile=record.id,
                lineterm="",
            )
        )

    def _excluded_experience(self, query: str) -> list[dict[str, Any]]:
        tokens = set(_tokenize(query))
        excluded = []
        for status in (
            ExperienceStatus.SHADOW,
            ExperienceStatus.CANARY,
            ExperienceStatus.REJECTED,
            ExperienceStatus.SUPERSEDED,
            ExperienceStatus.ROLLED_BACK,
            ExperienceStatus.EXPIRED,
        ):
            for record in self.store.list(
                namespace=self.identity.namespace,
                status=status,
                include_expired=True,
                limit=100,
            ):
                overlap = sorted(tokens & set(_tokenize(f"{record.title} {record.content}")))
                if overlap or status in {ExperienceStatus.SHADOW, ExperienceStatus.CANARY}:
                    excluded.append(
                        {
                            "experience_id": record.id,
                            "status": record.status.value,
                            "reason": (
                                "not_active_verified_experience"
                                if record.status in {ExperienceStatus.SHADOW, ExperienceStatus.CANARY}
                                else f"status_{record.status.value}"
                            ),
                            "overlap": overlap,
                        }
                    )
        return excluded


def runbook_from_experience(
    record: ExperienceRecord,
    *,
    evidence_count: int = 0,
) -> dict[str, Any]:
    metadata = dict(record.metadata)
    tool_plan = metadata.get("tool_plan") or list(record.applicability.tools)
    error_codes = metadata.get("error_codes") or []
    return {
        "schema": WORKSPACE_RUNBOOK_SCHEMA,
        "id": record.id,
        "version": record.version,
        "kind": record.kind.value,
        "status": record.status.value,
        "title": record.title,
        "scope": {"namespace": record.namespace},
        "preconditions": record.applicability.as_dict(),
        "actions": list(tool_plan),
        "expected_verifiable_result": record.outcome.as_dict(),
        "failure_symptoms": list(error_codes),
        "applicability": record.applicability.as_dict(),
        "expires_at": record.expires_at,
        "confidence": record.confidence,
        "evidence_count": int(evidence_count),
        "source_trajectory_ids": (
            [record.trajectory.trajectory_id] if record.trajectory else []
        ),
        "provenance": {
            "source": record.source.as_dict(),
            "trajectory": record.trajectory.as_dict() if record.trajectory else None,
            "content_sha256": record.content_sha256,
        },
        "supersedes_id": record.supersedes_id,
        "rollback_of_id": record.rollback_of_id,
    }


def render_runbook_markdown(runbook: Mapping[str, Any]) -> str:
    lines = [
        f"# {runbook.get('title')}",
        "",
        f"- Kind: `{runbook.get('kind')}`",
        f"- Status: `{runbook.get('status')}`",
        f"- Confidence: `{runbook.get('confidence')}`",
        f"- Evidence count: `{runbook.get('evidence_count')}`",
        "",
        "## Preconditions",
        "```json",
        json.dumps(runbook.get("preconditions") or {}, ensure_ascii=False, sort_keys=True, indent=2),
        "```",
        "",
        "## Actions",
    ]
    actions = runbook.get("actions") or []
    if actions:
        lines.extend(f"- `{action}`" for action in actions)
    else:
        lines.append("- No command sequence recorded.")
    lines.extend(
        [
            "",
            "## Expected Result",
            "```json",
            json.dumps(
                runbook.get("expected_verifiable_result") or {},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            "```",
            "",
            "## Provenance",
            "```json",
            json.dumps(runbook.get("provenance") or {}, ensure_ascii=False, sort_keys=True, indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def workspace_mcp_config(config: WorkspaceConfig) -> dict[str, Any]:
    return {
        "mcpServers": {
            "wavemind-workspace": {
                "command": "wavemind-mcp",
                "args": ["--db", config.memory_db_path],
                "env": {
                    "WAVEMIND_EXPERIENCE_DB": config.experience_db_path,
                    "WAVEMIND_WORKSPACE_NAMESPACE": config.identity.namespace,
                },
            }
        }
    }


def _safe_project_root(root: str | Path, *, allow_private_root: bool) -> Path:
    project_root = Path(root).expanduser().resolve()
    if not project_root.exists():
        raise FileNotFoundError(project_root)
    lowered_parts = {part.lower() for part in project_root.parts}
    if not allow_private_root and lowered_parts & _PRIVATE_PARTS:
        raise WorkspacePathError(
            "workspace root points at a private agent history directory; "
            "pass allow_private_root only for explicit imports"
        )
    return project_root


def _resolve_workspace_config_path(
    path_or_root: str | Path,
    *,
    allow_private_root: bool,
) -> Path:
    raw = Path(path_or_root).expanduser()
    if raw.name == "workspace.json" and raw.parent.name == ".wavemind":
        config_path = raw.resolve()
        project_root = config_path.parent.parent
    elif raw.exists() and raw.is_file():
        raise WorkspacePathError("workspace config must be .wavemind/workspace.json")
    else:
        project_root = _safe_project_root(raw, allow_private_root=allow_private_root)
        config_path = project_root / ".wavemind" / "workspace.json"
    project_root = _safe_project_root(project_root, allow_private_root=allow_private_root)
    state_dir = project_root / ".wavemind"
    config_path = config_path.resolve()
    if config_path.name != "workspace.json" or config_path.parent != state_dir:
        raise WorkspacePathError("workspace config must be .wavemind/workspace.json")
    if not _is_relative_to(config_path, project_root):
        raise WorkspacePathError("workspace config escapes workspace root")
    return config_path


def _normalize_workspace_payload(payload: Mapping[str, Any], project_root: Path) -> dict[str, Any]:
    selected = dict(payload)
    attachments = selected.get("attachments")
    if attachments is None:
        return selected
    if not isinstance(attachments, list):
        raise ValueError("attachments must be an array")
    normalized = []
    root = project_root.resolve()
    for index, raw in enumerate(attachments):
        if not isinstance(raw, Mapping):
            raise ValueError("attachments entries must be objects")
        label = str(raw.get("label") or raw.get("name") or f"attachment-{index}")
        if raw.get("path") is not None:
            raw_path = Path(str(raw["path"]))
            path = raw_path if raw_path.is_absolute() else root / raw_path
            resolved = path.resolve()
            if not _is_relative_to(resolved, root):
                raise WorkspacePathError("attachment path escapes workspace root")
            if any(part.lower() in _PRIVATE_PARTS for part in resolved.parts):
                raise WorkspacePathError("attachment path targets a private assistant directory")
            data = resolved.read_bytes()
            normalized.append(
                {
                    "label": label,
                    "source": "file",
                    "path": resolved.relative_to(root).as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            continue
        if raw.get("content") is not None:
            data = (
                raw["content"].encode("utf-8")
                if isinstance(raw["content"], str)
                else json.dumps(raw["content"], sort_keys=True).encode("utf-8")
            )
            if len(data) > _ATTACHMENT_CONTENT_LIMIT_BYTES:
                raise ValueError("attachment content exceeds workspace event limit")
            normalized.append(
                {
                    "label": label,
                    "source": "inline",
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            continue
        raise ValueError("attachment requires path or content")
    selected["attachments"] = normalized
    return selected


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _project_fingerprint_source(root: Path) -> dict[str, Any]:
    git_root = _git(root, "rev-parse", "--show-toplevel")
    if git_root:
        git_root_path = Path(git_root).resolve()
        remote = _normalize_remote(_git(git_root_path, "config", "--get", "remote.origin.url") or "")
        first_commit = _git(git_root_path, "rev-list", "--max-parents=0", "HEAD") or ""
        return {
            "kind": "git",
            "remote_origin": remote,
            "first_commit": first_commit,
        }
    markers = []
    for name in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", ".git"):
        if (root / name).exists():
            markers.append(name)
    return {
        "kind": "directory",
        "root_name": root.name,
        "markers": markers,
    }


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _normalize_remote(remote: str) -> str:
    value = remote.strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        value = f"https://{host}/{path}"
    return value.lower()


def _slug(value: str) -> str:
    normalized = _SLUG_RE.sub("-", str(value).strip())
    normalized = normalized.strip("-._:")
    if not normalized:
        raise ValueError("workspace namespace parts must not be empty")
    return normalized[:96]


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_:-]+", text.lower())
