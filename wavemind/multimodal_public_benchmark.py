from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .core import WaveMind
from .encoders import HashingTextEncoder
from .multimodal import (
    CrossModalMemoryLayer,
    CrossModalQueryResult,
    MemoryPayload,
    _rank_group_confidence,
    cross_modal_descriptor,
    normalize_modality,
)
from .multimodal_local import (
    LocalClapAudioEncoder,
    LocalClipMediaEncoder,
    LocalSentenceTextEncoder,
)


PUBLIC_MULTIMODAL_SUITE_SCHEMA = "wavemind.public_multimodal_suite.v1"
PUBLIC_MULTIMODAL_RESULT_SCHEMA = "wavemind.multimodal_encoder_benchmark.v2"
_OPAQUE_ASSET_ID_PREFIX = "a_"
_OPAQUE_QUERY_ID_PREFIX = "q_"
_OPAQUE_ID_HEX_LENGTH = 32
_FORBIDDEN_ASSET_KEYS = {
    "answer",
    "caption",
    "class",
    "description",
    "label",
    "relevant",
    "summary",
    "target",
    "title",
    "transcript",
}
_REAL_MODALITIES = ("text", "image", "audio", "video", "3d")


@dataclass(frozen=True)
class PublicAsset:
    id: str
    modality: str
    path: Path
    sha256: str
    total_bytes: int
    media_type: str
    dataset_id: str
    object_uri: str
    object_verified: bool


@dataclass(frozen=True)
class PublicQueryPart:
    modality: str
    path: Path
    sha256: str
    weight: float


@dataclass(frozen=True)
class PublicQuery:
    id: str
    parts: tuple[PublicQueryPart, ...]
    target_modalities: tuple[str, ...]
    relevant_asset_ids: frozenset[str]

    @property
    def query_modality(self) -> str:
        if len(self.parts) != 1:
            return "mixed"
        return self.parts[0].modality


@dataclass(frozen=True)
class PublicMultimodalSuite:
    path: Path
    name: str
    revision: str
    license: str
    datasets: tuple[dict[str, Any], ...]
    assets: tuple[PublicAsset, ...]
    queries: tuple[PublicQuery, ...]
    asset_manifest_sha256: str
    query_manifest_sha256: str
    ground_truth_sha256: str

    @property
    def manifest_sha256(self) -> str:
        return _sha256_file(self.path)


@dataclass(frozen=True)
class _QueryExecution:
    query: PublicQuery
    groups: tuple[tuple[str, str, np.ndarray], ...]
    encoding_ms: float


