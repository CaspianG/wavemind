from __future__ import annotations

import itertools
import json
import math
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evaluation_statistics import paired_cluster_bootstrap
from .evidence import canonical_json_bytes, sha256_bytes, utc_now


SCIENTIFIC_EVENT_SCHEMA = "wavemind.scientific_memory_event.v1"
INFLUENCE_RECEIPT_SCHEMA = "wavemind.influence_receipt.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MemoryKind(str, Enum):
    FACT = "fact"
    STATE_TRANSITION = "state_transition"
    PROCEDURE = "procedure"
    CONSTRAINT = "constraint"
    FAILED_STRATEGY = "failed_strategy"


class MemoryLifecycle(str, Enum):
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    DEMOTED = "demoted"
    REVOKED = "revoked"


class ScientificEventType(str, Enum):
    MEMORY_REGISTERED = "memory_registered"
    INFLUENCE_USED = "influence_used"
    VERIFICATION_ACCEPTED = "verification_accepted"
    VERIFICATION_REJECTED = "verification_rejected"
    MEMORY_PROMOTED = "memory_promoted"
    MEMORY_DEMOTED = "memory_demoted"
    MEMORY_REVOKED = "memory_revoked"
    MEMORY_ROLLED_BACK = "memory_rolled_back"


class VerifierKind(str, Enum):
    TEST = "test"
    TOOL = "tool"
    ENVIRONMENT = "environment"
    OPERATOR = "operator"
    AGENT_SELF = "agent_self"


class VerificationDecision(str, Enum):
    VERIFIED = "verified"
    FALSIFIED = "falsified"
    INCONCLUSIVE = "inconclusive"


class CanaryArm(str, Enum):
    MEMORY = "memory"
    CONTROL = "control"


@dataclass(frozen=True)
class ValidityInterval:
    valid_from: float | None = None
    valid_until: float | None = None

    def contains(self, moment: float) -> bool:
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return self.valid_until is None or moment <= self.valid_until


@dataclass(frozen=True)
class MemoryDefinition:
    memory_id: str
    kind: MemoryKind
    content: str
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    applicability: Mapping[str, str] = field(default_factory=dict)
    validity: ValidityInterval = field(default_factory=ValidityInterval)
    provenance: tuple[str, ...] = ()
    estimated_tokens: int = 1
    estimated_latency_ms: float = 0.0
    safety_risk: float = 0.0

    def __post_init__(self) -> None:
        if not self.memory_id.strip():
            raise ValueError("memory_id is required")
        if not self.content.strip():
            raise ValueError("memory content is required")
        if self.estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be positive")
        if self.estimated_latency_ms < 0.0:
            raise ValueError("estimated_latency_ms cannot be negative")
        if not 0.0 <= self.safety_risk <= 1.0:
            raise ValueError("safety_risk must be between zero and one")


@dataclass(frozen=True)
class VerifierResult:
    verifier_kind: VerifierKind
    verifier_id: str
    verifier_run_id: str
    decision: VerificationDecision
    treatment_outcome: float | None
    control_outcome: float | None
    evidence_uri: str
    evidence_sha256: str
    observed_at: str = field(default_factory=utc_now)
    false_verified_promotion: bool = False

    def independent(self) -> bool:
        return (
            self.verifier_kind is not VerifierKind.AGENT_SELF
            and bool(self.verifier_id.strip())
            and bool(self.verifier_run_id.strip())
            and bool(self.evidence_uri.strip())
            and bool(SHA256_RE.fullmatch(self.evidence_sha256))
        )

    def paired_effect(self) -> float | None:
        if self.decision is VerificationDecision.INCONCLUSIVE:
            return None
        if self.treatment_outcome is None or self.control_outcome is None:
            return None
        treatment = float(self.treatment_outcome)
        control = float(self.control_outcome)
        if not 0.0 <= treatment <= 1.0 or not 0.0 <= control <= 1.0:
            raise ValueError("paired outcomes must be between zero and one")
        effect = treatment - control
        return (
            effect if self.decision is VerificationDecision.VERIFIED else -abs(effect)
        )


@dataclass(frozen=True)
class InfluenceReceipt:
    receipt_id: str
    task_id: str
    case_id: str
    memory_attribution: Mapping[str, float]
    context_sha256: str
    action_sha256: str
    canary_arm: CanaryArm | None
    safe_for_randomization: bool
    created_at: str
    verifier_result: VerifierResult | None = None

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.memory_attribution))

    @property
    def carries_production_influence(self) -> bool:
        return bool(
            self.verifier_result
            and self.verifier_result.independent()
            and self.verifier_result.paired_effect() is not None
        )


