from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.ann_index_curve_benchmark import run_benchmark as run_ann_curve


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _docker_status() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)}
    if completed.returncode != 0:
        reason = (completed.stderr or completed.stdout).strip()
        return {"available": False, "reason": reason}
    return {"available": True, "server_version": completed.stdout.strip()}


def preflight(output_path: Path | None = None) -> dict[str, Any]:
    target = (output_path or PROJECT_ROOT).resolve()
    disk_root = target.anchor or str(target)
    usage = shutil.disk_usage(disk_root)
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "docker": _docker_status(),
        "modules": {
            "faiss": _module_available("faiss"),
            "qdrant_client": _module_available("qdrant_client"),
            "psycopg": _module_available("psycopg"),
            "numpy": _module_available("numpy"),
        },
        "environment": {
            "WAVEMIND_FAISS_PATH": bool(os.environ.get("WAVEMIND_FAISS_PATH")),
            "WAVEMIND_QDRANT_URL": bool(os.environ.get("WAVEMIND_QDRANT_URL")),
            "WAVEMIND_PGVECTOR_DSN": bool(os.environ.get("WAVEMIND_PGVECTOR_DSN")),
            "WAVEMIND_PGVECTOR_CREATE_HNSW": os.environ.get("WAVEMIND_PGVECTOR_CREATE_HNSW"),
            "WAVEMIND_PGVECTOR_EF_SEARCH": os.environ.get("WAVEMIND_PGVECTOR_EF_SEARCH"),
        },
        "disk": {
            "root": disk_root,
            "free_gb": round(usage.free / (1024**3), 2),
            "total_gb": round(usage.total / (1024**3), 2),
        },
    }


def run_production_load(
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    engines: Iterable[str],
    noise: float,
    output_path: Path | None = None,
) -> dict[str, Any]:
    size_list = [int(size) for size in sizes]
    payload = run_ann_curve(
        sizes=size_list,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        engines=engines,
        noise=noise,
    )
    payload["scenario"] = {
        **payload["scenario"],
        "name": "production_load_profile",
        "description": (
            "Service-backed large-N candidate-index load profile. The intended "
            "production path is SQLite/Postgres as source of truth plus persisted "
            "FAISS, Qdrant service, or pgvector HNSW for candidate generation. "
            "Skipped engines are reported explicitly when optional services or "
            "dependencies are not configured."
        ),
        "load_sizes": size_list,
        "default_target_sizes": [100000, 1000000],
    }
    payload["preflight"] = preflight(output_path=output_path)
    return payload


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| vectors | engine | recall@{top_k} | avg latency | p95 latency | build |")
    print("|---:|---|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(
                    f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - |"
                )
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
    parser.add_argument("--sizes", nargs="+", type=int, default=[100000, 1000000])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.08)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["faiss-persisted", "qdrant-service", "pgvector", "numpy", "quantized"],
        default=["faiss-persisted", "qdrant-service", "pgvector"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/production_load_results.json"))
    args = parser.parse_args()

    payload = run_production_load(
        sizes=args.sizes,
        dim=args.dim,
        query_count=args.queries,
        top_k=args.top_k,
        seed=args.seed,
        engines=args.engines,
        noise=args.noise,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
