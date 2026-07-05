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
from wavemind.scale import ProductionSLOTarget, evaluate_production_slo


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
            "WAVEMIND_QDRANT_HNSW_EF": os.environ.get("WAVEMIND_QDRANT_HNSW_EF"),
            "WAVEMIND_QDRANT_EXACT": os.environ.get("WAVEMIND_QDRANT_EXACT"),
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
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
    target_qps: float = 100.0,
    replicas: int = 3,
    autoscaling_max_replicas: int = 24,
    capacity_headroom: float = 0.70,
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
    add_slo_evaluation(
        payload,
        target_recall=target_recall,
        target_p99_ms=target_p99_ms,
        target_qps=target_qps,
        replicas=replicas,
        autoscaling_max_replicas=autoscaling_max_replicas,
        capacity_headroom=capacity_headroom,
    )
    return payload


def add_slo_evaluation(
    payload: dict[str, Any],
    *,
    target_recall: float,
    target_p99_ms: float,
    target_qps: float,
    replicas: int,
    autoscaling_max_replicas: int,
    capacity_headroom: float,
) -> dict[str, Any]:
    if target_recall <= 0 or target_recall > 1:
        raise ValueError("target_recall must be in (0, 1]")
    if target_p99_ms <= 0:
        raise ValueError("target_p99_ms must be positive")
    if target_qps <= 0:
        raise ValueError("target_qps must be positive")
    if replicas <= 0:
        raise ValueError("replicas must be positive")
    if autoscaling_max_replicas < replicas:
        raise ValueError("autoscaling_max_replicas must be >= replicas")
    if capacity_headroom <= 0 or capacity_headroom > 1:
        raise ValueError("capacity_headroom must be in (0, 1]")

    target = ProductionSLOTarget(
        target_recall_at_k=target_recall,
        target_p99_ms=target_p99_ms,
        target_qps=target_qps,
        replicas=replicas,
        autoscaling_max_replicas=autoscaling_max_replicas,
        capacity_headroom=capacity_headroom,
    )
    payload["scenario"]["slo_targets"] = target.as_dict()
    for size_result in payload.get("results", []):
        slo_rows = []
        for result in size_result.get("results", []):
            evaluation = evaluate_slo_result(
                result,
                target=target,
            )
            result["slo_status"] = evaluation["status"]
            result["slo_required_replicas"] = evaluation.get("required_replicas")
            result["slo_autoscaled_qps"] = evaluation.get("autoscaled_capacity_qps")
            slo_rows.append(evaluation)
        size_result["slo"] = slo_rows
    return payload


def evaluate_slo_result(
    result: dict[str, Any],
    *,
    target: ProductionSLOTarget,
) -> dict[str, Any]:
    if result.get("skipped"):
        return {
            "engine": result.get("engine", "unknown"),
            "status": "skipped",
            "reason": result.get("reason", "engine skipped"),
        }

    return evaluate_production_slo(
        engine=str(result.get("engine", "unknown")),
        recall_at_k=float(result.get("recall_at_k", 0.0)),
        avg_latency_ms=float(result.get("avg_latency_ms", 0.0)),
        p99_latency_ms=result.get("p99_latency_ms"),
        p95_latency_ms=result.get("p95_latency_ms"),
        target=target,
    ).as_dict()


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| vectors | engine | recall@{top_k} | avg latency | p95 latency | p99 latency | build |")
    print("|---:|---|---:|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(
                    f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - | - |"
                )
                continue
            print(
                f"| {size_result['vectors']} | {result['engine']} | "
                f"{result['recall_at_k']:.3f} | "
                f"{result['avg_latency_ms']:.2f} ms | "
                f"{result['p95_latency_ms']:.2f} ms | "
                f"{result['p99_latency_ms']:.2f} ms | "
                f"{result['build_ms']:.1f} ms |"
            )
    if payload["scenario"].get("slo_targets"):
        print("\n| vectors | engine | SLO | required replicas | autoscaled capacity | blockers |")
        print("|---:|---|---|---:|---:|---|")
        for size_result in payload["results"]:
            for row in size_result.get("slo", []):
                if row["status"] == "skipped":
                    print(
                        f"| {size_result['vectors']} | {row['engine']} | skipped | - | - | {row.get('reason', '')} |"
                    )
                    continue
                blockers = ", ".join(row["blocking_reasons"]) or "-"
                print(
                    f"| {size_result['vectors']} | {row['engine']} | {row['status']} | "
                    f"{row['required_replicas']} | "
                    f"{row['autoscaled_capacity_qps']:.1f} qps | {blockers} |"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100000, 1000000])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.08)
    parser.add_argument("--target-recall", type=float, default=0.95)
    parser.add_argument("--target-p99-ms", type=float, default=100.0)
    parser.add_argument("--target-qps", type=float, default=100.0)
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--autoscaling-max-replicas", type=int, default=24)
    parser.add_argument("--capacity-headroom", type=float, default=0.70)
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
        target_recall=args.target_recall,
        target_p99_ms=args.target_p99_ms,
        target_qps=args.target_qps,
        replicas=args.replicas,
        autoscaling_max_replicas=args.autoscaling_max_replicas,
        capacity_headroom=args.capacity_headroom,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
