from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

from .experience import (
    ExperienceApplicability,
    ExperienceKind,
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    ToolTrajectory,
    TrajectoryProvenance,
    TrajectoryStep,
    TrajectoryStepKind,
    TrustClass,
)
from .experience_compiler import ExperienceCompiler, ExperiencePacket
from .memory_firewall import FirewallContext


RUNTIME_EVENT_SCHEMA = "wavemind.agent_experience_event.v1"
RUNTIME_PACKET_SCHEMA = "wavemind.runtime_experience_packet.v1"


class AgentEventKind(str, Enum):
    SESSION_STARTED = "session.started"
    SESSION_FINISHED = "session.finished"
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    TASK_STARTED = "task.started"
    TASK_FINISHED = "task.finished"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    ERROR = "error"
    OUTCOME = "outcome"


class VerificationSource(str, Enum):
    TEST = "test"
    TOOL = "tool"
    ENVIRONMENT = "environment"
    OPERATOR = "operator"


@dataclass(frozen=True)
class AgentExperienceRuntimePolicy:
    max_payload_bytes: int = 64 * 1024
    max_events_per_run: int = 10_000
    intervention_score_threshold: float = 0.50
    default_packet_tokens: int = 400
    default_packet_items: int = 3
    secret_keys: tuple[str, ...] = (
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
    )

    def __post_init__(self) -> None:
        if self.max_payload_bytes < 1024:
            raise ValueError("max_payload_bytes must be at least 1024")
        if self.max_events_per_run < 8:
            raise ValueError("max_events_per_run must be at least 8")
        if not 0.0 <= self.intervention_score_threshold <= 1.0:
            raise ValueError("intervention_score_threshold must be in [0, 1]")
        if self.default_packet_tokens < 32:
            raise ValueError("default_packet_tokens must be at least 32")
        if self.default_packet_items < 1:
            raise ValueError("default_packet_items must be positive")


@dataclass(frozen=True)
class AgentExperienceEvent:
    id: str
    namespace: str
    run_id: str
    kind: AgentEventKind
    sequence: int
    occurred_at: float
    session_id: str | None = None
    task_id: str | None = None
    parent_event_id: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("event id", self.id),
            ("namespace", self.namespace),
            ("run id", self.run_id),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} must not be empty")
        object.__setattr__(self, "kind", AgentEventKind(self.kind))
        if int(self.sequence) < 0:
            raise ValueError("event sequence must be non-negative")
        if self.duration_ms is not None and float(self.duration_ms) < 0.0:
            raise ValueError("event duration_ms must be non-negative")
        _json(self.payload)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_EVENT_SCHEMA,
            "id": self.id,
            "namespace": self.namespace,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "kind": self.kind.value,
            "sequence": int(self.sequence),
            "occurred_at": float(self.occurred_at),
            "parent_event_id": self.parent_event_id,
            "tool_name": self.tool_name,
            "duration_ms": self.duration_ms,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class OutcomeVerification:
    evidence_id: str
    source: VerificationSource
    verifier: str
    success: bool
    score: float | None = None
    reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    verified_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("verification evidence_id must not be empty")
        if not self.verifier.strip():
            raise ValueError("verification verifier must not be empty")
        object.__setattr__(self, "source", VerificationSource(self.source))
        if self.score is not None and not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("verification score must be in [0, 1]")
        if bool(self.metadata.get("llm_self_assessed")):
            raise ValueError("LLM self-assessment is not valid outcome evidence")
        _json(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source"] = self.source.value
        return payload


@dataclass(frozen=True)
class VerificationContext:
    namespace: str
    run_id: str
    session_id: str | None
    task_id: str | None
    events: tuple[AgentExperienceEvent, ...]


class OutcomeVerifier(Protocol):
    def verify(self, context: VerificationContext) -> OutcomeVerification: ...


@dataclass(frozen=True)
class CallableOutcomeVerifier:
    source: VerificationSource
    verifier: str
    callback: Callable[[VerificationContext], bool | tuple[bool, float | None]]
    reference: str | None = None

    def verify(self, context: VerificationContext) -> OutcomeVerification:
        result = self.callback(context)
        if isinstance(result, tuple):
            success, score = bool(result[0]), result[1]
        else:
            success, score = bool(result), None
        digest = hashlib.sha256(
            f"{context.namespace}\0{context.run_id}\0{self.source.value}\0{self.verifier}".encode()
        ).hexdigest()[:24]
        return OutcomeVerification(
            evidence_id=f"verify_{digest}",
            source=self.source,
            verifier=self.verifier,
            success=success,
            score=score,
            reference=self.reference,
        )


@dataclass(frozen=True)
class EventCaptureResult:
    event: AgentExperienceEvent
    inserted: bool


@dataclass(frozen=True)
class ExperienceIntervention:
    inject: bool
    reason: str
    confidence: float
    packet: ExperiencePacket | None
    source_tool_result_refs: tuple[str, ...]
    decision_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_PACKET_SCHEMA,
            "inject": self.inject,
            "reason": self.reason,
            "confidence": self.confidence,
            "packet": self.packet.as_dict() if self.packet else None,
            "source_tool_result_refs": list(self.source_tool_result_refs),
            "decision_id": self.decision_id,
        }


