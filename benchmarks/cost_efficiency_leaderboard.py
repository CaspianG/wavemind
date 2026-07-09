from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]

MEASURED_ARTIFACTS = (
    "benchmarks/production_load_results.json",
    "benchmarks/production_load_qdrant_100k_tuned_results.json",
    "benchmarks/production_load_qdrant_1m_results.json",
    "benchmarks/production_load_qdrant_1m_tuned_results.json",
    "benchmarks/production_load_qdrant_1m_ef_sweep_results.json",
    "benchmarks/production_load_faiss_1m_results.json",
    "benchmarks/production_streaming_load_smoke_results.json",
    "benchmarks/production_streaming_load_ivfpq_100k_results.json",
    "benchmarks/production_streaming_load_ivfpq_1m_results.json",
    "benchmarks/production_streaming_load_ivfpq_10m_results.json",
    "benchmarks/production_streaming_load_qdrant_smoke_results.json",
    "benchmarks/production_streaming_load_qdrant_1m_results.json",
    "benchmarks/production_streaming_load_qdrant_1m_tuned_results.json",
    "benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json",
    "benchmarks/production_streaming_load_pgvector_smoke_results.json",
)


def build_cost_efficiency_leaderboard(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    load_errors: list[str] = []
    measured_rows = _measured_rows(root, load_errors)
    planned_rows = _planned_rows(root, load_errors)

    measured_rankings = _rank_by_target_class(measured_rows)
    planned_rankings = _rank_by_target_class(planned_rows)
    measured_frontier = _frontier(measured_rows)
    planned_frontier = _frontier(planned_rows)

    return {
        "schema": "wavemind.cost_efficiency_leaderboard.v1",
        "generated_at": _generated_at(root),
        "source_ref": _source_ref(root),
        "claim_boundary": (
            "Measured rows come from checked-in load artifacts. Planned rows are "
            "capacity and cost contracts only; they do not unlock production "
            "latency or recall claims until the matching benchmark result exists."
        ),
        "summary": {
            "measured_row_count": len(measured_rows),
            "planned_row_count": len(planned_rows),
            "measured_slo_pass_count": sum(
                1 for row in measured_rows if row["slo_status"] == "pass"
            ),
            "measured_valid_cost_count": sum(
                1 for row in measured_rows if row["cost_status"] == "valid_slo"
            ),
            "planned_valid_cost_count": sum(
                1 for row in planned_rows if row["cost_status"] == "valid_slo"
            ),
            "measured_frontier_profiles": [row["profile"] for row in measured_frontier],
            "planned_frontier_profiles": [row["profile"] for row in planned_frontier],
            "best_measured_by_target_class": {
                target_class: rows[0]["profile"]
                for target_class, rows in measured_rankings.items()
                if rows
            },
            "best_planned_by_target_class": {
                target_class: rows[0]["profile"]
                for target_class, rows in planned_rankings.items()
                if rows
            },
            "target_classes": sorted(set(measured_rankings) | set(planned_rankings)),
        },
        "measured_rankings": measured_rankings,
        "planned_rankings": planned_rankings,
        "measured_rows": measured_rows,
        "planned_rows": planned_rows,
        "load_errors": load_errors,
    }


def render_cost_efficiency_markdown(payload: dict[str, Any]) -> str:
    measured_rows = _table_rows(payload.get("measured_rows", []), limit=12)
    planned_rows = _table_rows(payload.get("planned_rows", []), limit=8)
    summary = payload.get("summary", {})
    return "\n".join(
        [
            "# WaveMind Cost Efficiency Leaderboard",
            "",
            f"Generated: `{payload.get('generated_at', 'unknown')}`.",
            "",
            str(payload.get("claim_boundary", "")),
            "",
            "## Summary",
            "",
            f"- Measured rows: `{summary.get('measured_row_count', 0)}`.",
            f"- Measured SLO pass rows: `{summary.get('measured_slo_pass_count', 0)}`.",
            f"- Measured valid cost rows: `{summary.get('measured_valid_cost_count', 0)}`.",
            f"- Planned cost rows: `{summary.get('planned_row_count', 0)}`.",
            f"- Measured frontier: `{', '.join(summary.get('measured_frontier_profiles', [])) or '-'}`.",
            f"- Planned frontier: `{', '.join(summary.get('planned_frontier_profiles', [])) or '-'}`.",
            "",
            "## Measured Cost Frontier",
            "",
            "| rank | profile | target class | engine | memories | recall | p99 ms | SLO | cost / 1M queries | monthly cost | source |",
            "|---:|---|---|---|---:|---:|---:|---|---:|---:|---|",
            *measured_rows,
            "",
            "## Planned Cost Frontier",
            "",
            "| rank | profile | target class | engine | memories | recall | p99 ms | SLO | cost / 1M queries | monthly cost | source |",
            "|---:|---|---|---|---:|---:|---:|---|---:|---:|---|",
            *planned_rows,
            "",
            "## Reading Rules",
            "",
            "- `measured` rows are allowed to support benchmark claims if their source artifact is current.",
            "- planned rows are capacity/cost contracts only.",
            "- `scale_required` means recall and p99 can be inside target, but more replicas are needed for the requested QPS.",
            "- Cost estimates use checked-in benchmark assumptions for required replicas, hourly replica cost, target QPS, vector size, and payload size.",
            "",
        ]
    )


def _measured_rows(root: Path, load_errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in MEASURED_ARTIFACTS:
        payload = _load_json(root / relative, load_errors, required=False)
        if not payload:
            continue
        for group, result in _iter_result_rows(payload):
            row = _row_from_result(relative, group, result)
            if row is not None:
                rows.append(row)
    rows.sort(key=_ranking_key)
    return _apply_ranks(rows)


def _planned_rows(root: Path, load_errors: list[str]) -> list[dict[str, Any]]:
    payload = _load_json(root / "benchmarks" / "production_scale_run_plan.json", load_errors)
    rows = [_row_from_plan(plan) for plan in payload.get("profiles", []) if isinstance(plan, dict)]
    rows = [row for row in rows if row is not None]
    rows.sort(key=_ranking_key)
    return _apply_ranks(rows)


def _iter_result_rows(payload: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for group in payload.get("results", []):
        if not isinstance(group, dict):
            continue
        nested = group.get("results")
        if isinstance(nested, list):
            for result in nested:
                if isinstance(result, dict):
                    yield group, result
        else:
            yield {}, group


def _row_from_result(
    source_file: str,
    group: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    if result.get("skipped"):
        return None
    if result.get("compute_cost_per_1m_queries_usd") is None:
        return None
    memory_count = _int_value(result.get("vectors") or group.get("vectors"))
    vector_dim = _int_value(result.get("vector_dim") or group.get("vector_dim"))
    profile = _profile_name(
        engine=str(result.get("engine") or "unknown"),
        memory_count=memory_count,
        source_file=source_file,
    )
    monthly_total = _float_value(result.get("monthly_total_cost_at_target_qps_usd"))
    return _normalize_row(
        {
            "profile": profile,
            "evidence_level": "measured",
            "source_file": source_file,
            "engine": str(result.get("engine") or "unknown"),
            "memory_count": memory_count,
            "vector_dim": vector_dim,
            "target_class": _target_class(memory_count),
            "recall_at_k": _float_value(
                result.get("recall_at_k") or result.get("target_recall_at_k")
            ),
            "p99_latency_ms": _float_value(result.get("p99_latency_ms")),
            "avg_latency_ms": _float_value(result.get("avg_latency_ms")),
            "target_qps": _float_value(result.get("target_qps")),
            "slo_status": str(result.get("slo_status") or "unknown"),
            "cost_status": str(result.get("cost_status") or "unknown"),
            "compute_cost_per_1m_queries_usd": _float_value(
                result.get("compute_cost_per_1m_queries_usd")
            ),
            "monthly_total_cost_at_target_qps_usd": monthly_total,
            "monthly_total_cost_per_1m_memories_usd": _cost_per_1m_memories(
                monthly_total,
                memory_count,
            ),
            "estimated_storage_gb": _float_value(result.get("estimated_storage_gb")),
            "claim_status": _measured_claim_status(result),
        }
    )


def _row_from_plan(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    cost = plan.get("cost_envelope")
    slo = plan.get("slo_capacity_envelope")
    if not isinstance(cost, Mapping) or not isinstance(slo, Mapping):
        return None
    return _normalize_row(
        {
            "profile": str(plan.get("profile") or plan.get("engine") or "unknown"),
            "evidence_level": "planned",
            "source_file": "benchmarks/production_scale_run_plan.json",
            "engine": str(plan.get("engine") or "unknown"),
            "memory_count": _int_value(plan.get("target_memories")),
            "vector_dim": _int_value(plan.get("vector_dim")),
            "target_class": _target_class(_int_value(plan.get("target_memories"))),
            "recall_at_k": _float_value(slo.get("recall_at_k")),
            "p99_latency_ms": _float_value(slo.get("p99_latency_ms")),
            "avg_latency_ms": _float_value(slo.get("avg_latency_ms")),
            "target_qps": _float_value(plan.get("target_qps") or slo.get("target_qps")),
            "slo_status": str(slo.get("status") or "unknown"),
            "cost_status": str(cost.get("cost_status") or "unknown"),
            "compute_cost_per_1m_queries_usd": _float_value(
                cost.get("compute_cost_per_1m_queries_usd")
            ),
            "monthly_total_cost_at_target_qps_usd": _float_value(
                cost.get("monthly_total_cost_at_target_qps_usd")
            ),
            "monthly_total_cost_per_1m_memories_usd": _float_value(
                cost.get("monthly_total_cost_per_1m_memories_usd")
            ),
            "estimated_storage_gb": _float_value(plan.get("estimated_application_storage_gb")),
            "claim_status": "plan_only",
            "output_artifact": plan.get("output_artifact"),
            "blockers": plan.get("blockers", []),
        }
    )


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    row["slo_pass"] = row["slo_status"] == "pass"
    row["valid_cost"] = row["cost_status"] == "valid_slo"
    row["frontier_score"] = _frontier_score(row)
    return row


def _measured_claim_status(result: Mapping[str, Any]) -> str:
    slo_status = str(result.get("slo_status") or "unknown")
    cost_status = str(result.get("cost_status") or "unknown")
    if cost_status != "valid_slo":
        return "cost_action_required"
    if slo_status == "pass":
        return "measured_slo_pass"
    if slo_status == "scale_required":
        return "measured_scale_required"
    if slo_status == "fail":
        return "measured_slo_fail"
    return "measured_incomplete_slo"


def _rank_by_target_class(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["target_class"]), []).append(row)
    for target_class, values in grouped.items():
        values.sort(key=_ranking_key)
        grouped[target_class] = _apply_ranks(values)
    return dict(sorted(grouped.items()))


def _apply_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        with_rank = dict(row)
        with_rank["rank"] = index
        ranked.append(with_rank)
    return ranked


def _frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("valid_cost")]
    frontier = [
        row
        for row in candidates
        if not any(_dominates(other, row) for other in candidates if other is not row)
    ]
    frontier.sort(key=_ranking_key)
    return _apply_ranks(frontier)


def _dominates(candidate: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    candidate_metrics = _comparable_metrics(candidate)
    other_metrics = _comparable_metrics(other)
    better_or_equal = (
        candidate_metrics["recall_at_k"] >= other_metrics["recall_at_k"]
        and candidate_metrics["p99_latency_ms"] <= other_metrics["p99_latency_ms"]
        and candidate_metrics["compute_cost_per_1m_queries_usd"]
        <= other_metrics["compute_cost_per_1m_queries_usd"]
        and candidate_metrics["monthly_total_cost_per_1m_memories_usd"]
        <= other_metrics["monthly_total_cost_per_1m_memories_usd"]
        and candidate_metrics["memory_count"] >= other_metrics["memory_count"]
    )
    strictly_better = any(
        (
            candidate_metrics["recall_at_k"] > other_metrics["recall_at_k"],
            candidate_metrics["p99_latency_ms"] < other_metrics["p99_latency_ms"],
            candidate_metrics["compute_cost_per_1m_queries_usd"]
            < other_metrics["compute_cost_per_1m_queries_usd"],
            candidate_metrics["monthly_total_cost_per_1m_memories_usd"]
            < other_metrics["monthly_total_cost_per_1m_memories_usd"],
            candidate_metrics["memory_count"] > other_metrics["memory_count"],
        )
    )
    return better_or_equal and strictly_better


def _comparable_metrics(row: Mapping[str, Any]) -> dict[str, float]:
    return {
        "memory_count": float(row.get("memory_count") or 0.0),
        "recall_at_k": float(row.get("recall_at_k") or 0.0),
        "p99_latency_ms": float(row.get("p99_latency_ms") or 1_000_000_000.0),
        "compute_cost_per_1m_queries_usd": float(
            row.get("compute_cost_per_1m_queries_usd") or 1_000_000_000.0
        ),
        "monthly_total_cost_per_1m_memories_usd": float(
            row.get("monthly_total_cost_per_1m_memories_usd") or 1_000_000_000.0
        ),
    }


def _ranking_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    slo_priority = {"pass": 0, "scale_required": 1, "fail": 2}
    return (
        0 if row.get("valid_cost") else 1,
        slo_priority.get(str(row.get("slo_status")), 9),
        -float(row.get("recall_at_k") or 0.0),
        float(row.get("p99_latency_ms") or 1_000_000_000.0),
        float(row.get("compute_cost_per_1m_queries_usd") or 1_000_000_000.0),
        -int(row.get("memory_count") or 0),
        str(row.get("profile") or ""),
    )


def _frontier_score(row: Mapping[str, Any]) -> float:
    recall = float(row.get("recall_at_k") or 0.0)
    p99 = max(float(row.get("p99_latency_ms") or 1_000_000.0), 0.001)
    cost = max(float(row.get("compute_cost_per_1m_queries_usd") or 1_000_000.0), 0.001)
    memories = max(float(row.get("memory_count") or 0.0), 1.0)
    return (recall * memories) / (p99 * cost)


def _table_rows(rows: Any, *, limit: int) -> list[str]:
    if not isinstance(rows, list):
        return []
    ranked = sorted((row for row in rows if isinstance(row, dict)), key=_ranking_key)[:limit]
    return [
        (
            f"| {int(row.get('rank') or index)} | {row.get('profile', '-')} | "
            f"{row.get('target_class', '-')} | {row.get('engine', '-')} | "
            f"{int(row.get('memory_count') or 0):,} | {_fmt(row.get('recall_at_k'))} | "
            f"{_fmt(row.get('p99_latency_ms'))} | {row.get('slo_status', '-')} | "
            f"${_fmt(row.get('compute_cost_per_1m_queries_usd'))} | "
            f"${_fmt(row.get('monthly_total_cost_at_target_qps_usd'))} | "
            f"`{row.get('source_file', '-')}` |"
        )
        for index, row in enumerate(ranked, start=1)
    ]


def _profile_name(*, engine: str, memory_count: int, source_file: str) -> str:
    stem = Path(source_file).stem
    normalized_engine = engine.lower().replace(" ", "-")
    return f"{_target_class(memory_count)}-{normalized_engine}-{stem}"


def _target_class(memory_count: int) -> str:
    if memory_count >= 100_000_000:
        return "100m_plus"
    if memory_count >= 50_000_000:
        return "50m"
    if memory_count >= 10_000_000:
        return "10m"
    if memory_count >= 1_000_000:
        return "1m"
    if memory_count >= 100_000:
        return "100k"
    return "sub_100k"


def _cost_per_1m_memories(monthly_total: float | None, memory_count: int) -> float | None:
    if monthly_total is None or memory_count <= 0:
        return None
    return monthly_total / max(memory_count / 1_000_000.0, 0.001)


def _load_json(path: Path, errors: list[str], *, required: bool = True) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            errors.append(f"missing {path.as_posix()}")
        return {}
    except Exception as exc:
        errors.append(f"cannot read {path.as_posix()}: {exc}")
        return {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number:,.2f}".rstrip("0").rstrip(".")
    if abs(number) >= 10:
        return f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _generated_at(root: Path) -> str:
    value = os.environ.get("WAVEMIND_BENCHMARK_GENERATED_AT")
    if value:
        return value
    matrix = _load_json(root / "benchmarks" / "benchmark_matrix_results.json", [], required=False)
    matrix_time = matrix.get("generated_at")
    if isinstance(matrix_time, str) and matrix_time:
        return matrix_time
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str:
    value = os.environ.get("GITHUB_SHA") or os.environ.get("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/cost_efficiency_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/COST_EFFICIENCY.md"),
    )
    args = parser.parse_args()

    payload = build_cost_efficiency_leaderboard()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_cost_efficiency_markdown(payload),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
