from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


QUALITY_METRIC_ORDER = (
    "evidence_recall_at_k",
    "precision_at_1",
    "precision@1",
    "token_f1",
    "ndcg_at_k",
    "recall_at_k",
    "mrr_at_k",
    "concept_formation",
    "concept_consolidation",
    "stale_suppression",
    "suppression_rate",
    "direction_accuracy_at_1",
)


METRIC_LABELS = {
    "evidence_recall_at_k": "evidence recall@k",
    "precision_at_1": "precision@1",
    "precision@1": "precision@1",
    "token_f1": "token F1",
    "ndcg_at_k": "nDCG@k",
    "recall_at_k": "Recall@k",
    "mrr_at_k": "MRR@k",
    "concept_formation": "concept formation",
    "concept_consolidation": "concept consolidation",
    "stale_suppression": "stale suppression",
    "suppression_rate": "stale suppression",
    "direction_accuracy_at_1": "direction@1",
    "avg_latency_ms": "avg latency",
}


def load_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root / "benchmarks" / "benchmark_matrix_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if abs(value) < 10:
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return f"{value:.1f}"
    return str(value)


def metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key.replace("_", " "))


def is_wavemind_engine(name: str) -> bool:
    normalized = name.lower()
    return (
        normalized.startswith("wavemind")
        or "wavemind" in normalized
        or normalized in {"static_agent_memory", "dynamic_agent_memory"}
    )


def representative_metrics(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value if value else None
    if isinstance(value, list) and value:
        last = value[-1]
        return last if isinstance(last, dict) else None
    return None


def choose_quality_metric(entry: dict[str, Any], current: dict[str, Any]) -> str | None:
    metric_keys: set[str] = set()
    for metrics in current.values():
        representative = representative_metrics(metrics)
        if representative:
            metric_keys.update(representative)
    if entry.get("id") == "longmemeval_answer_generation" and "token_f1" in metric_keys:
        return "token_f1"
    for key in QUALITY_METRIC_ORDER:
        if key in metric_keys:
            return key
    return None


def best_engine(
    current: dict[str, Any],
    *,
    metric: str,
    wavemind: bool,
) -> tuple[str, dict[str, Any]] | None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for engine, metrics in current.items():
        if is_wavemind_engine(engine) != wavemind:
            continue
        representative = representative_metrics(metrics)
        if representative is None or metric not in representative:
            continue
        candidates.append((engine, representative))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            float(item[1].get(metric, 0.0)),
            -float(item[1].get("avg_latency_ms", 1_000_000_000.0)),
        ),
    )


def display_engine_name(name: str) -> str:
    return {
        "static_agent_memory": "WaveMind static capacity",
        "dynamic_agent_memory": "WaveMind dynamic capacity",
    }.get(name, name)


def latency_text(metrics: dict[str, Any] | None) -> str:
    if not metrics:
        return "-"
    latency = metrics.get("avg_latency_ms")
    if latency is None:
        return "-"
    return f"{fmt(latency)} ms"


def row_status(
    wave: tuple[str, dict[str, Any]] | None,
    baseline: tuple[str, dict[str, Any]] | None,
    metric: str,
) -> str:
    if wave is None:
        return "No WaveMind result"
    if baseline is None:
        return "WaveMind-only check"
    wave_score = float(wave[1].get(metric, 0.0))
    baseline_score = float(baseline[1].get(metric, 0.0))
    delta = wave_score - baseline_score
    if delta > 1e-9:
        return "WaveMind leads on quality"
    if delta < -1e-9:
        return "Baseline leads on quality"
    wave_latency = wave[1].get("avg_latency_ms")
    baseline_latency = baseline[1].get("avg_latency_ms")
    if wave_latency is not None and baseline_latency is not None:
        if float(wave_latency) < float(baseline_latency) * 0.90:
            return "Quality tie; WaveMind faster"
        if float(wave_latency) <= float(baseline_latency) * 1.10:
            return "Quality tie; comparable latency"
        return "Quality tie; WaveMind slower"
    return "Quality tie"


