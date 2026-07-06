from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .encoders import HashingTextEncoder, TextEncoder


_CROSS_MODAL_VERSION = "wavemind.cross_modal.v1"
_MODALITY_ALIASES: dict[str, tuple[str, ...]] = {
    "image": ("image", "visual", "picture", "chart", "screenshot", "diagram", "caption"),
    "audio": ("audio", "voice", "speech", "call", "meeting", "transcript", "recording"),
    "table": ("table", "spreadsheet", "metric", "rows", "columns", "numbers", "dataset"),
    "event": ("event", "timeline", "timestamp", "action", "actor", "state change"),
    "video": ("video", "clip", "scene", "demo", "recording", "frames", "transcript"),
    "3d": ("3d", "model", "mesh", "asset", "geometry", "object", "scene"),
    "graph": ("graph", "relationship", "triple", "entity", "knowledge graph", "link"),
}
_TOKEN_RE = re.compile(r"[\w$.-]+", re.UNICODE)


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


@dataclass(frozen=True)
class CrossModalQueryResult:
    id: int
    text: str
    modality: str
    score: float
    cross_modal_score: float
    base_score: float
    namespace: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    matched_features: tuple[str, ...]
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "modality": self.modality,
            "score": self.score,
            "cross_modal_score": self.cross_modal_score,
            "base_score": self.base_score,
            "namespace": self.namespace,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "matched_features": list(self.matched_features),
            "provenance": self.provenance,
        }


