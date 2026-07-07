from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

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


@dataclass(frozen=True)
class CrossModalContractFixture:
    modality: str
    payload: MemoryPayload
    query: str
    query_vector: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "payload": self.payload.as_dict(),
            "query": self.query,
            "query_vector_dim": len(self.query_vector),
        }


@dataclass(frozen=True)
class CrossModalEncoderContractReport:
    encoder_name: str
    vector_dim: int
    ok: bool
    modalities: tuple[str, ...]
    payloads: int
    target_queries: int
    global_queries: int
    target_precision_at_1: float
    global_precision_at_1: float
    target_modality_routing_rate: float
    persisted_vector_rate: float
    normalized_vector_rate: float
    finite_vector_rate: float
    provenance_rate: float
    min_global_margin: float
    min_required_margin: float
    failures: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "encoder_name": self.encoder_name,
            "vector_dim": self.vector_dim,
            "ok": self.ok,
            "modalities": list(self.modalities),
            "payloads": self.payloads,
            "target_queries": self.target_queries,
            "global_queries": self.global_queries,
            "target_precision_at_1": self.target_precision_at_1,
            "global_precision_at_1": self.global_precision_at_1,
            "target_modality_routing_rate": self.target_modality_routing_rate,
            "persisted_vector_rate": self.persisted_vector_rate,
            "normalized_vector_rate": self.normalized_vector_rate,
            "finite_vector_rate": self.finite_vector_rate,
            "provenance_rate": self.provenance_rate,
            "min_global_margin": self.min_global_margin,
            "min_required_margin": self.min_required_margin,
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class TemporalEventQueryResult:
    id: int
    text: str
    score: float
    base_score: float
    temporal_score: float
    namespace: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    timestamp: str | None
    timestamp_epoch: float | None
    end_timestamp: str | None
    end_timestamp_epoch: float | None
    time_distance_seconds: float | None
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": self.score,
            "base_score": self.base_score,
            "temporal_score": self.temporal_score,
            "namespace": self.namespace,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "timestamp_epoch": self.timestamp_epoch,
            "end_timestamp": self.end_timestamp,
            "end_timestamp_epoch": self.end_timestamp_epoch,
            "time_distance_seconds": self.time_distance_seconds,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class KnowledgeGraphQueryResult:
    id: int
    text: str
    score: float
    base_score: float
    graph_score: float
    namespace: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    subject: str
    predicate: str
    object: str
    depth: int
    path: tuple[dict[str, str], ...]
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": self.score,
            "base_score": self.base_score,
            "graph_score": self.graph_score,
            "namespace": self.namespace,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "depth": self.depth,
            "path": list(self.path),
            "provenance": self.provenance,
        }


class CrossModalEncoder(Protocol):
    name: str
    vector_dim: int

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        ...

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        ...


class DescriptorCrossModalEncoder:
    """Descriptor encoder used by default and as a compatibility baseline."""

    name = "descriptor"

    def __init__(
        self,
        encoder: TextEncoder | None = None,
        *,
        vector_dim: int = 128,
    ) -> None:
        self.encoder = encoder or HashingTextEncoder(vector_dim=vector_dim)
        self.vector_dim = int(self.encoder.vector_dim)

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        explicit = cross_modal_vector_from_metadata(payload.metadata, vector_dim=self.vector_dim)
        if explicit is not None:
            return explicit
        return _normalize_vector(self.encoder.encode_vector(descriptor), vector_dim=self.vector_dim)

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        return _normalize_vector(self.encoder.encode_vector(descriptor), vector_dim=self.vector_dim)


class PrecomputedCrossModalEncoder:
    """Strict encoder for externally computed CLIP/audio/video/3D vectors."""

    name = "precomputed"

    def __init__(self, *, vector_dim: int, name: str | None = None) -> None:
        if vector_dim <= 0:
            raise ValueError("vector_dim must be positive.")
        self.vector_dim = int(vector_dim)
        if name:
            self.name = str(name)

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        vector = cross_modal_vector_from_metadata(payload.metadata, vector_dim=self.vector_dim)
        if vector is None:
            raise ValueError(
                "PrecomputedCrossModalEncoder requires payload metadata with "
                "`cross_modal_vector`, `cross_modal_embedding`, `embedding`, or `vector`."
            )
        return vector

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        raise ValueError(
            "PrecomputedCrossModalEncoder requires `query_vector=` in "
            "CrossModalMemoryLayer.query()."
        )


