from __future__ import annotations

import json
import math
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .core import WaveMind
from .encoders import HashingTextEncoder
from .multimodal import (
    CrossModalMemoryLayer,
    MemoryPayload,
    PrecomputedCrossModalEncoder,
    normalize_modality,
)


EXTERNAL_MULTIMODAL_SCHEMA = "wavemind.multimodal_external_encoder_benchmark.v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return payload


def _as_vector(value: Any, *, name: str) -> np.ndarray:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a vector sequence")
    try:
        vector = np.asarray(list(value), dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric values") from exc
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError(f"{name} must be a non-empty 1D vector")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} contains non-finite values")
    return vector


def _norm(vector: np.ndarray) -> float:
    return float(np.linalg.norm(vector))


def _is_normalized(vector: np.ndarray, *, tolerance: float = 1e-3) -> bool:
    return abs(_norm(vector) - 1.0) <= tolerance


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])


def _p99(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)
    return float(ordered[index])


def _avg(values: Sequence[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _asset_text(asset: dict[str, Any]) -> str:
    text = _first_present(
        asset,
        "text",
        "descriptor",
        "caption",
        "transcript",
        "summary",
        "title",
    )
    if text is None:
        text = f"{asset.get('modality', 'asset')} asset {asset.get('id', '')}"
    return str(text)


def _asset_uri(asset: dict[str, Any]) -> str:
    uri = _first_present(asset, "uri", "asset_uri", "s3_uri", "url")
    return str(uri or "")


def _asset_verified(asset: dict[str, Any]) -> bool:
    if "verified" in asset:
        return bool(asset["verified"])
    if "asset_verified" in asset:
        return bool(asset["asset_verified"])
    object_report = asset.get("object") if isinstance(asset.get("object"), dict) else {}
    return bool(object_report.get("verified"))


def _asset_total_bytes(asset: dict[str, Any]) -> int:
    value = _first_present(asset, "total_bytes", "asset_bytes", "bytes")
    if value is None and isinstance(asset.get("object"), dict):
        value = asset["object"].get("total_bytes")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _asset_sha256(asset: dict[str, Any]) -> str:
    value = _first_present(asset, "sha256", "asset_sha256")
    if value is None and isinstance(asset.get("object"), dict):
        value = asset["object"].get("sha256")
    return str(value or "")


def _asset_media_type(asset: dict[str, Any]) -> str:
    value = _first_present(asset, "media_type", "asset_media_type", "content_type")
    if value is None and isinstance(asset.get("object"), dict):
        value = asset["object"].get("media_type") or asset["object"].get("content_type")
    return str(value or "application/octet-stream")


def _asset_kind(asset: dict[str, Any]) -> str:
    return normalize_modality(asset.get("modality") or asset.get("kind") or "")


def _query_targets(query: dict[str, Any]) -> set[str]:
    values = []
    if "target_asset_id" in query:
        values.append(query["target_asset_id"])
    if "target_id" in query:
        values.append(query["target_id"])
    if isinstance(query.get("target_asset_ids"), list):
        values.extend(query["target_asset_ids"])
    if isinstance(query.get("relevant_asset_ids"), list):
        values.extend(query["relevant_asset_ids"])
    return {str(value) for value in values if value is not None}


def run_external_multimodal_evidence(
    manifest_path: str | Path,
    *,
    namespace: str = "__wavemind_external_multimodal__",
    db_path: str | Path | None = None,
    top_k: int = 3,
    require_object_store: bool = True,
) -> dict[str, Any]:
    """Run a strict external-vector multimodal evidence benchmark.

    The manifest is expected to come from a real external encoder pipeline:
    assets already have shared-space vectors, object-store metadata, and
    queries have precomputed query vectors. This runner verifies the storage and
    retrieval contract without embedding media inside the repository.
    """

    manifest_path = Path(manifest_path)
    manifest = _load_json(manifest_path)
    assets = manifest.get("assets")
    queries = manifest.get("queries")
    if not isinstance(assets, list) or not assets:
        raise ValueError("manifest.assets must be a non-empty list")
    if not isinstance(queries, list) or not queries:
        raise ValueError("manifest.queries must be a non-empty list")
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    encoder_name = str(manifest.get("encoder_name") or manifest.get("encoder") or "external")
    deployment = str(manifest.get("deployment") or "staging")
    environment = str(manifest.get("environment") or deployment)
    source = str(manifest.get("source") or "external-multimodal-manifest")
    object_store = str(manifest.get("object_store") or manifest.get("asset_store") or "")
    object_store_verification_mode = str(
        manifest.get("object_store_verification_mode")
        or manifest.get("object_verification")
        or "manifest"
    )
    vector_dim = int(manifest.get("vector_dim") or len(_as_vector(assets[0].get("vector"), name="assets[0].vector")))

    asset_vectors: dict[str, np.ndarray] = {}
    query_vectors: dict[str, np.ndarray] = {}
    asset_errors: list[str] = []
    query_errors: list[str] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            asset_errors.append(f"assets[{index}] is not an object")
            continue
        asset_id = str(asset.get("id") or f"asset-{index}")
        try:
            vector = _as_vector(asset.get("vector"), name=f"asset {asset_id} vector")
            if vector.size != vector_dim:
                raise ValueError(f"asset {asset_id} vector dimension {vector.size} != {vector_dim}")
            asset_vectors[asset_id] = vector
        except ValueError as exc:
            asset_errors.append(str(exc))
    for index, query in enumerate(queries):
        if not isinstance(query, dict):
            query_errors.append(f"queries[{index}] is not an object")
            continue
        query_id = str(query.get("id") or f"query-{index}")
        try:
            vector = _as_vector(query.get("vector"), name=f"query {query_id} vector")
            if vector.size != vector_dim:
                raise ValueError(f"query {query_id} vector dimension {vector.size} != {vector_dim}")
            query_vectors[query_id] = vector
        except ValueError as exc:
            query_errors.append(str(exc))
    if asset_errors or query_errors:
        return _failed_report(
            manifest=manifest,
            manifest_path=manifest_path,
            vector_dim=vector_dim,
            deployment=deployment,
            environment=environment,
            source=source,
            object_store=object_store,
            object_store_verification_mode=object_store_verification_mode,
            asset_errors=asset_errors,
            query_errors=query_errors,
        )

    modality_values = sorted({_asset_kind(asset) for asset in assets if _asset_kind(asset)})
    object_store_backed = [
        _asset_uri(asset).startswith("s3://")
        for asset in assets
        if isinstance(asset, dict)
    ]
    if require_object_store and not all(object_store_backed):
        asset_errors.append("all assets must use s3:// object-store URIs")
    if require_object_store and not object_store.lower().startswith("s3"):
        asset_errors.append("manifest.object_store must identify an s3-compatible object store")
    if asset_errors:
        return _failed_report(
            manifest=manifest,
            manifest_path=manifest_path,
            vector_dim=vector_dim,
            deployment=deployment,
            environment=environment,
            source=source,
            object_store=object_store,
            object_store_verification_mode=object_store_verification_mode,
            asset_errors=asset_errors,
            query_errors=query_errors,
        )

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="wavemind-multimodal-")
        resolved_db_path = Path(temp_dir.name) / "evidence.sqlite3"
    else:
        resolved_db_path = Path(db_path)
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

    memory = WaveMind(
        db_path=resolved_db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    asset_to_memory_id: dict[str, int] = {}
    memory_to_asset_id: dict[int, str] = {}
    ingest_errors: list[str] = []
    query_errors_runtime: list[str] = []
    query_latencies_ms: list[float] = []
    query_rows: list[dict[str, Any]] = []
    try:
        layer = CrossModalMemoryLayer(
            memory,
            cross_modal_encoder=PrecomputedCrossModalEncoder(
                vector_dim=vector_dim,
                name=encoder_name,
            ),
        )
        for index, asset in enumerate(assets):
            asset_id = str(asset.get("id") or f"asset-{index}")
            modality = _asset_kind(asset)
            metadata = {
                **(asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}),
                "external_asset_id": asset_id,
                "asset_uri": _asset_uri(asset),
                "asset_bucket": str(asset.get("asset_bucket") or ""),
                "asset_key": str(asset.get("asset_key") or ""),
                "asset_bytes": _asset_total_bytes(asset),
                "asset_sha256": _asset_sha256(asset),
                "asset_media_type": _asset_media_type(asset),
                "asset_verified": _asset_verified(asset),
                "object_store_verification_mode": object_store_verification_mode,
                "cross_modal_vector": asset_vectors[asset_id].astype(float).tolist(),
            }
            payload = MemoryPayload(
                kind=modality,
                text=_asset_text(asset),
                metadata=metadata,
                tags=tuple(str(tag) for tag in asset.get("tags", []) if tag),
            )
            try:
                memory_id = layer.remember(payload, namespace=namespace)
                asset_to_memory_id[asset_id] = memory_id
                memory_to_asset_id[memory_id] = asset_id
            except Exception as exc:
                ingest_errors.append(f"{asset_id}: {exc}")

        for index, query in enumerate(queries):
            if not isinstance(query, dict):
                continue
            query_id = str(query.get("id") or f"query-{index}")
            targets = _query_targets(query)
            if not targets:
                query_errors_runtime.append(f"{query_id}: missing target_asset_id")
                continue
            query_text = str(query.get("text") or query.get("query") or query_id)
            target_modality = (
                normalize_modality(query.get("target_modality"))
                if query.get("target_modality")
                else None
            )
            started = time.perf_counter()
            try:
                results = layer.query(
                    query_text,
                    namespace=namespace,
                    target_modality=target_modality,
                    top_k=max(1, top_k),
                    query_vector=query_vectors[query_id],
                )
            except Exception as exc:
                query_errors_runtime.append(f"{query_id}: {exc}")
                continue
            query_latencies_ms.append((time.perf_counter() - started) * 1000.0)
            result_asset_ids = [
                str(result.metadata.get("external_asset_id") or memory_to_asset_id.get(result.id, ""))
                for result in results
            ]
            result_modalities = [result.modality for result in results]
            hit_at_1 = bool(result_asset_ids[:1] and result_asset_ids[0] in targets)
            hit_at_k = bool(set(result_asset_ids[:top_k]) & targets)
            modality_hit = (
                bool(result_modalities[:1] and result_modalities[0] == target_modality)
                if target_modality
                else True
            )
            query_rows.append(
                {
                    "id": query_id,
                    "target_asset_ids": sorted(targets),
                    "target_modality": target_modality,
                    "top_asset_ids": result_asset_ids[:top_k],
                    "top_modalities": result_modalities[:top_k],
                    "hit_at_1": hit_at_1,
                    "hit_at_k": hit_at_k,
                    "target_modality_hit": modality_hit,
                    "latency_ms": query_latencies_ms[-1],
                }
            )

        records = memory.store.list(namespace=namespace, tags=["multimodal"])
    finally:
        memory.close()
        if temp_dir is not None:
            temp_dir.cleanup()

    record_count = len(records)
    vectors_persisted = 0
    provenance_count = 0
    asset_verified_count = 0
    dimension_matches = 0
    finite_vectors = 0
    normalized_vectors = 0
    for record in records:
        metadata = record.metadata
        vector = metadata.get("cross_modal_vector")
        try:
            vector_array = _as_vector(vector, name=f"record {record.id} vector")
        except ValueError:
            vector_array = np.asarray([], dtype=np.float32)
        if vector_array.size:
            vectors_persisted += 1
            finite_vectors += int(np.all(np.isfinite(vector_array)))
            normalized_vectors += int(_is_normalized(vector_array))
            dimension_matches += int(vector_array.size == vector_dim)
        provenance_count += int(bool(metadata.get("asset_uri")) and bool(metadata.get("asset_sha256")))
        asset_verified_count += int(bool(metadata.get("asset_verified")))

    query_count = len(query_rows)
    hit_at_1 = sum(1 for row in query_rows if row["hit_at_1"])
    hit_at_k = sum(1 for row in query_rows if row["hit_at_k"])
    modality_routing = [
        bool(row["target_modality_hit"])
        for row in query_rows
        if row.get("target_modality")
    ]
    query_vector_values = list(query_vectors.values())
    asset_vector_values = list(asset_vectors.values())
    all_vectors = asset_vector_values + query_vector_values
    total_ops = max(1, len(assets) + len(queries))
    errors = ingest_errors + query_errors_runtime
    encode_metrics = manifest.get("encoder_metrics") if isinstance(manifest.get("encoder_metrics"), dict) else {}
    payload_encode_p95_ms = _float_metric(
        encode_metrics,
        manifest,
        "payload_encode_p95_ms",
        "asset_encode_p95_ms",
    )
    query_encode_p95_ms = _float_metric(encode_metrics, manifest, "query_encode_p95_ms")

    metrics = {
        "precision_at_1": hit_at_1 / query_count if query_count else 0.0,
        f"precision_at_{top_k}": hit_at_k / query_count if query_count else 0.0,
        "cross_modal_precision_at_1": hit_at_1 / query_count if query_count else 0.0,
        "target_modality_routing_rate": (
            sum(1 for passed in modality_routing if passed) / len(modality_routing)
            if modality_routing
            else 1.0
        ),
        "vector_persistence_rate": vectors_persisted / record_count if record_count else 0.0,
        "provenance_rate": provenance_count / record_count if record_count else 0.0,
        "object_store_verified_rate": (
            asset_verified_count / record_count if record_count else 0.0
        ),
        "dimension_match_rate": dimension_matches / record_count if record_count else 0.0,
        "finite_vector_rate": (
            sum(1 for vector in all_vectors if np.all(np.isfinite(vector))) / len(all_vectors)
            if all_vectors
            else 0.0
        ),
        "normalized_vector_rate": (
            sum(1 for vector in all_vectors if _is_normalized(vector)) / len(all_vectors)
            if all_vectors
            else 0.0
        ),
        "persisted_finite_vector_rate": finite_vectors / record_count if record_count else 0.0,
        "persisted_normalized_vector_rate": normalized_vectors / record_count if record_count else 0.0,
        "query_avg_ms": _avg(query_latencies_ms),
        "query_p95_ms": _p95(query_latencies_ms),
        "query_p99_ms": _p99(query_latencies_ms),
        "payload_encode_p95_ms": payload_encode_p95_ms,
        "query_encode_p95_ms": query_encode_p95_ms,
        "error_rate": len(errors) / total_ops,
    }
    status = "pass" if not errors and query_count == len(queries) else "fail"
    return {
        "schema": EXTERNAL_MULTIMODAL_SCHEMA,
        "generated_at": _utc_now(),
        "manifest": str(manifest_path),
        "source": source,
        "deployment": deployment,
        "environment": environment,
        "node_mode": "external",
        "object_store": object_store,
        "object_store_verification_mode": object_store_verification_mode,
        "encoder_name": encoder_name,
        "vector_dim": vector_dim,
        "modalities": modality_values,
        "modality_count": len(modality_values),
        "payload_count": len(assets),
        "query_count": len(queries),
        "stored_payload_count": record_count,
        "status": status,
        "metrics": metrics,
        "queries": query_rows,
        "errors": errors,
        "claim_boundary": (
            "This artifact is eligible for multimodal admission only when the "
            "manifest came from an external encoder run and object-store-backed "
            "assets were verified before generating the report."
        ),
    }


def _float_metric(primary: dict[str, Any], secondary: dict[str, Any], *keys: str) -> float:
    for key in keys:
        for source in (primary, secondary):
            if key in source:
                try:
                    return float(source[key])
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


def _failed_report(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    vector_dim: int,
    deployment: str,
    environment: str,
    source: str,
    object_store: str,
    object_store_verification_mode: str,
    asset_errors: list[str],
    query_errors: list[str],
) -> dict[str, Any]:
    assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    queries = manifest.get("queries") if isinstance(manifest.get("queries"), list) else []
    modalities = sorted({_asset_kind(asset) for asset in assets if isinstance(asset, dict)})
    errors = asset_errors + query_errors
    total = max(1, len(assets) + len(queries))
    return {
        "schema": EXTERNAL_MULTIMODAL_SCHEMA,
        "generated_at": _utc_now(),
        "manifest": str(manifest_path),
        "source": source,
        "deployment": deployment,
        "environment": environment,
        "node_mode": "external",
        "object_store": object_store,
        "object_store_verification_mode": object_store_verification_mode,
        "encoder_name": str(manifest.get("encoder_name") or manifest.get("encoder") or "external"),
        "vector_dim": vector_dim,
        "modalities": modalities,
        "modality_count": len(modalities),
        "payload_count": len(assets),
        "query_count": len(queries),
        "stored_payload_count": 0,
        "status": "fail",
        "metrics": {
            "precision_at_1": 0.0,
            "precision_at_3": 0.0,
            "cross_modal_precision_at_1": 0.0,
            "target_modality_routing_rate": 0.0,
            "vector_persistence_rate": 0.0,
            "provenance_rate": 0.0,
            "object_store_verified_rate": 0.0,
            "dimension_match_rate": 0.0,
            "finite_vector_rate": 0.0,
            "normalized_vector_rate": 0.0,
            "query_p99_ms": 0.0,
            "payload_encode_p95_ms": 0.0,
            "query_encode_p95_ms": 0.0,
            "error_rate": len(errors) / total,
        },
        "queries": [],
        "errors": errors,
        "claim_boundary": (
            "Failed external multimodal evidence cannot unlock production "
            "multimodal claims."
        ),
    }


def render_external_multimodal_evidence_markdown(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    lines = [
        "# WaveMind External Multimodal Evidence",
        "",
        "This report is generated from a manifest of externally encoded multimodal",
        "assets and precomputed query vectors. It is the artifact consumed by",
        "`wavemind multimodal-admission`.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload.get('status')}` |",
        f"| source | `{payload.get('source')}` |",
        f"| deployment | `{payload.get('deployment')}` |",
        f"| environment | `{payload.get('environment')}` |",
        f"| object store | `{payload.get('object_store')}` |",
        f"| object verification | `{payload.get('object_store_verification_mode')}` |",
        f"| encoder | `{payload.get('encoder_name')}` |",
        f"| vector dim | `{payload.get('vector_dim')}` |",
        f"| modalities | `{payload.get('modality_count')}` |",
        f"| payloads | `{payload.get('payload_count')}` |",
        f"| queries | `{payload.get('query_count')}` |",
        f"| precision@1 | `{metrics.get('precision_at_1')}` |",
        f"| cross-modal precision@1 | `{metrics.get('cross_modal_precision_at_1')}` |",
        f"| target modality routing | `{metrics.get('target_modality_routing_rate')}` |",
        f"| vector persistence | `{metrics.get('vector_persistence_rate')}` |",
        f"| provenance | `{metrics.get('provenance_rate')}` |",
        f"| object-store verified | `{metrics.get('object_store_verified_rate')}` |",
        f"| query p99 ms | `{metrics.get('query_p99_ms')}` |",
        f"| payload encode p95 ms | `{metrics.get('payload_encode_p95_ms')}` |",
        f"| query encode p95 ms | `{metrics.get('query_encode_p95_ms')}` |",
        f"| error rate | `{metrics.get('error_rate')}` |",
        "",
        "## Errors",
        "",
    ]
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
