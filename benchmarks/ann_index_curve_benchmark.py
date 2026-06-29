from __future__ import annotations

import argparse
import json
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


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


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
        "p95_latency_ms": _p95(latencies),
        "build_ms": build_ms,
        "queries": len(queries),
    }


def run_qdrant(
    vectors: np.ndarray,
    queries: np.ndarray,
    expected: list[set[int]],
    top_k: int,
) -> dict[str, Any]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError("Install qdrant-client to run the Qdrant ANN curve") from exc
    client = QdrantClient(":memory:")
    collection_name = f"wavemind_ann_curve_{time.time_ns()}"
    started = time.perf_counter()
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=int(vectors.shape[1]), distance=Distance.COSINE),
    )
    points = [
        PointStruct(id=index + 1, vector=vector.tolist())
        for index, vector in enumerate(vectors)
    ]
    for offset in range(0, len(points), 1000):
        client.upsert(collection_name=collection_name, points=points[offset : offset + 1000])
    build_ms = (time.perf_counter() - started) * 1000.0
    ids: list[list[int]] = []
    latencies: list[float] = []
    for query in queries:
        started = time.perf_counter()
        hits = list(
            client.query_points(
                collection_name=collection_name,
                query=query.tolist(),
                limit=top_k,
                with_payload=False,
            ).points
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        ids.append([int(hit.id) for hit in hits])
    return {
        "engine": "Qdrant local",
        "recall_at_k": _recall_at_k(ids, expected, top_k),
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p95_latency_ms": _p95(latencies),
        "build_ms": build_ms,
        "queries": len(queries),
    }


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
        elif key in {"annoy", "faiss", "pgvector"}:
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
        elif key == "qdrant":
            try:
                results.append(run_qdrant(vectors, queries, expected, top_k))
            except RuntimeError as exc:
                results.append(
                    {
                        "engine": "Qdrant local",
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
    print(f"| vectors | engine | recall@{top_k} | avg latency | p95 latency | build |")
    print("|---:|---|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - |")
                continue
            print(
                f"| {size_result['vectors']} | {result['engine']} | "
                f"{result['recall_at_k']:.3f} | "
                f"{result['avg_latency_ms']:.2f} ms | "
                f"{result['p95_latency_ms']:.2f} ms | "
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
        choices=["numpy", "quantized", "annoy", "faiss", "pgvector", "qdrant"],
        default=["numpy", "quantized", "annoy", "faiss", "qdrant"],
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