class SentenceTransformersCrossModalEncoder:
    """Optional sentence-transformers backend for CLIP-style cross-modal memory."""

    def __init__(
        self,
        model_name: str = "clip-ViT-B-32",
        *,
        model: Any | None = None,
        vector_dim: int | None = None,
        image_loader: Callable[[Path], Any] | None = None,
        name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.model = model if model is not None else self._load_model(model_name)
        self.image_loader = image_loader
        inferred_dim = vector_dim or self._infer_vector_dim()
        if inferred_dim <= 0:
            raise ValueError("vector_dim must be positive.")
        self.vector_dim = int(inferred_dim)
        self.name = name or f"sentence-transformers/{model_name}"

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        explicit = cross_modal_vector_from_metadata(payload.metadata, vector_dim=self.vector_dim)
        if explicit is not None:
            return explicit
        model_input = self._payload_input(payload, descriptor)
        return self._encode_one(model_input)

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        return self._encode_one(query or descriptor)

    @staticmethod
    def _load_model(model_name: str) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "SentenceTransformersCrossModalEncoder requires the optional "
                "`wavemind[multimodal]` extra."
            ) from exc
        return SentenceTransformer(model_name)

    def _infer_vector_dim(self) -> int:
        getter = getattr(self.model, "get_sentence_embedding_dimension", None)
        if callable(getter):
            dim = getter()
            if dim:
                return int(dim)
        vector = self._encode_raw("dimension probe")
        return int(vector.shape[0])

    def _payload_input(self, payload: MemoryPayload, descriptor: str) -> Any:
        if normalize_modality(payload.kind) != "image":
            return descriptor
        path = _local_uri_path(payload.metadata.get("uri"))
        if path is None:
            return descriptor
        loader = self.image_loader or _load_pillow_image
        return loader(path)

    def _encode_one(self, value: Any) -> np.ndarray:
        return _normalize_vector(self._encode_raw(value), vector_dim=self.vector_dim)

    def _encode_raw(self, value: Any) -> np.ndarray:
        try:
            encoded = self.model.encode(
                [value],
                convert_to_numpy=True,
                normalize_embeddings=False,
            )
        except TypeError:
            encoded = self.model.encode([value])
        vector = np.asarray(encoded, dtype=np.float32)
        if vector.ndim == 2:
            if vector.shape[0] != 1:
                raise ValueError("Expected one encoded vector.")
            vector = vector[0]
        return vector.astype(np.float32)


class CrossModalMemoryLayer:
    """Typed payload memory layer with a pluggable shared embedding space.

    The default encoder is intentionally local and deterministic. Production
    deployments can pass a CLIP/audio/video/3D encoder that implements
    CrossModalEncoder while keeping the storage and provenance contract stable.
    """

    def __init__(
        self,
        memory: Any,
        *,
        encoder: TextEncoder | None = None,
        cross_modal_encoder: CrossModalEncoder | None = None,
        vector_dim: int = 128,
        base_weight: float = 0.20,
        cross_modal_weight: float = 0.75,
        modality_weight: float = 0.05,
    ) -> None:
        if cross_modal_encoder is not None and encoder is not None:
            raise ValueError("Use either encoder or cross_modal_encoder, not both.")
        self.memory = memory
        self.cross_modal_encoder = cross_modal_encoder or DescriptorCrossModalEncoder(
            encoder,
            vector_dim=vector_dim,
        )
        self.vector_dim = int(self.cross_modal_encoder.vector_dim)
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
        vector = self.cross_modal_encoder.encode_payload(merged_payload, descriptor)
        vector = _normalize_vector(vector, vector_dim=self.vector_dim)
        record_metadata = {
            **merged_payload.metadata,
            "modality": merged_payload.kind,
            "source": "wavemind_cross_modal",
            "cross_modal_version": _CROSS_MODAL_VERSION,
            "cross_modal_encoder": self.cross_modal_encoder.name,
            "cross_modal_descriptor": descriptor,
            "cross_modal_embedding_dim": self.vector_dim,
            "cross_modal_vector": vector.astype(float).tolist(),
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
        query_vector: Sequence[float] | np.ndarray | None = None,
    ) -> list[CrossModalQueryResult]:
        if top_k <= 0:
            return []
        modality = normalize_modality(target_modality) if target_modality else None
        required_tags = ["multimodal", modality] if modality else ["multimodal"]
        records = self.memory.store.list(namespace=namespace, tags=required_tags)
        if not records:
            return []

        query_descriptor = cross_modal_query_descriptor(query, target_modality=modality)
        if query_vector is None:
            encoded_query_vector = self.cross_modal_encoder.encode_query(
                query,
                target_modality=modality,
                descriptor=query_descriptor,
            )
        else:
            encoded_query_vector = np.asarray(query_vector, dtype=np.float32)
        encoded_query_vector = _normalize_vector(encoded_query_vector, vector_dim=self.vector_dim)
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
            vector = cross_modal_vector_from_metadata(
                record.metadata,
                vector_dim=self.vector_dim,
            )
            if vector is None:
                compatibility_payload = MemoryPayload(
                    kind=str(record.metadata.get("modality") or ""),
                    text=record.text,
                    metadata=record.metadata,
                    tags=record.tags,
                )
                vector = self.cross_modal_encoder.encode_payload(
                    compatibility_payload,
                    descriptor,
                )
                vector = _normalize_vector(vector, vector_dim=self.vector_dim)
            cross_score = float(np.dot(encoded_query_vector, vector))
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