class CrossModalMemoryLayer:
    """Typed payload memory layer with a shared deterministic embedding space.

    The default encoder is intentionally local and deterministic. Production
    deployments can pass a CLIP/audio/video/3D encoder that implements the same
    TextEncoder interface while keeping the storage and provenance contract
    stable.
    """

    def __init__(
        self,
        memory: Any,
        *,
        encoder: TextEncoder | None = None,
        vector_dim: int = 128,
        base_weight: float = 0.20,
        cross_modal_weight: float = 0.75,
        modality_weight: float = 0.05,
    ) -> None:
        self.memory = memory
        self.encoder = encoder or HashingTextEncoder(vector_dim=vector_dim)
        self.base_weight = float(base_weight)
        self.cross_modal_weight = float(cross_modal_weight)
        self.modality_weight = float(modality_weight)

    def remember(
        self,
        payload: MemoryPayload,
        *,
        namespace: str = "default",
        ttl_seconds: float | None = None,
        priority: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        merged_payload = MemoryPayload(
            kind=payload.kind,
            text=payload.text,
            metadata={**payload.metadata, **(metadata or {})},
            tags=payload.tags,
        )
        descriptor = cross_modal_descriptor(merged_payload)
        record_metadata = {
            "modality": merged_payload.kind,
            "source": "wavemind_cross_modal",
            "cross_modal_version": _CROSS_MODAL_VERSION,
            "cross_modal_descriptor": descriptor,
            "cross_modal_embedding_dim": self.encoder.vector_dim,
            **merged_payload.metadata,
        }
        tags = tuple(dict.fromkeys((*merged_payload.tags, merged_payload.kind, "multimodal")))
        return int(
            self.memory.remember(
                merged_payload.text,
                namespace=namespace,
                tags=tags,
                ttl_seconds=ttl_seconds,
                metadata=record_metadata,
                priority=priority,
            )
        )

    def query(
        self,
        query: str,
        *,
        namespace: str = "default",
        top_k: int = 3,
        target_modality: str | None = None,
        candidate_k: int | None = None,
        min_score: float | None = None,
    ) -> list[CrossModalQueryResult]:
        if top_k <= 0:
            return []
        modality = normalize_modality(target_modality) if target_modality else None
        required_tags = ["multimodal", modality] if modality else ["multimodal"]
        records = self.memory.store.list(namespace=namespace, tags=required_tags)
        if not records:
            return []

        query_descriptor = cross_modal_query_descriptor(query, target_modality=modality)
        query_vector = self.encoder.encode_vector(query_descriptor)
        base_scores = self._base_scores(
            query,
            namespace=namespace,
            tags=required_tags,
            candidate_k=max(candidate_k or top_k * 8, top_k),
        )
        query_tokens = _tokens(query_descriptor)
        scored: list[CrossModalQueryResult] = []
        for record in records:
            if record.id is None:
                continue
            descriptor = str(
                record.metadata.get("cross_modal_descriptor") or record.text
            )
            vector = self.encoder.encode_vector(descriptor)
            cross_score = float(np.dot(query_vector, vector))
            record_modality = normalize_modality(record.metadata.get("modality", ""))
            modality_score = 1.0 if modality and record_modality == modality else 0.0
            base_score = _bounded_score(base_scores.get(int(record.id), 0.0))
            score = (
                self.cross_modal_weight * cross_score
                + self.base_weight * base_score
                + self.modality_weight * modality_score
            )
            if min_score is not None and score < min_score:
                continue
            descriptor_tokens = _tokens(descriptor)
            matched = tuple(sorted((query_tokens & descriptor_tokens))[:12])
            scored.append(
                CrossModalQueryResult(
                    id=int(record.id),
                    text=record.text,
                    modality=record_modality,
                    score=float(score),
                    cross_modal_score=cross_score,
                    base_score=base_score,
                    namespace=record.namespace,
                    tags=record.tags,
                    metadata=record.metadata,
                    matched_features=matched,
                    provenance=_provenance(record.metadata, int(record.id), record_modality),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def _base_scores(
        self,
        query: str,
        *,
        namespace: str,
        tags: Iterable[str],
        candidate_k: int,
    ) -> dict[int, float]:
        try:
            return {
                int(result.id): float(result.score)
                for result in self.memory.query(
                    query,
                    namespace=namespace,
                    tags=tags,
                    top_k=candidate_k,
                    min_score=0.0,
                )
            }
        except Exception:
            return {}


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


def cross_modal_descriptor(payload: MemoryPayload) -> str:
    modality = normalize_modality(payload.kind)
    aliases = " ".join(_MODALITY_ALIASES.get(modality, (modality,)))
    fields = " ".join(
        f"{key}: {value}"
        for key, value in sorted(payload.metadata.items())
        if not isinstance(value, (dict, list, tuple))
    )
    structured = " ".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        for value in payload.metadata.values()
        if isinstance(value, (dict, list, tuple))
    )
    return " | ".join(
        part
        for part in (
            f"modality: {modality}",
            f"aliases: {aliases}",
            payload.text,
            fields,
            structured,
        )
        if part.strip()
    )


def cross_modal_query_descriptor(query: str, *, target_modality: str | None = None) -> str:
    modality = normalize_modality(target_modality) if target_modality else ""
    aliases = " ".join(_MODALITY_ALIASES.get(modality, ())) if modality else ""
    return " | ".join(
        part
        for part in (
            f"target modality: {modality}" if modality else "",
            f"target aliases: {aliases}" if aliases else "",
            query,
        )
        if part.strip()
    )


def normalize_modality(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "asset3d": "3d",
        "3d_asset": "3d",
        "mesh": "3d",
        "kg": "graph",
        "knowledge_graph": "graph",
    }
    return aliases.get(text, text)


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


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.strip()
    }


def _bounded_score(value: float) -> float:
    if value <= -1.0 or value >= 1.0:
        return math.tanh(value)
    return float(value)


def _provenance(metadata: dict[str, Any], memory_id: int, modality: str) -> dict[str, Any]:
    keys = (
        "uri",
        "title",
        "caption",
        "transcript",
        "summary",
        "timestamp",
        "actor",
        "source",
        "cross_modal_version",
    )
    provenance = {
        "memory_id": int(memory_id),
        "modality": modality,
    }
    for key in keys:
        if key in metadata and metadata[key] not in (None, ""):
            provenance[key] = metadata[key]
    return provenance


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
