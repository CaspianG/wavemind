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
from wavemind.scale import (
    ProductionCostTarget,
    ProductionSLOResult,
    ProductionSLOTarget,
    estimate_production_cost,
    evaluate_production_slo,
)


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
            "WAVEMIND_QDRANT_WARMUP_QUERIES": os.environ.get("WAVEMIND_QDRANT_WARMUP_QUERIES"),
            "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": os.environ.get("WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS"),
            "WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS": os.environ.get("WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS"),
            "WAVEMIND_QDRANT_INDEX_READY_POLL_SECONDS": os.environ.get("WAVEMIND_QDRANT_INDEX_READY_POLL_SECONDS"),
            "WAVEMIND_QDRANT_REQUIRE_FULL_INDEX": os.environ.get("WAVEMIND_QDRANT_REQUIRE_FULL_INDEX"),
            "WAVEMIND_QDRANT_HNSW_M": os.environ.get("WAVEMIND_QDRANT_HNSW_M"),
            "WAVEMIND_QDRANT_HNSW_EF_CONSTRUCT": os.environ.get("WAVEMIND_QDRANT_HNSW_EF_CONSTRUCT"),
            "WAVEMIND_QDRANT_HNSW_FULL_SCAN_THRESHOLD": os.environ.get("WAVEMIND_QDRANT_HNSW_FULL_SCAN_THRESHOLD"),
            "WAVEMIND_QDRANT_OPTIMIZER_DEFAULT_SEGMENT_NUMBER": os.environ.get("WAVEMIND_QDRANT_OPTIMIZER_DEFAULT_SEGMENT_NUMBER"),
            "WAVEMIND_QDRANT_OPTIMIZER_INDEXING_THRESHOLD": os.environ.get("WAVEMIND_QDRANT_OPTIMIZER_INDEXING_THRESHOLD"),
            "WAVEMIND_QDRANT_VECTOR_ON_DISK": os.environ.get("WAVEMIND_QDRANT_VECTOR_ON_DISK"),
            "WAVEMIND_QDRANT_ON_DISK_PAYLOAD": os.environ.get("WAVEMIND_QDRANT_ON_DISK_PAYLOAD"),
            "WAVEMIND_QDRANT_SHARD_NUMBER": os.environ.get("WAVEMIND_QDRANT_SHARD_NUMBER"),
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
    replica_hourly_cost_usd: float = 0.25,
    storage_gb_monthly_cost_usd: float = 0.10,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
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
            "FAISS, Qdrant service, pgvector HNSW, pgvector exact safety mode, "
            "or pgvector iterative-scan mode for candidate generation. "
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
        replica_hourly_cost_usd=replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=storage_gb_monthly_cost_usd,
        memory_payload_kb=memory_payload_kb,
        vector_dtype_bytes=vector_dtype_bytes,
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
    replica_hourly_cost_usd: float = 0.25,
    storage_gb_monthly_cost_usd: float = 0.10,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
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
    if replica_hourly_cost_usd < 0:
        raise ValueError("replica_hourly_cost_usd cannot be negative")
    if storage_gb_monthly_cost_usd < 0:
        raise ValueError("storage_gb_monthly_cost_usd cannot be negative")

    target = ProductionSLOTarget(
        target_recall_at_k=target_recall,
        target_p99_ms=target_p99_ms,
        target_qps=target_qps,
        replicas=replicas,
        autoscaling_max_replicas=autoscaling_max_replicas,
        capacity_headroom=capacity_headroom,
    )
    cost_target = ProductionCostTarget(
        replica_hourly_cost_usd=replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=storage_gb_monthly_cost_usd,
        memory_payload_kb=memory_payload_kb,
        vector_dtype_bytes=vector_dtype_bytes,
    )
    payload["scenario"]["slo_targets"] = target.as_dict()
    payload["scenario"]["cost_model"] = cost_target.as_dict()
    for size_result in payload.get("results", []):
        slo_rows = []
        cost_rows = []
        for result in size_result.get("results", []):
            evaluation = evaluate_slo_result(
                result,
                target=target,
            )
            cost = evaluate_cost_result(
                evaluation,
                memory_count=int(size_result.get("vectors", 0)),
                vector_dim=int(
                    payload["scenario"].get("dim")
                    or payload["scenario"].get("vector_dim")
                    or size_result.get("vector_dim")
                    or 1
                ),
                target=cost_target,
            )
            result["slo_status"] = evaluation["status"]
            result["slo_required_replicas"] = evaluation.get("required_replicas")
            result["slo_autoscaled_qps"] = evaluation.get("autoscaled_capacity_qps")
            result["cost_status"] = cost["cost_status"]
            result["compute_cost_per_1m_queries_usd"] = cost.get("compute_cost_per_1m_queries_usd")
            result["monthly_storage_cost_usd"] = cost.get("monthly_storage_cost_usd")
            result["monthly_total_cost_at_target_qps_usd"] = cost.get("monthly_total_cost_at_target_qps_usd")
            result["estimated_storage_gb"] = cost.get("total_storage_gb")
            evaluation.update(
                {
                    "cost_status": cost["cost_status"],
                    "compute_cost_per_1m_queries_usd": cost.get("compute_cost_per_1m_queries_usd"),
                    "monthly_storage_cost_usd": cost.get("monthly_storage_cost_usd"),
                    "monthly_total_cost_at_target_qps_usd": cost.get("monthly_total_cost_at_target_qps_usd"),
                    "estimated_storage_gb": cost.get("total_storage_gb"),
                }
            )
            slo_rows.append(evaluation)
            cost_rows.append(cost)
        size_result["slo"] = slo_rows
        size_result["cost"] = cost_rows
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


