from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping, Sequence


class ExperienceKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EPISODE = "episode"
    STATE = "state"
    STATE_TRANSITION = "state_transition"
    PROCEDURE = "procedure"
    WORKFLOW = "workflow"
    GOTCHA = "gotcha"
    SUCCESSFUL_STRATEGY = "successful_strategy"
    FAILURE = "failure"
    CONSTRAINT = "constraint"
    CORRECTION = "correction"


class TrustClass(str, Enum):
    SYSTEM = "system"
    EXPLICIT_USER = "explicit_user"
    VERIFIED_OPERATOR = "verified_operator"
    AGENT_GENERATED = "agent_generated"
    TOOL_OUTPUT = "tool_output"
    IMPORTED = "imported"
    UNTRUSTED_EXTERNAL = "untrusted_external"


class ExperienceStatus(str, Enum):
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class TrajectoryStepKind(str, Enum):
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE = "state"


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("experience data must be JSON serializable") from exc


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _coerce_enum(value: Any, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{label} must be one of: {choices}") from exc


def _require_text(value: Any, label: str, *, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{label} is limited to {max_length} characters")
    return normalized


@dataclass(frozen=True)
class ExperienceApplicability:
    domains: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    conditions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domains", _normalized_strings(self.domains))
        object.__setattr__(self, "task_types", _normalized_strings(self.task_types))
        object.__setattr__(self, "tools", _normalized_strings(self.tools))
        _json_dumps(self.conditions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "domains": list(self.domains),
            "task_types": list(self.task_types),
            "tools": list(self.tools),
            "conditions": dict(self.conditions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ExperienceApplicability":
        value = value or {}
        return cls(
            domains=tuple(value.get("domains") or ()),
            task_types=tuple(value.get("task_types") or ()),
            tools=tuple(value.get("tools") or ()),
            conditions=dict(value.get("conditions") or {}),
        )


@dataclass(frozen=True)
class ExperienceOutcome:
    success: bool | None = None
    score: float | None = None
    summary: str = ""
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score is not None and not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("outcome score must be in [0, 1]")
        object.__setattr__(
            self,
            "metrics",
            {str(key): float(value) for key, value in self.metrics.items()},
        )
        if len(self.summary) > 4096:
            raise ValueError("outcome summary is limited to 4096 characters")

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "score": self.score,
            "summary": self.summary,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ExperienceOutcome":
        value = value or {}
        return cls(
            success=value.get("success"),
            score=value.get("score"),
            summary=str(value.get("summary") or ""),
            metrics=dict(value.get("metrics") or {}),
        )


@dataclass(frozen=True)
class ExperienceSource:
    provider: str
    source_type: str
    source_id: str | None = None
    actor_id: str | None = None
    uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            _require_text(self.provider, "source provider", max_length=128),
        )
        object.__setattr__(
            self,
            "source_type",
            _require_text(self.source_type, "source type", max_length=128),
        )
        _json_dumps(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperienceSource":
        return cls(
            provider=str(value.get("provider") or ""),
            source_type=str(value.get("source_type") or ""),
            source_id=_optional_text(value.get("source_id")),
            actor_id=_optional_text(value.get("actor_id")),
            uri=_optional_text(value.get("uri")),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TrajectoryProvenance:
    trajectory_id: str
    step_ids: tuple[str, ...]
    source_sha256: str
    parent_trajectory_ids: tuple[str, ...] = ()
    raw_event_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trajectory_id",
            _require_text(self.trajectory_id, "trajectory id", max_length=256),
        )
        object.__setattr__(self, "step_ids", _normalized_strings(self.step_ids))
        object.__setattr__(
            self,
            "parent_trajectory_ids",
            _normalized_strings(self.parent_trajectory_ids),
        )
        if not _is_sha256(self.source_sha256):
            raise ValueError("trajectory source_sha256 must be a lowercase SHA-256")
        if int(self.raw_event_count) < 0:
            raise ValueError("raw_event_count must be non-negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "step_ids": list(self.step_ids),
            "source_sha256": self.source_sha256,
            "parent_trajectory_ids": list(self.parent_trajectory_ids),
            "raw_event_count": int(self.raw_event_count),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrajectoryProvenance":
        return cls(
            trajectory_id=str(value.get("trajectory_id") or ""),
            step_ids=tuple(value.get("step_ids") or ()),
            source_sha256=str(value.get("source_sha256") or ""),
            parent_trajectory_ids=tuple(value.get("parent_trajectory_ids") or ()),
            raw_event_count=int(value.get("raw_event_count") or 0),
        )


@dataclass(frozen=True)
class ExperienceRecord:
    id: str
    namespace: str
    kind: ExperienceKind
    title: str
    content: str
    applicability: ExperienceApplicability
    outcome: ExperienceOutcome
    confidence: float
    trust: TrustClass
    source: ExperienceSource
    observed_at: float
    created_at: float
    updated_at: float
    trajectory: TrajectoryProvenance | None = None
    expires_at: float | None = None
    version: int = 1
    status: ExperienceStatus = ExperienceStatus.SHADOW
    supersedes_id: str | None = None
    rollback_of_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", _require_text(self.id, "experience id", max_length=256)
        )
        object.__setattr__(
            self,
            "namespace",
            _require_text(self.namespace, "namespace", max_length=256),
        )
        object.__setattr__(
            self, "kind", _coerce_enum(self.kind, ExperienceKind, "experience kind")
        )
        object.__setattr__(
            self,
            "trust",
            _coerce_enum(self.trust, TrustClass, "experience trust"),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ExperienceStatus, "experience status"),
        )
        object.__setattr__(
            self, "title", _require_text(self.title, "title", max_length=512)
        )
        object.__setattr__(
            self, "content", _require_text(self.content, "content", max_length=262_144)
        )
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if int(self.version) < 1:
            raise ValueError("version must be positive")
        if self.expires_at is not None and float(self.expires_at) <= float(
            self.created_at
        ):
            raise ValueError("expires_at must be later than created_at")
        _json_dumps(self.metadata)

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= _now()

    @property
    def content_sha256(self) -> str:
        return _sha256(
            {
                "kind": self.kind.value,
                "title": self.title,
                "content": self.content,
                "applicability": self.applicability.as_dict(),
                "outcome": self.outcome.as_dict(),
                "source": self.source.as_dict(),
                "trajectory": self.trajectory.as_dict() if self.trajectory else None,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "wavemind.experience.v1",
            "id": self.id,
            "namespace": self.namespace,
            "kind": self.kind.value,
            "title": self.title,
            "content": self.content,
            "applicability": self.applicability.as_dict(),
            "outcome": self.outcome.as_dict(),
            "confidence": float(self.confidence),
            "trust": self.trust.value,
            "source": self.source.as_dict(),
            "observed_at": float(self.observed_at),
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "trajectory": self.trajectory.as_dict() if self.trajectory else None,
            "expires_at": self.expires_at,
            "version": int(self.version),
            "status": self.status.value,
            "supersedes_id": self.supersedes_id,
            "rollback_of_id": self.rollback_of_id,
            "metadata": dict(self.metadata),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def create(
        cls,
        *,
        kind: ExperienceKind | str,
        title: str,
        content: str,
        source: ExperienceSource,
        namespace: str = "default",
        applicability: ExperienceApplicability | None = None,
        outcome: ExperienceOutcome | None = None,
        confidence: float = 0.5,
        trust: TrustClass | str = TrustClass.AGENT_GENERATED,
        observed_at: float | None = None,
        trajectory: TrajectoryProvenance | None = None,
        expires_at: float | None = None,
        status: ExperienceStatus | str = ExperienceStatus.SHADOW,
        metadata: Mapping[str, Any] | None = None,
        id: str | None = None,
    ) -> "ExperienceRecord":
        now = _now()
        return cls(
            id=id or _new_id("exp"),
            namespace=namespace,
            kind=_coerce_enum(kind, ExperienceKind, "experience kind"),
            title=title,
            content=content,
            applicability=applicability or ExperienceApplicability(),
            outcome=outcome or ExperienceOutcome(),
            confidence=float(confidence),
            trust=_coerce_enum(trust, TrustClass, "experience trust"),
            source=source,
            observed_at=float(observed_at if observed_at is not None else now),
            created_at=now,
            updated_at=now,
            trajectory=trajectory,
            expires_at=expires_at,
            status=_coerce_enum(status, ExperienceStatus, "experience status"),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperienceRecord":
        trajectory = value.get("trajectory")
        return cls(
            id=str(value["id"]),
            namespace=str(value.get("namespace") or "default"),
            kind=_coerce_enum(value["kind"], ExperienceKind, "experience kind"),
            title=str(value["title"]),
            content=str(value["content"]),
            applicability=ExperienceApplicability.from_dict(value.get("applicability")),
            outcome=ExperienceOutcome.from_dict(value.get("outcome")),
            confidence=float(value.get("confidence", 0.5)),
            trust=_coerce_enum(
                value.get("trust", TrustClass.AGENT_GENERATED.value),
                TrustClass,
                "experience trust",
            ),
            source=ExperienceSource.from_dict(value.get("source") or {}),
            observed_at=float(value.get("observed_at") or _now()),
            created_at=float(value.get("created_at") or _now()),
            updated_at=float(value.get("updated_at") or _now()),
            trajectory=(
                TrajectoryProvenance.from_dict(trajectory) if trajectory else None
            ),
            expires_at=value.get("expires_at"),
            version=int(value.get("version") or 1),
            status=_coerce_enum(
                value.get("status", ExperienceStatus.SHADOW.value),
                ExperienceStatus,
                "experience status",
            ),
            supersedes_id=_optional_text(value.get("supersedes_id")),
            rollback_of_id=_optional_text(value.get("rollback_of_id")),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TrajectoryStep:
    id: str
    sequence: int
    kind: TrajectoryStepKind
    name: str | None = None
    input: Any = None
    output: Any = None
    success: bool | None = None
    started_at: float | None = None
    finished_at: float | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", _require_text(self.id, "trajectory step id", max_length=256)
        )
        object.__setattr__(
            self,
            "kind",
            _coerce_enum(self.kind, TrajectoryStepKind, "trajectory step kind"),
        )
        if int(self.sequence) < 0:
            raise ValueError("trajectory step sequence must be non-negative")
        _json_dumps(self.input)
        _json_dumps(self.output)
        _json_dumps(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sequence": int(self.sequence),
            "kind": self.kind.value,
            "name": self.name,
            "input": self.input,
            "output": self.output,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "parent_id": self.parent_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], sequence: int) -> "TrajectoryStep":
        return cls(
            id=str(value.get("id") or value.get("step_id") or _new_id("step")),
            sequence=int(value.get("sequence", sequence)),
            kind=_coerce_enum(
                value.get("kind", TrajectoryStepKind.STATE.value),
                TrajectoryStepKind,
                "trajectory step kind",
            ),
            name=_optional_text(value.get("name")),
            input=value.get("input"),
            output=value.get("output"),
            success=value.get("success"),
            started_at=_optional_float(value.get("started_at")),
            finished_at=_optional_float(value.get("finished_at")),
            parent_id=_optional_text(value.get("parent_id")),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ToolTrajectory:
    id: str
    provider: str
    namespace: str
    steps: tuple[TrajectoryStep, ...]
    source_sha256: str
    started_at: float | None = None
    ended_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_event_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", _require_text(self.id, "trajectory id", max_length=256)
        )
        object.__setattr__(
            self, "provider", _require_text(self.provider, "provider", max_length=128)
        )
        object.__setattr__(
            self,
            "namespace",
            _require_text(self.namespace, "namespace", max_length=256),
        )
        if not self.steps:
            raise ValueError("trajectory must contain at least one step")
        if tuple(step.sequence for step in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("trajectory step sequences must be contiguous from zero")
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("trajectory step ids must be unique")
        if not _is_sha256(self.source_sha256):
            raise ValueError("trajectory source_sha256 must be a lowercase SHA-256")
        _json_dumps(self.metadata)

    @property
    def success(self) -> bool | None:
        outcomes = [
            step.success
            for step in self.steps
            if step.kind == TrajectoryStepKind.TOOL_RESULT
            and step.success is not None
        ]
        if not outcomes:
            return None
        return all(outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "wavemind.tool_trajectory.v1",
            "id": self.id,
            "provider": self.provider,
            "namespace": self.namespace,
            "steps": [step.as_dict() for step in self.steps],
            "source_sha256": self.source_sha256,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "metadata": dict(self.metadata),
            "raw_event_count": int(self.raw_event_count),
            "success": self.success,
        }


@dataclass(frozen=True)
class ExperienceIngestReport:
    trajectory_id: str
    provider: str
    inserted: bool
    step_count: int
    experience_ids: tuple[str, ...]
    source_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperienceAuditEvent:
    action: str
    created_at: float
    experience_id: str | None = None
    trajectory_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True)
class CandidateValidationSummary:
    experience_id: str
    validation_count: int
    successful_count: int
    failed_count: int
    success_rate: float
    average_score: float | None
    evidence_ids: tuple[str, ...]


class SQLiteExperienceStore:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or ":memory:")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
        self.ensure_schema()

    def __enter__(self) -> "SQLiteExperienceStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def ensure_schema(self) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_records (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    applicability_json TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    trust TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    trajectory_id TEXT,
                    trajectory_json TEXT,
                    expires_at REAL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    supersedes_id TEXT,
                    rollback_of_id TEXT,
                    metadata_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    dedupe_key TEXT UNIQUE
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_trajectories (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    started_at REAL,
                    ended_at REAL,
                    metadata_json TEXT NOT NULL,
                    raw_event_count INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(namespace, source_sha256)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_trajectory_steps (
                    trajectory_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT,
                    input_json TEXT,
                    output_json TEXT,
                    success INTEGER,
                    started_at REAL,
                    finished_at REAL,
                    parent_id TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(trajectory_id, step_id),
                    UNIQUE(trajectory_id, sequence),
                    FOREIGN KEY(trajectory_id)
                        REFERENCES experience_trajectories(id) ON DELETE CASCADE
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    experience_id TEXT,
                    trajectory_id TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_candidate_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experience_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    successful INTEGER NOT NULL,
                    score REAL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(experience_id, evidence_id),
                    FOREIGN KEY(experience_id)
                        REFERENCES experience_records(id) ON DELETE CASCADE
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_lookup "
                "ON experience_records(namespace, status, kind, trust)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_expiry "
                "ON experience_records(expires_at)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_trajectory "
                "ON experience_records(trajectory_id)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_audit_time "
                "ON experience_audit_events(created_at)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_validation "
                "ON experience_candidate_validations(experience_id, created_at)"
            )

    def put(
        self,
        record: ExperienceRecord,
        *,
        dedupe_key: str | None = None,
    ) -> ExperienceRecord:
        with self._lock, self.conn:
            existing = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (record.id,)
            ).fetchone()
            if existing is not None:
                stored = _experience_from_row(existing)
                if stored.as_dict() != record.as_dict():
                    raise ValueError(
                        f"experience id {record.id!r} already exists with different data"
                    )
                return stored
            if dedupe_key:
                duplicate = self.conn.execute(
                    "SELECT * FROM experience_records WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if duplicate is not None:
                    return _experience_from_row(duplicate)
            self._insert_record(record, dedupe_key=dedupe_key)
            self._audit("inserted", experience_id=record.id)
        return record

    def get(
        self,
        experience_id: str,
        *,
        include_inactive: bool = True,
    ) -> ExperienceRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (experience_id,)
            ).fetchone()
        if row is None:
            return None
        record = _experience_from_row(row)
        if not include_inactive and (
            record.status != ExperienceStatus.ACTIVE or record.is_expired
        ):
            return None
        return record

    def list(
        self,
        *,
        namespace: str | None = None,
        kind: ExperienceKind | str | None = None,
        trust: TrustClass | str | None = None,
        status: ExperienceStatus | str | None = None,
        trajectory_id: str | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> list[ExperienceRecord]:
        if not 1 <= int(limit) <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        clauses: list[str] = []
        values: list[Any] = []
        if namespace is not None:
            clauses.append("namespace = ?")
            values.append(namespace)
        if kind is not None:
            clauses.append("kind = ?")
            values.append(_coerce_enum(kind, ExperienceKind, "experience kind").value)
        if trust is not None:
            clauses.append("trust = ?")
            values.append(_coerce_enum(trust, TrustClass, "experience trust").value)
        if status is not None:
            clauses.append("status = ?")
            values.append(
                _coerce_enum(status, ExperienceStatus, "experience status").value
            )
        if trajectory_id is not None:
            clauses.append("trajectory_id = ?")
            values.append(trajectory_id)
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            values.append(_now())
            clauses.append("status != ?")
            values.append(ExperienceStatus.EXPIRED.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(int(limit))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM experience_records
                {where}
                ORDER BY observed_at DESC, created_at DESC, id ASC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [_experience_from_row(row) for row in rows]

    def supersede(
        self,
        experience_id: str,
        replacement: ExperienceRecord,
        *,
        reason: str,
    ) -> ExperienceRecord:
        reason = _require_text(reason, "supersession reason", max_length=4096)
        with self._lock, self.conn:
            current_row = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (experience_id,)
            ).fetchone()
            if current_row is None:
                raise KeyError(experience_id)
            current = _experience_from_row(current_row)
            if current.status not in {
                ExperienceStatus.ACTIVE,
                ExperienceStatus.SHADOW,
                ExperienceStatus.QUARANTINED,
            }:
                raise ValueError(
                    f"cannot supersede experience in {current.status.value} status"
                )
            if replacement.namespace != current.namespace:
                raise ValueError("replacement must remain in the same namespace")
            if replacement.id == current.id:
                raise ValueError("replacement must use a new experience id")
            now = _now()
            promoted = replace(
                replacement,
                version=current.version + 1,
                supersedes_id=current.id,
                updated_at=now,
            )
            self.conn.execute(
                """
                UPDATE experience_records
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (ExperienceStatus.SUPERSEDED.value, now, current.id),
            )
            self._insert_record(promoted)
            self._audit(
                "superseded",
                experience_id=current.id,
                metadata={"replacement_id": promoted.id, "reason": reason},
            )
        return promoted

    def transition_status(
        self,
        experience_id: str,
        status: ExperienceStatus | str,
        *,
        reason: str,
        actor: str = "experience_compiler",
    ) -> ExperienceRecord:
        target = _coerce_enum(status, ExperienceStatus, "experience status")
        reason = _require_text(reason, "transition reason", max_length=4096)
        actor = _require_text(actor, "transition actor", max_length=256)
        allowed = {
            ExperienceStatus.SHADOW: {
                ExperienceStatus.CANARY,
                ExperienceStatus.QUARANTINED,
                ExperienceStatus.REJECTED,
                ExperienceStatus.EXPIRED,
            },
            ExperienceStatus.CANARY: {
                ExperienceStatus.ACTIVE,
                ExperienceStatus.QUARANTINED,
                ExperienceStatus.REJECTED,
                ExperienceStatus.EXPIRED,
            },
            ExperienceStatus.ACTIVE: {
                ExperienceStatus.QUARANTINED,
                ExperienceStatus.REJECTED,
                ExperienceStatus.EXPIRED,
            },
            ExperienceStatus.QUARANTINED: {
                ExperienceStatus.SHADOW,
                ExperienceStatus.REJECTED,
                ExperienceStatus.EXPIRED,
            },
        }
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (experience_id,)
            ).fetchone()
            if row is None:
                raise KeyError(experience_id)
            current = _experience_from_row(row)
            if target == current.status:
                return current
            if target not in allowed.get(current.status, set()):
                raise ValueError(
                    f"invalid experience transition: {current.status.value} -> "
                    f"{target.value}"
                )
            now = _now()
            self.conn.execute(
                """
                UPDATE experience_records
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (target.value, now, experience_id),
            )
            self._audit(
                "status_transition",
                experience_id=experience_id,
                metadata={
                    "from": current.status.value,
                    "to": target.value,
                    "reason": reason,
                    "actor": actor,
                },
            )
        return replace(current, status=target, updated_at=now)

    def add_candidate_validation(
        self,
        experience_id: str,
        *,
        evidence_id: str,
        successful: bool,
        score: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CandidateValidationSummary:
        evidence_id = _require_text(
            evidence_id, "validation evidence id", max_length=512
        )
        if score is not None and not 0.0 <= float(score) <= 1.0:
            raise ValueError("validation score must be in [0, 1]")
        with self._lock, self.conn:
            exists = self.conn.execute(
                "SELECT id FROM experience_records WHERE id = ?", (experience_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(experience_id)
            try:
                self.conn.execute(
                    """
                    INSERT INTO experience_candidate_validations (
                        experience_id, evidence_id, successful, score,
                        created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experience_id,
                        evidence_id,
                        int(bool(successful)),
                        score,
                        _now(),
                        _json_dumps(dict(metadata or {})),
                    ),
                )
            except sqlite3.IntegrityError:
                row = self.conn.execute(
                    """
                    SELECT successful, score, metadata_json
                    FROM experience_candidate_validations
                    WHERE experience_id = ? AND evidence_id = ?
                    """,
                    (experience_id, evidence_id),
                ).fetchone()
                if (
                    bool(row["successful"]) != bool(successful)
                    or row["score"] != score
                    or _json_loads(row["metadata_json"], {}) != dict(metadata or {})
                ):
                    raise ValueError(
                        "validation evidence id already exists with different data"
                    ) from None
            else:
                self._audit(
                    "candidate_validated",
                    experience_id=experience_id,
                    metadata={
                        "evidence_id": evidence_id,
                        "successful": bool(successful),
                        "score": score,
                    },
                )
        return self.candidate_validation_summary(experience_id)

    def candidate_validation_summary(
        self, experience_id: str
    ) -> CandidateValidationSummary:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT evidence_id, successful, score
                FROM experience_candidate_validations
                WHERE experience_id = ?
                ORDER BY created_at, id
                """,
                (experience_id,),
            ).fetchall()
        successful = sum(int(bool(row["successful"])) for row in rows)
        scores = [float(row["score"]) for row in rows if row["score"] is not None]
        count = len(rows)
        return CandidateValidationSummary(
            experience_id=experience_id,
            validation_count=count,
            successful_count=successful,
            failed_count=count - successful,
            success_rate=successful / count if count else 0.0,
            average_score=sum(scores) / len(scores) if scores else None,
            evidence_ids=tuple(str(row["evidence_id"]) for row in rows),
        )

    def delete(
        self,
        experience_id: str,
        *,
        reason: str,
        actor: str,
    ) -> bool:
        reason = _require_text(reason, "delete reason", max_length=4096)
        actor = _require_text(actor, "delete actor", max_length=256)
        with self._lock, self.conn:
            row = self.conn.execute(
                """
                SELECT namespace, kind, trust, content_sha256
                FROM experience_records WHERE id = ?
                """,
                (experience_id,),
            ).fetchone()
            if row is None:
                return False
            self.conn.execute(
                "DELETE FROM experience_candidate_validations WHERE experience_id = ?",
                (experience_id,),
            )
            self.conn.execute(
                "DELETE FROM experience_records WHERE id = ?", (experience_id,)
            )
            self._audit(
                "deleted",
                experience_id=experience_id,
                metadata={
                    "reason": reason,
                    "actor": actor,
                    "namespace": row["namespace"],
                    "kind": row["kind"],
                    "trust": row["trust"],
                    "content_sha256": row["content_sha256"],
                },
            )
        return True

    def rollback(self, experience_id: str, *, reason: str) -> ExperienceRecord:
        reason = _require_text(reason, "rollback reason", max_length=4096)
        with self._lock, self.conn:
            current_row = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (experience_id,)
            ).fetchone()
            if current_row is None:
                raise KeyError(experience_id)
            current = _experience_from_row(current_row)
            if not current.supersedes_id:
                raise ValueError("experience has no prior version to roll back to")
            prior_row = self.conn.execute(
                "SELECT * FROM experience_records WHERE id = ?",
                (current.supersedes_id,),
            ).fetchone()
            if prior_row is None:
                raise ValueError("prior experience version is missing")
            prior = _experience_from_row(prior_row)
            now = _now()
            restored = replace(
                prior,
                id=_new_id("exp"),
                version=current.version + 1,
                status=ExperienceStatus.ACTIVE,
                supersedes_id=current.id,
                rollback_of_id=current.id,
                created_at=now,
                updated_at=now,
                metadata={
                    **prior.metadata,
                    "rollback_reason": reason,
                    "restored_from_id": prior.id,
                },
            )
            self.conn.execute(
                """
                UPDATE experience_records
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (ExperienceStatus.ROLLED_BACK.value, now, current.id),
            )
            self._insert_record(restored)
            self._audit(
                "rolled_back",
                experience_id=current.id,
                metadata={
                    "restored_id": restored.id,
                    "restored_from_id": prior.id,
                    "reason": reason,
                },
            )
        return restored

    def expire_due(self, *, now: float | None = None) -> int:
        cutoff = float(now if now is not None else _now())
        with self._lock, self.conn:
            rows = self.conn.execute(
                """
                SELECT id FROM experience_records
                WHERE expires_at IS NOT NULL
                  AND expires_at <= ?
                  AND status NOT IN (?, ?, ?, ?)
                """,
                (
                    cutoff,
                    ExperienceStatus.EXPIRED.value,
                    ExperienceStatus.REJECTED.value,
                    ExperienceStatus.SUPERSEDED.value,
                    ExperienceStatus.ROLLED_BACK.value,
                ),
            ).fetchall()
            ids = [str(row["id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                self.conn.execute(
                    f"""
                    UPDATE experience_records
                    SET status = ?, updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [ExperienceStatus.EXPIRED.value, cutoff, *ids],
                )
                for experience_id in ids:
                    self._audit(
                        "expired",
                        experience_id=experience_id,
                        metadata={"cutoff": cutoff},
                    )
        return len(ids)

    def ingest_trajectory(
        self,
        trajectory: ToolTrajectory,
        *,
        trust: TrustClass | str = TrustClass.TOOL_OUTPUT,
        status: ExperienceStatus | str = ExperienceStatus.SHADOW,
        confidence: float = 0.5,
    ) -> ExperienceIngestReport:
        trust = _coerce_enum(trust, TrustClass, "experience trust")
        status = _coerce_enum(status, ExperienceStatus, "experience status")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        with self._lock, self.conn:
            existing = self.conn.execute(
                """
                SELECT id, provider FROM experience_trajectories
                WHERE namespace = ? AND source_sha256 = ?
                """,
                (trajectory.namespace, trajectory.source_sha256),
            ).fetchone()
            if existing is not None:
                existing_id = str(existing["id"])
                experience_ids = tuple(
                    str(row["id"])
                    for row in self.conn.execute(
                        """
                        SELECT id FROM experience_records
                        WHERE trajectory_id = ?
                        ORDER BY created_at, id
                        """,
                        (existing_id,),
                    ).fetchall()
                )
                return ExperienceIngestReport(
                    trajectory_id=existing_id,
                    provider=str(existing["provider"]),
                    inserted=False,
                    step_count=self._trajectory_step_count(existing_id),
                    experience_ids=experience_ids,
                    source_sha256=trajectory.source_sha256,
                )
            id_row = self.conn.execute(
                "SELECT source_sha256 FROM experience_trajectories WHERE id = ?",
                (trajectory.id,),
            ).fetchone()
            if id_row is not None:
                raise ValueError(
                    f"trajectory id {trajectory.id!r} already exists with different data"
                )
            self.conn.execute(
                """
                INSERT INTO experience_trajectories (
                    id, namespace, provider, source_sha256, started_at, ended_at,
                    metadata_json, raw_event_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trajectory.id,
                    trajectory.namespace,
                    trajectory.provider,
                    trajectory.source_sha256,
                    trajectory.started_at,
                    trajectory.ended_at,
                    _json_dumps(trajectory.metadata),
                    int(trajectory.raw_event_count),
                    _now(),
                ),
            )
            for step in trajectory.steps:
                self.conn.execute(
                    """
                    INSERT INTO experience_trajectory_steps (
                        trajectory_id, step_id, sequence, kind, name, input_json,
                        output_json, success, started_at, finished_at, parent_id,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trajectory.id,
                        step.id,
                        int(step.sequence),
                        step.kind.value,
                        step.name,
                        _json_dumps(step.input),
                        _json_dumps(step.output),
                        None if step.success is None else int(step.success),
                        step.started_at,
                        step.finished_at,
                        step.parent_id,
                        _json_dumps(step.metadata),
                    ),
                )
            episode = experience_from_trajectory(
                trajectory,
                trust=trust,
                status=status,
                confidence=float(confidence),
            )
            self._insert_record(
                episode,
                dedupe_key=f"trajectory:{trajectory.namespace}:{trajectory.source_sha256}",
            )
            self._audit(
                "trajectory_ingested",
                experience_id=episode.id,
                trajectory_id=trajectory.id,
                metadata={
                    "provider": trajectory.provider,
                    "step_count": len(trajectory.steps),
                },
            )
        return ExperienceIngestReport(
            trajectory_id=trajectory.id,
            provider=trajectory.provider,
            inserted=True,
            step_count=len(trajectory.steps),
            experience_ids=(episode.id,),
            source_sha256=trajectory.source_sha256,
        )

    def get_trajectory(self, trajectory_id: str) -> ToolTrajectory | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM experience_trajectories WHERE id = ?",
                (trajectory_id,),
            ).fetchone()
            if row is None:
                return None
            step_rows = self.conn.execute(
                """
                SELECT * FROM experience_trajectory_steps
                WHERE trajectory_id = ?
                ORDER BY sequence
                """,
                (trajectory_id,),
            ).fetchall()
        return ToolTrajectory(
            id=str(row["id"]),
            provider=str(row["provider"]),
            namespace=str(row["namespace"]),
            source_sha256=str(row["source_sha256"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            metadata=_json_loads(row["metadata_json"], {}),
            raw_event_count=int(row["raw_event_count"]),
            steps=tuple(_trajectory_step_from_row(item) for item in step_rows),
        )

    def get_trajectory_by_source(
        self,
        *,
        namespace: str,
        source_sha256: str,
    ) -> ToolTrajectory | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id FROM experience_trajectories
                WHERE namespace = ? AND source_sha256 = ?
                """,
                (namespace, source_sha256),
            ).fetchone()
        return self.get_trajectory(str(row["id"])) if row is not None else None

    def list_for_trajectory(self, trajectory_id: str) -> list[ExperienceRecord]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM experience_records
                WHERE trajectory_id = ?
                ORDER BY created_at, id
                """,
                (trajectory_id,),
            ).fetchall()
        return [_experience_from_row(row) for row in rows]

    def list_trajectories(
        self,
        *,
        namespace: str | None = None,
        limit: int = 10_000,
    ) -> list[ToolTrajectory]:
        if not 1 <= int(limit) <= 100_000:
            raise ValueError("limit must be between 1 and 100000")
        query = "SELECT id FROM experience_trajectories"
        values: list[Any] = []
        if namespace is not None:
            query += " WHERE namespace = ?"
            values.append(namespace)
        query += " ORDER BY created_at, id LIMIT ?"
        values.append(int(limit))
        with self._lock:
            rows = self.conn.execute(query, values).fetchall()
        return [
            trajectory
            for row in rows
            if (trajectory := self.get_trajectory(str(row["id"]))) is not None
        ]

    def restore_trajectory(self, trajectory: ToolTrajectory) -> bool:
        with self._lock, self.conn:
            existing = self.conn.execute(
                "SELECT source_sha256 FROM experience_trajectories WHERE id = ?",
                (trajectory.id,),
            ).fetchone()
            if existing is not None:
                if str(existing["source_sha256"]) != trajectory.source_sha256:
                    raise ValueError(
                        f"trajectory id {trajectory.id!r} already exists with "
                        "different data"
                    )
                restored = self.get_trajectory(trajectory.id)
                if restored != trajectory:
                    raise ValueError(
                        f"trajectory id {trajectory.id!r} failed exact replay validation"
                    )
                return False
            digest_row = self.conn.execute(
                """
                SELECT id FROM experience_trajectories
                WHERE namespace = ? AND source_sha256 = ?
                """,
                (trajectory.namespace, trajectory.source_sha256),
            ).fetchone()
            if digest_row is not None:
                raise ValueError(
                    "trajectory source already exists under a different id: "
                    f"{digest_row['id']}"
                )
            self.conn.execute(
                """
                INSERT INTO experience_trajectories (
                    id, namespace, provider, source_sha256, started_at, ended_at,
                    metadata_json, raw_event_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trajectory.id,
                    trajectory.namespace,
                    trajectory.provider,
                    trajectory.source_sha256,
                    trajectory.started_at,
                    trajectory.ended_at,
                    _json_dumps(trajectory.metadata),
                    int(trajectory.raw_event_count),
                    _now(),
                ),
            )
            for step in trajectory.steps:
                self.conn.execute(
                    """
                    INSERT INTO experience_trajectory_steps (
                        trajectory_id, step_id, sequence, kind, name, input_json,
                        output_json, success, started_at, finished_at, parent_id,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trajectory.id,
                        step.id,
                        int(step.sequence),
                        step.kind.value,
                        step.name,
                        _json_dumps(step.input),
                        _json_dumps(step.output),
                        None if step.success is None else int(step.success),
                        step.started_at,
                        step.finished_at,
                        step.parent_id,
                        _json_dumps(step.metadata),
                    ),
                )
            self._audit(
                "trajectory_restored",
                trajectory_id=trajectory.id,
                metadata={"source_sha256": trajectory.source_sha256},
            )
        return True

    def candidate_validations(
        self,
        *,
        experience_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT experience_id, evidence_id, successful, score,
                   created_at, metadata_json
            FROM experience_candidate_validations
        """
        values: list[Any] = []
        if experience_id is not None:
            query += " WHERE experience_id = ?"
            values.append(experience_id)
        query += " ORDER BY experience_id, created_at, id"
        with self._lock:
            rows = self.conn.execute(query, values).fetchall()
        return [
            {
                "experience_id": str(row["experience_id"]),
                "evidence_id": str(row["evidence_id"]),
                "successful": bool(row["successful"]),
                "score": row["score"],
                "created_at": float(row["created_at"]),
                "metadata": _json_loads(row["metadata_json"], {}),
            }
            for row in rows
        ]

    def audit_events(
        self,
        *,
        experience_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 100,
    ) -> list[ExperienceAuditEvent]:
        clauses = []
        values: list[Any] = []
        if experience_id is not None:
            clauses.append("experience_id = ?")
            values.append(experience_id)
        if trajectory_id is not None:
            clauses.append("trajectory_id = ?")
            values.append(trajectory_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(int(limit))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM experience_audit_events
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [
            ExperienceAuditEvent(
                id=int(row["id"]),
                action=str(row["action"]),
                created_at=float(row["created_at"]),
                experience_id=row["experience_id"],
                trajectory_id=row["trajectory_id"],
                metadata=_json_loads(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _insert_record(
        self,
        record: ExperienceRecord,
        *,
        dedupe_key: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO experience_records (
                id, namespace, kind, title, content, applicability_json,
                outcome_json, confidence, trust, source_json, observed_at,
                created_at, updated_at, trajectory_id, trajectory_json,
                expires_at, version, status, supersedes_id, rollback_of_id,
                metadata_json, content_sha256, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.namespace,
                record.kind.value,
                record.title,
                record.content,
                _json_dumps(record.applicability.as_dict()),
                _json_dumps(record.outcome.as_dict()),
                float(record.confidence),
                record.trust.value,
                _json_dumps(record.source.as_dict()),
                float(record.observed_at),
                float(record.created_at),
                float(record.updated_at),
                record.trajectory.trajectory_id if record.trajectory else None,
                _json_dumps(record.trajectory.as_dict())
                if record.trajectory
                else None,
                record.expires_at,
                int(record.version),
                record.status.value,
                record.supersedes_id,
                record.rollback_of_id,
                _json_dumps(record.metadata),
                record.content_sha256,
                dedupe_key,
            ),
        )

    def _audit(
        self,
        action: str,
        *,
        experience_id: str | None = None,
        trajectory_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO experience_audit_events (
                action, created_at, experience_id, trajectory_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                action,
                _now(),
                experience_id,
                trajectory_id,
                _json_dumps(dict(metadata or {})),
            ),
        )

    def _trajectory_step_count(self, trajectory_id: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM experience_trajectory_steps
            WHERE trajectory_id = ?
            """,
            (trajectory_id,),
        ).fetchone()
        return int(row["count"])


def parse_tool_trajectory(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    provider: str | None = None,
    namespace: str = "default",
    trajectory_id: str | None = None,
) -> ToolTrajectory:
    raw_payload: Any = list(payload) if _is_sequence(payload) else dict(payload)
    selected_provider = (
        provider
        or (
            str(payload.get("provider") or "")
            if isinstance(payload, Mapping)
            else ""
        )
        or _detect_provider(raw_payload)
    ).strip().lower()
    if selected_provider in {"openai", "openai_agents", "openai_responses"}:
        steps = _parse_openai_steps(raw_payload)
        normalized_provider = "openai"
    elif selected_provider in {"anthropic", "claude"}:
        steps = _parse_anthropic_steps(raw_payload)
        normalized_provider = "anthropic"
    elif selected_provider in {"mcp", "model_context_protocol"}:
        steps = _parse_mcp_steps(raw_payload)
        normalized_provider = "mcp"
    elif selected_provider in {"generic", "jsonl", "wavemind"}:
        steps = _parse_generic_steps(raw_payload)
        normalized_provider = "generic"
    else:
        raise ValueError(
            "provider must be openai, anthropic, mcp, generic, or jsonl"
        )
    if not steps:
        raise ValueError("trajectory payload did not contain any usable steps")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    selected_id = (
        trajectory_id
        or _optional_text(payload_mapping.get("trajectory_id"))
        or _optional_text(payload_mapping.get("id"))
        or f"traj_{_sha256(raw_payload)[:24]}"
    )
    return ToolTrajectory(
        id=selected_id,
        provider=normalized_provider,
        namespace=namespace,
        steps=tuple(replace(step, sequence=index) for index, step in enumerate(steps)),
        source_sha256=_sha256(raw_payload),
        started_at=_optional_float(payload_mapping.get("started_at")),
        ended_at=_optional_float(payload_mapping.get("ended_at")),
        metadata={
            key: value
            for key, value in dict(payload_mapping.get("metadata") or {}).items()
        },
        raw_event_count=_raw_event_count(raw_payload),
    )


def iter_jsonl_trajectories(
    path: str | Path,
    *,
    provider: str | None = None,
    namespace: str = "default",
    max_line_bytes: int = 2 * 1024 * 1024,
) -> Iterator[ToolTrajectory]:
    if int(max_line_bytes) < 1:
        raise ValueError("max_line_bytes must be positive")
    path = Path(path)
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if len(raw_line) > int(max_line_bytes):
                raise ValueError(
                    f"{path}:{line_number} exceeds the JSONL line size limit"
                )
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(payload, (dict, list)):
                raise ValueError(
                    f"trajectory at {path}:{line_number} must be an object or array"
                )
            yield parse_tool_trajectory(
                payload,
                provider=provider,
                namespace=namespace,
            )


def ingest_jsonl_trajectories(
    store: SQLiteExperienceStore,
    path: str | Path,
    *,
    provider: str | None = None,
    namespace: str = "default",
    trust: TrustClass | str = TrustClass.IMPORTED,
    status: ExperienceStatus | str = ExperienceStatus.SHADOW,
    confidence: float = 0.5,
    max_line_bytes: int = 2 * 1024 * 1024,
) -> list[ExperienceIngestReport]:
    return [
        store.ingest_trajectory(
            trajectory,
            trust=trust,
            status=status,
            confidence=confidence,
        )
        for trajectory in iter_jsonl_trajectories(
            path,
            provider=provider,
            namespace=namespace,
            max_line_bytes=max_line_bytes,
        )
    ]


def experience_from_trajectory(
    trajectory: ToolTrajectory,
    *,
    trust: TrustClass | str = TrustClass.TOOL_OUTPUT,
    status: ExperienceStatus | str = ExperienceStatus.SHADOW,
    confidence: float = 0.5,
) -> ExperienceRecord:
    tool_calls = [
        step.name or "unnamed_tool"
        for step in trajectory.steps
        if step.kind == TrajectoryStepKind.TOOL_CALL
    ]
    failures = [
        step
        for step in trajectory.steps
        if step.kind == TrajectoryStepKind.TOOL_RESULT and step.success is False
    ]
    unique_tools = tuple(dict.fromkeys(tool_calls))
    if unique_tools:
        tool_summary = ", ".join(unique_tools)
        content = (
            f"Agent trajectory used {tool_summary} across {len(trajectory.steps)} "
            f"recorded steps."
        )
    else:
        content = f"Agent trajectory contained {len(trajectory.steps)} recorded steps."
    if failures:
        content += f" {len(failures)} tool result(s) failed."
    elif trajectory.success is True:
        content += " All recorded tool results succeeded."
    provenance = TrajectoryProvenance(
        trajectory_id=trajectory.id,
        step_ids=tuple(step.id for step in trajectory.steps),
        source_sha256=trajectory.source_sha256,
        raw_event_count=trajectory.raw_event_count,
    )
    return ExperienceRecord.create(
        kind=ExperienceKind.EPISODE,
        title=f"{trajectory.provider} agent trajectory",
        content=content,
        namespace=trajectory.namespace,
        applicability=ExperienceApplicability(tools=unique_tools),
        outcome=ExperienceOutcome(
            success=trajectory.success,
            score=(
                1.0
                if trajectory.success is True
                else 0.0
                if trajectory.success is False
                else None
            ),
            summary=(
                "Recorded tool execution completed successfully."
                if trajectory.success is True
                else "Recorded tool execution contains a failed result."
                if trajectory.success is False
                else "The source did not include a final success signal."
            ),
            metrics={
                "step_count": float(len(trajectory.steps)),
                "tool_call_count": float(len(tool_calls)),
                "failure_count": float(len(failures)),
            },
        ),
        confidence=confidence,
        trust=trust,
        source=ExperienceSource(
            provider=trajectory.provider,
            source_type="tool_trajectory",
            source_id=trajectory.id,
            metadata={"source_sha256": trajectory.source_sha256},
        ),
        observed_at=trajectory.ended_at or trajectory.started_at,
        trajectory=provenance,
        status=status,
        metadata={"trajectory_provider": trajectory.provider},
    )


def _parse_generic_steps(payload: Any) -> list[TrajectoryStep]:
    source = payload.get("steps") if isinstance(payload, Mapping) else payload
    if not _is_sequence(source):
        raise ValueError("generic trajectory payload requires a steps array")
    return [
        TrajectoryStep.from_dict(item, sequence=index)
        for index, item in enumerate(source)
        if isinstance(item, Mapping)
    ]


def _parse_openai_steps(payload: Any) -> list[TrajectoryStep]:
    events = _event_sequence(payload, keys=("output", "events", "spans", "items"))
    steps: list[TrajectoryStep] = []
    calls: dict[str, int] = {}
    for event in events:
        item = event.get("item") if isinstance(event.get("item"), Mapping) else event
        span_data = (
            item.get("span_data")
            if isinstance(item.get("span_data"), Mapping)
            else item
        )
        event_type = str(
            span_data.get("type") or item.get("type") or event.get("type") or ""
        ).lower()
        if event_type in {"function_call", "tool_call", "function"}:
            call_id = str(
                span_data.get("call_id")
                or span_data.get("id")
                or item.get("call_id")
                or item.get("id")
                or _new_id("call")
            )
            arguments = (
                span_data.get("arguments")
                if "arguments" in span_data
                else span_data.get("input")
            )
            step = TrajectoryStep(
                id=call_id,
                sequence=len(steps),
                kind=TrajectoryStepKind.TOOL_CALL,
                name=_optional_text(span_data.get("name")),
                input=_decode_json_string(arguments),
                started_at=_optional_float(span_data.get("started_at")),
                finished_at=_optional_float(span_data.get("finished_at")),
                metadata={"provider_event_type": event_type},
            )
            calls[call_id] = len(steps)
            steps.append(step)
            if "output" in span_data:
                result_id = f"{call_id}:result"
                output = span_data.get("output")
                steps.append(
                    TrajectoryStep(
                        id=result_id,
                        sequence=len(steps),
                        kind=TrajectoryStepKind.TOOL_RESULT,
                        name=step.name,
                        output=_decode_json_string(output),
                        success=not _looks_like_error(output),
                        parent_id=call_id,
                        metadata={"provider_event_type": "function_span_result"},
                    )
                )
        elif event_type in {"function_call_output", "tool_result"}:
            call_id = str(
                span_data.get("call_id")
                or span_data.get("tool_call_id")
                or span_data.get("id")
                or _new_id("call")
            )
            output = span_data.get("output", span_data.get("result"))
            name = None
            if call_id in calls:
                name = steps[calls[call_id]].name
            steps.append(
                TrajectoryStep(
                    id=f"{call_id}:result",
                    sequence=len(steps),
                    kind=TrajectoryStepKind.TOOL_RESULT,
                    name=name,
                    output=_decode_json_string(output),
                    success=not _looks_like_error(output),
                    parent_id=call_id,
                    metadata={"provider_event_type": event_type},
                )
            )
        elif event_type == "message":
            steps.append(
                TrajectoryStep(
                    id=str(span_data.get("id") or _new_id("msg")),
                    sequence=len(steps),
                    kind=TrajectoryStepKind.MESSAGE,
                    input=span_data.get("content"),
                    metadata={
                        "role": span_data.get("role"),
                        "provider_event_type": event_type,
                    },
                )
            )
    return steps


def _parse_anthropic_steps(payload: Any) -> list[TrajectoryStep]:
    messages = _event_sequence(payload, keys=("messages", "events", "content"))
    steps: list[TrajectoryStep] = []
    call_names: dict[str, str | None] = {}
    for message in messages:
        role = message.get("role")
        blocks = message.get("content")
        if not _is_sequence(blocks):
            blocks = [message]
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            block_type = str(block.get("type") or "").lower()
            if block_type == "tool_use":
                call_id = str(block.get("id") or _new_id("call"))
                name = _optional_text(block.get("name"))
                call_names[call_id] = name
                steps.append(
                    TrajectoryStep(
                        id=call_id,
                        sequence=len(steps),
                        kind=TrajectoryStepKind.TOOL_CALL,
                        name=name,
                        input=block.get("input"),
                        metadata={"role": role, "provider_event_type": block_type},
                    )
                )
            elif block_type == "tool_result":
                call_id = str(block.get("tool_use_id") or _new_id("call"))
                is_error = bool(block.get("is_error", False))
                steps.append(
                    TrajectoryStep(
                        id=f"{call_id}:result",
                        sequence=len(steps),
                        kind=TrajectoryStepKind.TOOL_RESULT,
                        name=call_names.get(call_id),
                        output=block.get("content"),
                        success=not is_error,
                        parent_id=call_id,
                        metadata={"role": role, "provider_event_type": block_type},
                    )
                )
            elif block_type in {"text", "thinking"}:
                steps.append(
                    TrajectoryStep(
                        id=str(block.get("id") or _new_id("msg")),
                        sequence=len(steps),
                        kind=TrajectoryStepKind.MESSAGE,
                        input=block.get("text", block.get("thinking")),
                        metadata={"role": role, "provider_event_type": block_type},
                    )
                )
    return steps


def _parse_mcp_steps(payload: Any) -> list[TrajectoryStep]:
    events = _event_sequence(payload, keys=("events", "messages", "items"))
    steps: list[TrajectoryStep] = []
    calls: dict[str, str | None] = {}
    for event in events:
        request = (
            event.get("request")
            if isinstance(event.get("request"), Mapping)
            else event
        )
        response = (
            event.get("response")
            if isinstance(event.get("response"), Mapping)
            else None
        )
        method = str(request.get("method") or "")
        if method == "tools/call":
            call_id = str(request.get("id") or _new_id("call"))
            params = request.get("params") or {}
            if not isinstance(params, Mapping):
                params = {}
            name = _optional_text(params.get("name"))
            calls[call_id] = name
            steps.append(
                TrajectoryStep(
                    id=call_id,
                    sequence=len(steps),
                    kind=TrajectoryStepKind.TOOL_CALL,
                    name=name,
                    input=params.get("arguments"),
                    metadata={"method": method},
                )
            )
            if response is not None:
                steps.append(_mcp_result_step(call_id, name, response, len(steps)))
        elif response is not None:
            call_id = str(response.get("id") or request.get("id") or "")
            if call_id and call_id in calls:
                steps.append(
                    _mcp_result_step(
                        call_id,
                        calls.get(call_id),
                        response,
                        len(steps),
                    )
                )
        elif "result" in event or "error" in event:
            call_id = str(event.get("id") or "")
            if call_id and call_id in calls:
                steps.append(
                    _mcp_result_step(
                        call_id,
                        calls.get(call_id),
                        event,
                        len(steps),
                    )
                )
    return steps


def _mcp_result_step(
    call_id: str,
    name: str | None,
    response: Mapping[str, Any],
    sequence: int,
) -> TrajectoryStep:
    failed = "error" in response or bool(
        isinstance(response.get("result"), Mapping)
        and response["result"].get("isError")
    )
    return TrajectoryStep(
        id=f"{call_id}:result",
        sequence=sequence,
        kind=TrajectoryStepKind.TOOL_RESULT,
        name=name,
        output=response.get("error", response.get("result")),
        success=not failed,
        parent_id=call_id,
        metadata={"method": "tools/call"},
    )


def _event_sequence(payload: Any, *, keys: Sequence[str]) -> list[Mapping[str, Any]]:
    if _is_sequence(payload):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in keys:
        value = payload.get(key)
        if _is_sequence(value):
            return [item for item in value if isinstance(item, Mapping)]
    return [payload]


def _detect_provider(payload: Any) -> str:
    events = _event_sequence(payload, keys=("events", "messages", "output", "items"))
    for event in events:
        method = str(event.get("method") or "")
        if method.startswith("tools/"):
            return "mcp"
        blocks = event.get("content")
        if _is_sequence(blocks) and any(
            isinstance(block, Mapping)
            and block.get("type") in {"tool_use", "tool_result"}
            for block in blocks
        ):
            return "anthropic"
        event_type = str(event.get("type") or "")
        if event_type in {
            "function_call",
            "function_call_output",
            "response.output_item.added",
        }:
            return "openai"
    if isinstance(payload, Mapping) and "steps" in payload:
        return "generic"
    raise ValueError("could not detect trajectory provider")


def _experience_from_row(row: sqlite3.Row) -> ExperienceRecord:
    trajectory = _json_loads(row["trajectory_json"], None)
    return ExperienceRecord(
        id=str(row["id"]),
        namespace=str(row["namespace"]),
        kind=ExperienceKind(str(row["kind"])),
        title=str(row["title"]),
        content=str(row["content"]),
        applicability=ExperienceApplicability.from_dict(
            _json_loads(row["applicability_json"], {})
        ),
        outcome=ExperienceOutcome.from_dict(_json_loads(row["outcome_json"], {})),
        confidence=float(row["confidence"]),
        trust=TrustClass(str(row["trust"])),
        source=ExperienceSource.from_dict(_json_loads(row["source_json"], {})),
        observed_at=float(row["observed_at"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        trajectory=TrajectoryProvenance.from_dict(trajectory) if trajectory else None,
        expires_at=row["expires_at"],
        version=int(row["version"]),
        status=ExperienceStatus(str(row["status"])),
        supersedes_id=row["supersedes_id"],
        rollback_of_id=row["rollback_of_id"],
        metadata=_json_loads(row["metadata_json"], {}),
    )


def _trajectory_step_from_row(row: sqlite3.Row) -> TrajectoryStep:
    success = row["success"]
    return TrajectoryStep(
        id=str(row["step_id"]),
        sequence=int(row["sequence"]),
        kind=TrajectoryStepKind(str(row["kind"])),
        name=row["name"],
        input=_json_loads(row["input_json"], None),
        output=_json_loads(row["output_json"], None),
        success=None if success is None else bool(success),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        parent_id=row["parent_id"],
        metadata=_json_loads(row["metadata_json"], {}),
    )


def _normalized_strings(values: Iterable[Any]) -> tuple[str, ...]:
    normalized = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(normalized)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _decode_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _looks_like_error(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value.get("error") or value.get("is_error") or value.get("isError"))
    return False


def _raw_event_count(payload: Any) -> int:
    if _is_sequence(payload):
        return len(payload)
    if isinstance(payload, Mapping):
        for key in ("steps", "events", "messages", "output", "items", "spans"):
            value = payload.get(key)
            if _is_sequence(value):
                return len(value)
    return 1
