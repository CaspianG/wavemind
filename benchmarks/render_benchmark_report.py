from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root / "benchmarks" / "benchmark_matrix_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value < 10:
            return f"{value:.2f}"
        return f"{value:.1f}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)


METRIC_LABELS = {
    "precision_at_1": "precision@1",
    "precision_at_3": "precision@3",
    "precision@1": "precision@1",
    "precision@3": "precision@3",
    "ndcg_at_k": "nDCG@k",
    "recall_at_k": "Recall@k",
    "target_recall_at_k": "target recall@k",
    "target_recall_at_1": "target recall@1",
    "evidence_recall_at_k": "evidence recall@k",
    "mrr_at_k": "MRR@k",
    "stale_suppression": "stale suppression",
    "suppression_rate": "stale suppression",
    "concept_formation": "concept formation",
    "concept_consolidation": "concept consolidation",
    "decay_ratio": "decay ratio",
    "context_budget_saved": "context saved",
    "avg_latency_ms": "avg latency",
    "p95_latency_ms": "p95 latency",
    "p99_latency_ms": "p99 latency",
    "slo_status": "SLO",
    "slo_required_replicas": "required replicas",
    "slo_autoscaled_qps": "autoscaled QPS",
    "cost_status": "cost status",
    "compute_cost_per_1m_queries_usd": "cost / 1M queries",
    "monthly_total_cost_at_target_qps_usd": "monthly target cost",
    "estimated_storage_gb": "storage",
    "readiness_score": "readiness score",
    "overall_status": "overall status",
    "pass_count": "passed criteria",
    "action_required_count": "action required",
    "fail_count": "failed criteria",
    "total_criteria": "total criteria",
    "prewarm_warmed": "prewarm warmed",
    "prewarm_hit": "prewarm hit",
    "repair_repaired_total": "repair repaired",
    "repair_ok": "repair ok",
    "recalled_after_repair": "recall after repair",
    "tombstone_replication_factor": "tombstone RF",
    "tombstone_suppressed_before_repair": "tombstone suppress before repair",
    "tombstone_repair_deleted_records": "tombstone deleted",
    "tombstone_suppressed_after_repair": "tombstone suppress after repair",
    "anti_entropy_worker_ok": "anti-entropy worker ok",
    "anti_entropy_worker_repaired_total": "anti-entropy repaired",
    "anti_entropy_worker_tombstone_deleted": "anti-entropy tombstone deleted",
    "architecture_advice_status": "architecture advice",
    "architecture_advice_recommendation_ids": "architecture ids",
    "architecture_next_commands": "architecture commands",
    "memory_os_architecture_advice_status": "Memory OS architecture advice",
    "memory_os_architecture_recommendations": "Memory OS architecture ids",
}


def metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key.replace("_", " "))


def metric_line(current: dict[str, Any] | None) -> str:
    if not current:
        return "No checked-in result yet."
    parts: list[str] = []
    for engine, metrics in current.items():
        if metrics is None:
            parts.append(f"{engine}: no checked-in result")
        elif isinstance(metrics, list):
            rows = len(metrics)
            last = metrics[-1] if metrics else {}
            parts.append(
                f"{engine}: {rows} points, last p@1 {fmt(last.get('precision_at_1'))}, "
                f"avg {fmt(last.get('avg_latency_ms'))} ms"
            )
        elif metrics.get("skipped"):
            reason = str(metrics.get("reason") or "not configured")
            parts.append(f"{engine}: skipped - {reason}")
        else:
            metric_bits = [
                f"{metric_label(key)} {fmt(value)}"
                for key, value in metrics.items()
            ]
            parts.append(f"{engine}: " + ", ".join(metric_bits))
    return "<br>".join(parts)


def table(entries: list[dict[str, Any]], include_results: bool) -> str:
    if include_results:
        header = "| benchmark | category | status | current result | next step |\n|---|---|---|---|---|\n"
    else:
        header = "| benchmark | category | status | competitors | target |\n|---|---|---|---|---|\n"
    rows: list[str] = []
    for entry in entries:
        name = entry["name"]
        if entry.get("source_url"):
            name = f"[{name}]({entry['source_url']})"
        if include_results:
            rows.append(
                f"| {name} | {entry['category']} | {entry['status']} | "
                f"{metric_line(entry.get('current'))} | {entry.get('next_step', '-')} |"
            )
        else:
            competitors = ", ".join(entry.get("competitors", [])) or "-"
            rows.append(
                f"| {name} | {entry['category']} | {entry['status']} | "
                f"{competitors} | {entry.get('target', '-')} |"
            )
    return header + "\n".join(rows) + "\n"


def render_report(root: Path = PROJECT_ROOT) -> str:
    payload = load_matrix(root)
    entries = payload["benchmarks"]
    completed = [entry for entry in entries if entry["status"] == "implemented"]
    runner_ready = [entry for entry in entries if entry["status"] == "runner-ready"]
    planned = [entry for entry in entries if entry["status"] == "planned"]

    runner_ready_block = (
        table(runner_ready, include_results=True).rstrip()
        if runner_ready
        else "None currently. LoCoMo and BEIR/SciFact now have checked-in retrieval results."
    )

    lines = [
        "# WaveMind Benchmark Report",
        "",
        "This report is generated from `benchmarks/benchmark_matrix_results.json`.",
        f"Last refresh: `{payload.get('generated_at', 'unknown')}` from `{payload.get('source_ref', 'unknown')}`.",
        "It separates completed local runs from runner-ready public benchmarks and planned external evaluations.",
        "",
        "Planned rows are not claimed wins. They are the public proof path WaveMind must complete before stronger production claims.",
        "",
        "## Completed Runs",
        "",
        table(completed, include_results=True).rstrip(),
        "",
        "## Runner-Ready Public Benchmarks",
        "",
        runner_ready_block,
        "",
        "## Public Benchmark Roadmap",
        "",
        table(planned, include_results=False).rstrip(),
        "",
        "## Reading Guide",
        "",
        "- Retrieval benchmarks such as BEIR, MTEB, and MIRACL test whether WaveMind can preserve vector-search quality.",
        "- Vector database benchmarks such as ANN-Benchmarks and VectorDBBench test latency, recall, and scale, not memory policy.",
        "- Agent-memory benchmarks such as LoCoMo and LongMemEval are the most important public proof targets for WaveMind.",
        "- The synthetic dynamic-memory and long-memory evidence checks remain useful regression tests, but they are not substitutes for public datasets.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/BENCHMARK_REPORT.md"),
    )
    args = parser.parse_args()
    report = render_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