def default_cross_modal_contract_fixtures(
    *,
    vector_dim: int = 8,
) -> tuple[CrossModalContractFixture, ...]:
    """Return deterministic external-vector fixtures for all supported modalities."""

    if vector_dim < 7:
        raise ValueError("vector_dim must be at least 7 for the default contract.")

    def one_hot(index: int) -> tuple[float, ...]:
        vector = [0.0] * vector_dim
        vector[index] = 1.0
        return tuple(vector)

    fixtures = (
        (
            "image",
            image_payload(
                "s3://contract/revenue-chart.png",
                caption="enterprise revenue expansion chart",
            ),
            "visual chart about enterprise revenue expansion",
        ),
        (
            "audio",
            audio_payload(
                "s3://contract/support-call.wav",
                transcript="customer call requested SSO and audit log export",
            ),
            "voice call asking for SSO audit logs",
        ),
        (
            "table",
            table_payload(
                [{"segment": "enterprise", "arr": 2000}],
                title="ARR by segment table",
            ),
            "spreadsheet table with enterprise ARR metrics",
        ),
        (
            "event",
            event_payload(
                "account upgraded to enterprise plan",
                actor="tenant:acme",
                properties={"plan": "enterprise"},
            ),
            "timeline event where account upgraded plan",
        ),
        (
            "video",
            video_payload(
                "s3://contract/memory-demo.mp4",
                summary="memory graph heatmap demo video",
                transcript="agent suppresses stale facts after corrections",
                scenes=["memory graph heatmap", "stale fact suppression"],
            ),
            "video scene about memory graph stale fact suppression",
        ),
        (
            "3d",
            asset3d_payload(
                "s3://contract/robot-arm.glb",
                description="3D robot arm model for warehouse picking",
                format="glb",
                labels=["robot arm", "warehouse", "picking"],
            ),
            "3D warehouse robot arm model",
        ),
        (
            "graph",
            graph_payload(
                [
                    ("trading agent", "uses", "WaveMind memory"),
                    ("WaveMind memory", "stores", "dynamic preferences"),
                ],
                title="agent knowledge graph",
                summary="trading agent uses WaveMind memory",
            ),
            "knowledge graph relation trading agent uses memory",
        ),
    )
    return tuple(
        CrossModalContractFixture(
            modality=modality,
            payload=MemoryPayload(
                kind=payload.kind,
                text=payload.text,
                metadata={**payload.metadata, "cross_modal_vector": list(one_hot(index))},
                tags=payload.tags,
            ),
            query=query,
            query_vector=one_hot(index),
        )
        for index, (modality, payload, query) in enumerate(fixtures)
    )


