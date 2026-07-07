from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.production_load_benchmark import add_slo_evaluation, preflight


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms <= 1e-12, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def _normalize_one(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector
    return (vector / norm).astype(np.float32)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((pct / 100.0) * (len(ordered) - 1)))),
    )
    return ordered[index]


def _optional_int_env(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return int(value)


def _optional_bool_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value.lower() in {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return bool(default)
    return value.lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return int(default)
    return int(value)


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _split_env_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()]


def _safe_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} must be a simple SQL identifier")
    return value


def _vector_literal(vector: np.ndarray) -> str:
    normalized = _normalize_one(vector)
    return json.dumps([float(value) for value in normalized], separators=(",", ":"))


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass(frozen=True)
class QdrantShardTarget:
    index: int
    url: str
    collection_name: str
    api_key: str | None = None


def _qdrant_shard_index(point_id: int, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    return (int(point_id) - 1) % int(shard_count)


def _qdrant_shard_targets_from_env(base_collection_name: str) -> list[QdrantShardTarget]:
    urls = _split_env_list(os.environ.get("WAVEMIND_QDRANT_URLS"))
    if not urls:
        url = os.environ.get("WAVEMIND_QDRANT_URL")
        if url:
            urls = [url]
    api_keys = _split_env_list(os.environ.get("WAVEMIND_QDRANT_API_KEYS"))
    default_api_key = os.environ.get("WAVEMIND_QDRANT_API_KEY")
    targets: list[QdrantShardTarget] = []
    for index, url in enumerate(urls):
        api_key = api_keys[index] if index < len(api_keys) else default_api_key
        targets.append(
            QdrantShardTarget(
                index=index,
                url=url,
                collection_name=f"{base_collection_name}_s{index:03d}",
                api_key=api_key,
            )
        )
    return targets


def _merge_scored_hits(hits_by_shard: Iterable[Iterable[Any]], top_k: int) -> list[int]:
    scored: list[tuple[float, int]] = []
    for hits in hits_by_shard:
        for hit in hits:
            scored.append((float(getattr(hit, "score", 0.0)), int(hit.id)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [point_id for _, point_id in scored[: int(top_k)]]


def _pgvector_config_from_env() -> dict[str, Any]:
    return {
        "table": _safe_identifier(
            os.environ.get("WAVEMIND_PGVECTOR_TABLE", "wavemind_streaming_vectors"),
            "WAVEMIND_PGVECTOR_TABLE",
        ),
        "collection": os.environ.get("WAVEMIND_PGVECTOR_COLLECTION")
        or f"streaming_load_{time.time_ns()}",
        "create_hnsw": _bool_env("WAVEMIND_PGVECTOR_CREATE_HNSW", True),
        "hnsw_m": _optional_int_env("WAVEMIND_PGVECTOR_HNSW_M"),
        "hnsw_ef_construction": _optional_int_env("WAVEMIND_PGVECTOR_HNSW_EF_CONSTRUCTION"),
        "ef_search": _optional_int_env("WAVEMIND_PGVECTOR_EF_SEARCH"),
        "exact": _bool_env("WAVEMIND_PGVECTOR_EXACT", False),
        "iterative_scan": os.environ.get("WAVEMIND_PGVECTOR_ITERATIVE_SCAN"),
        "max_scan_tuples": _optional_int_env("WAVEMIND_PGVECTOR_MAX_SCAN_TUPLES"),
        "scan_mem_multiplier": _optional_int_env("WAVEMIND_PGVECTOR_SCAN_MEM_MULTIPLIER"),
        "keep_collection": _bool_env("WAVEMIND_PGVECTOR_KEEP_COLLECTION", False),
    }


def _qdrant_collection_config_from_env() -> dict[str, Any]:
    hnsw = _without_none(
        {
            "m": _optional_int_env("WAVEMIND_QDRANT_HNSW_M"),
            "ef_construct": _optional_int_env("WAVEMIND_QDRANT_HNSW_EF_CONSTRUCT"),
            "full_scan_threshold": _optional_int_env("WAVEMIND_QDRANT_HNSW_FULL_SCAN_THRESHOLD"),
            "max_indexing_threads": _optional_int_env("WAVEMIND_QDRANT_HNSW_MAX_INDEXING_THREADS"),
            "on_disk": _optional_bool_env("WAVEMIND_QDRANT_HNSW_ON_DISK"),
            "payload_m": _optional_int_env("WAVEMIND_QDRANT_HNSW_PAYLOAD_M"),
            "inline_storage": _optional_bool_env("WAVEMIND_QDRANT_HNSW_INLINE_STORAGE"),
        }
    )
    optimizers = _without_none(
        {
            "default_segment_number": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_DEFAULT_SEGMENT_NUMBER"),
            "max_segment_size": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MAX_SEGMENT_SIZE"),
            "memmap_threshold": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MEMMAP_THRESHOLD"),
            "indexing_threshold": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_INDEXING_THRESHOLD"),
            "flush_interval_sec": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_FLUSH_INTERVAL_SEC"),
            "max_optimization_threads": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MAX_THREADS"),
        }
    )
    return {
        "hnsw": hnsw,
        "optimizers": optimizers,
        "vector_on_disk": _optional_bool_env("WAVEMIND_QDRANT_VECTOR_ON_DISK"),
        "on_disk_payload": _optional_bool_env("WAVEMIND_QDRANT_ON_DISK_PAYLOAD"),
        "shard_number": _optional_int_env("WAVEMIND_QDRANT_SHARD_NUMBER"),
    }


@contextmanager
def _local_no_proxy(url: str):
    if not any(host in url for host in ("127.0.0.1", "localhost", "::1")):
        yield
        return
    original_no_proxy = os.environ.get("NO_PROXY")
    original_no_proxy_lower = os.environ.get("no_proxy")
    local_hosts = "127.0.0.1,localhost,::1"
    os.environ["NO_PROXY"] = (
        f"{original_no_proxy},{local_hosts}" if original_no_proxy else local_hosts
    )
    os.environ["no_proxy"] = (
        f"{original_no_proxy_lower},{local_hosts}" if original_no_proxy_lower else local_hosts
    )
    try:
        yield
    finally:
        if original_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = original_no_proxy
        if original_no_proxy_lower is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = original_no_proxy_lower


def choose_source_ids(count: int, query_count: int, seed: int) -> list[int]:
    if count <= 0:
        return []
    capped = min(int(query_count), int(count))
    rng = np.random.default_rng(seed + 4049)
    return [int(id) + 1 for id in rng.choice(count, size=capped, replace=False)]


def iter_vector_batches(
    *,
    count: int,
    dim: int,
    seed: int,
    batch_size: int,
    source_ids: Iterable[int],
) -> Iterable[tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]]:
    rng = np.random.default_rng(seed)
    source_set = set(int(id) for id in source_ids)
    for start in range(0, count, batch_size):
        size = min(batch_size, count - start)
        ids = np.arange(start + 1, start + size + 1, dtype=np.int64)
        vectors = _normalize(rng.normal(size=(size, dim)).astype(np.float32))
        captured: dict[int, np.ndarray] = {}
        end = start + size
        for source_id in source_set:
            if start < source_id <= end:
                captured[source_id] = vectors[source_id - start - 1].copy()
        yield ids, vectors, captured


def make_queries(
    *,
    source_ids: list[int],
    source_vectors: dict[int, np.ndarray],
    seed: int,
    noise: float,
) -> list[tuple[int, np.ndarray]]:
    missing = [id for id in source_ids if id not in source_vectors]
    if missing:
        sample = ", ".join(str(id) for id in missing[:5])
        raise RuntimeError(f"Missing source vectors for query ids: {sample}")
    rng = np.random.default_rng(seed + 1009)
    queries = []
    for source_id in source_ids:
        source = source_vectors[source_id]
        perturbation = rng.normal(scale=noise, size=source.shape[0]).astype(np.float32)
        queries.append((source_id, _normalize_one(source + perturbation)))
    return queries


def training_sample(*, dim: int, seed: int, sample_size: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 7919)
    return _normalize(rng.normal(size=(int(sample_size), int(dim))).astype(np.float32))


def _metrics_from_hits(
    *,
    engine: str,
    vector_count: int,
    dim: int,
    batch_size: int,
    top_k: int,
    build_ms: float,
    query_rows: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in query_rows]
    target_hits = [bool(row["target_hit"]) for row in query_rows]
    target_hit_at_1 = [bool(row["target_hit_at_1"]) for row in query_rows]
    result = {
        "engine": engine,
        "vectors": int(vector_count),
        "vector_dim": int(dim),
        "batch_size": int(batch_size),
        "recall_at_k": statistics.mean(target_hits) if target_hits else 0.0,
        "target_recall_at_k": statistics.mean(target_hits) if target_hits else 0.0,
        "target_recall_at_1": statistics.mean(target_hit_at_1) if target_hit_at_1 else 0.0,
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
        "p99_latency_ms": _percentile(latencies, 99),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "build_ms": float(build_ms),
        "queries": len(query_rows),
        "recall_definition": "source vector id appears in top_k for a noisy copy of that vector",
    }
    if extra:
        result.update(extra)
    return result


def skipped_result(engine: str, reason: str) -> dict[str, Any]:
    return {
        "engine": engine,
        "skipped": True,
        "reason": reason,
    }


def _bytes_to_gb(value: float) -> float:
    return float(value) / float(1024**3)


def _round_gb(value: float) -> float:
    return round(float(value), 3)


def _env_ready(names: Iterable[str]) -> tuple[bool, list[str]]:
    missing = [name for name in names if not os.environ.get(name)]
    return not missing, missing


def _streaming_plan_row(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engine: str,
    output_path: Path | None,
    planned_result_output_path: Path | None,
    target_recall: float,
    target_p99_ms: float,
    target_qps: float,
    replicas: int,
    autoscaling_max_replicas: int,
    capacity_headroom: float,
    memory_payload_kb: float,
    vector_dtype_bytes: int,
    disk_free_gb: float,
    safety_factor: float,
) -> dict[str, Any]:
    key = engine.lower()
    canonical = {
        "numpy-streaming": "WaveMind numpy-streaming",
        "faiss-persisted": "WaveMind faiss-persisted streaming",
        "faiss-ivfpq-persisted": "WaveMind faiss-ivfpq-persisted streaming",
        "qdrant-service": "Qdrant service streaming",
        "qdrant-sharded": "Qdrant sharded service streaming",
        "qdrant-sharded-service": "Qdrant sharded service streaming",
        "qdrant-sharded-streaming": "Qdrant sharded service streaming",
        "pgvector-service": "WaveMind pgvector streaming",
        "pgvector-streaming": "WaveMind pgvector streaming",
    }.get(key, engine)
    vector_bytes = int(count) * int(dim) * int(vector_dtype_bytes)
    payload_bytes = int(count) * float(memory_payload_kb) * 1024.0
    source_vector_bytes = min(int(query_count), int(count)) * int(dim) * int(vector_dtype_bytes)
    batch_bytes = min(int(batch_size), int(count)) * int(dim) * int(vector_dtype_bytes)
    blockers: list[str] = []
    required_env: list[str] = []
    module_requirements: list[str] = []
    index_bytes = vector_bytes
    transient_bytes = batch_bytes + source_vector_bytes
    index_mode = "full matrix"
    command_env: dict[str, str] = {}

    if key == "numpy-streaming":
        index_mode = "full float32 matrix; smoke/testing only at large N"
        if count > 1_000_000:
            blockers.append("numpy_streaming_not_large_n_production_path")
    elif key == "faiss-persisted":
        module_requirements = ["faiss"]
        required_env = ["WAVEMIND_FAISS_PATH"]
        index_bytes = vector_bytes + int(count) * 8
        index_mode = "persisted FAISS flat index plus int64 ids"
        command_env = {"WAVEMIND_FAISS_PATH": "./state/wavemind-faiss-50m.faiss"}
    elif key == "faiss-ivfpq-persisted":
        module_requirements = ["faiss"]
        required_env = ["WAVEMIND_FAISS_IVFPQ_PATH"]
        nlist = _int_env("WAVEMIND_FAISS_IVFPQ_NLIST", 4096)
        pq_m = _int_env("WAVEMIND_FAISS_IVFPQ_M", 16)
        nbits = _int_env("WAVEMIND_FAISS_IVFPQ_NBITS", 8)
        nprobe = _int_env("WAVEMIND_FAISS_IVFPQ_NPROBE", min(1024, nlist))
        training_size = _int_env("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", max(200_000, nlist * 40))
        if dim % pq_m != 0:
            blockers.append(f"vector_dim_not_divisible_by_ivfpq_m:{dim}%{pq_m}")
        code_bytes = int(count) * int(math.ceil((pq_m * nbits) / 8.0))
        id_bytes = int(count) * 8
        centroid_bytes = int(nlist) * int(dim) * int(vector_dtype_bytes)
        training_bytes = int(training_size) * int(dim) * int(vector_dtype_bytes)
        index_bytes = code_bytes + id_bytes + centroid_bytes
        transient_bytes += training_bytes
        index_mode = "persisted FAISS IVF-PQ compressed codes plus int64 ids"
        command_env = {
            "WAVEMIND_FAISS_IVFPQ_PATH": "./state/wavemind-faiss-ivfpq-50m.faiss",
            "WAVEMIND_FAISS_IVFPQ_NLIST": str(nlist),
            "WAVEMIND_FAISS_IVFPQ_M": str(pq_m),
            "WAVEMIND_FAISS_IVFPQ_NBITS": str(nbits),
            "WAVEMIND_FAISS_IVFPQ_NPROBE": str(nprobe),
            "WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE": str(training_size),
        }
    elif key == "qdrant-service":
        module_requirements = ["qdrant_client"]
        required_env = ["WAVEMIND_QDRANT_URL"]
        index_bytes = 0
        index_mode = "remote Qdrant service storage; local runner stores only generated batches"
        command_env = {"WAVEMIND_QDRANT_URL": "http://qdrant.example:6333"}
    elif key in {"qdrant-sharded", "qdrant-sharded-service", "qdrant-sharded-streaming"}:
        module_requirements = ["qdrant_client"]
        required_env = ["WAVEMIND_QDRANT_URLS"]
        index_bytes = 0
        shard_count = max(2, _int_env("WAVEMIND_QDRANT_SHARD_COUNT", 4))
        index_mode = (
            "remote horizontally sharded Qdrant storage; local runner routes ids "
            "across service URLs and fanout-merges top-k"
        )
        command_env = {
            "WAVEMIND_QDRANT_URLS": ",".join(
                f"http://qdrant-{index}.example:6333" for index in range(shard_count)
            ),
            "WAVEMIND_QDRANT_COLLECTION_PREFIX": "wavemind_streaming_load_10m",
            "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE": "2000",
            "WAVEMIND_QDRANT_FANOUT_WORKERS": str(shard_count),
            "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": "30",
            "WAVEMIND_QDRANT_WARMUP_QUERIES": "100",
        }
    elif key in {"pgvector", "pgvector-service", "pgvector-streaming"}:
        module_requirements = ["psycopg"]
        required_env = ["WAVEMIND_PGVECTOR_DSN"]
        index_bytes = 0
        index_mode = "remote PostgreSQL/pgvector storage; local runner stores only generated batches"
        command_env = {
            "WAVEMIND_PGVECTOR_DSN": "postgresql://user:password@postgres.example:5432/wavemind",
            "WAVEMIND_PGVECTOR_CREATE_HNSW": "1",
            "WAVEMIND_PGVECTOR_EF_SEARCH": "1000",
        }
    else:
        raise ValueError(f"Unknown engine: {engine}")

    module_status = {
        name: _module_available(name)
        for name in module_requirements
        if name in module_requirements
    }
    missing_modules = [name for name, ok in module_status.items() if not ok]
    if missing_modules:
        blockers.extend(f"missing_module:{name}" for name in missing_modules)
    env_ok, missing_env = _env_ready(required_env)
    if not env_ok:
        blockers.extend(f"missing_env:{name}" for name in missing_env)

    required_local_free_gb = _bytes_to_gb((index_bytes + transient_bytes) * safety_factor)
    if disk_free_gb < required_local_free_gb:
        blockers.append("insufficient_local_disk_for_index_and_transient_batches")

    command_output_path = planned_result_output_path or output_path or Path("benchmarks/production_streaming_load_results.json")
    command_parts = [
        "python",
        "benchmarks/production_streaming_load_benchmark.py",
        "--sizes",
        str(int(count)),
        "--dim",
        str(int(dim)),
        "--queries",
        str(int(query_count)),
        "--top-k",
        str(int(top_k)),
        "--seed",
        str(int(seed)),
        "--noise",
        str(float(noise)),
        "--batch-size",
        str(int(batch_size)),
        "--engines",
        engine,
        "--target-recall",
        str(float(target_recall)),
        "--target-p99-ms",
        str(float(target_p99_ms)),
        "--target-qps",
        str(float(target_qps)),
        "--replicas",
        str(int(replicas)),
        "--autoscaling-max-replicas",
        str(int(autoscaling_max_replicas)),
        "--capacity-headroom",
        str(float(capacity_headroom)),
        "--output",
        str(command_output_path),
    ]
    return {
        "engine": canonical,
        "vectors": int(count),
        "vector_dim": int(dim),
        "queries": min(int(query_count), int(count)),
        "top_k": int(top_k),
        "batch_size": int(batch_size),
        "index_mode": index_mode,
        "estimated_index_gb": _round_gb(_bytes_to_gb(index_bytes)),
        "estimated_transient_runner_gb": _round_gb(_bytes_to_gb(transient_bytes)),
        "estimated_payload_storage_gb": _round_gb(_bytes_to_gb(payload_bytes)),
        "estimated_float_vector_storage_gb": _round_gb(_bytes_to_gb(vector_bytes)),
        "estimated_application_storage_gb": _round_gb(_bytes_to_gb(vector_bytes + payload_bytes)),
        "required_local_free_gb": _round_gb(required_local_free_gb),
        "disk_free_gb": round(float(disk_free_gb), 3),
        "safety_factor": float(safety_factor),
        "module_requirements": module_status,
        "required_env": required_env,
        "missing_env": missing_env,
        "command_env": command_env,
        "command": " ".join(command_parts),
        "status": "ready" if not blockers else "action_required",
        "blockers": blockers,
        "claim_boundary": "preflight only; this is not a completed latency or recall benchmark",
    }


def plan_streaming_load(
    *,
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
    output_path: Path | None = None,
    planned_result_output_path: Path | None = None,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
    target_qps: float = 100.0,
    replicas: int = 3,
    autoscaling_max_replicas: int = 24,
    capacity_headroom: float = 0.70,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
    safety_factor: float = 1.25,
) -> dict[str, Any]:
    preflight_payload = preflight(output_path=output_path)
    disk_free_gb = float(preflight_payload.get("disk", {}).get("free_gb", 0.0))
    size_list = [int(size) for size in sizes]
    rows = [
        _streaming_plan_row(
            count=size,
            dim=dim,
            query_count=query_count,
            top_k=top_k,
            seed=seed,
            noise=noise,
            batch_size=batch_size,
            engine=engine,
            output_path=output_path,
            planned_result_output_path=planned_result_output_path,
            target_recall=target_recall,
            target_p99_ms=target_p99_ms,
            target_qps=target_qps,
            replicas=replicas,
            autoscaling_max_replicas=autoscaling_max_replicas,
            capacity_headroom=capacity_headroom,
            memory_payload_kb=memory_payload_kb,
            vector_dtype_bytes=vector_dtype_bytes,
            disk_free_gb=disk_free_gb,
            safety_factor=safety_factor,
        )
        for size in size_list
        for engine in engines
    ]
    return {
        "schema": "wavemind.production_streaming_load_plan.v1",
        "status": "ready" if rows and all(row["status"] == "ready" for row in rows) else "action_required",
        "scenario": {
            "name": "production_streaming_load_plan",
            "description": "Plan-only preflight for large-N streaming load runs. It estimates local index/transient storage, application storage, required environment, and the exact reproduction command without generating vectors.",
            "sizes": size_list,
            "vector_dim": int(dim),
            "queries_per_size": int(query_count),
            "top_k": int(top_k),
            "seed": int(seed),
            "noise": float(noise),
            "batch_size": int(batch_size),
            "engines": list(engines),
            "target_recall_at_k": float(target_recall),
            "target_p99_ms": float(target_p99_ms),
            "target_qps": float(target_qps),
            "replicas": int(replicas),
            "autoscaling_max_replicas": int(autoscaling_max_replicas),
            "capacity_headroom": float(capacity_headroom),
            "plan_only": True,
        },
        "preflight": preflight_payload,
        "plans": rows,
    }


def artifact_index_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return path.name


def run_numpy_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    matrix_batches: list[np.ndarray] = []
    id_batches: list[np.ndarray] = []
    started = time.perf_counter()
    for ids, vectors, captured in iter_vector_batches(
        count=count,
        dim=dim,
        seed=seed + count,
        batch_size=batch_size,
        source_ids=source_ids,
    ):
        id_batches.append(ids)
        matrix_batches.append(vectors)
        source_vectors.update(captured)
    ids = np.concatenate(id_batches) if id_batches else np.zeros((0,), dtype=np.int64)
    matrix = np.vstack(matrix_batches).astype(np.float32) if matrix_batches else np.zeros((0, dim), dtype=np.float32)
    build_ms = (time.perf_counter() - started) * 1000.0
    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    rows: list[dict[str, Any]] = []
    k = min(top_k, len(ids))
    for source_id, query in queries:
        started = time.perf_counter()
        scores = matrix @ query
        if k <= 0:
            top_ids = np.zeros((0,), dtype=np.int64)
        else:
            positions = np.argpartition(scores, -k)[-k:]
            positions = positions[np.argsort(scores[positions])[::-1]]
            top_ids = ids[positions]
        latency_ms = (time.perf_counter() - started) * 1000.0
        top = [int(id) for id in top_ids]
        rows.append(
            {
                "source_id": int(source_id),
                "target_hit": int(source_id) in top,
                "target_hit_at_1": bool(top and top[0] == int(source_id)),
                "latency_ms": latency_ms,
            }
        )
    return _metrics_from_hits(
        engine="WaveMind numpy-streaming",
        vector_count=count,
        dim=dim,
        batch_size=batch_size,
        top_k=top_k,
        build_ms=build_ms,
        query_rows=rows,
        extra={"memory_mode": "stores full matrix; smoke/testing only"},
    )


def run_faiss_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    path = os.environ.get("WAVEMIND_FAISS_PATH")
    if not path:
        return skipped_result("WaveMind faiss-persisted streaming", "Set WAVEMIND_FAISS_PATH to run streaming FAISS")
    try:
        import faiss
    except ImportError as exc:
        return skipped_result("WaveMind faiss-persisted streaming", f"Install faiss-cpu: {exc}")
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(int(dim)))
    started = time.perf_counter()
    for ids, vectors, captured in iter_vector_batches(
        count=count,
        dim=dim,
        seed=seed + count,
        batch_size=batch_size,
        source_ids=source_ids,
    ):
        index.add_with_ids(vectors.astype(np.float32), ids.astype(np.int64))
        source_vectors.update(captured)
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(output))
    build_ms = (time.perf_counter() - started) * 1000.0
    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    rows: list[dict[str, Any]] = []
    for source_id, query in queries:
        started = time.perf_counter()
        _, labels = index.search(query.reshape(1, -1).astype(np.float32), top_k)
        latency_ms = (time.perf_counter() - started) * 1000.0
        top = [int(id) for id in labels[0] if int(id) >= 0]
        rows.append(
            {
                "source_id": int(source_id),
                "target_hit": int(source_id) in top,
                "target_hit_at_1": bool(top and top[0] == int(source_id)),
                "latency_ms": latency_ms,
            }
        )
    return _metrics_from_hits(
        engine="WaveMind faiss-persisted streaming",
        vector_count=count,
        dim=dim,
        batch_size=batch_size,
        top_k=top_k,
        build_ms=build_ms,
        query_rows=rows,
        extra={
            "index_path": artifact_index_path(output),
            "memory_mode": "streaming add_with_ids; query source vectors only",
        },
    )