def evaluate_cost_result(
    evaluation: dict[str, Any],
    *,
    memory_count: int,
    vector_dim: int,
    target: ProductionCostTarget,
) -> dict[str, Any]:
    if evaluation.get("status") == "skipped":
        return {
            "engine": evaluation.get("engine", "unknown"),
            "cost_status": "skipped",
            "reason": evaluation.get("reason", "engine skipped"),
        }
    slo = ProductionSLOResult(
        engine=str(evaluation["engine"]),
        status=str(evaluation["status"]),
        target_recall_at_k=float(evaluation["target_recall_at_k"]),
        target_p99_ms=float(evaluation["target_p99_ms"]),
        target_qps=float(evaluation["target_qps"]),
        recall_at_k=float(evaluation["recall_at_k"]),
        p99_latency_ms=float(evaluation["p99_latency_ms"]),
        avg_latency_ms=float(evaluation["avg_latency_ms"]),
        per_replica_qps_at_headroom=float(evaluation["per_replica_qps_at_headroom"]),
        current_replicas=int(evaluation["current_replicas"]),
        current_capacity_qps=float(evaluation["current_capacity_qps"]),
        required_replicas=int(evaluation["required_replicas"]),
        autoscaling_max_replicas=int(evaluation["autoscaling_max_replicas"]),
        autoscaled_capacity_qps=float(evaluation["autoscaled_capacity_qps"]),
        blocking_reasons=tuple(evaluation["blocking_reasons"]),
    )
    return estimate_production_cost(
        slo=slo,
        memory_count=memory_count,
        vector_dim=vector_dim,
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
    if payload["scenario"].get("cost_model"):
        print("\n| vectors | engine | cost status | compute / 1M queries | monthly target cost | storage |")
        print("|---:|---|---|---:|---:|---:|")
        for size_result in payload["results"]:
            for row in size_result.get("cost", []):
                if row["cost_status"] == "skipped":
                    print(
                        f"| {size_result['vectors']} | {row['engine']} | skipped | - | - | - |"
                    )
                    continue
                print(
                    f"| {size_result['vectors']} | {row['engine']} | {row['cost_status']} | "
                    f"${row['compute_cost_per_1m_queries_usd']:.4f} | "
                    f"${row['monthly_total_cost_at_target_qps_usd']:.2f} | "
                    f"{row['total_storage_gb']:.2f} GB |"
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
    parser.add_argument("--replica-hourly-cost-usd", type=float, default=0.25)
    parser.add_argument("--storage-gb-monthly-cost-usd", type=float, default=0.10)
    parser.add_argument("--memory-payload-kb", type=float, default=2.0)
    parser.add_argument("--vector-dtype-bytes", type=int, default=4)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=[
            "faiss-persisted",
            "qdrant-service",
            "pgvector",
            "pgvector-exact",
            "pgvector-iterative",
            "numpy",
            "quantized",
        ],
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