def validate_precomputed_cross_modal_contract(
    memory: Any,
    *,
    fixtures: Sequence[CrossModalContractFixture] | None = None,
    namespace: str = "__wavemind_multimodal_contract__",
    vector_dim: int | None = None,
    encoder_name: str = "precomputed-contract",
    min_required_margin: float = 0.20,
) -> CrossModalEncoderContractReport:
    """Validate that external multimodal vectors obey WaveMind's retrieval contract.

    The contract is intentionally strict and read as a production preflight:
    payload vectors must be finite, normalized after storage, persisted in
    metadata, retrievable globally, routable by target modality, and returned
    with provenance. It is designed for CLIP/audio/video/3D/table/event/graph
    pipelines that compute vectors outside WaveMind.
    """

    selected = tuple(fixtures or default_cross_modal_contract_fixtures())
    if not selected:
        return CrossModalEncoderContractReport(
            encoder_name=encoder_name,
            vector_dim=int(vector_dim or 0),
            ok=False,
            modalities=(),
            payloads=0,
            target_queries=0,
            global_queries=0,
            target_precision_at_1=0.0,
            global_precision_at_1=0.0,
            target_modality_routing_rate=0.0,
            persisted_vector_rate=0.0,
            normalized_vector_rate=0.0,
            finite_vector_rate=0.0,
            provenance_rate=0.0,
            min_global_margin=0.0,
            min_required_margin=float(min_required_margin),
            failures=("no fixtures provided",),
        )
    resolved_dim = int(vector_dim or len(selected[0].query_vector))
    layer = CrossModalMemoryLayer(
        memory,
        cross_modal_encoder=PrecomputedCrossModalEncoder(
            vector_dim=resolved_dim,
            name=encoder_name,
        ),
    )
    failures: list[str] = []
    ids: dict[str, int] = {}
    for fixture in selected:
        modality = normalize_modality(fixture.modality)
        if len(fixture.query_vector) != resolved_dim:
            failures.append(f"{modality}: query vector dimension mismatch")
            continue
        try:
            ids[modality] = layer.remember(
                fixture.payload,
                namespace=namespace,
                metadata={
                    "contract_modality": modality,
                    "contract_query": fixture.query,
                },
            )
        except Exception as exc:
            failures.append(f"{modality}: remember failed: {exc}")

    records = memory.store.list(namespace=namespace, tags=["multimodal"])
    persisted = 0
    normalized = 0
    finite = 0
    for record in records:
        vector = cross_modal_vector_from_metadata(record.metadata, vector_dim=resolved_dim)
        if vector is None:
            continue
        persisted += 1
        if np.all(np.isfinite(vector)):
            finite += 1
        norm = float(np.linalg.norm(vector))
        if abs(norm - 1.0) <= 1e-5:
            normalized += 1

    target_hits = 0
    target_routes = 0
    global_hits = 0
    provenance_hits = 0
    margins: list[float] = []
    for fixture in selected:
        modality = normalize_modality(fixture.modality)
        expected_id = ids.get(modality)
        if expected_id is None:
            continue
        try:
            target = layer.query(
                fixture.query,
                namespace=namespace,
                target_modality=modality,
                top_k=2,
                query_vector=fixture.query_vector,
            )
            if target and target[0].id == expected_id:
                target_hits += 1
            if target and target[0].modality == modality:
                target_routes += 1

            global_results = layer.query(
                fixture.query,
                namespace=namespace,
                top_k=2,
                query_vector=fixture.query_vector,
            )
            if global_results and global_results[0].id == expected_id:
                global_hits += 1
            if global_results:
                if len(global_results) > 1:
                    margins.append(float(global_results[0].score - global_results[1].score))
                else:
                    margins.append(float(global_results[0].score))
            if (
                global_results
                and global_results[0].id == expected_id
                and global_results[0].provenance.get("memory_id") == expected_id
                and global_results[0].provenance.get("modality") == modality
            ):
                provenance_hits += 1
        except Exception as exc:
            failures.append(f"{modality}: query failed: {exc}")

    payload_count = len(selected)
    stored_count = len(ids)
    min_margin = min(margins) if margins else 0.0
    target_precision = _rate(target_hits, payload_count)
    global_precision = _rate(global_hits, payload_count)
    routing_rate = _rate(target_routes, payload_count)
    persisted_rate = _rate(persisted, stored_count)
    normalized_rate = _rate(normalized, stored_count)
    finite_rate = _rate(finite, stored_count)
    provenance_rate = _rate(provenance_hits, payload_count)
    if target_precision < 1.0:
        failures.append("target precision@1 below 1.0")
    if global_precision < 1.0:
        failures.append("global precision@1 below 1.0")
    if routing_rate < 1.0:
        failures.append("target modality routing below 1.0")
    if persisted_rate < 1.0:
        failures.append("persisted vector rate below 1.0")
    if normalized_rate < 1.0:
        failures.append("normalized vector rate below 1.0")
    if finite_rate < 1.0:
        failures.append("finite vector rate below 1.0")
    if provenance_rate < 1.0:
        failures.append("provenance rate below 1.0")
    if min_margin < min_required_margin:
        failures.append("global separation margin below required threshold")

    return CrossModalEncoderContractReport(
        encoder_name=encoder_name,
        vector_dim=resolved_dim,
        ok=not failures,
        modalities=tuple(normalize_modality(fixture.modality) for fixture in selected),
        payloads=payload_count,
        target_queries=payload_count,
        global_queries=payload_count,
        target_precision_at_1=target_precision,
        global_precision_at_1=global_precision,
        target_modality_routing_rate=routing_rate,
        persisted_vector_rate=persisted_rate,
        normalized_vector_rate=normalized_rate,
        finite_vector_rate=finite_rate,
        provenance_rate=provenance_rate,
        min_global_margin=float(min_margin),
        min_required_margin=float(min_required_margin),
        failures=tuple(failures),
    )