def slo_readout(current: dict[str, Any]) -> str | None:
    rows: list[tuple[str, dict[str, Any]]] = []
    for engine, metrics in current.items():
        representative = representative_metrics(metrics)
        if representative and representative.get("slo_status"):
            rows.append((engine, representative))
    if not rows:
        return None
    priority = {"pass": 0, "scale_required": 1, "fail": 2, "skipped": 3}
    engine, metrics = min(
        rows,
        key=lambda item: (
            priority.get(str(item[1].get("slo_status")), 99),
            int(item[1].get("slo_required_replicas") or 1_000_000),
        ),
    )
    status = str(metrics.get("slo_status"))
    if status == "pass":
        return f"production SLO pass: {display_engine_name(engine)}"
    if status == "scale_required":
        return f"production SLO needs scale: {display_engine_name(engine)}"
    if status == "fail":
        return "production SLO miss"
    return "production SLO not measured"


def leaderboard_row(entry: dict[str, Any]) -> str | None:
    current = entry.get("current")
    if not isinstance(current, dict) or not current:
        return None
    metric = choose_quality_metric(entry, current)
    if metric is None:
        return None
    wave = best_engine(current, metric=metric, wavemind=True)
    baseline = best_engine(current, metric=metric, wavemind=False)
    name = entry["name"]
    if entry.get("source_url"):
        name = f"[{name}]({entry['source_url']})"
    wave_text = "-"
    if wave is not None:
        wave_text = f"{display_engine_name(wave[0])}: {fmt(wave[1].get(metric))} / {latency_text(wave[1])}"
    baseline_text = "-"
    if baseline is not None:
        baseline_text = f"{display_engine_name(baseline[0])}: {fmt(baseline[1].get(metric))} / {latency_text(baseline[1])}"
    readout = row_status(wave, baseline, metric)
    if slo := slo_readout(current):
        readout = f"{readout}; {slo}"
    return (
        f"| {name} | {entry['category']} | {metric_label(metric)} | "
        f"{wave_text} | {baseline_text} | {readout} |"
    )


def render_leaderboard(root: Path = PROJECT_ROOT) -> str:
    payload = load_matrix(root)
    implemented = [
        entry for entry in payload["benchmarks"] if entry.get("status") == "implemented"
    ]
    rows = [row for entry in implemented if (row := leaderboard_row(entry))]
    table = "\n".join(rows)
    return "\n".join(
        [
            "# WaveMind Benchmark Leaderboard",
            "",
            "Generated from `benchmarks/benchmark_matrix_results.json`.",
            "",
            "This is a compact reader-facing view of checked-in benchmark results. It is not a universal vector-database leaderboard: each row uses the primary quality metric for that benchmark, and latency is shown separately so quality wins are not confused with speed wins.",
            "",
            "| benchmark | category | primary metric | best WaveMind result | best baseline result | readout |",
            "|---|---|---|---|---|---|",
            table,
            "",
            "## Reading Rules",
            "",
            "- `WaveMind leads on quality` means the best checked-in WaveMind row beats the best checked-in non-WaveMind baseline on that benchmark's primary quality metric.",
            "- `Quality tie; WaveMind slower` is still a real limitation. It means retrieval quality matched the baseline, but the current memory layer adds latency.",
            "- `production SLO pass/miss` uses the checked-in SLO gate: recall target, p99 target, requested QPS, current replicas, autoscaling max replicas, and capacity headroom.",
            "- `WaveMind-only check` is a regression or capacity check, not a competitor claim.",
            "- Planned public benchmarks stay in `benchmarks/BENCHMARK_REPORT.md` until a real result JSON is checked in.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/BENCHMARK_LEADERBOARD.md"),
    )
    args = parser.parse_args()
    leaderboard = render_leaderboard()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(leaderboard, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