@dataclass(frozen=True)
class ScientificEvent:
    schema: str
    sequence: int
    event_id: str
    event_type: ScientificEventType
    memory_id: str | None
    occurred_at: str
    actor: str
    payload: Mapping[str, Any]
    previous_sha256: str | None
    event_sha256: str


@dataclass(frozen=True)
class MemoryState:
    definition: MemoryDefinition
    lifecycle: MemoryLifecycle
    last_sequence: int
    reason: str | None = None

    @property
    def production_eligible(self) -> bool:
        return self.lifecycle is MemoryLifecycle.PRODUCTION


@dataclass(frozen=True)
class CausalEstimate:
    memory_id: str
    verified_pair_count: int
    independent_cluster_count: int
    mean_effect: float
    ci_lower: float
    ci_upper: float
    false_verified_promotions: int
    confidence_level: float
    method: str

    @property
    def uncertainty_width(self) -> float:
        return self.ci_upper - self.ci_lower


@dataclass(frozen=True)
class SelectionDecision:
    selected_memory_ids: tuple[str, ...]
    abstained: bool
    reason: str
    total_tokens: int
    estimated_latency_ms: float
    max_safety_risk: float
    estimates: Mapping[str, CausalEstimate]


def _memory_definition_payload(definition: MemoryDefinition) -> dict[str, Any]:
    return {
        "memory_id": definition.memory_id,
        "kind": definition.kind.value,
        "content": definition.content,
        "preconditions": list(definition.preconditions),
        "effects": list(definition.effects),
        "applicability": dict(sorted(definition.applicability.items())),
        "validity": asdict(definition.validity),
        "provenance": list(definition.provenance),
        "estimated_tokens": definition.estimated_tokens,
        "estimated_latency_ms": definition.estimated_latency_ms,
        "safety_risk": definition.safety_risk,
    }


def _definition_from_payload(payload: Mapping[str, Any]) -> MemoryDefinition:
    validity = payload.get("validity") or {}
    return MemoryDefinition(
        memory_id=str(payload["memory_id"]),
        kind=MemoryKind(str(payload["kind"])),
        content=str(payload["content"]),
        preconditions=tuple(str(item) for item in payload.get("preconditions", ())),
        effects=tuple(str(item) for item in payload.get("effects", ())),
        applicability={
            str(key): str(value)
            for key, value in dict(payload.get("applicability") or {}).items()
        },
        validity=ValidityInterval(
            valid_from=validity.get("valid_from"),
            valid_until=validity.get("valid_until"),
        ),
        provenance=tuple(str(item) for item in payload.get("provenance", ())),
        estimated_tokens=int(payload.get("estimated_tokens", 1)),
        estimated_latency_ms=float(payload.get("estimated_latency_ms", 0.0)),
        safety_risk=float(payload.get("safety_risk", 0.0)),
    )


def _verifier_payload(result: VerifierResult) -> dict[str, Any]:
    return {
        "verifier_kind": result.verifier_kind.value,
        "verifier_id": result.verifier_id,
        "verifier_run_id": result.verifier_run_id,
        "decision": result.decision.value,
        "treatment_outcome": result.treatment_outcome,
        "control_outcome": result.control_outcome,
        "evidence_uri": result.evidence_uri,
        "evidence_sha256": result.evidence_sha256,
        "observed_at": result.observed_at,
        "false_verified_promotion": result.false_verified_promotion,
    }


def _verifier_from_payload(payload: Mapping[str, Any]) -> VerifierResult:
    return VerifierResult(
        verifier_kind=VerifierKind(str(payload["verifier_kind"])),
        verifier_id=str(payload["verifier_id"]),
        verifier_run_id=str(payload["verifier_run_id"]),
        decision=VerificationDecision(str(payload["decision"])),
        treatment_outcome=payload.get("treatment_outcome"),
        control_outcome=payload.get("control_outcome"),
        evidence_uri=str(payload.get("evidence_uri") or ""),
        evidence_sha256=str(payload.get("evidence_sha256") or ""),
        observed_at=str(payload.get("observed_at") or utc_now()),
        false_verified_promotion=bool(payload.get("false_verified_promotion")),
    )