def run_faiss_ivfpq_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    path = os.environ.get("WAVEMIND_FAISS_IVFPQ_PATH") or os.environ.get("WAVEMIND_FAISS_PATH")
    engine = "WaveMind faiss-ivfpq-persisted streaming"
    if not path:
        return skipped_result(engine, "Set WAVEMIND_FAISS_IVFPQ_PATH to run streaming FAISS IVF-PQ")
    try:
        import faiss
    except ImportError as exc:
        return skipped_result(engine, f"Install faiss-cpu: {exc}")

    nlist = _int_env("WAVEMIND_FAISS_IVFPQ_NLIST", 4096)
    pq_m = _int_env("WAVEMIND_FAISS_IVFPQ_M", 16)
    nbits = _int_env("WAVEMIND_FAISS_IVFPQ_NBITS", 8)
    nprobe = _int_env("WAVEMIND_FAISS_IVFPQ_NPROBE", min(64, nlist))
    training_size = _int_env("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", max(100_000, nlist * 40))

    if dim % pq_m != 0:
        return skipped_result(engine, f"vector dim {dim} must be divisible by WAVEMIND_FAISS_IVFPQ_M={pq_m}")
    if nlist <= 0 or pq_m <= 0 or nbits <= 0:
        return skipped_result(engine, "IVF-PQ parameters nlist, M, and nbits must be positive")

    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    quantizer = faiss.IndexFlatIP(int(dim))
    index = faiss.IndexIVFPQ(
        quantizer,
        int(dim),
        int(nlist),
        int(pq_m),
        int(nbits),
        faiss.METRIC_INNER_PRODUCT,
    )
    index.nprobe = int(min(max(1, nprobe), nlist))

    started = time.perf_counter()
    sample = training_sample(dim=dim, seed=seed + count, sample_size=training_size)
    index.train(sample)
    for ids, vectors, captured in iter_vector_batches(
        count=count,
        dim=dim,
        seed=seed + count,
        batch_size=batch_size,
        source_ids=source_ids,
    ):
        index.add_with_ids(vectors.astype(np.float32), ids.astype(np.int64))
        source_vectors.update(captured)
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(output))
    build_ms = (time.perf_counter() - started) * 1000.0

    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    rows: list[dict[str, Any]] = []
    for source_id, query in queries:
        started = time.perf_counter()
        _, labels = index.search(query.reshape(1, -1).astype(np.float32), top_k)
        latency_ms = (time.perf_counter() - started) * 1000.0
        top = [int(id) for id in labels[0] if int(id) >= 0]
        rows.append(
            {
                "source_id": int(source_id),
                "target_hit": int(source_id) in top,
                "target_hit_at_1": bool(top and top[0] == int(source_id)),
                "latency_ms": latency_ms,
            }
        )
    return _metrics_from_hits(
        engine=engine,
        vector_count=count,
        dim=dim,
        batch_size=batch_size,
        top_k=top_k,
        build_ms=build_ms,
        query_rows=rows,
        extra={
            "index_path": artifact_index_path(output),
            "memory_mode": "streaming IVF-PQ; compressed codes plus query source vectors only",
            "faiss_index": "IndexIVFPQ",
            "ivfpq_nlist": int(nlist),
            "ivfpq_m": int(pq_m),
            "ivfpq_nbits": int(nbits),
            "ivfpq_nprobe": int(index.nprobe),
            "ivfpq_training_size": int(training_size),
            "compression_note": "approximate target-recall; tune nprobe/nlist/M for recall-latency tradeoff",
        },
    )