@dataclass(frozen=True)
class RunFinalization:
    run_id: str
    trajectory_id: str
    verification: OutcomeVerification | None
    candidate_ids: tuple[str, ...]
    candidate_statuses: dict[str, str]
    applied_experience_ids: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.verification is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trajectory_id": self.trajectory_id,
            "verified": self.verified,
            "verification": self.verification.as_dict() if self.verification else None,
            "candidate_ids": list(self.candidate_ids),
            "candidate_statuses": dict(self.candidate_statuses),
            "applied_experience_ids": list(self.applied_experience_ids),
        }


class AgentExperienceRuntime:
    """Evidence-gated runtime for capturing, learning, and injecting experience."""

    def __init__(
        self,
        compiler: ExperienceCompiler,
        *,
        policy: AgentExperienceRuntimePolicy | None = None,
    ) -> None:
        self.compiler = compiler
        self.store = compiler.store
        self.policy = policy or AgentExperienceRuntimePolicy()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.store._lock, self.store.conn:
            self.store.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_experience_events (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    session_id TEXT,
                    task_id TEXT,
                    kind TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    occurred_at REAL NOT NULL,
                    parent_event_id TEXT,
                    tool_name TEXT,
                    duration_ms REAL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(namespace, run_id, sequence)
                )
                """
            )
            self.store.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_experience_verifications (
                    evidence_id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    task_id TEXT,
                    source TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    successful INTEGER NOT NULL,
                    score REAL,
                    reference TEXT,
                    metadata_json TEXT NOT NULL,
                    verified_at REAL NOT NULL,
                    payload_sha256 TEXT NOT NULL
                )
                """
            )
            self.store.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_experience_injections (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    run_id TEXT,
                    task_id TEXT,
                    query_text TEXT NOT NULL,
                    inject INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    packet_json TEXT,
                    source_refs_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            self.store.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_events_run "
                "ON agent_experience_events(namespace, run_id, sequence)"
            )
            self.store.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_verifications_run "
                "ON agent_experience_verifications(namespace, run_id, verified_at)"
            )
            self.store.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_injections_time "
                "ON agent_experience_injections(namespace, created_at)"
            )

    def capture(self, event: AgentExperienceEvent) -> EventCaptureResult:
        payload = self._sanitize_payload(event.payload)
        prepared = AgentExperienceEvent(
            id=event.id,
            namespace=event.namespace,
            run_id=event.run_id,
            session_id=event.session_id,
            task_id=event.task_id,
            kind=event.kind,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            parent_event_id=event.parent_event_id,
            tool_name=event.tool_name,
            duration_ms=event.duration_ms,
            payload=payload,
        )
        serialized = _json(prepared.as_dict())
        payload_sha = hashlib.sha256(serialized.encode()).hexdigest()
        with self.store._lock, self.store.conn:
            count = self.store.conn.execute(
                "SELECT COUNT(*) FROM agent_experience_events WHERE namespace = ? AND run_id = ?",
                (prepared.namespace, prepared.run_id),
            ).fetchone()[0]
            existing = self.store.conn.execute(
                "SELECT payload_sha256 FROM agent_experience_events WHERE id = ?",
                (prepared.id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_sha256"]) != payload_sha:
                    raise ValueError("event id already exists with different data")
                return EventCaptureResult(event=prepared, inserted=False)
            if int(count) >= self.policy.max_events_per_run:
                raise ValueError("run exceeded max_events_per_run")
            self.store.conn.execute(
                """
                INSERT INTO agent_experience_events (
                    id, namespace, run_id, session_id, task_id, kind, sequence,
                    occurred_at, parent_event_id, tool_name, duration_ms,
                    payload_json, payload_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.id,
                    prepared.namespace,
                    prepared.run_id,
                    prepared.session_id,
                    prepared.task_id,
                    prepared.kind.value,
                    prepared.sequence,
                    prepared.occurred_at,
                    prepared.parent_event_id,
                    prepared.tool_name,
                    prepared.duration_ms,
                    _json(prepared.payload),
                    payload_sha,
                    time.time(),
                ),
            )
        return EventCaptureResult(event=prepared, inserted=True)

    def events(self, *, namespace: str, run_id: str) -> tuple[AgentExperienceEvent, ...]:
        with self.store._lock:
            rows = self.store.conn.execute(
                """
                SELECT * FROM agent_experience_events
                WHERE namespace = ? AND run_id = ?
                ORDER BY sequence, created_at, id
                """,
                (namespace, run_id),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def list_runs(self, *, namespace: str, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self.store._lock:
            rows = self.store.conn.execute(
                """
                SELECT run_id, MIN(occurred_at) AS started_at,
                       MAX(occurred_at) AS finished_at, COUNT(*) AS event_count,
                       MAX(session_id) AS session_id, MAX(task_id) AS task_id,
                       SUM(CASE WHEN kind = 'error' THEN 1 ELSE 0 END) AS error_count,
                       SUM(CASE WHEN kind = 'outcome' THEN 1 ELSE 0 END) AS outcome_count
                FROM agent_experience_events
                WHERE namespace = ?
                GROUP BY run_id
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (namespace, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def run_details(self, *, namespace: str, run_id: str) -> dict[str, Any]:
        events = self.events(namespace=namespace, run_id=run_id)
        if not events:
            raise KeyError(run_id)
        return {
            "run_id": run_id,
            "namespace": namespace,
            "events": [event.as_dict() for event in events],
            "verifications": self.verifications(namespace=namespace, run_id=run_id),
        }

    def snapshot(self, *, namespace: str, limit: int = 100) -> dict[str, Any]:
        records = self.store.list(namespace=namespace, limit=max(1, int(limit)))
        validations = self.store.candidate_validations()
        visible_ids = {record.id for record in records}
        return {
            "schema": "wavemind.agent_experience_snapshot.v1",
            "namespace": namespace,
            "runs": self.list_runs(namespace=namespace, limit=limit),
            "candidates": [record.as_dict() for record in records],
            "validation_evidence": [
                item for item in validations if item["experience_id"] in visible_ids
            ],
            "injection_decisions": self.injection_decisions(
                namespace=namespace,
                limit=limit,
            ),
            "audit_events": [
                asdict(event) for event in self.store.audit_events(limit=limit)
                if event.experience_id is None or event.experience_id in visible_ids
            ],
        }

    def next_sequence(self, *, namespace: str, run_id: str) -> int:
        events = self.events(namespace=namespace, run_id=run_id)
        if not events:
            raise KeyError(run_id)
        return max(event.sequence for event in events) + 1

    def finalize_external_run(
        self,
        *,
        namespace: str,
        run_id: str,
        verification: OutcomeVerification | None,
        applied_experience_ids: Sequence[str] = (),
    ) -> RunFinalization:
        events = self.events(namespace=namespace, run_id=run_id)
        if not events:
            raise KeyError(run_id)
        session_id = events[-1].session_id
        task_id = events[-1].task_id
        sequence = max(event.sequence for event in events) + 1
        terminal = {event.kind for event in events}
        payload = (
            {
                "verified": True,
                "success": verification.success,
                "score": verification.score,
                "source": verification.source.value,
                "verifier": verification.verifier,
                "evidence_id": verification.evidence_id,
                "reference": verification.reference,
            }
            if verification is not None
            else {"verified": False, "success": None}
        )
        for kind, event_payload in (
            (AgentEventKind.OUTCOME, payload),
            (AgentEventKind.TASK_FINISHED, {"verified": verification is not None}),
            (AgentEventKind.RUN_FINISHED, {}),
            (AgentEventKind.SESSION_FINISHED, {}),
        ):
            if kind in terminal:
                continue
            self.capture(
                AgentExperienceEvent(
                    id=f"evt_{uuid.uuid4().hex}",
                    namespace=namespace,
                    run_id=run_id,
                    session_id=session_id,
                    task_id=task_id,
                    kind=kind,
                    sequence=sequence,
                    occurred_at=time.time(),
                    payload=event_payload,
                )
            )
            sequence += 1
        return self.finalize_run(
            namespace=namespace,
            run_id=run_id,
            verification=verification,
            applied_experience_ids=applied_experience_ids,
        )

    def verifications(self, *, namespace: str, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_experience_verifications WHERE namespace = ?"
        values: list[Any] = [namespace]
        if run_id is not None:
            query += " AND run_id = ?"
            values.append(run_id)
        query += " ORDER BY verified_at, evidence_id"
        with self.store._lock:
            rows = self.store.conn.execute(query, tuple(values)).fetchall()
        return [
            {
                "evidence_id": row["evidence_id"],
                "namespace": row["namespace"],
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "source": row["source"],
                "verifier": row["verifier"],
                "successful": bool(row["successful"]),
                "score": row["score"],
                "reference": row["reference"],
                "metadata": json.loads(row["metadata_json"]),
                "verified_at": row["verified_at"],
            }
            for row in rows
        ]

    def decide(
        self,
        query: str,
        *,
        namespace: str,
        run_id: str | None = None,
        task_id: str | None = None,
        domains: Sequence[str] = (),
        task_types: Sequence[str] = (),
        tools: Sequence[str] = (),
        token_budget: int | None = None,
        top_k: int | None = None,
        canary: bool = False,
    ) -> ExperienceIntervention:
        clean_query = str(self._sanitize_payload({"query": query})["query"])
        packet = self.compiler.compile_packet(
            clean_query,
            namespace=namespace,
            context=FirewallContext(
                namespace=namespace,
                actor="agent_experience_runtime",
                actor_trust=TrustClass.TOOL_OUTPUT,
                validated_candidate=canary,
                canary=canary,
            ),
            token_budget=token_budget or self.policy.default_packet_tokens,
            top_k=top_k or self.policy.default_packet_items,
            domains=domains,
            task_types=task_types,
            tools=tools,
            include_canary=canary,
        )
        best_score = packet.items[0].score if packet.items else 0.0
        inject = bool(packet.items) and best_score >= self.policy.intervention_score_threshold
        if not packet.items:
            reason = "no_applicable_verified_experience"
        elif not inject:
            reason = "below_intervention_threshold"
        else:
            reason = "applicable_verified_experience"
        source_refs = self._source_tool_result_refs(packet) if inject else ()
        decision_id = f"inject_{uuid.uuid4().hex}"
        result = ExperienceIntervention(
            inject=inject,
            reason=reason,
            confidence=float(best_score),
            packet=packet if inject else None,
            source_tool_result_refs=source_refs,
            decision_id=decision_id,
        )
        with self.store._lock, self.store.conn:
            self.store.conn.execute(
                """
                INSERT INTO agent_experience_injections (
                    id, namespace, run_id, task_id, query_text, inject, reason,
                    confidence, packet_json, source_refs_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    namespace,
                    run_id,
                    task_id,
                    clean_query,
                    int(inject),
                    reason,
                    best_score,
                    _json(packet.as_dict()) if inject else None,
                    _json(list(source_refs)),
                    time.time(),
                ),
            )
        return result

    def injection_decisions(self, *, namespace: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.store._lock:
            rows = self.store.conn.execute(
                """
                SELECT * FROM agent_experience_injections
                WHERE namespace = ? ORDER BY created_at DESC LIMIT ?
                """,
                (namespace, int(limit)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "namespace": row["namespace"],
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "query": row["query_text"],
                "inject": bool(row["inject"]),
                "reason": row["reason"],
                "confidence": row["confidence"],
                "packet": json.loads(row["packet_json"]) if row["packet_json"] else None,
                "source_tool_result_refs": json.loads(row["source_refs_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def begin_run(
        self,
        *,
        namespace: str,
        objective: str,
        domain: str,
        task_type: str,
        session_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        applied_experience_ids: Sequence[str] = (),
    ) -> "CapturedRun":
        return CapturedRun(
            runtime=self,
            namespace=namespace,
            objective=objective,
            domain=domain,
            task_type=task_type,
            session_id=session_id or f"session_{uuid.uuid4().hex}",
            run_id=run_id or f"run_{uuid.uuid4().hex}",
            task_id=task_id or f"task_{uuid.uuid4().hex}",
            metadata=dict(metadata or {}),
            applied_experience_ids=tuple(dict.fromkeys(applied_experience_ids)),
        )

    @contextmanager
    def run(self, **kwargs: Any) -> Iterator["CapturedRun"]:
        handle = self.begin_run(**kwargs)
        try:
            yield handle
        except Exception as exc:
            handle.capture_error(exc, error_code=type(exc).__name__)
            handle.finish()
            raise
        finally:
            if not handle.finished:
                handle.finish()

    def finalize_run(
        self,
        *,
        namespace: str,
        run_id: str,
        verification: OutcomeVerification | None = None,
        applied_experience_ids: Sequence[str] = (),
    ) -> RunFinalization:
        events = self.events(namespace=namespace, run_id=run_id)
        if not events:
            raise KeyError(run_id)
        if verification is not None:
            self._store_verification(namespace, run_id, events[-1].task_id, verification)
        trajectory = _trajectory_from_events(events)
        self.store.ingest_trajectory(
            trajectory,
            trust=TrustClass.TOOL_OUTPUT,
            status=ExperienceStatus.SHADOW,
            confidence=1.0,
        )
        candidates = self._derive_candidates(trajectory, verification)
        statuses: dict[str, str] = {}
        for candidate in candidates:
            stored = self.store.get(candidate.id)
            if stored is None:
                stored, _ = self.compiler.submit(
                    candidate,
                    context=FirewallContext(
                        namespace=namespace,
                        actor="agent_experience_runtime",
                        actor_trust=TrustClass.TOOL_OUTPUT,
                    ),
                )
            if verification is not None:
                review = self.compiler.review_candidate(
                    stored.id,
                    evidence_id=f"{verification.evidence_id}:{stored.kind.value}",
                    successful=verification.success,
                    score=verification.score,
                    context=FirewallContext(
                        namespace=namespace,
                        actor="agent_experience_runtime",
                        actor_trust=TrustClass.TOOL_OUTPUT,
                    ),
                    metadata={
                        "run_id": run_id,
                        "verification_source": verification.source.value,
                        "verification_reference": verification.reference,
                    },
                )
                statuses[stored.id] = review.status.value
            else:
                statuses[stored.id] = stored.status.value

        derived_ids = {record.id for record in candidates}
        for experience_id in dict.fromkeys(applied_experience_ids):
            if experience_id in derived_ids:
                continue
            current = self.store.get(experience_id)
            if current is None or current.namespace != namespace or verification is None:
                continue
            review = self.compiler.review_candidate(
                experience_id,
                evidence_id=f"{verification.evidence_id}:applied",
                successful=verification.success,
                score=verification.score,
                context=FirewallContext(
                    namespace=namespace,
                    actor="agent_experience_runtime",
                    actor_trust=TrustClass.TOOL_OUTPUT,
                ),
                metadata={"run_id": run_id, "applied": True},
            )
            statuses[experience_id] = review.status.value

        return RunFinalization(
            run_id=run_id,
            trajectory_id=trajectory.id,
            verification=verification,
            candidate_ids=tuple(record.id for record in candidates),
            candidate_statuses=statuses,
            applied_experience_ids=tuple(dict.fromkeys(applied_experience_ids)),
        )

    def approve(self, experience_id: str, *, namespace: str, evidence_id: str, score: float = 1.0) -> str:
        status = ""
        for index in range(self.compiler.policy.activation_validation_count):
            review = self.compiler.review_candidate(
                experience_id,
                evidence_id=(
                    evidence_id if index == 0 else f"{evidence_id}:operator:{index + 1}"
                ),
                successful=True,
                score=score,
                context=FirewallContext(
                    namespace=namespace,
                    actor="operator",
                    actor_trust=TrustClass.VERIFIED_OPERATOR,
                    operator_override=True,
                ),
                metadata={"verification_source": VerificationSource.OPERATOR.value},
            )
            status = review.status.value
            if review.status is ExperienceStatus.ACTIVE:
                break
        return status

    def reject(self, experience_id: str, *, namespace: str, reason: str) -> ExperienceRecord:
        record = self.store.get(experience_id)
        if record is None or record.namespace != namespace:
            raise KeyError(experience_id)
        return self.compiler.reject(experience_id, reason=reason, actor="operator")

    def rollback(self, experience_id: str, *, namespace: str, reason: str) -> ExperienceRecord:
        return self.compiler.rollback(
            experience_id,
            reason=reason,
            context=FirewallContext(
                namespace=namespace,
                actor="operator",
                actor_trust=TrustClass.VERIFIED_OPERATOR,
                operator_override=True,
                consent_token="operator-approved",
            ),
        )

    def _store_verification(
        self,
        namespace: str,
        run_id: str,
        task_id: str | None,
        verification: OutcomeVerification,
    ) -> None:
        sanitized = self._sanitize_payload(
            {
                "reference": verification.reference,
                "metadata": verification.metadata,
            }
        )
        payload = verification.as_dict()
        payload["reference"] = sanitized["reference"]
        payload["metadata"] = sanitized["metadata"]
        payload.pop("verified_at", None)
        payload_sha = hashlib.sha256(_json(payload).encode()).hexdigest()
        with self.store._lock, self.store.conn:
            existing = self.store.conn.execute(
                "SELECT payload_sha256 FROM agent_experience_verifications WHERE evidence_id = ?",
                (verification.evidence_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_sha256"]) != payload_sha:
                    raise ValueError("verification evidence id already exists with different data")
                return
            self.store.conn.execute(
                """
                INSERT INTO agent_experience_verifications (
                    evidence_id, namespace, run_id, task_id, source, verifier,
                    successful, score, reference, metadata_json, verified_at,
                    payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification.evidence_id,
                    namespace,
                    run_id,
                    task_id,
                    verification.source.value,
                    verification.verifier,
                    int(verification.success),
                    verification.score,
                    sanitized["reference"],
                    _json(sanitized["metadata"]),
                    verification.verified_at,
                    payload_sha,
                ),
            )

    def _derive_candidates(
        self,
        trajectory: ToolTrajectory,
        verification: OutcomeVerification | None,
    ) -> tuple[ExperienceRecord, ...]:
        calls = [step for step in trajectory.steps if step.kind == TrajectoryStepKind.TOOL_CALL]
        errors = [
            step
            for step in trajectory.steps
            if step.kind == TrajectoryStepKind.TOOL_RESULT and step.success is False
        ]
        metadata = dict(trajectory.metadata)
        domain = str(metadata.get("domain") or "general")
        task_type = str(metadata.get("task_type") or "task")
        objective = str(metadata.get("objective") or task_type)
        verified = verification is not None
        evidence_success = bool(verification.success) if verification else False
        trust = TrustClass.TOOL_OUTPUT if verified else TrustClass.AGENT_GENERATED
        source_type = "independently_verified_run" if verified else "unverified_run"
        kinds: list[tuple[ExperienceKind, str, str, dict[str, Any]]] = []

        declared_tools = tuple(
            str(tool)
            for tool in metadata.get("declared_tools", ())
            if isinstance(tool, str) and tool.strip()
        )
        plan = tuple(
            dict.fromkeys(
                tuple(tool for tool in declared_tools if tool)
                + tuple(step.name for step in calls if step.name)
            )
        )
        if plan:
            kinds.append(
                (
                    ExperienceKind.PROCEDURE,
                    f"Verified procedure for {task_type}",
                    f"For {task_type}, use the observed tool sequence: {' -> '.join(plan)}.",
                    {"tool_plan": list(plan)},
                )
            )
        if errors:
            codes = sorted(
                {
                    str(step.metadata.get("error_code") or step.name or "tool_error")
                    for step in errors
                }
            )
            kind = ExperienceKind.GOTCHA if evidence_success else ExperienceKind.FAILURE
            label = "Recovered gotcha" if evidence_success else "Verified failure pattern"
            kinds.append(
                (
                    kind,
                    f"{label} for {task_type}",
                    f"Observed errors for {task_type}: {', '.join(codes)}.",
                    {"error_codes": codes, "recovered": evidence_success},
                )
            )
        for step in trajectory.steps:
            for key, kind in (
                ("constraint", ExperienceKind.CONSTRAINT),
                ("correction", ExperienceKind.CORRECTION),
            ):
                value = step.metadata.get(key)
                if isinstance(value, str) and value.strip():
                    kinds.append(
                        (
                            kind,
                            f"Observed {key} for {task_type}",
                            value.strip(),
                            {"source_step_id": step.id},
                        )
                    )

        records: list[ExperienceRecord] = []
        for kind, title, content, extra in kinds:
            fingerprint = hashlib.sha256(
                _json(
                    {
                        "namespace": trajectory.namespace,
                        "kind": kind.value,
                        "domain": domain,
                        "task_type": task_type,
                        "content": content,
                        "verified_track": verified,
                    }
                ).encode()
            ).hexdigest()[:24]
            records.append(
                ExperienceRecord.create(
                    id=f"exp_runtime_{fingerprint}",
                    namespace=trajectory.namespace,
                    kind=kind,
                    title=title,
                    content=content,
                    applicability=ExperienceApplicability(
                        domains=(domain,),
                        task_types=(task_type,),
                        tools=plan,
                    ),
                    outcome=ExperienceOutcome(
                        success=verification.success if verification else None,
                        score=verification.score if verification else None,
                        summary=(
                            f"Verified by {verification.source.value}:{verification.verifier}."
                            if verification
                            else "Awaiting independent outcome verification."
                        ),
                    ),
                    confidence=0.85 if verified else 0.35,
                    trust=trust,
                    status=ExperienceStatus.SHADOW,
                    source=ExperienceSource(
                        provider="agent_experience_runtime",
                        source_type=source_type,
                        source_id=trajectory.id,
                        metadata={
                            "verification_evidence_id": (
                                verification.evidence_id if verification else None
                            ),
                            "verification_reference": (
                                verification.reference if verification else None
                            ),
                        },
                    ),
                    trajectory=TrajectoryProvenance(
                        trajectory_id=trajectory.id,
                        step_ids=tuple(step.id for step in trajectory.steps),
                        source_sha256=trajectory.source_sha256,
                        raw_event_count=trajectory.raw_event_count,
                    ),
                    metadata={
                        **extra,
                        "objective": objective,
                        "runtime_run_id": metadata.get("run_id"),
                        "verification_required": True,
                    },
                )
            )
        return tuple(records)

    def _source_tool_result_refs(self, packet: ExperiencePacket) -> tuple[str, ...]:
        refs: list[str] = []
        for item in packet.items:
            trajectory_id = str(item.provenance.get("trajectory_id") or "")
            if not trajectory_id:
                continue
            trajectory = self.store.get_trajectory(trajectory_id)
            if trajectory is None:
                continue
            refs.extend(
                f"trajectory:{trajectory.id}#step:{step.id}"
                for step in trajectory.steps
                if step.kind == TrajectoryStepKind.TOOL_RESULT
            )
        return tuple(dict.fromkeys(refs))

    def _sanitize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        sanitized = _redact_value(dict(payload), secret_keys=set(self.policy.secret_keys))
        serialized = _json(sanitized)
        encoded = serialized.encode()
        if len(encoded) <= self.policy.max_payload_bytes:
            return sanitized
        return {
            "_truncated": True,
            "original_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "preview": serialized[: min(512, self.policy.max_payload_bytes // 2)],
        }


class CapturedRun:
    def __init__(
        self,
        *,
        runtime: AgentExperienceRuntime,
        namespace: str,
        objective: str,
        domain: str,
        task_type: str,
        session_id: str,
        run_id: str,
        task_id: str,
        metadata: dict[str, Any],
        applied_experience_ids: tuple[str, ...],
    ) -> None:
        self.runtime = runtime
        self.namespace = namespace
        self.objective = objective
        self.domain = domain
        self.task_type = task_type
        self.session_id = session_id
        self.run_id = run_id
        self.task_id = task_id
        self.metadata = metadata
        self.applied_experience_ids = applied_experience_ids
        self.finished = False
        self.verification: OutcomeVerification | None = None
        self.finalization: RunFinalization | None = None
        self._sequence = 0
        self._capture(AgentEventKind.SESSION_STARTED, {"metadata": metadata})
        self._capture(AgentEventKind.RUN_STARTED, {"objective": objective})
        self._capture(
            AgentEventKind.TASK_STARTED,
            {
                "objective": objective,
                "domain": domain,
                "task_type": task_type,
                "declared_tools": list(
                    dict.fromkeys(
                        str(tool) for tool in metadata.get("declared_tools", ())
                    )
                ),
            },
        )

    def _capture(
        self,
        kind: AgentEventKind,
        payload: Mapping[str, Any] | None = None,
        *,
        parent_event_id: str | None = None,
        tool_name: str | None = None,
        duration_ms: float | None = None,
    ) -> AgentExperienceEvent:
        event = AgentExperienceEvent(
            id=f"evt_{uuid.uuid4().hex}",
            namespace=self.namespace,
            run_id=self.run_id,
            session_id=self.session_id,
            task_id=self.task_id,
            kind=kind,
            sequence=self._sequence,
            occurred_at=time.time(),
            parent_event_id=parent_event_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            payload=self.runtime._sanitize_payload(dict(payload or {})),
        )
        self.runtime.capture(event)
        self._sequence += 1
        return event

    def execute_tool(
        self,
        tool_name: str,
        callback: Callable[..., Any],
        *args: Any,
        input: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        call = self.capture_tool_call(
            tool_name,
            dict(input) if input is not None else {"args": args, "kwargs": kwargs},
        )
        started = time.perf_counter()
        try:
            result = callback(*args, **kwargs)
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000.0
            self._capture(
                AgentEventKind.ERROR,
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "error_code": getattr(exc, "code", type(exc).__name__),
                },
                parent_event_id=call.id,
                tool_name=tool_name,
                duration_ms=duration,
            )
            self.capture_tool_result(
                tool_name,
                success=False,
                output={
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", type(exc).__name__),
                },
                parent_event_id=call.id,
                duration_ms=duration,
            )
            raise
        duration = (time.perf_counter() - started) * 1000.0
        self.capture_tool_result(
            tool_name,
            success=True,
            output=result,
            parent_event_id=call.id,
            duration_ms=duration,
        )
        return result

    def capture_tool_call(
        self,
        tool_name: str,
        input: Mapping[str, Any] | None = None,
    ) -> AgentExperienceEvent:
        return self._capture(
            AgentEventKind.TOOL_CALL,
            {"input": dict(input or {})},
            tool_name=tool_name,
        )

    def capture_tool_result(
        self,
        tool_name: str,
        *,
        success: bool,
        output: Any = None,
        parent_event_id: str | None = None,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentExperienceEvent:
        payload = {
            "success": bool(success),
            "output": output,
            **dict(metadata or {}),
        }
        return self._capture(
            AgentEventKind.TOOL_RESULT,
            payload,
            parent_event_id=parent_event_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
        )

    def capture_error(
        self,
        error: Exception | str,
        *,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentExperienceEvent:
        return self._capture(
            AgentEventKind.ERROR,
            {
                "error_type": type(error).__name__ if isinstance(error, Exception) else "error",
                "message": str(error),
                "error_code": error_code,
                "metadata": dict(metadata or {}),
            },
        )

    def verify(self, verifier: OutcomeVerifier) -> OutcomeVerification:
        context = VerificationContext(
            namespace=self.namespace,
            run_id=self.run_id,
            session_id=self.session_id,
            task_id=self.task_id,
            events=self.runtime.events(namespace=self.namespace, run_id=self.run_id),
        )
        verification = verifier.verify(context)
        if not isinstance(verification, OutcomeVerification):
            raise TypeError("outcome verifier must return OutcomeVerification")
        return self.accept_verification(verification)

    def accept_verification(
        self,
        verification: OutcomeVerification,
    ) -> OutcomeVerification:
        if not isinstance(verification, OutcomeVerification):
            raise TypeError("verification must be an OutcomeVerification")
        if self.verification is not None and self.verification != verification:
            raise ValueError("run already has different verification evidence")
        self.verification = verification
        self._capture(
            AgentEventKind.OUTCOME,
            {
                "verified": True,
                "success": verification.success,
                "score": verification.score,
                "source": verification.source.value,
                "verifier": verification.verifier,
                "evidence_id": verification.evidence_id,
                "reference": verification.reference,
            },
        )
        return verification

    def finish(self) -> RunFinalization:
        if self.finished:
            if self.finalization is None:
                raise RuntimeError("run is marked finished without finalization")
            return self.finalization
        if self.verification is None:
            self._capture(AgentEventKind.OUTCOME, {"verified": False, "success": None})
        self._capture(
            AgentEventKind.TASK_FINISHED,
            {"verified": self.verification is not None},
        )
        self._capture(AgentEventKind.RUN_FINISHED, {})
        self._capture(AgentEventKind.SESSION_FINISHED, {})
        self.finalization = self.runtime.finalize_run(
            namespace=self.namespace,
            run_id=self.run_id,
            verification=self.verification,
            applied_experience_ids=self.applied_experience_ids,
        )
        self.finished = True
        return self.finalization


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


def _redact_value(value: Any, *, secret_keys: set[str]) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            output[key] = "[REDACTED]" if normalized in secret_keys else _redact_value(item, secret_keys=secret_keys)
        return output
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, secret_keys=secret_keys) for item in value]
    if isinstance(value, str):
        redacted = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
        redacted = _BEARER_RE.sub("Bearer [REDACTED]", redacted)
        return _OPENAI_KEY_RE.sub("[REDACTED]", redacted)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)


def _trajectory_from_events(events: Sequence[AgentExperienceEvent]) -> ToolTrajectory:
    first = events[0]
    steps: list[TrajectoryStep] = []
    task_metadata: dict[str, Any] = {}
    verification: dict[str, Any] = {}
    for event in events:
        if event.kind == AgentEventKind.TASK_STARTED:
            task_metadata.update(event.payload)
        if event.kind == AgentEventKind.OUTCOME:
            verification = dict(event.payload)
        if event.kind == AgentEventKind.TOOL_CALL:
            kind = TrajectoryStepKind.TOOL_CALL
            success = None
            output = None
            input_value = event.payload.get("input")
        elif event.kind == AgentEventKind.TOOL_RESULT:
            kind = TrajectoryStepKind.TOOL_RESULT
            success = bool(event.payload.get("success"))
            output = event.payload.get("output") or event.payload
            input_value = None
        elif event.kind == AgentEventKind.ERROR:
            kind = TrajectoryStepKind.TOOL_RESULT
            success = False
            output = event.payload
            input_value = None
        else:
            kind = TrajectoryStepKind.STATE
            success = event.payload.get("success")
            output = event.payload
            input_value = None
        steps.append(
            TrajectoryStep(
                id=event.id,
                sequence=len(steps),
                kind=kind,
                name=event.tool_name or event.kind.value,
                input=input_value,
                output=output,
                success=success,
                started_at=event.occurred_at,
                finished_at=(
                    event.occurred_at + (event.duration_ms / 1000.0)
                    if event.duration_ms is not None
                    else event.occurred_at
                ),
                parent_id=event.parent_event_id,
                metadata={
                    "runtime_event_kind": event.kind.value,
                    "error_code": event.payload.get("error_code"),
                    **(
                        dict(event.payload.get("metadata") or {})
                        if isinstance(event.payload.get("metadata"), dict)
                        else {}
                    ),
                },
            )
        )
    payload = [event.as_dict() for event in events]
    source_sha = hashlib.sha256(_json(payload).encode()).hexdigest()
    return ToolTrajectory(
        id=f"trajectory_{first.run_id}",
        provider="agent_experience_runtime",
        namespace=first.namespace,
        steps=tuple(steps),
        source_sha256=source_sha,
        started_at=events[0].occurred_at,
        ended_at=events[-1].occurred_at,
        metadata={
            **task_metadata,
            "run_id": first.run_id,
            "session_id": first.session_id,
            "task_id": first.task_id,
            "verification": verification,
        },
        raw_event_count=len(events),
    )


def _event_from_row(row: Any) -> AgentExperienceEvent:
    return AgentExperienceEvent(
        id=str(row["id"]),
        namespace=str(row["namespace"]),
        run_id=str(row["run_id"]),
        session_id=row["session_id"],
        task_id=row["task_id"],
        kind=AgentEventKind(str(row["kind"])),
        sequence=int(row["sequence"]),
        occurred_at=float(row["occurred_at"]),
        parent_event_id=row["parent_event_id"],
        tool_name=row["tool_name"],
        duration_ms=row["duration_ms"],
        payload=json.loads(row["payload_json"]),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