class ScientificEventLog:
    """Append-only, hash-chained source of truth for causal memory state."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._events: list[ScientificEvent] = []
        self._lock = threading.RLock()
        self._path = Path(path).resolve() if path is not None else None
        self._connection: sqlite3.Connection | None = None
        self._closed = False
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                self._path,
                timeout=30.0,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scientific_memory_events (
                    sequence INTEGER PRIMARY KEY,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL
                )
                """
            )
            self._reload_from_storage()
            errors = self.validate_chain()
            if errors:
                self.close()
                raise ValueError(
                    "persisted scientific event chain is invalid: " + "; ".join(errors)
                )

    @property
    def path(self) -> Path | None:
        return self._path

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._closed = True

    def __enter__(self) -> "ScientificEventLog":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @staticmethod
    def _stored_event_payload(event: ScientificEvent) -> dict[str, Any]:
        return {
            "schema": event.schema,
            "sequence": event.sequence,
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "memory_id": event.memory_id,
            "occurred_at": event.occurred_at,
            "actor": event.actor,
            "payload": dict(event.payload),
            "previous_sha256": event.previous_sha256,
            "event_sha256": event.event_sha256,
        }

    @staticmethod
    def _event_from_stored_payload(payload: Mapping[str, Any]) -> ScientificEvent:
        return ScientificEvent(
            schema=str(payload["schema"]),
            sequence=int(payload["sequence"]),
            event_id=str(payload["event_id"]),
            event_type=ScientificEventType(str(payload["event_type"])),
            memory_id=(
                str(payload["memory_id"])
                if payload.get("memory_id") is not None
                else None
            ),
            occurred_at=str(payload["occurred_at"]),
            actor=str(payload["actor"]),
            payload=dict(payload.get("payload") or {}),
            previous_sha256=(
                str(payload["previous_sha256"])
                if payload.get("previous_sha256") is not None
                else None
            ),
            event_sha256=str(payload["event_sha256"]),
        )

    def _reload_from_storage(self) -> None:
        if self._connection is None:
            return
        rows = self._connection.execute(
            "SELECT sequence, event_sha256, event_json "
            "FROM scientific_memory_events ORDER BY sequence"
        ).fetchall()
        events: list[ScientificEvent] = []
        for sequence, digest, raw_payload in rows:
            try:
                payload = json.loads(str(raw_payload))
                event = self._event_from_stored_payload(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"persisted scientific event {sequence} cannot be decoded"
                ) from exc
            if event.sequence != int(sequence) or event.event_sha256 != str(digest):
                raise ValueError(
                    f"persisted scientific event index mismatch at {sequence}"
                )
            events.append(event)
        self._events = events

    @property
    def events(self) -> tuple[ScientificEvent, ...]:
        self._sync_for_read()
        return tuple(self._events)

    def _sync_for_read(self) -> None:
        if self._connection is None or self._closed:
            return
        with self._lock:
            self._reload_from_storage()

    def _append(
        self,
        event_type: ScientificEventType,
        *,
        memory_id: str | None,
        actor: str,
        payload: Mapping[str, Any],
    ) -> ScientificEvent:
        with self._lock:
            if self._closed:
                raise RuntimeError("scientific event log is closed")
            if self._connection is not None:
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._reload_from_storage()
                    chain_errors = self.validate_chain()
                    if chain_errors:
                        raise ValueError(
                            "scientific event chain changed before append: "
                            + "; ".join(chain_errors)
                        )
                    self._validate_append_preconditions(
                        event_type,
                        memory_id=memory_id,
                        payload=payload,
                    )
                    event = self._build_event(
                        event_type,
                        memory_id=memory_id,
                        actor=actor,
                        payload=payload,
                    )
                    stored = canonical_json_bytes(
                        self._stored_event_payload(event)
                    ).decode("utf-8")
                    self._connection.execute(
                        "INSERT INTO scientific_memory_events "
                        "(sequence, event_sha256, event_json) VALUES (?, ?, ?)",
                        (event.sequence, event.event_sha256, stored),
                    )
                    self._connection.execute("COMMIT")
                except Exception:
                    self._connection.execute("ROLLBACK")
                    raise
            else:
                self._validate_append_preconditions(
                    event_type,
                    memory_id=memory_id,
                    payload=payload,
                )
                event = self._build_event(
                    event_type,
                    memory_id=memory_id,
                    actor=actor,
                    payload=payload,
                )
            self._events.append(event)
            return event

    def _validate_append_preconditions(
        self,
        event_type: ScientificEventType,
        *,
        memory_id: str | None,
        payload: Mapping[str, Any],
    ) -> None:
        definitions = self.definitions()
        if event_type is ScientificEventType.MEMORY_REGISTERED:
            if memory_id in definitions:
                raise ValueError(f"memory already exists: {memory_id}")
            return
        if memory_id is not None and memory_id not in definitions:
            raise KeyError(f"unknown memory: {memory_id}")
        if event_type is ScientificEventType.INFLUENCE_USED:
            receipt_id = str((payload.get("receipt") or {}).get("receipt_id") or "")
            if receipt_id in self.receipts():
                raise ValueError(f"receipt already exists: {receipt_id}")
        elif event_type is ScientificEventType.VERIFICATION_ACCEPTED:
            receipt_id = str(payload.get("receipt_id") or "")
            receipt = self.receipts().get(receipt_id)
            if receipt is None:
                raise KeyError(f"unknown receipt: {receipt_id}")
            if receipt.verifier_result is not None:
                raise ValueError(f"receipt already verified: {receipt_id}")

    def _build_event(
        self,
        event_type: ScientificEventType,
        *,
        memory_id: str | None,
        actor: str,
        payload: Mapping[str, Any],
    ) -> ScientificEvent:
        sequence = len(self._events) + 1
        previous = self._events[-1].event_sha256 if self._events else None
        body = {
            "schema": SCIENTIFIC_EVENT_SCHEMA,
            "sequence": sequence,
            "event_type": event_type.value,
            "memory_id": memory_id,
            "occurred_at": utc_now(),
            "actor": actor,
            "payload": dict(payload),
            "previous_sha256": previous,
        }
        event_sha = sha256_bytes(canonical_json_bytes(body))
        return ScientificEvent(
            schema=SCIENTIFIC_EVENT_SCHEMA,
            sequence=sequence,
            event_id=f"scientific-event-{sequence:08d}-{event_sha[:12]}",
            event_type=event_type,
            memory_id=memory_id,
            occurred_at=str(body["occurred_at"]),
            actor=actor,
            payload=dict(payload),
            previous_sha256=previous,
            event_sha256=event_sha,
        )

    def validate_chain(self) -> list[str]:
        self._sync_for_read()
        errors: list[str] = []
        previous: str | None = None
        for expected_sequence, event in enumerate(self._events, start=1):
            if event.sequence != expected_sequence:
                errors.append(f"event sequence mismatch at {expected_sequence}")
            expected_event_id = (
                f"scientific-event-{event.sequence:08d}-{event.event_sha256[:12]}"
            )
            if event.event_id != expected_event_id:
                errors.append(f"event id mismatch at {expected_sequence}")
            if event.schema != SCIENTIFIC_EVENT_SCHEMA:
                errors.append(f"event schema mismatch at {expected_sequence}")
            if event.previous_sha256 != previous:
                errors.append(f"event parent mismatch at {expected_sequence}")
            body = {
                "schema": event.schema,
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "memory_id": event.memory_id,
                "occurred_at": event.occurred_at,
                "actor": event.actor,
                "payload": dict(event.payload),
                "previous_sha256": event.previous_sha256,
            }
            if sha256_bytes(canonical_json_bytes(body)) != event.event_sha256:
                errors.append(f"event digest mismatch at {expected_sequence}")
            previous = event.event_sha256
        return errors

    def definitions(self) -> dict[str, MemoryDefinition]:
        self._sync_for_read()
        result: dict[str, MemoryDefinition] = {}
        for event in self._events:
            if event.event_type is ScientificEventType.MEMORY_REGISTERED:
                definition = _definition_from_payload(event.payload["definition"])
                result[definition.memory_id] = definition
        return result

    def register_memory(
        self, definition: MemoryDefinition, *, actor: str = "system"
    ) -> ScientificEvent:
        if definition.memory_id in self.definitions():
            raise ValueError(f"memory already exists: {definition.memory_id}")
        return self._append(
            ScientificEventType.MEMORY_REGISTERED,
            memory_id=definition.memory_id,
            actor=actor,
            payload={"definition": _memory_definition_payload(definition)},
        )

    def _require_memory(self, memory_id: str) -> MemoryDefinition:
        try:
            return self.definitions()[memory_id]
        except KeyError as exc:
            raise KeyError(f"unknown memory: {memory_id}") from exc

    def record_influence(
        self,
        *,
        receipt_id: str,
        task_id: str,
        case_id: str,
        memory_attribution: Mapping[str, float],
        context_sha256: str,
        action_sha256: str,
        safe_for_randomization: bool,
        canary_arm: CanaryArm | None = None,
        actor: str = "agent-runtime",
    ) -> InfluenceReceipt:
        if receipt_id in self.receipts():
            raise ValueError(f"receipt already exists: {receipt_id}")
        if not task_id or not case_id:
            raise ValueError("task_id and case_id are required")
        if not memory_attribution:
            raise ValueError("memory attribution is required")
        for memory_id in memory_attribution:
            self._require_memory(memory_id)
        weights = {str(key): float(value) for key, value in memory_attribution.items()}
        if any(value <= 0.0 for value in weights.values()):
            raise ValueError("attribution weights must be positive")
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("attribution weights must sum to one")
        for name, digest in (("context", context_sha256), ("action", action_sha256)):
            if not SHA256_RE.fullmatch(digest):
                raise ValueError(f"{name} digest must be sha256")
        if canary_arm is not None and not safe_for_randomization:
            raise ValueError("randomized canary is forbidden for unsafe scenarios")
        receipt = InfluenceReceipt(
            receipt_id=receipt_id,
            task_id=task_id,
            case_id=case_id,
            memory_attribution=dict(sorted(weights.items())),
            context_sha256=context_sha256,
            action_sha256=action_sha256,
            canary_arm=canary_arm,
            safe_for_randomization=bool(safe_for_randomization),
            created_at=utc_now(),
        )
        self._append(
            ScientificEventType.INFLUENCE_USED,
            memory_id=None,
            actor=actor,
            payload={
                "schema": INFLUENCE_RECEIPT_SCHEMA,
                "receipt": {
                    "receipt_id": receipt.receipt_id,
                    "task_id": receipt.task_id,
                    "case_id": receipt.case_id,
                    "memory_attribution": dict(receipt.memory_attribution),
                    "context_sha256": receipt.context_sha256,
                    "action_sha256": receipt.action_sha256,
                    "canary_arm": receipt.canary_arm.value
                    if receipt.canary_arm
                    else None,
                    "safe_for_randomization": receipt.safe_for_randomization,
                    "created_at": receipt.created_at,
                },
            },
        )
        return receipt

    def verify_influence(
        self,
        receipt_id: str,
        result: VerifierResult,
        *,
        actor: str = "verifier-gateway",
    ) -> InfluenceReceipt:
        receipts = self.receipts()
        if receipt_id not in receipts:
            raise KeyError(f"unknown receipt: {receipt_id}")
        receipt = receipts[receipt_id]
        if receipt.verifier_result is not None:
            raise ValueError(f"receipt already verified: {receipt_id}")
        accepted = result.independent()
        self._append(
            (
                ScientificEventType.VERIFICATION_ACCEPTED
                if accepted
                else ScientificEventType.VERIFICATION_REJECTED
            ),
            memory_id=None,
            actor=actor,
            payload={
                "receipt_id": receipt_id,
                "verifier_result": _verifier_payload(result),
                "reason": None
                if accepted
                else "verifier is not independent or evidence is incomplete",
            },
        )
        if not accepted:
            return receipt
        return replace(receipt, verifier_result=result)

    def receipts(self) -> dict[str, InfluenceReceipt]:
        self._sync_for_read()
        receipts: dict[str, InfluenceReceipt] = {}
        for event in self._events:
            if event.event_type is ScientificEventType.INFLUENCE_USED:
                payload = event.payload["receipt"]
                arm = payload.get("canary_arm")
                receipts[str(payload["receipt_id"])] = InfluenceReceipt(
                    receipt_id=str(payload["receipt_id"]),
                    task_id=str(payload["task_id"]),
                    case_id=str(payload["case_id"]),
                    memory_attribution={
                        str(key): float(value)
                        for key, value in dict(payload["memory_attribution"]).items()
                    },
                    context_sha256=str(payload["context_sha256"]),
                    action_sha256=str(payload["action_sha256"]),
                    canary_arm=CanaryArm(str(arm)) if arm else None,
                    safe_for_randomization=bool(payload["safe_for_randomization"]),
                    created_at=str(payload["created_at"]),
                )
            elif event.event_type is ScientificEventType.VERIFICATION_ACCEPTED:
                receipt_id = str(event.payload["receipt_id"])
                if receipt_id in receipts:
                    receipts[receipt_id] = replace(
                        receipts[receipt_id],
                        verifier_result=_verifier_from_payload(
                            event.payload["verifier_result"]
                        ),
                    )
        return receipts

    def _lifecycle_events(self, memory_id: str) -> list[ScientificEvent]:
        return [
            event
            for event in self._events
            if event.memory_id == memory_id
            and event.event_type
            in {
                ScientificEventType.MEMORY_REGISTERED,
                ScientificEventType.MEMORY_PROMOTED,
                ScientificEventType.MEMORY_DEMOTED,
                ScientificEventType.MEMORY_REVOKED,
                ScientificEventType.MEMORY_ROLLED_BACK,
            }
        ]

    def memory_state(self, memory_id: str) -> MemoryState:
        definition = self._require_memory(memory_id)
        lifecycle = MemoryLifecycle.CANDIDATE
        reason: str | None = None
        last_sequence = 0
        for event in self._lifecycle_events(memory_id):
            last_sequence = event.sequence
            if event.event_type is ScientificEventType.MEMORY_PROMOTED:
                lifecycle = MemoryLifecycle.PRODUCTION
            elif event.event_type is ScientificEventType.MEMORY_DEMOTED:
                lifecycle = MemoryLifecycle.DEMOTED
            elif event.event_type is ScientificEventType.MEMORY_REVOKED:
                lifecycle = MemoryLifecycle.REVOKED
            elif event.event_type is ScientificEventType.MEMORY_ROLLED_BACK:
                lifecycle = MemoryLifecycle(str(event.payload["restored_lifecycle"]))
            reason = event.payload.get("reason") or reason
        return MemoryState(definition, lifecycle, last_sequence, reason)

    def set_lifecycle(
        self,
        memory_id: str,
        lifecycle: MemoryLifecycle,
        *,
        reason: str,
        causal_estimate: CausalEstimate | None = None,
        actor: str = "causal-utility-controller",
    ) -> ScientificEvent:
        self._require_memory(memory_id)
        event_type = {
            MemoryLifecycle.PRODUCTION: ScientificEventType.MEMORY_PROMOTED,
            MemoryLifecycle.DEMOTED: ScientificEventType.MEMORY_DEMOTED,
            MemoryLifecycle.REVOKED: ScientificEventType.MEMORY_REVOKED,
        }.get(lifecycle)
        if event_type is None:
            raise ValueError(
                "candidate lifecycle can only be restored through rollback"
            )
        return self._append(
            event_type,
            memory_id=memory_id,
            actor=actor,
            payload={
                "reason": reason,
                "causal_estimate": asdict(causal_estimate) if causal_estimate else None,
            },
        )

    def rollback_memory(
        self,
        memory_id: str,
        *,
        target_sequence: int,
        reason: str,
        actor: str = "operator",
    ) -> ScientificEvent:
        events = [
            event
            for event in self._lifecycle_events(memory_id)
            if event.sequence <= int(target_sequence)
        ]
        if not events:
            raise ValueError("rollback target predates memory registration")
        lifecycle = MemoryLifecycle.CANDIDATE
        for event in events:
            if event.event_type is ScientificEventType.MEMORY_PROMOTED:
                lifecycle = MemoryLifecycle.PRODUCTION
            elif event.event_type is ScientificEventType.MEMORY_DEMOTED:
                lifecycle = MemoryLifecycle.DEMOTED
            elif event.event_type is ScientificEventType.MEMORY_REVOKED:
                lifecycle = MemoryLifecycle.REVOKED
            elif event.event_type is ScientificEventType.MEMORY_ROLLED_BACK:
                lifecycle = MemoryLifecycle(str(event.payload["restored_lifecycle"]))
        return self._append(
            ScientificEventType.MEMORY_ROLLED_BACK,
            memory_id=memory_id,
            actor=actor,
            payload={
                "target_sequence": int(target_sequence),
                "restored_lifecycle": lifecycle.value,
                "reason": reason,
            },
        )