def run_qdrant_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    url = os.environ.get("WAVEMIND_QDRANT_URL")
    if not url:
        return skipped_result("Qdrant service streaming", "Set WAVEMIND_QDRANT_URL to run streaming Qdrant")
    try:
        upsert_batch_size = _positive_int_env("WAVEMIND_QDRANT_UPSERT_BATCH_SIZE", 5000)
    except ValueError as exc:
        return skipped_result("Qdrant service streaming", str(exc))
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            HnswConfigDiff,
            OptimizersConfigDiff,
            PointStruct,
            SearchParams,
            VectorParams,
        )
    except ImportError as exc:
        return skipped_result("Qdrant service streaming", f"Install qdrant-client: {exc}")

    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    collection_name = os.environ.get("WAVEMIND_QDRANT_COLLECTION") or f"wavemind_streaming_load_{time.time_ns()}"
    collection_config = _qdrant_collection_config_from_env()
    hnsw_config = (
        HnswConfigDiff(**collection_config["hnsw"])
        if collection_config["hnsw"]
        else None
    )
    optimizers_config = (
        OptimizersConfigDiff(**collection_config["optimizers"])
        if collection_config["optimizers"]
        else None
    )
    recreate_kwargs = _without_none(
        {
            "hnsw_config": hnsw_config,
            "optimizers_config": optimizers_config,
            "on_disk_payload": collection_config["on_disk_payload"],
            "shard_number": collection_config["shard_number"],
        }
    )
    with _local_no_proxy(url):
        client = QdrantClient(
            url=url,
            api_key=os.environ.get("WAVEMIND_QDRANT_API_KEY"),
            timeout=float(os.environ.get("WAVEMIND_QDRANT_TIMEOUT", "120")),
        )
    try:
        started = time.perf_counter()
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=int(dim),
                distance=Distance.COSINE,
                on_disk=collection_config["vector_on_disk"],
            ),
            timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
            **recreate_kwargs,
        )
        for ids, vectors, captured in iter_vector_batches(
            count=count,
            dim=dim,
            seed=seed + count,
            batch_size=batch_size,
            source_ids=source_ids,
        ):
            points = [
                PointStruct(id=int(id), vector=vector.tolist())
                for id, vector in zip(ids, vectors)
            ]
            for point_chunk in _chunks(points, upsert_batch_size):
                client.upsert(collection_name=collection_name, points=point_chunk)
            source_vectors.update(captured)
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        build_ms = (time.perf_counter() - started) * 1000.0
        hnsw_ef = os.environ.get("WAVEMIND_QDRANT_HNSW_EF")
        exact = os.environ.get("WAVEMIND_QDRANT_EXACT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        search_params = None
        if hnsw_ef or exact:
            search_params = SearchParams(
                hnsw_ef=int(hnsw_ef) if hnsw_ef else None,
                exact=exact or None,
            )
        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        warmup_queries = int(os.environ.get("WAVEMIND_QDRANT_WARMUP_QUERIES", "0"))
        if warmup_queries > 0 and queries:
            for index in range(warmup_queries):
                _, query = queries[index % len(queries)]
                list(
                    client.query_points(
                        collection_name=collection_name,
                        query=query.tolist(),
                        limit=top_k,
                        with_payload=False,
                        search_params=search_params,
                    ).points
                )
        rows: list[dict[str, Any]] = []
        for source_id, query in queries:
            started = time.perf_counter()
            hits = list(
                client.query_points(
                    collection_name=collection_name,
                    query=query.tolist(),
                    limit=top_k,
                    with_payload=False,
                    search_params=search_params,
                ).points
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            top = [int(hit.id) for hit in hits]
            rows.append(
                {
                    "source_id": int(source_id),
                    "target_hit": int(source_id) in top,
                    "target_hit_at_1": bool(top and top[0] == int(source_id)),
                    "latency_ms": latency_ms,
                }
            )
        return _metrics_from_hits(
            engine="Qdrant service streaming",
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "collection_name": collection_name,
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "search_params": {
                    "hnsw_ef": int(hnsw_ef) if hnsw_ef else None,
                    "exact": exact,
                },
                "collection_params": collection_config,
                "upsert_batch_size": upsert_batch_size,
                "memory_mode": "streaming upsert; query source vectors only",
            },
        )
    finally:
        if os.environ.get("WAVEMIND_QDRANT_KEEP_COLLECTION", "0").lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            try:
                client.delete_collection(collection_name=collection_name)
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            close()


def run_qdrant_sharded_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    engine = "Qdrant sharded service streaming"
    base_collection_name = (
        os.environ.get("WAVEMIND_QDRANT_COLLECTION_PREFIX")
        or os.environ.get("WAVEMIND_QDRANT_COLLECTION")
        or f"wavemind_streaming_load_{time.time_ns()}"
    )
    targets = _qdrant_shard_targets_from_env(base_collection_name)
    if len(targets) < 2:
        return skipped_result(
            engine,
            "Set WAVEMIND_QDRANT_URLS to at least two comma-separated Qdrant service URLs",
        )
    try:
        upsert_batch_size = _positive_int_env("WAVEMIND_QDRANT_UPSERT_BATCH_SIZE", 5000)
        fanout_workers = min(
            len(targets),
            _positive_int_env("WAVEMIND_QDRANT_FANOUT_WORKERS", len(targets)),
        )
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            HnswConfigDiff,
            OptimizersConfigDiff,
            PointStruct,
            SearchParams,
            VectorParams,
        )
    except ImportError as exc:
        return skipped_result(engine, f"Install qdrant-client: {exc}")

    collection_config = _qdrant_collection_config_from_env()
    hnsw_config = (
        HnswConfigDiff(**collection_config["hnsw"])
        if collection_config["hnsw"]
        else None
    )
    optimizers_config = (
        OptimizersConfigDiff(**collection_config["optimizers"])
        if collection_config["optimizers"]
        else None
    )
    recreate_kwargs = _without_none(
        {
            "hnsw_config": hnsw_config,
            "optimizers_config": optimizers_config,
            "on_disk_payload": collection_config["on_disk_payload"],
            "shard_number": collection_config["shard_number"],
        }
    )
    clients = []
    for target in targets:
        with _local_no_proxy(target.url):
            clients.append(
                QdrantClient(
                    url=target.url,
                    api_key=target.api_key,
                    timeout=float(os.environ.get("WAVEMIND_QDRANT_TIMEOUT", "120")),
                )
            )

    def query_target(client: Any, target: QdrantShardTarget, query: np.ndarray, search_params: Any) -> list[Any]:
        return list(
            client.query_points(
                collection_name=target.collection_name,
                query=query.tolist(),
                limit=top_k,
                with_payload=False,
                search_params=search_params,
            ).points
        )

    try:
        source_ids = choose_source_ids(count, query_count, seed)
        source_vectors: dict[int, np.ndarray] = {}
        started = time.perf_counter()
        for client, target in zip(clients, targets):
            client.recreate_collection(
                collection_name=target.collection_name,
                vectors_config=VectorParams(
                    size=int(dim),
                    distance=Distance.COSINE,
                    on_disk=collection_config["vector_on_disk"],
                ),
                timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
                **recreate_kwargs,
            )
        for ids, vectors, captured in iter_vector_batches(
            count=count,
            dim=dim,
            seed=seed + count,
            batch_size=batch_size,
            source_ids=source_ids,
        ):
            points_by_shard: dict[int, list[Any]] = {index: [] for index in range(len(targets))}
            for point_id, vector in zip(ids, vectors):
                shard_index = _qdrant_shard_index(int(point_id), len(targets))
                points_by_shard[shard_index].append(
                    PointStruct(id=int(point_id), vector=vector.tolist())
                )
            for shard_index, points in points_by_shard.items():
                if not points:
                    continue
                client = clients[shard_index]
                collection_name = targets[shard_index].collection_name
                for point_chunk in _chunks(points, upsert_batch_size):
                    client.upsert(collection_name=collection_name, points=point_chunk)
            source_vectors.update(captured)
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        build_ms = (time.perf_counter() - started) * 1000.0
        hnsw_ef = os.environ.get("WAVEMIND_QDRANT_HNSW_EF")
        exact = os.environ.get("WAVEMIND_QDRANT_EXACT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        search_params = None
        if hnsw_ef or exact:
            search_params = SearchParams(
                hnsw_ef=int(hnsw_ef) if hnsw_ef else None,
                exact=exact or None,
            )
        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        with concurrent.futures.ThreadPoolExecutor(max_workers=fanout_workers) as executor:
            warmup_queries = int(os.environ.get("WAVEMIND_QDRANT_WARMUP_QUERIES", "0"))
            if warmup_queries > 0 and queries:
                for index in range(warmup_queries):
                    _, query = queries[index % len(queries)]
                    list(
                        executor.map(
                            lambda pair: query_target(pair[0], pair[1], query, search_params),
                            zip(clients, targets),
                        )
                    )
            rows: list[dict[str, Any]] = []
            for source_id, query in queries:
                started = time.perf_counter()
                hits_by_shard = list(
                    executor.map(
                        lambda pair: query_target(pair[0], pair[1], query, search_params),
                        zip(clients, targets),
                    )
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                top = _merge_scored_hits(hits_by_shard, top_k)
                rows.append(
                    {
                        "source_id": int(source_id),
                        "target_hit": int(source_id) in top,
                        "target_hit_at_1": bool(top and top[0] == int(source_id)),
                        "latency_ms": latency_ms,
                    }
                )
        return _metrics_from_hits(
            engine=engine,
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "collection_prefix": base_collection_name,
                "collection_names": [target.collection_name for target in targets],
                "shard_count": len(targets),
                "fanout_workers": fanout_workers,
                "routing": "point_id_minus_one_mod_shard_count",
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "search_params": {
                    "hnsw_ef": int(hnsw_ef) if hnsw_ef else None,
                    "exact": exact,
                },
                "collection_params": collection_config,
                "upsert_batch_size": upsert_batch_size,
                "memory_mode": "horizontally sharded streaming upsert; parallel fanout query merge",
            },
        )
    finally:
        keep = os.environ.get("WAVEMIND_QDRANT_KEEP_COLLECTION", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        for client, target in zip(clients, targets):
            if not keep:
                try:
                    client.delete_collection(collection_name=target.collection_name)
                except Exception:
                    pass
            close = getattr(client, "close", None)
            if callable(close):
                close()


def run_pgvector_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    dsn = os.environ.get("WAVEMIND_PGVECTOR_DSN")
    engine = "WaveMind pgvector streaming"
    if not dsn:
        return skipped_result(engine, "Set WAVEMIND_PGVECTOR_DSN to run streaming pgvector")
    try:
        import psycopg
    except ImportError as exc:
        return skipped_result(engine, f'Install PostgreSQL support with: pip install "wavemind[postgres]": {exc}')

    try:
        config = _pgvector_config_from_env()
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    iterative_scan = config.get("iterative_scan")
    if iterative_scan and iterative_scan not in {"strict_order", "relaxed_order", "off"}:
        return skipped_result(
            engine,
            "WAVEMIND_PGVECTOR_ITERATIVE_SCAN must be strict_order, relaxed_order, or off",
        )

    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    table = str(config["table"])
    collection = str(config["collection"])
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        started = time.perf_counter()
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                collection TEXT NOT NULL,
                memory_id BIGINT NOT NULL,
                embedding vector({int(dim)}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, memory_id)
            )
            """
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_collection_idx ON {table} (collection)")
        conn.execute(f"DELETE FROM {table} WHERE collection = %s", (collection,))
        insert_sql = (
            f"INSERT INTO {table} (collection, memory_id, embedding, updated_at) "
            f"VALUES (%s, %s, %s::vector, now()) "
            f"ON CONFLICT (collection, memory_id) "
            f"DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now()"
        )
        with conn.cursor() as cur:
            for ids, vectors, captured in iter_vector_batches(
                count=count,
                dim=dim,
                seed=seed + count,
                batch_size=batch_size,
                source_ids=source_ids,
            ):
                rows = [
                    (collection, int(id), _vector_literal(vector))
                    for id, vector in zip(ids, vectors)
                ]
                cur.executemany(insert_sql, rows)
                source_vectors.update(captured)
        if config["create_hnsw"]:
            options = []
            if config["hnsw_m"] is not None:
                options.append(f"m = {int(config['hnsw_m'])}")
            if config["hnsw_ef_construction"] is not None:
                options.append(f"ef_construction = {int(config['hnsw_ef_construction'])}")
            with_options = f" WITH ({', '.join(options)})" if options else ""
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw_idx "
                f"ON {table} USING hnsw (embedding vector_cosine_ops)"
                f"{with_options}"
            )
        conn.execute(f"ANALYZE {table}")
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_PGVECTOR_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        build_ms = (time.perf_counter() - started) * 1000.0

        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        if config["ef_search"] is not None:
            conn.execute(f"SET hnsw.ef_search = {int(config['ef_search'])}")
        if iterative_scan:
            conn.execute(f"SET hnsw.iterative_scan = '{iterative_scan}'")
        if config["max_scan_tuples"] is not None:
            conn.execute(f"SET hnsw.max_scan_tuples = {int(config['max_scan_tuples'])}")
        if config["scan_mem_multiplier"] is not None:
            conn.execute(f"SET hnsw.scan_mem_multiplier = {int(config['scan_mem_multiplier'])}")
        if config["exact"]:
            conn.execute("SET enable_indexscan = off")
            conn.execute("SET enable_bitmapscan = off")

        warmup_queries = int(os.environ.get("WAVEMIND_PGVECTOR_WARMUP_QUERIES", "0"))
        search_sql = (
            f"SELECT memory_id FROM {table} "
            f"WHERE collection = %s "
            f"ORDER BY embedding <=> %s::vector "
            f"LIMIT %s"
        )
        if warmup_queries > 0 and queries:
            for index in range(warmup_queries):
                _, query = queries[index % len(queries)]
                conn.execute(search_sql, (collection, _vector_literal(query), int(top_k))).fetchall()
        rows: list[dict[str, Any]] = []
        for source_id, query in queries:
            started = time.perf_counter()
            hits = conn.execute(search_sql, (collection, _vector_literal(query), int(top_k))).fetchall()
            latency_ms = (time.perf_counter() - started) * 1000.0
            top = [int(row[0]) for row in hits]
            rows.append(
                {
                    "source_id": int(source_id),
                    "target_hit": int(source_id) in top,
                    "target_hit_at_1": bool(top and top[0] == int(source_id)),
                    "latency_ms": latency_ms,
                }
            )
        return _metrics_from_hits(
            engine=engine,
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "table": table,
                "collection": collection,
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "search_params": {
                    "hnsw_ef": config["ef_search"],
                    "exact": config["exact"],
                    "iterative_scan": iterative_scan,
                    "max_scan_tuples": config["max_scan_tuples"],
                    "scan_mem_multiplier": config["scan_mem_multiplier"],
                },
                "collection_params": {
                    "create_hnsw": config["create_hnsw"],
                    "hnsw_m": config["hnsw_m"],
                    "hnsw_ef_construction": config["hnsw_ef_construction"],
                },
                "memory_mode": "streaming PostgreSQL insert; query source vectors only",
            },
        )
    finally:
        try:
            if not config.get("keep_collection"):
                conn.execute(f"DELETE FROM {table} WHERE collection = %s", (collection,))
        finally:
            conn.close()


def run_size(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
) -> dict[str, Any]:
    results = []
    for engine in engines:
        key = engine.lower()
        kwargs = {
            "count": count,
            "dim": dim,
            "query_count": query_count,
            "top_k": top_k,
            "seed": seed,
            "noise": noise,
            "batch_size": batch_size,
        }
        if key in {"numpy", "numpy-streaming"}:
            results.append(run_numpy_streaming(**kwargs))
        elif key in {"faiss", "faiss-persisted", "faiss-streaming"}:
            results.append(run_faiss_streaming(**kwargs))
        elif key in {"faiss-ivfpq", "faiss-ivfpq-persisted", "faiss-ivfpq-streaming"}:
            results.append(run_faiss_ivfpq_streaming(**kwargs))
        elif key in {"qdrant", "qdrant-service", "qdrant-streaming"}:
            results.append(run_qdrant_streaming(**kwargs))
        elif key in {"qdrant-sharded", "qdrant-sharded-service", "qdrant-sharded-streaming"}:
            results.append(run_qdrant_sharded_streaming(**kwargs))
        elif key in {"pgvector", "pgvector-service", "pgvector-streaming"}:
            results.append(run_pgvector_streaming(**kwargs))
        else:
            raise ValueError(f"Unknown engine: {engine}")
    return {
        "vectors": int(count),
        "vector_dim": int(dim),
        "queries": min(int(query_count), int(count)),
        "top_k": int(top_k),
        "noise": float(noise),
        "batch_size": int(batch_size),
        "results": results,
    }


def run_streaming_load(
    *,
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
    output_path: Path | None = None,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
    target_qps: float = 100.0,
    replicas: int = 3,
    autoscaling_max_replicas: int = 24,
    capacity_headroom: float = 0.70,
    replica_hourly_cost_usd: float = 0.25,
    storage_gb_monthly_cost_usd: float = 0.10,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
) -> dict[str, Any]:
    size_list = [int(size) for size in sizes]
    payload = {
        "scenario": {
            "name": "production_streaming_load_profile",
            "description": (
                "Memory-bounded production load profile for 10M+ vector runs. "
                "Vectors are generated and inserted in batches. Quality is measured "
                "as target-recall: whether a noisy copy of a known source vector "
                "returns that source id in top-k. This is scalable to large N and "
                "complements exact-neighbor benchmarks at smaller N. Use persisted "
                "FAISS IVF-PQ for memory-bounded 10M+ compressed-index profiles."
            ),
            "sizes": size_list,
            "vector_dim": int(dim),
            "queries_per_size": int(query_count),
            "top_k": int(top_k),
            "seed": int(seed),
            "noise": float(noise),
            "batch_size": int(batch_size),
            "target_recall_definition": "source id appears in top-k for a noisy copy of that source vector",
            "memory_model": "streaming batches; stores only selected query source vectors outside the index",
            "default_target_sizes": [10_000_000, 50_000_000],
        },
        "preflight": preflight(output_path=output_path),
        "results": [
            run_size(
                count=size,
                dim=dim,
                query_count=query_count,
                top_k=top_k,
                seed=seed,
                noise=noise,
                batch_size=batch_size,
                engines=engines,
            )
            for size in size_list
        ],
    }
    add_slo_evaluation(
        payload,
        target_recall=target_recall,
        target_p99_ms=target_p99_ms,
        target_qps=target_qps,
        replicas=replicas,
        autoscaling_max_replicas=autoscaling_max_replicas,
        capacity_headroom=capacity_headroom,
        replica_hourly_cost_usd=replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=storage_gb_monthly_cost_usd,
        memory_payload_kb=memory_payload_kb,
        vector_dtype_bytes=vector_dtype_bytes,
    )
    return payload


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| vectors | engine | target recall@{top_k} | avg latency | p95 latency | p99 latency | build |")
    print("|---:|---|---:|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - | - |")
                continue
            print(
                f"| {size_result['vectors']} | {result['engine']} | "
                f"{result['target_recall_at_k']:.3f} | "
                f"{result['avg_latency_ms']:.2f} ms | "
                f"{result['p95_latency_ms']:.2f} ms | "
                f"{result['p99_latency_ms']:.2f} ms | "
                f"{result['build_ms']:.1f} ms |"
            )


def print_plan_table(payload: dict[str, Any]) -> None:
    print("| vectors | engine | status | local free | required local free | blockers |")
    print("|---:|---|---|---:|---:|---|")
    for row in payload.get("plans", []):
        blockers = ", ".join(row.get("blockers", [])) or "-"
        print(
            f"| {row['vectors']} | {row['engine']} | {row['status']} | "
            f"{row['disk_free_gb']:.2f} GB | {row['required_local_free_gb']:.2f} GB | {blockers} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000_000])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.08)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--target-recall", type=float, default=0.95)
    parser.add_argument("--target-p99-ms", type=float, default=100.0)
    parser.add_argument("--target-qps", type=float, default=100.0)
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--autoscaling-max-replicas", type=int, default=24)
    parser.add_argument("--capacity-headroom", type=float, default=0.70)
    parser.add_argument("--replica-hourly-cost-usd", type=float, default=0.25)
    parser.add_argument("--storage-gb-monthly-cost-usd", type=float, default=0.10)
    parser.add_argument("--memory-payload-kb", type=float, default=2.0)
    parser.add_argument("--vector-dtype-bytes", type=int, default=4)
    parser.add_argument("--plan-only", action="store_true", help="Write a large-N preflight plan without generating vectors.")
    parser.add_argument("--planned-result-output", type=Path, default=None, help="Result JSON path embedded in plan-only reproduction commands.")
    parser.add_argument("--safety-factor", type=float, default=1.25, help="Disk safety factor for plan-only local index/transient storage estimates.")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=[
            "numpy-streaming",
            "faiss-persisted",
            "faiss-ivfpq-persisted",
            "qdrant-service",
            "qdrant-sharded-service",
            "pgvector-service",
            "pgvector-streaming",
        ],
        default=["faiss-persisted", "qdrant-service"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/production_streaming_load_results.json"))
    args = parser.parse_args()
    if args.plan_only:
        payload = plan_streaming_load(
            sizes=args.sizes,
            dim=args.dim,
            query_count=args.queries,
            top_k=args.top_k,
            seed=args.seed,
            noise=args.noise,
            batch_size=args.batch_size,
            engines=args.engines,
            output_path=args.output,
            planned_result_output_path=args.planned_result_output,
            target_recall=args.target_recall,
            target_p99_ms=args.target_p99_ms,
            target_qps=args.target_qps,
            replicas=args.replicas,
            autoscaling_max_replicas=args.autoscaling_max_replicas,
            capacity_headroom=args.capacity_headroom,
            memory_payload_kb=args.memory_payload_kb,
            vector_dtype_bytes=args.vector_dtype_bytes,
            safety_factor=args.safety_factor,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print_plan_table(payload)
        print(f"\nWrote {args.output}")
        return 0
    payload = run_streaming_load(
        sizes=args.sizes,
        dim=args.dim,
        query_count=args.queries,
        top_k=args.top_k,
        seed=args.seed,
        noise=args.noise,
        batch_size=args.batch_size,
        engines=args.engines,
        output_path=args.output,
        target_recall=args.target_recall,
        target_p99_ms=args.target_p99_ms,
        target_qps=args.target_qps,
        replicas=args.replicas,
        autoscaling_max_replicas=args.autoscaling_max_replicas,
        capacity_headroom=args.capacity_headroom,
        replica_hourly_cost_usd=args.replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=args.storage_gb_monthly_cost_usd,
        memory_payload_kb=args.memory_payload_kb,
        vector_dtype_bytes=args.vector_dtype_bytes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