def load_public_multimodal_suite(path: str | Path) -> PublicMultimodalSuite:
    suite_path = Path(path).resolve()
    suite = _load_json_object(suite_path)
    if suite.get("schema") != PUBLIC_MULTIMODAL_SUITE_SCHEMA:
        raise ValueError(
            f"suite.schema must be `{PUBLIC_MULTIMODAL_SUITE_SCHEMA}`."
        )
    root = suite_path.parent
    name = _required_text(suite, "name")
    revision = _required_text(suite, "revision")
    license_text = _required_text(suite, "license")
    datasets = suite.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("suite.datasets must be a non-empty list.")
    for index, dataset in enumerate(datasets):
        if not isinstance(dataset, dict):
            raise ValueError(f"suite.datasets[{index}] must be an object.")
        for key in ("id", "name", "revision", "license", "source_url"):
            _required_text(dataset, key, context=f"suite.datasets[{index}]")

    asset_manifest_path, asset_manifest_sha = _verified_child_file(
        root,
        suite,
        path_key="asset_manifest",
        sha_key="asset_manifest_sha256",
    )
    query_manifest_path, query_manifest_sha = _verified_child_file(
        root,
        suite,
        path_key="query_manifest",
        sha_key="query_manifest_sha256",
    )
    ground_truth_path, ground_truth_sha = _verified_child_file(
        root,
        suite,
        path_key="ground_truth",
        sha_key="ground_truth_sha256",
    )
    raw_assets = _load_json_list(asset_manifest_path)
    raw_queries = _load_json_list(query_manifest_path)
    ground_truth = _load_json_object(ground_truth_path)
    dataset_ids = {str(row["id"]) for row in datasets}

    assets: list[PublicAsset] = []
    asset_ids: set[str] = set()
    for index, row in enumerate(raw_assets):
        if not isinstance(row, dict):
            raise ValueError(f"asset_manifest[{index}] must be an object.")
        _reject_semantic_asset_metadata(row, index=index)
        asset_id = _opaque_id(
            row.get("id"),
            prefix=_OPAQUE_ASSET_ID_PREFIX,
            context=f"asset_manifest[{index}].id",
        )
        if asset_id in asset_ids:
            raise ValueError(f"duplicate asset ID `{asset_id}`.")
        asset_ids.add(asset_id)
        modality = _required_modality(row, "modality", context=f"asset {asset_id}")
        dataset_id = _required_text(row, "dataset_id", context=f"asset {asset_id}")
        if dataset_id not in dataset_ids:
            raise ValueError(
                f"asset `{asset_id}` references unknown dataset `{dataset_id}`."
            )
        asset_path, digest = _verified_content_file(
            root,
            row,
            context=f"asset {asset_id}",
            opaque_id=asset_id,
        )
        total_bytes = _required_positive_int(
            row,
            "bytes",
            context=f"asset {asset_id}",
        )
        if total_bytes != asset_path.stat().st_size:
            raise ValueError(
                f"asset `{asset_id}` byte size does not match its file."
            )
        object_uri = _required_text(row, "object_uri", context=f"asset {asset_id}")
        if not object_uri.startswith("s3://"):
            raise ValueError(
                f"asset `{asset_id}` must declare an s3:// object_uri."
            )
        if not bool(row.get("object_verified")):
            raise ValueError(
                f"asset `{asset_id}` must have object_verified=true."
            )
        assets.append(
            PublicAsset(
                id=asset_id,
                modality=modality,
                path=asset_path,
                sha256=digest,
                total_bytes=total_bytes,
                media_type=_required_text(
                    row,
                    "media_type",
                    context=f"asset {asset_id}",
                ),
                dataset_id=dataset_id,
                object_uri=object_uri,
                object_verified=True,
            )
        )

    relevant_map = ground_truth.get("relevant_asset_ids")
    if not isinstance(relevant_map, dict):
        raise ValueError(
            "ground_truth.relevant_asset_ids must map opaque query IDs to asset IDs."
        )
    queries: list[PublicQuery] = []
    query_ids: set[str] = set()
    for index, row in enumerate(raw_queries):
        if not isinstance(row, dict):
            raise ValueError(f"query_manifest[{index}] must be an object.")
        query_id = _opaque_id(
            row.get("id"),
            prefix=_OPAQUE_QUERY_ID_PREFIX,
            context=f"query_manifest[{index}].id",
        )
        if query_id in query_ids:
            raise ValueError(f"duplicate query ID `{query_id}`.")
        query_ids.add(query_id)
        raw_parts = row.get("parts")
        if not isinstance(raw_parts, list) or not raw_parts:
            raise ValueError(f"query `{query_id}` must contain at least one part.")
        parts: list[PublicQueryPart] = []
        for part_index, raw_part in enumerate(raw_parts):
            if not isinstance(raw_part, dict):
                raise ValueError(
                    f"query `{query_id}` part {part_index} must be an object."
                )
            modality = _required_modality(
                raw_part,
                "modality",
                context=f"query {query_id} part {part_index}",
            )
            part_path, digest = _verified_content_file(
                root,
                raw_part,
                context=f"query {query_id} part {part_index}",
                opaque_id=query_id,
            )
            weight = float(raw_part.get("weight", 1.0))
            if not math.isfinite(weight) or weight <= 0.0:
                raise ValueError(
                    f"query `{query_id}` part {part_index} weight must be positive."
                )
            parts.append(
                PublicQueryPart(
                    modality=modality,
                    path=part_path,
                    sha256=digest,
                    weight=weight,
                )
            )
        raw_targets = row.get("target_modalities")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise ValueError(
                f"query `{query_id}` must declare target_modalities."
            )
        targets = tuple(
            dict.fromkeys(
                _normalize_required_modality(value, context=f"query {query_id}")
                for value in raw_targets
            )
        )
        raw_relevant = relevant_map.get(query_id)
        if not isinstance(raw_relevant, list) or not raw_relevant:
            raise ValueError(
                f"ground truth for query `{query_id}` must contain asset IDs."
            )
        relevant = frozenset(str(value) for value in raw_relevant)
        unknown = relevant - asset_ids
        if unknown:
            raise ValueError(
                f"ground truth for query `{query_id}` references unknown assets: "
                f"{', '.join(sorted(unknown))}."
            )
        queries.append(
            PublicQuery(
                id=query_id,
                parts=tuple(parts),
                target_modalities=targets,
                relevant_asset_ids=relevant,
            )
        )
    extra_ground_truth = set(str(key) for key in relevant_map) - query_ids
    if extra_ground_truth:
        raise ValueError(
            "ground truth contains query IDs absent from query_manifest: "
            f"{', '.join(sorted(extra_ground_truth))}."
        )
    return PublicMultimodalSuite(
        path=suite_path,
        name=name,
        revision=revision,
        license=license_text,
        datasets=tuple(dict(row) for row in datasets),
        assets=tuple(assets),
        queries=tuple(queries),
        asset_manifest_sha256=asset_manifest_sha,
        query_manifest_sha256=query_manifest_sha,
        ground_truth_sha256=ground_truth_sha,
    )