class CausalUtilityController:
    def __init__(
        self,
        event_log: ScientificEventLog,
        *,
        bootstrap_repeats: int = 2000,
        bootstrap_seed: int = 17,
        confidence_level: float = 0.95,
        minimum_verified_pairs: int = 3,
        promotion_effect_floor: float = 0.0,
        forgetting_effect_ceiling: float = 0.0,
    ) -> None:
        if bootstrap_repeats < 100:
            raise ValueError("bootstrap_repeats must be at least 100")
        if minimum_verified_pairs < 2:
            raise ValueError("minimum_verified_pairs must be at least two")
        self.event_log = event_log
        self.bootstrap_repeats = int(bootstrap_repeats)
        self.bootstrap_seed = int(bootstrap_seed)
        self.confidence_level = float(confidence_level)
        self.minimum_verified_pairs = int(minimum_verified_pairs)
        self.promotion_effect_floor = float(promotion_effect_floor)
        self.forgetting_effect_ceiling = float(forgetting_effect_ceiling)

    def assign_canary(
        self,
        case_id: str,
        *,
        safe_for_randomization: bool,
        seed: int,
        treatment_probability: float = 0.5,
    ) -> CanaryArm:
        if not safe_for_randomization:
            raise ValueError("randomized canary is forbidden for unsafe scenarios")
        if not 0.0 < treatment_probability < 1.0:
            raise ValueError("treatment_probability must be between zero and one")
        digest = sha256_bytes(f"{seed}:{case_id}".encode("utf-8"))
        draw = int(digest[:16], 16) / float(0xFFFFFFFFFFFFFFFF)
        return CanaryArm.MEMORY if draw < treatment_probability else CanaryArm.CONTROL

    def estimate(self, memory_id: str) -> CausalEstimate:
        self.event_log._require_memory(memory_id)
        rows: list[dict[str, Any]] = []
        false_promotions = 0
        for receipt in self.event_log.receipts().values():
            if (
                memory_id not in receipt.memory_attribution
                or not receipt.carries_production_influence
            ):
                continue
            result = receipt.verifier_result
            assert result is not None
            effect = result.paired_effect()
            if effect is None:
                continue
            weight = float(receipt.memory_attribution[memory_id])
            rows.append(
                {
                    "case_id": receipt.case_id,
                    "control": 0.0,
                    "treatment": effect * weight,
                }
            )
            false_promotions += int(result.false_verified_promotion)
        cluster_count = len({str(row["case_id"]) for row in rows})
        if len(rows) < self.minimum_verified_pairs or cluster_count < 2:
            mean = (
                sum(float(row["treatment"]) for row in rows) / len(rows)
                if rows
                else 0.0
            )
            return CausalEstimate(
                memory_id=memory_id,
                verified_pair_count=len(rows),
                independent_cluster_count=cluster_count,
                mean_effect=mean,
                ci_lower=-1.0,
                ci_upper=1.0,
                false_verified_promotions=false_promotions,
                confidence_level=self.confidence_level,
                method="insufficient-independent-pairs",
            )
        estimate = paired_cluster_bootstrap(
            rows,
            cluster_key="case_id",
            baseline_key="control",
            treatment_key="treatment",
            repeats=self.bootstrap_repeats,
            seed=self.bootstrap_seed,
            confidence_level=self.confidence_level,
        )
        return CausalEstimate(
            memory_id=memory_id,
            verified_pair_count=len(rows),
            independent_cluster_count=int(estimate["cluster_count"]),
            mean_effect=float(estimate["mean_difference"]),
            ci_lower=float(estimate["ci_lower"]),
            ci_upper=float(estimate["ci_upper"]),
            false_verified_promotions=false_promotions,
            confidence_level=self.confidence_level,
            method="paired-cluster-bootstrap",
        )

    def update_lifecycle(self, memory_id: str) -> MemoryState:
        estimate = self.estimate(memory_id)
        state = self.event_log.memory_state(memory_id)
        if (
            estimate.verified_pair_count >= self.minimum_verified_pairs
            and estimate.false_verified_promotions == 0
            and estimate.ci_lower > self.promotion_effect_floor
        ):
            if state.lifecycle is not MemoryLifecycle.PRODUCTION:
                self.event_log.set_lifecycle(
                    memory_id,
                    MemoryLifecycle.PRODUCTION,
                    reason="lower confidence bound proves positive paired utility",
                    causal_estimate=estimate,
                )
        elif (
            estimate.verified_pair_count >= self.minimum_verified_pairs
            and estimate.ci_upper < self.forgetting_effect_ceiling
        ):
            if state.lifecycle is not MemoryLifecycle.REVOKED:
                self.event_log.set_lifecycle(
                    memory_id,
                    MemoryLifecycle.REVOKED,
                    reason="upper confidence bound proves negative marginal utility",
                    causal_estimate=estimate,
                )
        elif state.lifecycle is MemoryLifecycle.PRODUCTION:
            self.event_log.set_lifecycle(
                memory_id,
                MemoryLifecycle.DEMOTED,
                reason="positive production utility is no longer proven",
                causal_estimate=estimate,
            )
        return self.event_log.memory_state(memory_id)

    def select_minimal_memories(
        self,
        memory_ids: Iterable[str],
        *,
        context: Mapping[str, str],
        moment: float,
        token_budget: int,
        latency_budget_ms: float,
        max_safety_risk: float,
        risk_aversion: float = 0.25,
    ) -> SelectionDecision:
        if token_budget <= 0 or latency_budget_ms < 0.0:
            raise ValueError("selection budgets are invalid")
        candidates: list[tuple[float, MemoryDefinition, CausalEstimate]] = []
        estimates: dict[str, CausalEstimate] = {}
        for memory_id in sorted(set(memory_ids)):
            state = self.event_log.memory_state(memory_id)
            definition = state.definition
            estimate = self.estimate(memory_id)
            estimates[memory_id] = estimate
            applicable = all(
                str(context.get(key)) == expected
                for key, expected in definition.applicability.items()
            )
            if (
                not state.production_eligible
                or not applicable
                or not definition.validity.contains(moment)
                or definition.safety_risk > max_safety_risk
                or estimate.false_verified_promotions > 0
                or estimate.ci_lower <= self.promotion_effect_floor
            ):
                continue
            risk_adjusted = (
                estimate.ci_lower - risk_aversion * estimate.uncertainty_width
            )
            if risk_adjusted <= 0.0:
                continue
            score = risk_adjusted / max(1, definition.estimated_tokens)
            candidates.append((score, definition, estimate))
        candidates.sort(key=lambda item: (-item[0], item[1].memory_id))
        selected: list[str] = []
        tokens = 0
        latency = 0.0
        safety = 0.0
        for _, definition, _ in candidates:
            if tokens + definition.estimated_tokens > token_budget:
                continue
            if latency + definition.estimated_latency_ms > latency_budget_ms:
                continue
            selected.append(definition.memory_id)
            tokens += definition.estimated_tokens
            latency += definition.estimated_latency_ms
            safety = max(safety, definition.safety_risk)
        if not selected:
            return SelectionDecision(
                selected_memory_ids=(),
                abstained=True,
                reason="no applicable memory has proven positive risk-adjusted utility",
                total_tokens=0,
                estimated_latency_ms=0.0,
                max_safety_risk=0.0,
                estimates=estimates,
            )
        return SelectionDecision(
            selected_memory_ids=tuple(selected),
            abstained=False,
            reason="minimal positive-utility set within frozen constraints",
            total_tokens=tokens,
            estimated_latency_ms=latency,
            max_safety_risk=safety,
            estimates=estimates,
        )


