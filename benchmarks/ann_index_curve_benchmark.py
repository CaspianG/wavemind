from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.indexes import create_vector_index


@dataclass(frozen=True)
class VectorRecord:
    id: int
    vector: np.ndarray


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms <= 1e-12, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def make_vectors(count: int, dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return _normalize(rng.normal(size=(count, dim)).astype(np.float32))


def make_queries(vectors: np.ndarray, query_count: int, seed: int, noise: float) -> np.ndarray:
    rng = np.random.default_rng(seed + 1009)
    ids = rng.choice(vectors.shape[0], size=query_count, replace=False)
    noise_matrix = rng.normal(scale=noise, size=(query_count, vectors.shape[1])).astype(np.float32)
    return _normalize(vectors[ids] + noise_matrix)


def exact_neighbors(vectors: np.ndarray, queries: np.ndarray, top_k: int) -> list[set[int]]:
    scores = queries @ vectors.T
    order = np.argsort(scores, axis=1)[:, ::-1][:, :top_k]
    return [set(int(id) + 1 for id in row) for row in order]


def _recall_at_k(results: list[list[int]], expected: list[set[int]], top_k: int) -> float:
    recalls = []
    for row, truth in zip(results, expected):
        recalls.append(len(set(row[:top_k]) & truth) / max(1, len(truth)))
    return statistics.mean(recalls) if recalls else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((pct / 100.0) * (len(ordered) - 1)))),
    )
    return ordered[index]


def run_wavemind_index(
    kind: str,
    vectors: np.ndarray,
    queries: np.ndarray,
    expected: list[set[int]],
    top_k: int,
) -> dict[str, Any]:
    records = [VectorRecord(id=index + 1, vector=vector) for index, vector in enumerate(vectors)]
    index = create_vector_index(kind, vector_dim=vectors.shape[1])
    started = time.perf_counter()
    index.build(records)
    build_ms = (time.perf_counter() - started) * 1000.0
    ids: list[list[int]] = []
    latencies: list[float] = []
    for query in queries:
        started = time.perf_counter()
        result = index.search(query, top_k=top_k)
        latencies.append((time.perf_counter() - started) * 1000.0)
        ids.append([item.id for item in result])
    return {
        "engine": f"WaveMind {kind}",
        "recall_at_k": _recall_at_k(ids, expected, top_k),
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
        "p99_latency_ms": _percentile(latencies, 99),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "build_ms": build_ms,
        "queries": len(queries),
    }


