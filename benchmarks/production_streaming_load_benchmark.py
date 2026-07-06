from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from contextlib import contextmanager
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


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


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
            "index_path": str(output),
            "memory_mode": "streaming add_with_ids; query source vectors only",
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
            client.upsert(collection_name=collection_name, points=points)
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
        elif key in {"qdrant", "qdrant-service", "qdrant-streaming"}:
            results.append(run_qdrant_streaming(**kwargs))
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
                "complements exact-neighbor benchmarks at smaller N."
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
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["numpy-streaming", "faiss-persisted", "qdrant-service"],
        default=["faiss-persisted", "qdrant-service"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/production_streaming_load_results.json"))
    args = parser.parse_args()
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