@dataclass(frozen=True)
class GraphEvidenceNode:
    memory_id: str
    evidence_count: int
    counterevidence_count: int
    relevance: float
    utility_lower_bound: float
    uncertainty_width: float
    estimated_tokens: int


class EvidenceConstrainedAssociativeGraph:
    """Preregistered graph candidate with an explicit, auditable energy."""

    def __init__(
        self,
        *,
        evidence_weight: float = 0.20,
        counterevidence_weight: float = 0.50,
        utility_weight: float = 1.0,
        uncertainty_weight: float = 0.25,
        association_weight: float = 0.10,
        conflict_weight: float = 0.50,
    ) -> None:
        self.evidence_weight = float(evidence_weight)
        self.counterevidence_weight = float(counterevidence_weight)
        self.utility_weight = float(utility_weight)
        self.uncertainty_weight = float(uncertainty_weight)
        self.association_weight = float(association_weight)
        self.conflict_weight = float(conflict_weight)

    def energy(
        self,
        nodes: Sequence[GraphEvidenceNode],
        *,
        associations: Mapping[tuple[str, str], float] | None = None,
        conflicts: Mapping[tuple[str, str], float] | None = None,
    ) -> float:
        value = 0.0
        for node in nodes:
            value += -node.relevance
            value -= self.evidence_weight * math.log1p(node.evidence_count)
            value += self.counterevidence_weight * node.counterevidence_count
            value -= self.utility_weight * node.utility_lower_bound
            value += self.uncertainty_weight * node.uncertainty_width
        selected = {node.memory_id for node in nodes}
        for (left, right), weight in (associations or {}).items():
            if left in selected and right in selected:
                value -= self.association_weight * float(weight)
        for (left, right), weight in (conflicts or {}).items():
            if left in selected and right in selected:
                value += self.conflict_weight * float(weight)
        return value

    def select(
        self,
        nodes: Sequence[GraphEvidenceNode],
        *,
        token_budget: int,
        associations: Mapping[tuple[str, str], float] | None = None,
        conflicts: Mapping[tuple[str, str], float] | None = None,
    ) -> tuple[str, ...]:
        eligible = [
            node
            for node in nodes
            if node.evidence_count > 0
            and node.utility_lower_bound > 0.0
            and node.counterevidence_count == 0
        ]
        if len(eligible) > 20:
            raise ValueError(
                "exact preregistered graph selection is limited to 20 nodes"
            )
        best: tuple[float, int, tuple[str, ...]] | None = None
        for size in range(1, len(eligible) + 1):
            for subset in itertools.combinations(eligible, size):
                tokens = sum(node.estimated_tokens for node in subset)
                if tokens > token_budget:
                    continue
                ids = tuple(sorted(node.memory_id for node in subset))
                candidate = (
                    self.energy(
                        subset,
                        associations=associations,
                        conflicts=conflicts,
                    ),
                    tokens,
                    ids,
                )
                if best is None or candidate < best:
                    best = candidate
        return best[2] if best is not None and best[0] < 0.0 else ()