def run_public_multimodal_benchmark(
    suite_path: str | Path,
    *,
    output_dir: str | Path,
    cache_folder: str | Path | None = None,
    repeats: int = 3,
    batch_size: int = 16,
    top_k: int = 3,
    lifecycle_artifact: str | Path | None = None,
    encoder_factory: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive.")
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    if top_k < 1:
        raise ValueError("top_k must be positive.")
    suite = load_public_multimodal_suite(suite_path)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    source_sha = _source_sha()
    dependency_lock_sha = _dependency_lock_sha256()
    lifecycle = _load_lifecycle(lifecycle_artifact)
    per_asset_rows: list[dict[str, Any]] = []
    per_query_rows: list[dict[str, Any]] = []
    repeat_summaries: list[dict[str, Any]] = []
    spaces: dict[str, dict[str, Any]] = {}
    modality_encoders: dict[str, list[tuple[str, Any]]] = {}

    for repeat_index in range(repeats):
        factory = encoder_factory or (
            lambda: _default_encoders(cache_folder=cache_folder)
        )
        encoders = dict(factory())
        _validate_encoder_set(encoders)
        spaces = {
            space_id: encoder.embedding_space.as_dict()
            for space_id, encoder in encoders.items()
        }
        modality_encoders = _modality_encoder_index(encoders)
        repeat_root = output_root / f"repeat-{repeat_index + 1}"
        repeat_root.mkdir(parents=True, exist_ok=True)
        layers: dict[str, CrossModalMemoryLayer] = {}
        memories: dict[str, WaveMind] = {}
        memory_to_asset: dict[str, dict[int, str]] = {}
        stored_vectors: dict[str, dict[int, np.ndarray]] = {}
        asset_latencies: dict[str, list[float]] = {
            modality: [] for modality in _REAL_MODALITIES
        }
        batch_elapsed_ms = 0.0
        query_executions: list[_QueryExecution] = []
        try:
            for space_id, encoder in encoders.items():
                memory = WaveMind(
                    db_path=repeat_root / f"{_safe_name(space_id)}.sqlite3",
                    encoder=HashingTextEncoder(vector_dim=64),
                    width=16,
                    height=16,
                    layers=1,
                )
                layer = CrossModalMemoryLayer(
                    memory,
                    cross_modal_encoder=encoder,
                    base_weight=0.0,
                    cross_modal_weight=1.0,
                    modality_weight=0.0,
                )
                memories[space_id] = memory
                layers[space_id] = layer
                memory_to_asset[space_id] = {}
                stored_vectors[space_id] = {}
                supported_assets = [
                    asset
                    for asset in suite.assets
                    if asset.modality in encoder.embedding_space.modalities
                ]
                for modality in encoder.embedding_space.modalities:
                    modality_assets = [
                        asset
                        for asset in supported_assets
                        if asset.modality == modality
                    ]
                    for offset in range(0, len(modality_assets), batch_size):
                        batch_assets = modality_assets[offset : offset + batch_size]
                        payloads = [_asset_payload(asset) for asset in batch_assets]
                        started = time.perf_counter()
                        vectors = encoder.encode_payloads(payloads)
                        batch_elapsed_ms += (
                            time.perf_counter() - started
                        ) * 1000.0
                        if len(vectors) != len(batch_assets):
                            raise RuntimeError(
                                f"encoder `{encoder.name}` returned {len(vectors)} "
                                f"vectors for {len(batch_assets)} assets."
                            )
                        for asset, payload, vector in zip(
                            batch_assets,
                            payloads,
                            vectors,
                            strict=True,
                        ):
                            individual_started = time.perf_counter()
                            individual = encoder.encode_payload(
                                payload,
                                cross_modal_descriptor(payload),
                            )
                            encode_ms = (
                                time.perf_counter() - individual_started
                            ) * 1000.0
                            asset_latencies[asset.modality].append(encode_ms)
                            if not np.allclose(individual, vector, atol=1e-5):
                                raise RuntimeError(
                                    f"batch/individual parity failed for asset `{asset.id}`."
                                )
                            memory_id = layer._remember_encoded_payload(
                                payload,
                                vector,
                                descriptor=cross_modal_descriptor(payload),
                                namespace=f"public:{repeat_index + 1}",
                                ttl_seconds=None,
                                priority=1.0,
                            )
                            memory_to_asset[space_id][memory_id] = asset.id
                            stored_vectors[space_id][memory_id] = _unit_vector(vector)
                            per_asset_rows.append(
                                {
                                    "repeat": repeat_index + 1,
                                    "asset_id": asset.id,
                                    "modality": asset.modality,
                                    "dataset_id": asset.dataset_id,
                                    "sha256": asset.sha256,
                                    "bytes": asset.total_bytes,
                                    "object_uri": asset.object_uri,
                                    "object_verified": asset.object_verified,
                                    "space_id": space_id,
                                    "encoder_backend": encoder.name,
                                    "model_revision": encoder.embedding_space.model_revision,
                                    "vector_dim": encoder.vector_dim,
                                    "vector_sha256": _vector_sha256(vector),
                                    "individual_encode_ms": encode_ms,
                                    "batch_individual_parity": True,
                                    "persisted": True,
                                }
                            )
            query_executions = [
                _encode_query_execution(
                    query,
                    encoders=encoders,
                    modality_encoders=modality_encoders,
                )
                for query in suite.queries
            ]
            query_rows = _execute_queries(
                query_executions,
                layers=layers,
                memory_to_asset=memory_to_asset,
                namespace=f"public:{repeat_index + 1}",
                top_k=top_k,
                repeat=repeat_index + 1,
            )
            per_query_rows.extend(query_rows)
            persisted_parity = _persisted_vector_parity(
                memories,
                stored_vectors=stored_vectors,
                namespace=f"public:{repeat_index + 1}",
            )
            for memory in memories.values():
                memory.close()
            memories.clear()
            reloaded_layers, reloaded_memories = _reload_layers(
                repeat_root,
                encoders=encoders,
            )
            try:
                reloaded_rows = _execute_queries(
                    query_executions,
                    layers=reloaded_layers,
                    memory_to_asset=memory_to_asset,
                    namespace=f"public:{repeat_index + 1}",
                    top_k=top_k,
                    repeat=repeat_index + 1,
                )
            finally:
                for memory in reloaded_memories.values():
                    memory.close()
            reload_parity = _query_reload_parity(query_rows, reloaded_rows)
            summary = _repeat_summary(
                query_rows,
                persisted_parity=persisted_parity,
                reload_parity=reload_parity,
            )
            summary["repeat"] = repeat_index + 1
            summary["asset_encode_p95_ms"] = {
                modality: _percentile(values, 95.0)
                for modality, values in asset_latencies.items()
            }
            summary["batch_throughput_assets_per_second"] = (
                0.0
                if batch_elapsed_ms <= 0.0
                else len(suite.assets) / (batch_elapsed_ms / 1000.0)
            )
            repeat_summaries.append(summary)
        finally:
            for memory in memories.values():
                memory.close()

    per_asset_path = output_root / "multimodal_per_asset.jsonl"
    per_query_path = output_root / "multimodal_per_query.jsonl"
    _write_jsonl(per_asset_path, per_asset_rows)
    _write_jsonl(per_query_path, per_query_rows)
    result = _build_result(
        suite,
        source_sha=source_sha,
        dependency_lock_sha=dependency_lock_sha,
        spaces=spaces,
        modality_encoders=modality_encoders,
        per_asset_rows=per_asset_rows,
        per_query_rows=per_query_rows,
        repeat_summaries=repeat_summaries,
        per_asset_path=per_asset_path,
        per_query_path=per_query_path,
        lifecycle=lifecycle,
    )
    return result


def write_public_multimodal_benchmark_artifacts(
    suite_path: str | Path,
    *,
    output_dir: str | Path,
    result_path: str | Path,
    cache_folder: str | Path | None = None,
    repeats: int = 3,
    batch_size: int = 16,
    top_k: int = 3,
    lifecycle_artifact: str | Path,
    encoder_factory: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    result = run_public_multimodal_benchmark(
        suite_path,
        output_dir=output_dir,
        cache_folder=cache_folder,
        repeats=repeats,
        batch_size=batch_size,
        top_k=top_k,
        lifecycle_artifact=lifecycle_artifact,
        encoder_factory=encoder_factory,
    )
    destination = Path(result_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _default_encoders(*, cache_folder: str | Path | None) -> dict[str, Any]:
    encoders = (
        LocalSentenceTextEncoder(cache_folder=cache_folder),
        LocalClipMediaEncoder(cache_folder=cache_folder),
        LocalClapAudioEncoder(cache_folder=cache_folder),
    )
    return {
        encoder.embedding_space.space_id: encoder
        for encoder in encoders
    }


def _validate_encoder_set(encoders: Mapping[str, Any]) -> None:
    if not encoders:
        raise ValueError("At least one real local encoder is required.")
    supported = set()
    for space_id, encoder in encoders.items():
        if space_id != encoder.embedding_space.space_id:
            raise ValueError(
                f"Encoder mapping key `{space_id}` does not match its embedding space."
            )
        if not encoder.embedding_space.production_eligible:
            raise ValueError(
                f"Encoder `{encoder.name}` is not production eligible."
            )
        if not callable(getattr(encoder, "encode_payloads", None)):
            raise ValueError(
                f"Encoder `{encoder.name}` does not implement real batch encoding."
            )
        supported.update(encoder.embedding_space.modalities)
    missing = set(_REAL_MODALITIES) - supported
    if missing:
        raise ValueError(
            f"Real encoder set is missing modalities: {', '.join(sorted(missing))}."
        )


def _modality_encoder_index(
    encoders: Mapping[str, Any],
) -> dict[str, list[tuple[str, Any]]]:
    result: dict[str, list[tuple[str, Any]]] = {
        modality: [] for modality in _REAL_MODALITIES
    }
    for space_id, encoder in encoders.items():
        for modality in encoder.embedding_space.modalities:
            if modality in result:
                result[modality].append((space_id, encoder))
    return result


def _asset_payload(asset: PublicAsset) -> MemoryPayload:
    if asset.modality == "text":
        text = asset.path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"text asset `{asset.id}` is empty.")
    else:
        text = "opaque local media payload"
    return MemoryPayload(
        kind=asset.modality,
        text=text,
        metadata={
            "uri": str(asset.path),
            "asset_sha256": asset.sha256,
            "asset_bytes": asset.total_bytes,
            "asset_media_type": asset.media_type,
            "asset_uri": asset.object_uri,
            "asset_verified": asset.object_verified,
            "dataset_revision": asset.dataset_id,
        },
        tags=("public-benchmark",),
    )


def _query_part_payload(part: PublicQueryPart) -> MemoryPayload:
    if part.modality == "text":
        text = part.path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"text query part `{part.path}` is empty.")
        return MemoryPayload(kind="text", text=text)
    return MemoryPayload(
        kind=part.modality,
        text="opaque local query media",
        metadata={"uri": str(part.path)},
    )


def _encode_query_execution(
    query: PublicQuery,
    *,
    encoders: Mapping[str, Any],
    modality_encoders: Mapping[str, Sequence[tuple[str, Any]]],
) -> _QueryExecution:
    started = time.perf_counter()
    groups: list[tuple[str, str, np.ndarray]] = []
    used_part_indexes: set[int] = set()
    for target_modality in query.target_modalities:
        grouped_parts: dict[
            str,
            tuple[Any, list[tuple[int, PublicQueryPart]]],
        ] = {}
        for part_index, part in enumerate(query.parts):
            for space_id, encoder in modality_encoders[part.modality]:
                if target_modality not in encoder.embedding_space.modalities:
                    continue
                entry = grouped_parts.setdefault(space_id, (encoder, []))
                entry[1].append((part_index, part))
                used_part_indexes.add(part_index)
        for space_id, (encoder, compatible_parts) in grouped_parts.items():
            vectors = []
            weights = []
            for _, part in compatible_parts:
                payload = _query_part_payload(part)
                if part.modality == "text":
                    vector = encoder.encode_query(
                        payload.text,
                        target_modality=target_modality,
                        descriptor=payload.text,
                    )
                else:
                    vector = encoder.encode_payload(
                        payload,
                        cross_modal_descriptor(payload),
                    )
                vectors.append(np.asarray(vector, dtype=np.float32))
                weights.append(part.weight)
            groups.append(
                (
                    space_id,
                    target_modality,
                    _weighted_unit_vector(vectors, weights),
                )
            )
    if not groups:
        part_modalities = ", ".join(part.modality for part in query.parts)
        raise ValueError(
            f"query `{query.id}` has no compatible shared space for "
            f"{part_modalities} -> {', '.join(query.target_modalities)}."
        )
    missing_parts = [
        query.parts[index].modality
        for index in range(len(query.parts))
        if index not in used_part_indexes
    ]
    if missing_parts:
        raise ValueError(
            f"query `{query.id}` has parts with no compatible target space: "
            f"{', '.join(missing_parts)}."
        )
    return _QueryExecution(
        query=query,
        groups=tuple(groups),
        encoding_ms=(time.perf_counter() - started) * 1000.0,
    )


def _execute_queries(
    executions: Sequence[_QueryExecution],
    *,
    layers: Mapping[str, CrossModalMemoryLayer],
    memory_to_asset: Mapping[str, Mapping[int, str]],
    namespace: str,
    top_k: int,
    repeat: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for execution in executions:
        started = time.perf_counter()
        groups = []
        for space_id, target_modality, vector in execution.groups:
            results = layers[space_id].query(
                "opaque benchmark query",
                namespace=namespace,
                target_modality=target_modality,
                top_k=max(top_k * 4, top_k),
                query_vector=vector,
                query_space_id=space_id,
            )
            groups.append((space_id, target_modality, results))
        ranked = _rank_fuse_asset_ids(
            groups,
            memory_to_asset=memory_to_asset,
            top_k=top_k,
        )
        retrieval_ms = (time.perf_counter() - started) * 1000.0
        top_ids = [row["asset_id"] for row in ranked]
        hit = bool(top_ids and top_ids[0] in execution.query.relevant_asset_ids)
        query_modality = execution.query.query_modality
        rows.append(
            {
                "repeat": repeat,
                "query_id": execution.query.id,
                "query_modality": query_modality,
                "part_modalities": [
                    part.modality for part in execution.query.parts
                ],
                "target_modalities": list(execution.query.target_modalities),
                "relevant_asset_ids": sorted(execution.query.relevant_asset_ids),
                "top_asset_ids": top_ids,
                "hit_at_1": hit,
                "encoding_ms": execution.encoding_ms,
                "retrieval_ms": retrieval_ms,
                "end_to_end_ms": execution.encoding_ms + retrieval_ms,
                "groups": [
                    {
                        "space_id": space_id,
                        "target_modality": target_modality,
                    }
                    for space_id, target_modality, _ in execution.groups
                ],
                "fusion": "confidence_weighted_reciprocal_rank",
                "incompatible_spaces_compared": False,
            }
        )
    return rows


def _rank_fuse_asset_ids(
    groups: Sequence[tuple[str, str, Sequence[CrossModalQueryResult]]],
    *,
    memory_to_asset: Mapping[str, Mapping[int, str]],
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    contributions: dict[str, list[dict[str, Any]]] = {}
    active = [
        (
            space_id,
            target_modality,
            _rank_group_confidence(results),
            results,
        )
        for space_id, target_modality, results in groups
        if results
    ]
    confidence_total = sum(confidence for _, _, confidence, _ in active)
    for space_id, target_modality, confidence, results in active:
        group_weight = (
            confidence / confidence_total if confidence_total > 0.0 else 0.0
        )
        for rank, result in enumerate(results, start=1):
            asset_id = memory_to_asset[space_id].get(result.id)
            if not asset_id:
                continue
            factor = (rrf_k + 1.0) / (rrf_k + float(rank))
            contribution = group_weight * factor
            scores[asset_id] = scores.get(asset_id, 0.0) + contribution
            contributions.setdefault(asset_id, []).append(
                {
                    "space_id": space_id,
                    "target_modality": target_modality,
                    "rank": rank,
                    "group_confidence": confidence,
                    "raw_score": result.score,
                    "contribution": contribution,
                }
            )
    ordered = sorted(scores, key=lambda asset_id: scores[asset_id], reverse=True)
    return [
        {
            "asset_id": asset_id,
            "score": scores[asset_id],
            "contributions": contributions[asset_id],
        }
        for asset_id in ordered[:top_k]
    ]


def _persisted_vector_parity(
    memories: Mapping[str, WaveMind],
    *,
    stored_vectors: Mapping[str, Mapping[int, np.ndarray]],
    namespace: str,
) -> float:
    expected = 0
    matched = 0
    for space_id, memory in memories.items():
        records = memory.store.list(namespace=namespace, tags=["multimodal"])
        by_id = {int(record.id): record for record in records if record.id is not None}
        for memory_id, vector in stored_vectors[space_id].items():
            expected += 1
            record = by_id.get(memory_id)
            if record is None:
                continue
            persisted = np.asarray(
                record.metadata.get("cross_modal_vector"),
                dtype=np.float32,
            )
            if persisted.shape == vector.shape and np.array_equal(persisted, vector):
                matched += 1
    return _rate(matched, expected)


def _reload_layers(
    repeat_root: Path,
    *,
    encoders: Mapping[str, Any],
) -> tuple[dict[str, CrossModalMemoryLayer], dict[str, WaveMind]]:
    layers = {}
    memories = {}
    for space_id, encoder in encoders.items():
        memory = WaveMind(
            db_path=repeat_root / f"{_safe_name(space_id)}.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
        )
        memories[space_id] = memory
        layers[space_id] = CrossModalMemoryLayer(
            memory,
            cross_modal_encoder=encoder,
            base_weight=0.0,
            cross_modal_weight=1.0,
            modality_weight=0.0,
        )
    return layers, memories


def _query_reload_parity(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> float:
    after_by_id = {str(row["query_id"]): row for row in after}
    matches = 0
    for row in before:
        reloaded = after_by_id.get(str(row["query_id"]))
        if reloaded and row.get("top_asset_ids") == reloaded.get("top_asset_ids"):
            matches += 1
    return _rate(matches, len(before))


def _repeat_summary(
    query_rows: Sequence[Mapping[str, Any]],
    *,
    persisted_parity: float,
    reload_parity: float,
) -> dict[str, Any]:
    precision = _rate(
        sum(1 for row in query_rows if bool(row.get("hit_at_1"))),
        len(query_rows),
    )
    cross_rows = [
        row
        for row in query_rows
        if row.get("query_modality") == "mixed"
        or any(
            part != target
            for part in row.get("part_modalities", [])
            for target in row.get("target_modalities", [])
        )
    ]
    mixed_rows = [
        row for row in query_rows if row.get("query_modality") == "mixed"
    ]
    return {
        "precision_at_1": precision,
        "cross_modal_precision_at_1": _rate(
            sum(1 for row in cross_rows if bool(row.get("hit_at_1"))),
            len(cross_rows),
        ),
        "mixed_multimodal_precision_at_1": _rate(
            sum(1 for row in mixed_rows if bool(row.get("hit_at_1"))),
            len(mixed_rows),
        ),
        "retrieval_p99_ms": _percentile(
            [float(row["retrieval_ms"]) for row in query_rows],
            99.0,
        ),
        "query_p99_ms": _percentile(
            [float(row["end_to_end_ms"]) for row in query_rows],
            99.0,
        ),
        "encoding_p95_ms": _percentile(
            [float(row["encoding_ms"]) for row in query_rows],
            95.0,
        ),
        "persisted_vector_parity": persisted_parity,
        "reload_query_parity": reload_parity,
        "error_rate": 0.0,
    }


def _build_result(
    suite: PublicMultimodalSuite,
    *,
    source_sha: str,
    dependency_lock_sha: str,
    spaces: Mapping[str, Mapping[str, Any]],
    modality_encoders: Mapping[str, Sequence[tuple[str, Any]]],
    per_asset_rows: Sequence[Mapping[str, Any]],
    per_query_rows: Sequence[Mapping[str, Any]],
    repeat_summaries: Sequence[Mapping[str, Any]],
    per_asset_path: Path,
    per_query_path: Path,
    lifecycle: Mapping[str, Any],
) -> dict[str, Any]:
    latest_repeat = len(repeat_summaries)
    latest_assets = [
        row for row in per_asset_rows if int(row["repeat"]) == latest_repeat
    ]
    latest_queries = [
        row for row in per_query_rows if int(row["repeat"]) == latest_repeat
    ]
    asset_counts = {
        modality: sum(
            1 for asset in suite.assets if asset.modality == modality
        )
        for modality in _REAL_MODALITIES
    }
    query_counts = {
        modality: sum(
            1
            for row in latest_queries
            if modality in row.get("target_modalities", [])
        )
        for modality in _REAL_MODALITIES
    }
    modality_precision = {
        modality: _rate(
            sum(
                1
                for row in latest_queries
                if modality in row.get("target_modalities", [])
                and bool(row.get("hit_at_1"))
            ),
            query_counts[modality],
        )
        for modality in _REAL_MODALITIES
    }
    modality_p95 = {
        modality: _percentile(
            [
                float(row["individual_encode_ms"])
                for row in latest_assets
                if row["modality"] == modality
            ],
            95.0,
        )
        for modality in _REAL_MODALITIES
    }
    modality_metrics = {}
    for modality in _REAL_MODALITIES:
        rows = modality_encoders[modality]
        modality_metrics[modality] = {
            "asset_count": asset_counts[modality],
            "query_count": query_counts[modality],
            "precision_at_1": modality_precision[modality],
            "encode_p95_ms": modality_p95[modality],
            "encoder_backend": "+".join(
                sorted({str(encoder.name) for _, encoder in rows})
            ),
            "model_revision": "+".join(
                sorted(
                    {
                        str(encoder.embedding_space.model_revision)
                        for _, encoder in rows
                    }
                )
            ),
            "shared_space_ids": [space_id for space_id, _ in rows],
        }
    pair_rows = []
    for query_modality, target_modality in (
        ("text", "image"),
        ("image", "text"),
        ("text", "audio"),
        ("audio", "text"),
        ("text", "video"),
        ("video", "text"),
        ("text", "3d"),
        ("3d", "text"),
    ):
        rows = [
            row
            for row in latest_queries
            if row.get("query_modality") == query_modality
            and row.get("target_modalities") == [target_modality]
        ]
        shared_space = _shared_space_for_pair(
            spaces,
            query_modality,
            target_modality,
        )
        pair_rows.append(
            {
                "query_modality": query_modality,
                "target_modality": target_modality,
                "query_count": len(rows),
                "precision_at_1": _rate(
                    sum(1 for row in rows if bool(row.get("hit_at_1"))),
                    len(rows),
                ),
                "shared_space_id": shared_space,
            }
        )
    latest_summary = dict(repeat_summaries[-1])
    verdicts = [
        _quality_verdict(summary)
        for summary in repeat_summaries
    ]
    admission_eligible = (
        len(suite.assets) >= 1_000
        and len(suite.queries) >= 200
        and len(repeat_summaries) >= 3
        and all(asset_counts[modality] >= 100 for modality in _REAL_MODALITIES)
        and all(query_counts[modality] >= 20 for modality in _REAL_MODALITIES)
        and all(
            modality_precision[modality] >= 0.85
            for modality in _REAL_MODALITIES
        )
        and all(
            modality_p95[modality] <= _encoding_budget_ms(modality)
            for modality in _REAL_MODALITIES
        )
        and all(
            int(row["query_count"]) >= 20
            and float(row["precision_at_1"]) >= 0.85
            and bool(row["shared_space_id"])
            for row in pair_rows
        )
        and all(bool(lifecycle.get(key)) for key in _lifecycle_pass_keys())
        and bool(lifecycle.get("object_store_pass"))
        and verdicts
        and all(value == "pass" for value in verdicts)
    )
    return {
        "schema": PUBLIC_MULTIMODAL_RESULT_SCHEMA,
        "generated_at": _utc_now(),
        "status": "pass" if admission_eligible else "fail",
        "admission_eligible": admission_eligible,
        "source": "local-open-source-multimodal-benchmark",
        "source_sha": source_sha,
        "deployment": "local-evidence",
        "environment": "local",
        "asset_source": "real_public_assets",
        "object_store": "minio-s3-compatible",
        "object_store_backend": str(
            lifecycle.get("object_store_backend") or "minio"
        ),
        "dataset": {
            "name": suite.name,
            "revision": suite.revision,
            "license": suite.license,
            "asset_source": "real_public_assets",
            "manifest_sha256": suite.manifest_sha256,
            "ground_truth_sha256": suite.ground_truth_sha256,
            "asset_manifest_sha256": suite.asset_manifest_sha256,
            "query_manifest_sha256": suite.query_manifest_sha256,
            "datasets": [dict(row) for row in suite.datasets],
        },
        "environment_fingerprint": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hardware": _hardware_fingerprint(),
            "dependency_lock_sha256": dependency_lock_sha,
        },
        "modalities": list(_REAL_MODALITIES),
        "modality_count": len(_REAL_MODALITIES),
        "payload_count": len(suite.assets),
        "query_count": len(suite.queries),
        "shared_spaces": {
            space_id: dict(row)
            for space_id, row in spaces.items()
        },
        "modality_metrics": modality_metrics,
        "cross_modal_pairs": pair_rows,
        "lifecycle": dict(lifecycle),
        "leakage_checks": {
            "pass": True,
            "filename_leakage": False,
            "caption_leakage": False,
            "id_leakage": False,
            "metadata_leakage": False,
            "contract": "opaque filenames + separate ground truth + no semantic asset metadata",
        },
        "repeatability": {
            "run_count": len(repeat_summaries),
            "stable_verdict": len(set(verdicts)) == 1,
            "verdicts": verdicts,
            "summaries": [dict(row) for row in repeat_summaries],
        },
        "evidence_files": {
            "per_query": {
                "path": per_query_path.name,
                "sha256": _sha256_file(per_query_path),
            },
            "per_asset": {
                "path": per_asset_path.name,
                "sha256": _sha256_file(per_asset_path),
            },
        },
        "metrics": {
            "macro_precision_at_1": latest_summary["precision_at_1"],
            "cross_modal_precision_at_1": latest_summary[
                "cross_modal_precision_at_1"
            ],
            "mixed_multimodal_precision_at_1": latest_summary[
                "mixed_multimodal_precision_at_1"
            ],
            "persisted_vector_parity": latest_summary[
                "persisted_vector_parity"
            ],
            "reload_query_parity": latest_summary["reload_query_parity"],
            "retrieval_p99_ms": latest_summary["retrieval_p99_ms"],
            "query_p99_ms": latest_summary["query_p99_ms"],
            "batch_throughput_assets_per_second": latest_summary[
                "batch_throughput_assets_per_second"
            ],
            "error_rate": latest_summary["error_rate"],
        },
    }


def _quality_verdict(summary: Mapping[str, Any]) -> str:
    passed = (
        float(summary.get("precision_at_1", 0.0)) >= 0.90
        and float(summary.get("cross_modal_precision_at_1", 0.0)) >= 0.90
        and float(summary.get("mixed_multimodal_precision_at_1", 0.0)) >= 0.90
        and float(summary.get("persisted_vector_parity", 0.0)) == 1.0
        and float(summary.get("reload_query_parity", 0.0)) == 1.0
        and float(summary.get("retrieval_p99_ms", float("inf"))) <= 250.0
        and float(summary.get("error_rate", 1.0)) == 0.0
    )
    return "pass" if passed else "fail"


def _encoding_budget_ms(modality: str) -> float:
    return {
        "text": 250.0,
        "image": 250.0,
        "audio": 1_000.0,
        "video": 2_000.0,
        "3d": 1_000.0,
    }[modality]


def _lifecycle_pass_keys() -> tuple[str, ...]:
    return (
        "ingest_pass",
        "checksum_pass",
        "reload_pass",
        "persistence_pass",
        "namespace_isolation_pass",
        "ttl_pass",
        "physical_delete_pass",
        "tombstone_pass",
        "backup_restore_pass",
        "orphan_cleanup_pass",
    )


def _shared_space_for_pair(
    spaces: Mapping[str, Mapping[str, Any]],
    first: str,
    second: str,
) -> str:
    for space_id, row in spaces.items():
        modalities = {
            normalize_modality(value)
            for value in row.get("modalities", [])
        }
        if {first, second}.issubset(modalities):
            return space_id
    return ""


def _load_lifecycle(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError(
            "A verified filesystem/MinIO lifecycle artifact is required."
    )
    payload = _load_json_object(Path(path).resolve())
    lifecycle = payload.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise ValueError("Lifecycle artifact must contain a lifecycle object.")
    required = tuple(
        name.removesuffix("_pass")
        for name in _lifecycle_pass_keys()
    )
    missing = [
        name
        for name in required
        if not bool(lifecycle.get(f"{name}_pass"))
    ]
    if missing:
        raise ValueError(
            "Lifecycle artifact failed required checks: "
            f"{', '.join(missing)}."
        )
    if str(payload.get("status") or "").lower() != "pass":
        raise ValueError("Lifecycle artifact status must be pass.")
    if not bool(lifecycle.get("object_store_pass")):
        raise ValueError("Lifecycle artifact object-store verification must pass.")
    object_store_backend = str(
        lifecycle.get("object_store_backend") or ""
    ).strip()
    if not object_store_backend:
        raise ValueError("Lifecycle artifact must identify the object-store backend.")
    return {
        "object_store_backend": object_store_backend,
        "object_store_pass": True,
        **{f"{name}_pass": True for name in required},
        "artifact_schema": payload.get("schema"),
        "artifact_source_ref": payload.get("source_ref"),
        "artifact_sha256": _sha256_file(Path(path).resolve()),
    }


def _reject_semantic_asset_metadata(
    row: Mapping[str, Any],
    *,
    index: int,
) -> None:
    offending = sorted(
        key
        for key in row
        if any(token in str(key).lower() for token in _FORBIDDEN_ASSET_KEYS)
    )
    if offending:
        raise ValueError(
            f"asset_manifest[{index}] contains semantic leakage fields: "
            f"{', '.join(offending)}."
        )


def _opaque_id(value: Any, *, prefix: str, context: str) -> str:
    text = str(value or "").strip().lower()
    expected_length = len(prefix) + _OPAQUE_ID_HEX_LENGTH
    if (
        len(text) != expected_length
        or not text.startswith(prefix)
        or any(character not in "0123456789abcdef" for character in text[len(prefix) :])
    ):
        raise ValueError(
            f"{context} must be `{prefix}` followed by "
            f"{_OPAQUE_ID_HEX_LENGTH} hexadecimal characters."
        )
    return text


def _verified_child_file(
    root: Path,
    mapping: Mapping[str, Any],
    *,
    path_key: str,
    sha_key: str,
) -> tuple[Path, str]:
    path = _safe_child(root, _required_text(mapping, path_key))
    expected = _required_sha256(mapping, sha_key)
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(f"{path_key} checksum mismatch: expected {expected}, got {actual}.")
    return path, actual


def _verified_content_file(
    root: Path,
    mapping: Mapping[str, Any],
    *,
    context: str,
    opaque_id: str,
) -> tuple[Path, str]:
    path = _safe_child(root, _required_text(mapping, "path", context=context))
    if path.stem.lower() != opaque_id:
        raise ValueError(
            f"{context} filename stem must equal its opaque ID; semantic filenames "
            "are forbidden."
        )
    expected = _required_sha256(mapping, "sha256", context=context)
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(
            f"{context} checksum mismatch: expected {expected}, got {actual}."
        )
    return path, actual


def _safe_child(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes suite root: {value}") from exc
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"suite file does not exist: {candidate}")
    return candidate


def _required_text(
    mapping: Mapping[str, Any],
    key: str,
    *,
    context: str = "suite",
) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise ValueError(f"{context}.{key} is required.")
    return value


def _required_sha256(
    mapping: Mapping[str, Any],
    key: str,
    *,
    context: str = "suite",
) -> str:
    value = _required_text(mapping, key, context=context).lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{context}.{key} must be a SHA-256 digest.")
    return value


def _required_positive_int(
    mapping: Mapping[str, Any],
    key: str,
    *,
    context: str,
) -> int:
    try:
        value = int(mapping.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}.{key} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{context}.{key} must be a positive integer.")
    return value


def _required_modality(
    mapping: Mapping[str, Any],
    key: str,
    *,
    context: str,
) -> str:
    return _normalize_required_modality(
        mapping.get(key),
        context=f"{context}.{key}",
    )


def _normalize_required_modality(value: Any, *, context: str) -> str:
    modality = normalize_modality(value)
    if modality not in _REAL_MODALITIES:
        raise ValueError(
            f"{context} must be one of: {', '.join(_REAL_MODALITIES)}."
        )
    return modality


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _load_json_list(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"JSON file must contain a list: {path}")
    return payload


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    text = "".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _vector_sha256(vector: Any) -> str:
    return hashlib.sha256(np.asarray(vector, dtype=np.float32).tobytes()).hexdigest()


def _unit_vector(vector: Any) -> np.ndarray:
    selected = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(selected))
    if norm <= 1e-12:
        return selected
    return (selected / norm).astype(np.float32)


def _weighted_unit_vector(
    vectors: Sequence[np.ndarray],
    weights: Sequence[float],
) -> np.ndarray:
    if not vectors or len(vectors) != len(weights):
        raise ValueError("Vector fusion requires aligned vectors and weights.")
    shape = vectors[0].shape
    if any(vector.shape != shape for vector in vectors):
        raise ValueError("Only vectors from one explicit shared space may be fused.")
    total = float(sum(weights))
    fused = np.zeros(shape, dtype=np.float32)
    for vector, weight in zip(vectors, weights, strict=True):
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise ValueError("Query encoder produced a zero vector.")
        fused += np.float32(weight / total) * (vector / norm)
    norm = float(np.linalg.norm(fused))
    if norm <= 1e-12:
        raise ValueError("Mixed query vectors cancel to zero.")
    return (fused / norm).astype(np.float32)


def _safe_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _percentile(values: Iterable[float], percentile: float) -> float:
    selected = sorted(float(value) for value in values)
    if not selected:
        return 0.0
    index = min(
        len(selected) - 1,
        max(0, math.ceil((percentile / 100.0) * len(selected)) - 1),
    )
    return selected[index]


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise RuntimeError("Could not resolve an exact source commit SHA.")
    return value


def _dependency_lock_sha256() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    normalized = "\n".join(sorted(completed.stdout.splitlines())) + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hardware_fingerprint() -> str:
    cpu = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER") or "unknown-cpu"
    return f"{cpu}; logical_cpus={os.cpu_count() or 0}"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run WaveMind's strict real-asset local multimodal benchmark."
        )
    )
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--lifecycle-artifact", required=True, type=Path)
    parser.add_argument("--cache-folder", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args(argv)
    result = write_public_multimodal_benchmark_artifacts(
        args.suite,
        output_dir=args.output_dir,
        result_path=args.result,
        cache_folder=args.cache_folder,
        repeats=args.repeats,
        batch_size=args.batch_size,
        top_k=args.top_k,
        lifecycle_artifact=args.lifecycle_artifact,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "payload_count": result["payload_count"],
                "query_count": result["query_count"],
                "result": str(args.result.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