def run_qdrant(
    vectors: np.ndarray,
    queries: np.ndarray,
    expected: list[set[int]],
    top_k: int,
    service: bool = False,
) -> dict[str, Any]:
    if service:
        url = os.environ.get("WAVEMIND_QDRANT_URL")
        if not url:
            raise RuntimeError("Set WAVEMIND_QDRANT_URL to run the Qdrant service profile")
    else:
        url = ":memory:"
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, SearchParams, VectorParams
    except ImportError as exc:
        raise RuntimeError("Install qdrant-client to run the Qdrant ANN curve") from exc
    with _local_no_proxy(url):
        if service:
            client = QdrantClient(
                url=url,
                api_key=os.environ.get("WAVEMIND_QDRANT_API_KEY"),
                timeout=float(os.environ.get("WAVEMIND_QDRANT_TIMEOUT", "120")),
            )
            engine = "Qdrant service"
        else:
            client = QdrantClient(url)
            engine = "Qdrant local"
    collection_name = f"wavemind_ann_curve_{time.time_ns()}"
    try:
        started = time.perf_counter()
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=int(vectors.shape[1]), distance=Distance.COSINE),
            timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
        )
        batch = []
        for index, vector in enumerate(vectors):
            batch.append(PointStruct(id=index + 1, vector=vector.tolist()))
            if len(batch) >= 1000:
                client.upsert(collection_name=collection_name, points=batch)
                batch.clear()
        if batch:
            client.upsert(collection_name=collection_name, points=batch)
        build_ms = (time.perf_counter() - started) * 1000.0
        ids: list[list[int]] = []
        latencies: list[float] = []
        for query in queries:
            started = time.perf_counter()
            search_params = None
            hnsw_ef = os.environ.get("WAVEMIND_QDRANT_HNSW_EF")
            exact = os.environ.get("WAVEMIND_QDRANT_EXACT", "").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if hnsw_ef or exact:
                search_params = SearchParams(
                    hnsw_ef=int(hnsw_ef) if hnsw_ef else None,
                    exact=exact or None,
                )
            hits = list(
                client.query_points(
                    collection_name=collection_name,
                    query=query.tolist(),
                    limit=top_k,
                    with_payload=False,
                    search_params=search_params,
                ).points
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            ids.append([int(hit.id) for hit in hits])
        return {
            "engine": engine,
            "recall_at_k": _recall_at_k(ids, expected, top_k),
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
            "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_latency_ms": _percentile(latencies, 95),
            "p99_latency_ms": _percentile(latencies, 99),
            "max_latency_ms": max(latencies) if latencies else 0.0,
            "build_ms": build_ms,
            "queries": len(queries),
            "search_params": {
                "hnsw_ef": int(hnsw_ef) if hnsw_ef else None,
                "exact": exact,
            },
        }
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
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    engines: Iterable[str],
    noise: float,
) -> dict[str, Any]:
    vectors = make_vectors(count=count, dim=dim, seed=seed + count)
    queries = make_queries(vectors, query_count=min(query_count, count), seed=seed + count, noise=noise)
    expected = exact_neighbors(vectors, queries, top_k=top_k)
    results = []
    for engine in engines:
        key = engine.lower()
        if key in {"numpy", "exact"}:
            results.append(run_wavemind_index("numpy", vectors, queries, expected, top_k))
        elif key in {"quantized", "int8"}:
            results.append(run_wavemind_index("quantized", vectors, queries, expected, top_k))
        elif key in {"annoy", "faiss", "pgvector", "faiss-persisted", "persisted-faiss"}:
            try:
                results.append(run_wavemind_index(key, vectors, queries, expected, top_k))
            except (ImportError, ValueError) as exc:
                results.append(
                    {
                        "engine": f"WaveMind {key}",
                        "skipped": True,
                        "reason": str(exc),
                    }
                )
        elif key in {"qdrant", "qdrant-local"}:
            try:
                results.append(run_qdrant(vectors, queries, expected, top_k, service=False))
            except Exception as exc:
                results.append(
                    {
                        "engine": "Qdrant local",
                        "skipped": True,
                        "reason": str(exc),
                    }
                )
        elif key == "qdrant-service":
            try:
                results.append(run_qdrant(vectors, queries, expected, top_k, service=True))
            except Exception as exc:
                results.append(
                    {
                        "engine": "Qdrant service",
                        "skipped": True,
                        "reason": str(exc),
                    }
                )
        else:
            raise ValueError(f"Unknown engine: {engine}")
    return {
        "vectors": count,
        "vector_dim": dim,
        "queries": len(queries),
        "top_k": top_k,
        "noise": noise,
        "results": results,
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


def run_benchmark(
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    engines: Iterable[str],
    noise: float,
) -> dict[str, Any]:
    return {
        "scenario": {
            "name": "ann_index_curve",
            "description": (
                "ANN/VectorDBBench-style local recall/latency curve. Random normalized "
                "vectors are queried with noisy copies, and recall@k is measured against "
                "exact cosine nearest neighbors."
            ),
            "sizes": list(sizes),
            "vector_dim": dim,
            "queries_per_size": query_count,
            "top_k": top_k,
            "seed": seed,
            "noise": noise,
        },
        "results": [
            run_size(
                count=count,
                dim=dim,
                query_count=query_count,
                top_k=top_k,
                seed=seed,
                engines=engines,
                noise=noise,
            )
            for count in sizes
        ],
    }


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| vectors | engine | recall@{top_k} | avg latency | p95 latency | p99 latency | build |")
    print("|---:|---|---:|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - | - |")
                continue
            print(
                f"| {size_result['vectors']} | {result['engine']} | "
                f"{result['recall_at_k']:.3f} | "
                f"{result['avg_latency_ms']:.2f} ms | "
                f"{result['p95_latency_ms']:.2f} ms | "
                f"{result['p99_latency_ms']:.2f} ms | "
                f"{result['build_ms']:.1f} ms |"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 5000, 10000])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.08)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=[
            "numpy",
            "quantized",
            "annoy",
            "faiss",
            "faiss-persisted",
            "pgvector",
            "qdrant",
            "qdrant-local",
            "qdrant-service",
        ],
        default=["numpy", "quantized", "annoy", "faiss", "qdrant-local"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/ann_index_curve_results.json"))
    args = parser.parse_args()
    payload = run_benchmark(
        sizes=args.sizes,
        dim=args.dim,
        query_count=args.queries,
        top_k=args.top_k,
        seed=args.seed,
        engines=args.engines,
        noise=args.noise,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
