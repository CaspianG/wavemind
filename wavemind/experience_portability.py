from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .experience import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    ToolTrajectory,
    TrajectoryStep,
    TrustClass,
)


PORTABLE_EXPERIENCE_SCHEMA = "wavemind.portable_experience.v1"


@dataclass(frozen=True)
class PortableImportReport:
    record_count: int
    trajectory_count: int
    validation_count: int
    inserted_records: int
    inserted_trajectories: int
    parity: float
    source_sha256: str

    @property
    def exact(self) -> bool:
        return self.parity == 1.0


def export_experience_bundle(
    store: SQLiteExperienceStore,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    records = store.list(
        namespace=namespace,
        include_expired=True,
        limit=10_000,
    )
    trajectories = store.list_trajectories(namespace=namespace, limit=100_000)
    validations = [
        row
        for row in store.candidate_validations()
        if namespace is None
        or (
            (record := store.get(str(row["experience_id"]))) is not None
            and record.namespace == namespace
        )
    ]
    payload = {
        "schema": PORTABLE_EXPERIENCE_SCHEMA,
        "namespace": namespace,
        "records": [record.as_dict() for record in records],
        "trajectories": [trajectory.as_dict() for trajectory in trajectories],
        "validations": validations,
        "manifest": {
            "record_count": len(records),
            "trajectory_count": len(trajectories),
            "validation_count": len(validations),
        },
    }
    payload["content_sha256"] = _bundle_sha256(payload)
    return payload


def write_experience_bundle(
    store: SQLiteExperienceStore,
    path: str | Path,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    payload = export_experience_bundle(store, namespace=namespace)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def load_experience_bundle(
    source: str | Path | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(source, Mapping):
        payload = dict(source)
    else:
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if payload.get("schema") != PORTABLE_EXPERIENCE_SCHEMA:
        raise ValueError("unsupported portable experience bundle schema")
    expected = str(payload.get("content_sha256") or "")
    if len(expected) != 64 or _bundle_sha256(payload) != expected:
        raise ValueError("portable experience bundle checksum mismatch")
    manifest = payload.get("manifest") or {}
    for key, collection in (
        ("record_count", payload.get("records") or []),
        ("trajectory_count", payload.get("trajectories") or []),
        ("validation_count", payload.get("validations") or []),
    ):
        if int(manifest.get(key, -1)) != len(collection):
            raise ValueError(f"portable experience manifest {key} mismatch")
    return payload


def import_experience_bundle(
    store: SQLiteExperienceStore,
    source: str | Path | Mapping[str, Any],
) -> PortableImportReport:
    payload = load_experience_bundle(source)
    inserted_records = 0
    inserted_trajectories = 0
    for row in payload.get("records") or []:
        record = ExperienceRecord.from_dict(row)
        existing = store.get(record.id)
        stored = store.put(record)
        inserted_records += int(existing is None)
        if stored.as_dict() != record.as_dict():
            raise ValueError(f"experience replay mismatch for {record.id}")
    for row in payload.get("trajectories") or []:
        trajectory = _trajectory_from_dict(row)
        inserted_trajectories += int(store.restore_trajectory(trajectory))
    for row in payload.get("validations") or []:
        store.add_candidate_validation(
            str(row["experience_id"]),
            evidence_id=str(row["evidence_id"]),
            successful=bool(row["successful"]),
            score=row.get("score"),
            metadata=dict(row.get("metadata") or {}),
        )
    replayed = export_experience_bundle(
        store,
        namespace=payload.get("namespace"),
    )
    parity = experience_bundle_parity(payload, replayed)
    return PortableImportReport(
        record_count=len(payload.get("records") or []),
        trajectory_count=len(payload.get("trajectories") or []),
        validation_count=len(payload.get("validations") or []),
        inserted_records=inserted_records,
        inserted_trajectories=inserted_trajectories,
        parity=parity,
        source_sha256=str(payload["content_sha256"]),
    )


def experience_bundle_parity(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
) -> float:
    source_keys = _semantic_keys(source)
    target_keys = _semantic_keys(target)
    if not source_keys and not target_keys:
        return 1.0
    union = source_keys | target_keys
    return len(source_keys & target_keys) / len(union)


def import_mem0_json(
    store: SQLiteExperienceStore,
    source: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    namespace: str = "default",
) -> list[ExperienceRecord]:
    payload = _load_json_source(source)
    if isinstance(payload, Mapping):
        rows = payload.get("results") or payload.get("memories") or payload.get("data")
        if rows is None and ("memory" in payload or "text" in payload):
            rows = [payload]
    else:
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("Mem0 import requires a memory array")
    imported = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"Mem0 memory at index {index} must be an object")
        content = str(row.get("memory") or row.get("text") or "").strip()
        if not content:
            continue
        source_id = str(row.get("id") or row.get("memory_id") or f"mem0-{index}")
        metadata = dict(row.get("metadata") or {})
        record = ExperienceRecord.create(
            id=_import_id("mem0", namespace, source_id),
            kind=_kind_from_metadata(metadata),
            title=str(metadata.get("title") or f"Imported Mem0 memory {index + 1}"),
            content=content,
            source=ExperienceSource(
                provider="mem0",
                source_type="memory_export",
                source_id=source_id,
                metadata={"original_metadata": metadata},
            ),
            namespace=namespace,
            confidence=float(row.get("confidence") or metadata.get("confidence") or 0.5),
            trust=TrustClass.IMPORTED,
            status=ExperienceStatus.SHADOW,
            metadata={"import_format": "mem0", **metadata},
        )
        imported.append(
            _put_imported(
                store,
                record,
                dedupe_key=f"mem0:{namespace}:{source_id}",
            )
        )
    return imported


def import_conversation_jsonl(
    store: SQLiteExperienceStore,
    path: str | Path,
    *,
    namespace: str = "default",
    max_line_bytes: int = 2 * 1024 * 1024,
) -> list[ExperienceRecord]:
    imported = []
    with Path(path).open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if len(raw) > max_line_bytes:
                raise ValueError(f"conversation line {line_number} exceeds size limit")
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, Mapping):
                raise ValueError(f"conversation line {line_number} must be an object")
            content = _conversation_content(row.get("content"))
            if not content:
                continue
            role = str(row.get("role") or "unknown")
            source_id = str(
                row.get("id")
                or row.get("message_id")
                or f"{Path(path).name}:{line_number}"
            )
            record = ExperienceRecord.create(
                id=_import_id("chat", namespace, source_id),
                kind=(
                    ExperienceKind.PREFERENCE
                    if role == "user" and row.get("preference") is True
                    else ExperienceKind.EPISODE
                ),
                title=f"Imported {role} message",
                content=content,
                source=ExperienceSource(
                    provider=str(row.get("provider") or "conversation_jsonl"),
                    source_type="conversation_message",
                    source_id=source_id,
                    metadata={"role": role},
                ),
                namespace=namespace,
                confidence=0.5,
                trust=(
                    TrustClass.EXPLICIT_USER
                    if role == "user"
                    else TrustClass.IMPORTED
                ),
                status=ExperienceStatus.SHADOW,
                metadata={"import_format": "conversation_jsonl", "role": role},
            )
            imported.append(
                _put_imported(
                    store,
                    record,
                    dedupe_key=f"chat:{namespace}:{source_id}",
                )
            )
    return imported


def import_anthropic_memory(
    store: SQLiteExperienceStore,
    source: str | Path | Mapping[str, str],
    *,
    namespace: str = "default",
) -> list[ExperienceRecord]:
    files: dict[str, str] = {}
    if isinstance(source, Mapping):
        files = {str(path): str(content) for path, content in source.items()}
    else:
        root = Path(source)
        if root.is_file():
            files[f"/memories/{root.name}"] = root.read_text(encoding="utf-8")
        else:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    files[f"/memories/{relative}"] = path.read_text(encoding="utf-8")
    imported = []
    for path, content in files.items():
        normalized = validate_anthropic_memory_path(path)
        if normalized == "/memories":
            continue
        source_id = normalized
        record = ExperienceRecord.create(
            id=_import_id("anthropic", namespace, source_id),
            kind=ExperienceKind.PROCEDURE,
            title=PurePosixPath(normalized).name,
            content=content,
            source=ExperienceSource(
                provider="anthropic",
                source_type="memory_tool_file",
                source_id=source_id,
                uri=normalized,
            ),
            namespace=namespace,
            confidence=0.5,
            trust=TrustClass.IMPORTED,
            status=ExperienceStatus.SHADOW,
            metadata={"import_format": "anthropic_memory", "path": normalized},
        )
        imported.append(
            _put_imported(
                store,
                record,
                dedupe_key=f"anthropic:{namespace}:{normalized}",
            )
        )
    return imported


def _semantic_keys(payload: Mapping[str, Any]) -> set[str]:
    keys = {
        "record:" + hashlib.sha256(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for row in payload.get("records") or []
    }
    keys.update(
        f"trajectory:{row.get('id')}:{row.get('source_sha256')}"
        for row in payload.get("trajectories") or []
    )
    keys.update(
        "validation:"
        + ":".join(
            (
                str(row.get("experience_id")),
                str(row.get("evidence_id")),
                str(bool(row.get("successful"))),
                str(row.get("score")),
                hashlib.sha256(
                    json.dumps(
                        row.get("metadata") or {},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            )
        )
        for row in payload.get("validations") or []
    )
    return keys


def _bundle_sha256(payload: Mapping[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _import_id(provider: str, namespace: str, source_id: str) -> str:
    digest = hashlib.sha256(
        f"{provider}\0{namespace}\0{source_id}".encode("utf-8")
    ).hexdigest()
    return f"exp_{provider}_{digest[:24]}"


def _put_imported(
    store: SQLiteExperienceStore,
    record: ExperienceRecord,
    *,
    dedupe_key: str,
) -> ExperienceRecord:
    existing = store.get(record.id)
    if existing is None:
        return store.put(record, dedupe_key=dedupe_key)
    comparable_fields = (
        "id",
        "namespace",
        "kind",
        "title",
        "content",
        "applicability",
        "outcome",
        "confidence",
        "trust",
        "source",
        "trajectory",
        "expires_at",
        "status",
        "supersedes_id",
        "rollback_of_id",
        "metadata",
    )
    if any(getattr(existing, name) != getattr(record, name) for name in comparable_fields):
        raise ValueError(
            f"import source for experience {record.id!r} changed since first import"
        )
    return existing


def _trajectory_from_dict(value: Mapping[str, Any]) -> ToolTrajectory:
    return ToolTrajectory(
        id=str(value["id"]),
        provider=str(value["provider"]),
        namespace=str(value.get("namespace") or "default"),
        steps=tuple(
            TrajectoryStep.from_dict(row, sequence=index)
            for index, row in enumerate(value.get("steps") or [])
        ),
        source_sha256=str(value["source_sha256"]),
        started_at=value.get("started_at"),
        ended_at=value.get("ended_at"),
        metadata=dict(value.get("metadata") or {}),
        raw_event_count=int(value.get("raw_event_count") or 0),
    )


def _load_json_source(
    source: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> Any:
    if isinstance(source, (str, Path)):
        return json.loads(Path(source).read_text(encoding="utf-8"))
    return source


def _kind_from_metadata(metadata: Mapping[str, Any]) -> ExperienceKind:
    value = str(metadata.get("type") or metadata.get("kind") or "fact")
    try:
        return ExperienceKind(value)
    except ValueError:
        return ExperienceKind.FACT


def _conversation_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence):
        parts = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return ""


def validate_anthropic_memory_path(value: str) -> str:
    raw = str(value).replace("\\", "/")
    lowered = raw.lower()
    if "%2e" in lowered or "%2f" in lowered or "%5c" in lowered:
        raise ValueError("Anthropic memory path contains encoded traversal")
    path = PurePosixPath(raw)
    if not raw.startswith("/memories") or ".." in path.parts:
        raise ValueError("Anthropic memory paths must stay under /memories")
    normalized = "/" + "/".join(part for part in path.parts if part != "/")
    if normalized != "/memories" and not normalized.startswith("/memories/"):
        raise ValueError("Anthropic memory paths must stay under /memories")
    return normalized
