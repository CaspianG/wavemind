from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class MemoryPayload:
    kind: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


def image_payload(
    uri: str | Path,
    *,
    caption: str,
    alt_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    return _payload(
        "image",
        {
            "caption": caption,
            "alt_text": alt_text or "",
            "uri": str(uri),
        },
        metadata=metadata,
        tags=tags,
    )


def audio_payload(
    uri: str | Path,
    *,
    transcript: str,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    return _payload(
        "audio",
        {
            "transcript": transcript,
            "summary": summary or "",
            "uri": str(uri),
        },
        metadata=metadata,
        tags=tags,
    )


def video_payload(
    uri: str | Path,
    *,
    transcript: str | None = None,
    summary: str,
    scenes: Sequence[str] | None = None,
    duration_seconds: float | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    payload_metadata = dict(metadata or {})
    if duration_seconds is not None:
        payload_metadata["duration_seconds"] = float(duration_seconds)
    return _payload(
        "video",
        {
            "summary": summary,
            "transcript": transcript or "",
            "scenes": json.dumps(list(scenes or ()), ensure_ascii=False),
            "duration_seconds": "" if duration_seconds is None else str(float(duration_seconds)),
            "uri": str(uri),
        },
        metadata=payload_metadata,
        tags=tags,
    )


def asset3d_payload(
    uri: str | Path,
    *,
    description: str,
    format: str | None = None,
    labels: Sequence[str] | None = None,
    dimensions: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    return _payload(
        "3d",
        {
            "description": description,
            "format": format or "",
            "labels": json.dumps(list(labels or ()), ensure_ascii=False),
            "dimensions": json.dumps(dimensions or {}, ensure_ascii=False, sort_keys=True),
            "uri": str(uri),
        },
        metadata=metadata,
        tags=tags,
    )


def graph_payload(
    triples: Sequence[tuple[str, str, str] | dict[str, Any]],
    *,
    title: str,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    normalized = [_normalize_triple(triple) for triple in triples]
    return _payload(
        "graph",
        {
            "title": title,
            "summary": summary or "",
            "triples": json.dumps(normalized[:12], ensure_ascii=False, sort_keys=True),
            "triple_count": str(len(normalized)),
        },
        metadata={**(metadata or {}), "triple_count": len(normalized)},
        tags=tags,
    )


def table_payload(
    rows: Sequence[dict[str, Any]],
    *,
    title: str,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    preview = rows[:5]
    return _payload(
        "table",
        {
            "title": title,
            "rows": json.dumps(preview, ensure_ascii=False, sort_keys=True),
            "row_count": str(len(rows)),
        },
        metadata={**(metadata or {}), "row_count": len(rows)},
        tags=tags,
    )


def event_payload(
    name: str,
    *,
    actor: str | None = None,
    timestamp: str | None = None,
    properties: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    return _payload(
        "event",
        {
            "name": name,
            "actor": actor or "",
            "timestamp": timestamp or "",
            "properties": json.dumps(properties or {}, ensure_ascii=False, sort_keys=True),
        },
        metadata=metadata,
        tags=tags,
    )


def remember_payload(
    memory: Any,
    payload: MemoryPayload,
    *,
    namespace: str = "default",
    ttl_seconds: float | None = None,
    priority: float = 1.0,
) -> int:
    metadata = {
        "modality": payload.kind,
        "source": "wavemind_payload",
        **payload.metadata,
    }
    tags = tuple(dict.fromkeys((*payload.tags, payload.kind)))
    return int(
        memory.remember(
            payload.text,
            namespace=namespace,
            tags=tags,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            priority=priority,
        )
    )


def _payload(
    kind: str,
    fields: dict[str, str],
    *,
    metadata: dict[str, Any] | None,
    tags: Iterable[str] | None,
) -> MemoryPayload:
    text = " | ".join(
        f"{key}: {value}"
        for key, value in fields.items()
        if str(value).strip()
    )
    return MemoryPayload(
        kind=kind,
        text=f"{kind} memory | {text}",
        metadata={**fields, **(metadata or {})},
        tags=tuple(dict.fromkeys(tags or ())),
    )


def _normalize_triple(triple: tuple[str, str, str] | dict[str, Any]) -> dict[str, str]:
    if isinstance(triple, dict):
        subject = triple.get("subject", triple.get("s", ""))
        predicate = triple.get("predicate", triple.get("p", ""))
        object_value = triple.get("object", triple.get("o", ""))
    else:
        subject, predicate, object_value = triple
    return {
        "subject": str(subject),
        "predicate": str(predicate),
        "object": str(object_value),
    }