class TemporalEventMemoryLayer:
    """Temporal event retrieval layer over WaveMind event payloads.

    Events remain ordinary WaveMind memories with durable metadata. This layer
    adds interval filtering, actor filtering, around-time scoring, and recency
    scoring without requiring a separate event database.
    """

    def __init__(
        self,
        memory: Any,
        *,
        base_weight: float = 0.70,
        temporal_weight: float = 0.30,
    ) -> None:
        self.memory = memory
        self.base_weight = float(base_weight)
        self.temporal_weight = float(temporal_weight)

    def remember(
        self,
        name: str,
        *,
        namespace: str = "default",
        actor: str | None = None,
        timestamp: str | datetime | int | float | None = None,
        end_timestamp: str | datetime | int | float | None = None,
        duration_seconds: float | None = None,
        properties: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: Iterable[str] | None = None,
        ttl_seconds: float | None = None,
        priority: float = 1.0,
    ) -> int:
        payload = event_payload(
            name,
            actor=actor,
            timestamp=timestamp,
            end_timestamp=end_timestamp,
            duration_seconds=duration_seconds,
            properties=properties,
            metadata=metadata,
            tags=tags,
        )
        return remember_payload(
            self.memory,
            payload,
            namespace=namespace,
            ttl_seconds=ttl_seconds,
            priority=priority,
        )

    def query(
        self,
        query: str,
        *,
        namespace: str = "default",
        top_k: int = 3,
        candidate_k: int | None = None,
        actor: str | None = None,
        start: str | datetime | int | float | None = None,
        end: str | datetime | int | float | None = None,
        around: str | datetime | int | float | None = None,
        tolerance_seconds: float | None = None,
        recency_anchor: str | datetime | int | float | None = None,
        recency_half_life_seconds: float | None = None,
        min_score: float | None = None,
    ) -> list[TemporalEventQueryResult]:
        if top_k <= 0:
            return []
        start_epoch = timestamp_epoch(start)
        end_epoch = timestamp_epoch(end)
        around_epoch = timestamp_epoch(around)
        recency_epoch = timestamp_epoch(recency_anchor)
        normalized_actor = actor.lower() if actor else None
        needs_temporal_scan = any(
            value is not None
            for value in (start_epoch, end_epoch, around_epoch, recency_epoch, normalized_actor)
        )

        base_results = self.memory.query(
            query,
            namespace=namespace,
            tags=["event"],
            top_k=max(candidate_k or top_k * 12, top_k),
            min_score=0.0,
        )
        base_scores = {int(result.id): float(result.score) for result in base_results}
        records_by_id = {
            int(record.id): record
            for record in self.memory.store.list(namespace=namespace, tags=["event"])
            if record.id is not None
        }
        candidate_ids = list(dict.fromkeys([int(result.id) for result in base_results]))
        if needs_temporal_scan:
            for id in records_by_id:
                if id not in base_scores:
                    candidate_ids.append(id)
                    base_scores[id] = 0.0

        scored: list[TemporalEventQueryResult] = []
        for id in candidate_ids:
            record = records_by_id.get(id)
            if record is None or record.is_expired:
                continue
            metadata = record.metadata
            if normalized_actor is not None:
                record_actor = str(metadata.get("actor", "")).lower()
                if record_actor != normalized_actor:
                    continue
            event_start = _metadata_epoch(metadata, "timestamp_epoch", "timestamp")
            event_end = _metadata_epoch(metadata, "end_timestamp_epoch", "end_timestamp")
            if event_end is None:
                event_end = event_start
            if not _event_overlaps(event_start, event_end, start_epoch, end_epoch):
                continue

            temporal_score, distance = _temporal_score(
                event_start=event_start,
                event_end=event_end,
                around_epoch=around_epoch,
                tolerance_seconds=tolerance_seconds,
                recency_epoch=recency_epoch,
                recency_half_life_seconds=recency_half_life_seconds,
            )
            base_score = _bounded_score(base_scores.get(id, 0.0))
            score = self.base_weight * base_score + self.temporal_weight * temporal_score
            if min_score is not None and score < min_score:
                continue
            scored.append(
                TemporalEventQueryResult(
                    id=id,
                    text=record.text,
                    score=float(score),
                    base_score=float(base_score),
                    temporal_score=float(temporal_score),
                    namespace=record.namespace,
                    tags=record.tags,
                    metadata=metadata,
                    timestamp=_metadata_text(metadata, "timestamp"),
                    timestamp_epoch=event_start,
                    end_timestamp=_metadata_text(metadata, "end_timestamp"),
                    end_timestamp_epoch=event_end,
                    time_distance_seconds=distance,
                    provenance=_provenance(metadata, id, "event"),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


class KnowledgeGraphMemoryLayer:
    """Knowledge-graph retrieval layer over WaveMind graph payloads.

    Graphs remain ordinary WaveMind memories. This layer builds a query-time
    adjacency view from persisted triples so backups, replication, TTL, tags,
    and namespaces keep the same storage contract as text and multimodal memory.
    """

    def __init__(
        self,
        memory: Any,
        *,
        base_weight: float = 0.35,
        graph_weight: float = 0.65,
    ) -> None:
        self.memory = memory
        self.base_weight = float(base_weight)
        self.graph_weight = float(graph_weight)

    def remember_triples(
        self,
        triples: Sequence[tuple[str, str, str] | dict[str, Any]],
        *,
        namespace: str = "default",
        title: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: Iterable[str] | None = None,
        ttl_seconds: float | None = None,
        priority: float = 1.0,
    ) -> int:
        payload = graph_payload(
            triples,
            title=title,
            summary=summary,
            metadata=metadata,
            tags=tags,
        )
        return remember_payload(
            self.memory,
            payload,
            namespace=namespace,
            ttl_seconds=ttl_seconds,
            priority=priority,
        )

    def query(
        self,
        query: str,
        *,
        namespace: str = "default",
        top_k: int = 3,
        candidate_k: int | None = None,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        max_depth: int = 1,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> list[KnowledgeGraphQueryResult]:
        if top_k <= 0:
            return []
        depth_limit = max(1, int(max_depth))
        required_tags = tuple(dict.fromkeys(("graph", *(tags or ()))))
        records = [
            record
            for record in self.memory.store.list(namespace=namespace, tags=required_tags)
            if record.id is not None and not record.is_expired
        ]
        if not records:
            return []

        base_scores = self._base_scores(
            query,
            namespace=namespace,
            tags=required_tags,
            candidate_k=max(candidate_k or top_k * 12, top_k),
        )
        query_tokens = _tokens(query)
        subject_key = _graph_key(subject)
        predicate_key = _graph_key(predicate)
        object_key = _graph_key(object)

        scored: list[KnowledgeGraphQueryResult] = []
        seen: set[tuple[int, tuple[tuple[str, str, str], ...]]] = set()

        for record in records:
            record_id = int(record.id)
            for triple in _metadata_triples(record.metadata):
                if not _triple_matches(
                    triple,
                    subject=subject_key,
                    predicate=predicate_key,
                    object=object_key,
                ):
                    continue
                graph_score = _direct_graph_score(
                    triple,
                    query_tokens=query_tokens,
                    subject=subject_key,
                    predicate=predicate_key,
                    object=object_key,
                )
                self._append_result(
                    scored,
                    seen,
                    record=record,
                    triple=triple,
                    path=(triple,),
                    depth=1,
                    graph_score=graph_score,
                    base_score=base_scores.get(record_id, 0.0),
                    min_score=min_score,
                )

        if depth_limit > 1 and subject_key is not None:
            for record, triple, path in self._traverse(
                records,
                start=subject_key,
                target=object_key,
                predicate=predicate_key,
                max_depth=depth_limit,
            ):
                record_id = int(record.id)
                graph_score = _path_graph_score(
                    path,
                    query_tokens=query_tokens,
                    target=object_key,
                )
                self._append_result(
                    scored,
                    seen,
                    record=record,
                    triple=triple,
                    path=tuple(path),
                    depth=len(path),
                    graph_score=graph_score,
                    base_score=base_scores.get(record_id, 0.0),
                    min_score=min_score,
                )

        scored.sort(key=lambda item: (item.score, -item.depth), reverse=True)
        return scored[:top_k]

    def _base_scores(
        self,
        query: str,
        *,
        namespace: str,
        tags: Iterable[str],
        candidate_k: int,
    ) -> dict[int, float]:
        if not str(query or "").strip():
            return {}
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

    def _append_result(
        self,
        scored: list[KnowledgeGraphQueryResult],
        seen: set[tuple[int, tuple[tuple[str, str, str], ...]]],
        *,
        record: Any,
        triple: dict[str, str],
        path: tuple[dict[str, str], ...],
        depth: int,
        graph_score: float,
        base_score: float,
        min_score: float | None,
    ) -> None:
        record_id = int(record.id)
        path_key = tuple(
            (
                _graph_key(step.get("subject")) or "",
                _graph_key(step.get("predicate")) or "",
                _graph_key(step.get("object")) or "",
            )
            for step in path
        )
        key = (record_id, path_key)
        if key in seen:
            return
        seen.add(key)
        bounded_base = _bounded_score(base_score)
        bounded_graph = max(0.0, min(1.0, float(graph_score)))
        score = self.base_weight * bounded_base + self.graph_weight * bounded_graph
        if min_score is not None and score < min_score:
            return
        scored.append(
            KnowledgeGraphQueryResult(
                id=record_id,
                text=record.text,
                score=float(score),
                base_score=float(bounded_base),
                graph_score=float(bounded_graph),
                namespace=record.namespace,
                tags=record.tags,
                metadata=record.metadata,
                subject=triple.get("subject", ""),
                predicate=triple.get("predicate", ""),
                object=triple.get("object", ""),
                depth=int(depth),
                path=tuple(dict(step) for step in path),
                provenance=_graph_provenance(record.metadata, record_id, triple, path),
            )
        )

    def _traverse(
        self,
        records: Sequence[Any],
        *,
        start: str,
        target: str | None,
        predicate: str | None,
        max_depth: int,
    ) -> list[tuple[Any, dict[str, str], list[dict[str, str]]]]:
        edges_by_subject: dict[str, list[tuple[Any, dict[str, str]]]] = {}
        for record in records:
            for triple in _metadata_triples(record.metadata):
                triple_subject = _graph_key(triple.get("subject"))
                if not triple_subject:
                    continue
                edges_by_subject.setdefault(triple_subject, []).append((record, triple))

        matches: list[tuple[Any, dict[str, str], list[dict[str, str]]]] = []
        frontier: list[tuple[str, list[dict[str, str]], set[str]]] = [(start, [], {start})]
        for depth in range(max_depth):
            next_frontier: list[tuple[str, list[dict[str, str]], set[str]]] = []
            for current, path, visited in frontier:
                for record, triple in edges_by_subject.get(current, []):
                    object_key = _graph_key(triple.get("object"))
                    if not object_key:
                        continue
                    new_path = [*path, triple]
                    predicate_ok = predicate is None or _graph_key(triple.get("predicate")) == predicate
                    target_ok = target is None or object_key == target
                    if predicate_ok and target_ok:
                        matches.append((record, triple, new_path))
                    if depth + 1 < max_depth and object_key not in visited:
                        next_frontier.append((object_key, new_path, {*visited, object_key}))
            frontier = next_frontier
        return matches


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
    preview = json.dumps(normalized[:12], ensure_ascii=False, sort_keys=True)
    persisted = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return _payload(
        "graph",
        {
            "title": title,
            "summary": summary or "",
            "triples": preview,
            "triple_count": str(len(normalized)),
        },
        metadata={**(metadata or {}), "triples": persisted, "triple_count": len(normalized)},
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
    timestamp: str | datetime | int | float | None = None,
    end_timestamp: str | datetime | int | float | None = None,
    duration_seconds: float | None = None,
    properties: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: Iterable[str] | None = None,
) -> MemoryPayload:
    start_iso, start_epoch = normalize_timestamp(timestamp)
    end_iso, end_epoch = normalize_timestamp(end_timestamp)
    if end_epoch is None and start_epoch is not None and duration_seconds is not None:
        end_epoch = start_epoch + float(duration_seconds)
        end_iso = _iso_from_epoch(end_epoch)
    payload_metadata = dict(metadata or {})
    if start_iso is not None:
        payload_metadata["timestamp"] = start_iso
        payload_metadata["timestamp_epoch"] = start_epoch
    if end_iso is not None:
        payload_metadata["end_timestamp"] = end_iso
        payload_metadata["end_timestamp_epoch"] = end_epoch
    if duration_seconds is not None:
        payload_metadata["duration_seconds"] = float(duration_seconds)
    return _payload(
        "event",
        {
            "name": name,
            "actor": actor or "",
            "timestamp": start_iso or "",
            "end_timestamp": end_iso or "",
            "properties": json.dumps(properties or {}, ensure_ascii=False, sort_keys=True),
        },
        metadata=payload_metadata,
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


def normalize_timestamp(
    value: str | datetime | int | float | None,
) -> tuple[str | None, float | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return _iso_from_datetime(dt), float(dt.timestamp())
    if isinstance(value, (int, float)):
        epoch = float(value)
        if not math.isfinite(epoch):
            raise ValueError("timestamp epoch must be finite")
        return _iso_from_epoch(epoch), epoch
    text = str(value).strip()
    if not text:
        return None, None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        epoch = float(text)
        return _iso_from_epoch(epoch), epoch
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported timestamp format: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return _iso_from_datetime(dt), float(dt.timestamp())


def timestamp_epoch(value: str | datetime | int | float | None) -> float | None:
    return normalize_timestamp(value)[1]


def cross_modal_vector_from_metadata(
    metadata: dict[str, Any],
    *,
    vector_dim: int | None = None,
) -> np.ndarray | None:
    for key in (
        "cross_modal_vector",
        "cross_modal_embedding",
        "embedding",
        "vector",
    ):
        if key not in metadata:
            continue
        value = metadata[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return _normalize_vector(value, vector_dim=vector_dim)
    return None


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
        tags=tuple(dict.fromkeys((kind, *(tags or ())))),
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


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _normalize_vector(
    value: Sequence[float] | np.ndarray,
    *,
    vector_dim: int | None = None,
) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.ndim != 1:
        raise ValueError("Cross-modal vectors must be one-dimensional.")
    if vector_dim is not None and int(vector.shape[0]) != int(vector_dim):
        raise ValueError(
            f"Cross-modal vector dimension {vector.shape[0]} does not match {vector_dim}."
        )
    if not np.all(np.isfinite(vector)):
        raise ValueError("Cross-modal vectors must contain only finite values.")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)


def _local_uri_path(value: Any) -> Path | None:
    uri = str(value or "").strip()
    if not uri or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", uri):
        return None
    path = Path(uri)
    return path if path.exists() and path.is_file() else None


def _load_pillow_image(path: Path) -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "Image payload encoding requires Pillow. Install `wavemind[multimodal]`."
        ) from exc
    with Image.open(path) as image:
        return image.convert("RGB").copy()


def _provenance(metadata: dict[str, Any], memory_id: int, modality: str) -> dict[str, Any]:
    keys = (
        "uri",
        "title",
        "caption",
        "transcript",
        "summary",
        "timestamp",
        "end_timestamp",
        "duration_seconds",
        "actor",
        "source",
        "cross_modal_version",
        "asset_uri",
        "asset_sha256",
        "asset_bytes",
        "asset_media_type",
        "asset_verified",
    )
    provenance = {
        "memory_id": int(memory_id),
        "modality": modality,
    }
    for key in keys:
        if key in metadata and metadata[key] not in (None, ""):
            provenance[key] = metadata[key]
    return provenance


def _iso_from_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_epoch(epoch: float) -> str:
    return _iso_from_datetime(datetime.fromtimestamp(float(epoch), tz=timezone.utc))


def _metadata_epoch(
    metadata: dict[str, Any],
    epoch_key: str,
    text_key: str,
) -> float | None:
    value = metadata.get(epoch_key)
    if value not in (None, ""):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return timestamp_epoch(metadata.get(text_key))


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _event_overlaps(
    event_start: float | None,
    event_end: float | None,
    start_epoch: float | None,
    end_epoch: float | None,
) -> bool:
    if start_epoch is None and end_epoch is None:
        return True
    if event_start is None:
        return False
    effective_end = event_end if event_end is not None else event_start
    if start_epoch is not None and effective_end < start_epoch:
        return False
    if end_epoch is not None and event_start > end_epoch:
        return False
    return True


def _temporal_score(
    *,
    event_start: float | None,
    event_end: float | None,
    around_epoch: float | None,
    tolerance_seconds: float | None,
    recency_epoch: float | None,
    recency_half_life_seconds: float | None,
) -> tuple[float, float | None]:
    if event_start is None:
        return 0.0, None
    effective_end = event_end if event_end is not None else event_start
    scores: list[float] = []
    distance: float | None = None
    if around_epoch is not None:
        if event_start <= around_epoch <= effective_end:
            distance = 0.0
        else:
            distance = min(abs(event_start - around_epoch), abs(effective_end - around_epoch))
        tolerance = max(float(tolerance_seconds or 86400.0), 1.0)
        scores.append(math.exp(-distance / tolerance))
    if recency_epoch is not None:
        age = max(0.0, recency_epoch - effective_end)
        half_life = max(float(recency_half_life_seconds or 86400.0), 1.0)
        scores.append(0.5 ** (age / half_life))
    if not scores:
        return 1.0, distance
    return max(0.0, min(1.0, sum(scores) / len(scores))), distance


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


def _metadata_triples(metadata: dict[str, Any]) -> list[dict[str, str]]:
    value = metadata.get("triples")
    if value in (None, ""):
        return []
    try:
        if isinstance(value, str):
            parsed = json.loads(value)
        else:
            parsed = value
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    triples: list[dict[str, str]] = []
    for item in parsed:
        try:
            triple = _normalize_triple(item)
        except (TypeError, ValueError):
            continue
        if triple["subject"].strip() and triple["predicate"].strip() and triple["object"].strip():
            triples.append(triple)
    return triples


def _graph_key(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"[_\s]+", " ", text)
    return text


def _triple_matches(
    triple: dict[str, str],
    *,
    subject: str | None,
    predicate: str | None,
    object: str | None,
) -> bool:
    return (
        (subject is None or _graph_key(triple.get("subject")) == subject)
        and (predicate is None or _graph_key(triple.get("predicate")) == predicate)
        and (object is None or _graph_key(triple.get("object")) == object)
    )


def _direct_graph_score(
    triple: dict[str, str],
    *,
    query_tokens: set[str],
    subject: str | None,
    predicate: str | None,
    object: str | None,
) -> float:
    requested = [value for value in (subject, predicate, object) if value is not None]
    tokens = _tokens(
        " ".join(
            (
                triple.get("subject", ""),
                triple.get("predicate", ""),
                triple.get("object", ""),
            )
        )
    )
    if query_tokens and tokens:
        overlap_score = len(query_tokens & tokens) / max(1, min(len(query_tokens), len(tokens)))
    else:
        overlap_score = 0.0
    if requested:
        return max(0.80, min(1.0, 0.80 + overlap_score * 0.20))
    return min(1.0, overlap_score)


def _path_graph_score(
    path: Sequence[dict[str, str]],
    *,
    query_tokens: set[str],
    target: str | None,
) -> float:
    if not path:
        return 0.0
    path_text = " ".join(
        " ".join((step.get("subject", ""), step.get("predicate", ""), step.get("object", "")))
        for step in path
    )
    path_tokens = _tokens(path_text)
    if query_tokens and path_tokens:
        overlap = len(query_tokens & path_tokens) / max(1, min(len(query_tokens), len(path_tokens)))
    else:
        overlap = 0.0
    target_bonus = 0.30 if target is not None and _graph_key(path[-1].get("object")) == target else 0.0
    depth_penalty = max(0.0, (len(path) - 1) * 0.08)
    return max(0.0, min(1.0, 0.78 + target_bonus + overlap * 0.18 - depth_penalty))


def _graph_provenance(
    metadata: dict[str, Any],
    memory_id: int,
    triple: dict[str, str],
    path: Sequence[dict[str, str]],
) -> dict[str, Any]:
    provenance = _provenance(metadata, memory_id, "graph")
    provenance["triple"] = dict(triple)
    provenance["path"] = [dict(step) for step in path]
    provenance["depth"] = len(path)
    if "triple_count" in metadata:
        provenance["triple_count"] = metadata["triple_count"]
    return provenance
