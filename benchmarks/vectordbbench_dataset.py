from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.ann_index_curve_benchmark import make_queries, make_vectors


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def exact_neighbor_lists(vectors: np.ndarray, queries: np.ndarray, top_k: int) -> list[list[int]]:
    scores = np.asarray(queries, dtype=np.float32) @ np.asarray(vectors, dtype=np.float32).T
    order = np.argsort(scores, axis=1)[:, ::-1][:, :top_k]
    return [[int(value) + 1 for value in row] for row in order]


def build_rows(
    *,
    train_vectors: np.ndarray,
    test_vectors: np.ndarray,
    neighbors: list[list[int]],
    label_count: int,
) -> dict[str, list[dict[str, Any]]]:
    train_rows = [
        {
            "id": index + 1,
            "vector": np.asarray(vector, dtype=np.float32).tolist(),
        }
        for index, vector in enumerate(train_vectors)
    ]
    test_rows = [
        {
            "id": index + 1,
            "vector": np.asarray(vector, dtype=np.float32).tolist(),
        }
        for index, vector in enumerate(test_vectors)
    ]
    neighbor_rows = [
        {
            "id": index + 1,
            "neighbors": [int(value) for value in row],
        }
        for index, row in enumerate(neighbors)
    ]
    scalar_rows = [
        {
            "id": index + 1,
            "label": f"tenant-{(index % max(1, label_count)) + 1}",
        }
        for index in range(len(train_rows))
    ]
    return {
        "train": train_rows,
        "test": test_rows,
        "neighbors": neighbor_rows,
        "scalar_labels": scalar_rows,
    }


def write_parquet_dataset(rows: dict[str, list[dict[str, Any]]], output_dir: Path) -> dict[str, Any]:
    if not _module_available("pandas"):
        raise RuntimeError('Install pandas to export VectorDBBench parquet files: pip install "pandas"')
    if not _module_available("pyarrow"):
        raise RuntimeError('Install pyarrow to export VectorDBBench parquet files: pip install "pyarrow"')
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for name, payload in rows.items():
        path = output_dir / f"{name}.parquet"
        pd.DataFrame(payload).to_parquet(path, engine="pyarrow", index=False)
        files[name] = path.as_posix()
    return files


def build_manifest(
    *,
    output_dir: Path,
    vectors: int,
    queries: int,
    dim: int,
    top_k: int,
    seed: int,
    noise: float,
    label_count: int,
    files: dict[str, str],
    status: str = "ready",
    reason: str | None = None,
) -> dict[str, Any]:
    manifest = {
        "benchmark": "VectorDBBench custom dataset",
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "WaveMind deterministic synthetic production vectors",
        "metric": "cosine",
        "schema": {
            "train": {"id": "int", "vector": "list[float32]"},
            "test": {"id": "int", "vector": "list[float32]"},
            "neighbors": {"id": "int", "neighbors": "list[int]"},
            "scalar_labels": {"id": "int", "label": "str"},
        },
        "dataset": {
            "vectors": int(vectors),
            "queries": int(queries),
            "dim": int(dim),
            "top_k": int(top_k),
            "seed": int(seed),
            "noise": float(noise),
            "label_count": int(label_count),
        },
        "files": files,
        "output_dir": output_dir.as_posix(),
        "reproduce": {
            "generate": (
                "python benchmarks/vectordbbench_dataset.py "
                f"--vectors {int(vectors)} --queries {int(queries)} --dim {int(dim)} "
                f"--top-k {int(top_k)} --seed {int(seed)} --noise {float(noise)} "
                f"--output-dir {output_dir.as_posix()}"
            ),
            "install": 'pip install "wavemind[bench]"',
            "run_with_vectordbbench": (
                "Use train.parquet, test.parquet, neighbors.parquet, and "
                "scalar_labels.parquet as a VectorDBBench custom dataset."
            ),
        },
    }
    if reason:
        manifest["reason"] = reason
    return manifest


def generate_dataset(
    *,
    output_dir: Path,
    vectors: int = 10_000,
    queries: int = 100,
    dim: int = 128,
    top_k: int = 10,
    seed: int = 42,
    noise: float = 0.01,
    label_count: int = 16,
    manifest_path: Path | None = None,
    require_parquet: bool = True,
) -> dict[str, Any]:
    if vectors <= 0:
        raise ValueError("vectors must be positive")
    if queries <= 0:
        raise ValueError("queries must be positive")
    if queries > vectors:
        raise ValueError("queries must be <= vectors")
    if dim <= 0:
        raise ValueError("dim must be positive")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if top_k > vectors:
        raise ValueError("top_k must be <= vectors")

    train_vectors = make_vectors(vectors, dim, seed)
    test_vectors = make_queries(train_vectors, queries, seed, noise)
    neighbors = exact_neighbor_lists(train_vectors, test_vectors, top_k)
    rows = build_rows(
        train_vectors=train_vectors,
        test_vectors=test_vectors,
        neighbors=neighbors,
        label_count=label_count,
    )

    try:
        files = write_parquet_dataset(rows, output_dir)
        manifest = build_manifest(
            output_dir=output_dir,
            vectors=vectors,
            queries=queries,
            dim=dim,
            top_k=top_k,
            seed=seed,
            noise=noise,
            label_count=label_count,
            files=files,
        )
    except RuntimeError as exc:
        if require_parquet:
            raise
        manifest = build_manifest(
            output_dir=output_dir,
            vectors=vectors,
            queries=queries,
            dim=dim,
            top_k=top_k,
            seed=seed,
            noise=noise,
            label_count=label_count,
            files={},
            status="skipped",
            reason=str(exc),
        )

    target_manifest = manifest_path or output_dir / "manifest.json"
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a VectorDBBench custom dataset for WaveMind scale testing.")
    parser.add_argument("--vectors", type=int, default=10_000)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.01)
    parser.add_argument("--label-count", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/data/vectordbbench-wavemind"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/vectordbbench_dataset_manifest.json"))
    parser.add_argument(
        "--allow-missing-parquet",
        action="store_true",
        help="Write a skipped manifest instead of failing when pandas/pyarrow is not installed.",
    )
    args = parser.parse_args(argv)

    manifest = generate_dataset(
        output_dir=args.output_dir,
        vectors=args.vectors,
        queries=args.queries,
        dim=args.dim,
        top_k=args.top_k,
        seed=args.seed,
        noise=args.noise,
        label_count=args.label_count,
        manifest_path=args.manifest,
        require_parquet=not args.allow_missing_parquet,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if manifest["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
