from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


QUALITY_METRIC_ORDER = (
    "task_success_rate",
    "evidence_recall_at_k",
    "precision_at_1",
    "precision@1",
    "token_f1",
    "ndcg_at_k",
    "recall_at_k",
    "target_recall_at_k",
    "readiness_score",
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
    "target_recall_at_k": "target recall@k",
    "target_recall_at_1": "target recall@1",
    "readiness_score": "readiness score",
    "mrr_at_k": "MRR@k",
    "concept_formation": "concept formation",
    "concept_consolidation": "concept consolidation",
    "stale_suppression": "stale suppression",
    "suppression_rate": "stale suppression",
    "direction_accuracy_at_1": "direction@1",
    "avg_latency_ms": "avg latency",
    "task_success_rate": "task success",
    "decision_success_at_1": "top-1 decision",
    "stale_error_rate": "stale error rate",
    "coherent_turn_rate": "coherent turn rate",
}


def load_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root / "benchmarks" / "benchmark_matrix_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_if_exists(root: Path, relative_path: str) -> dict[str, Any] | None:
    path = root / relative_path
    if not path.exists():
        return None
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


def cost_readout(current: dict[str, Any]) -> str | None:
    rows: list[tuple[str, dict[str, Any]]] = []
    for engine, metrics in current.items():
        representative = representative_metrics(metrics)
        if representative and representative.get("compute_cost_per_1m_queries_usd") is not None:
            rows.append((engine, representative))
    if not rows:
        return None
    valid_rows = [
        row for row in rows
        if row[1].get("cost_status") == "valid_slo"
    ]
    ranked = valid_rows or rows
    engine, metrics = min(
        ranked,
        key=lambda item: float(item[1].get("compute_cost_per_1m_queries_usd") or 1_000_000_000.0),
    )
    prefix = "cost" if valid_rows else "cost if SLO fixed"
    return (
        f"{prefix}: {display_engine_name(engine)} "
        f"${float(metrics['compute_cost_per_1m_queries_usd']):.2f}/1M queries"
    )


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
    if cost := cost_readout(current):
        readout = f"{readout}; {cost}"
    return (
        f"| {name} | {entry['category']} | {metric_label(metric)} | "
        f"{wave_text} | {baseline_text} | {readout} |"
    )


def _matrix_entry(payload: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    for entry in payload.get("benchmarks", []):
        if entry.get("id") == entry_id:
            return entry
    return None


def _first_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    results = payload.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}


def evidence_status_rows(payload: dict[str, Any], root: Path = PROJECT_ROOT) -> list[str]:
    rows: list[tuple[str, str, str, str]] = []

    rows.append(
        (
            "Artifact freshness",
            f"{payload.get('refresh_profile', 'unknown')} matrix refresh at `{payload.get('generated_at', 'unknown')}`",
            f"source `{payload.get('source_ref', 'unknown')}`; audit gate enforced by `validate_benchmark_artifacts.py`",
            "Keep weekly refresh green before public claims.",
        )
    )

    remote_serverless = load_json_if_exists(
        root,
        "deploy/serverless/observed-telemetry.remote.json",
    )
    loopback_serverless = load_json_if_exists(
        root,
        "deploy/serverless/observed-telemetry.loopback.json",
    )
    serverless = remote_serverless or loopback_serverless
    if serverless:
        is_remote = remote_serverless is not None
        mode = str(serverless.get("node_mode") or ("external" if is_remote else "loopback"))
        rows.append(
            (
                "Serverless telemetry",
                (
                    f"{mode} API pool; `{serverless.get('source', 'unknown')}`; "
                    f"{serverless.get('measured_replicas', '?')} measured replicas"
                ),
                (
                    f"observed SLO `{serverless.get('observed_slo_pass')}`; "
                    + ("remote evidence" if is_remote else "loopback evidence, not a managed-serverless claim")
                ),
                (
                    "Keep remote telemetry current with `.github/workflows/serverless-observed-telemetry.yml`."
                    if is_remote
                    else "Run `.github/workflows/serverless-observed-telemetry.yml` against deployed API nodes."
                ),
            )
        )

    http_cluster = load_json_if_exists(root, "benchmarks/http_cluster_load_results.json")
    http_scenario = (http_cluster or {}).get("scenario", {})
    http_result = _first_result(http_cluster)
    if http_cluster:
        environment = str(http_scenario.get("environment", "unknown"))
        rows.append(
            (
                "External HTTP cluster load",
                f"{environment}; `{http_scenario.get('source', 'unknown')}`; {http_scenario.get('node_count', '?')} nodes",
                (
                    f"SLO `{http_result.get('slo_pass')}`; "
                    + ("remote cluster evidence" if environment != "local-loopback" else "local loopback service-node evidence")
                ),
                "Run `.github/workflows/external-http-cluster-load.yml` with a remote node manifest.",
            )
        )

    streaming = load_json_if_exists(root, "benchmarks/production_streaming_load_ivfpq_10m_results.json")
    streaming_result = _first_result(streaming)
    if streaming_result and isinstance(streaming_result.get("results"), list):
        nested_results = streaming_result["results"]
        if nested_results and isinstance(nested_results[0], dict):
            streaming_result = nested_results[0]
    if streaming_result:
        rows.append(
            (
                "10M streaming load",
                f"local `{streaming_result.get('engine', 'unknown')}` profile",
                (
                    f"target recall `{fmt(streaming_result.get('target_recall_at_k'))}`, "
                    f"p99 `{fmt(streaming_result.get('p99_latency_ms'))} ms`, "
                    f"SLO `{streaming_result.get('slo_status', 'unknown')}`"
                ),
                "Repeat at 50M and add service-backed Qdrant/pgvector 10M artifacts.",
            )
        )

    readiness = _matrix_entry(payload, "production_readiness_gate")
    readiness_current = (readiness or {}).get("current", {})
    readiness_metrics = representative_metrics(
        readiness_current.get("WaveMind production readiness")
        if isinstance(readiness_current, dict)
        else None
    )
    if readiness_metrics:
        rows.append(
            (
                "Production readiness gate",
                "checked-in benchmark artifacts",
                (
                    f"`{readiness_metrics.get('overall_status')}`; "
                    f"{readiness_metrics.get('pass_count')}/{readiness_metrics.get('total_criteria')} pass"
                ),
                str((readiness or {}).get("next_step", "Keep the gate green.")),
            )
        )

    competitors = load_json_if_exists(root, "benchmarks/memory_competitor_results.json")
    competitor_results = competitors.get("results", []) if competitors else []
    skipped = [
        result.get("engine", "unknown")
        for result in competitor_results
        if isinstance(result, dict) and result.get("skipped")
    ]
    if competitor_results:
        rows.append(
            (
                "Competitor adapters",
                "checked local adapters plus optional external services",
                f"configured `{len(competitor_results) - len(skipped)}`; skipped `{', '.join(skipped) or '-'}`",
                "Configure skipped external services before claiming full competitor coverage.",
            )
        )

    return [
        f"| {area} | {source} | {status} | {next_action} |"
        for area, source, status, next_action in rows
    ]


def render_leaderboard(root: Path = PROJECT_ROOT) -> str:
    payload = load_matrix(root)
    implemented = [
        entry for entry in payload["benchmarks"] if entry.get("status") == "implemented"
    ]
    rows = [row for entry in implemented if (row := leaderboard_row(entry))]
    table = "\n".join(rows)
    evidence_rows = "\n".join(evidence_status_rows(payload, root))
    return "\n".join(
        [
            "# WaveMind Benchmark Leaderboard",
            "",
            "Generated from `benchmarks/benchmark_matrix_results.json`.",
            f"Last refresh: `{payload.get('generated_at', 'unknown')}` from `{payload.get('source_ref', 'unknown')}`.",
            "",
            "This is a compact reader-facing view of checked-in benchmark results. It is not a universal vector-database leaderboard: each row uses the primary quality metric for that benchmark, and latency is shown separately so quality wins are not confused with speed wins.",
            "",
            "| benchmark | category | primary metric | best WaveMind result | best baseline result | readout |",
            "|---|---|---|---|---|---|",
            table,
            "",
            "## Evidence Source Status",
            "",
            "| area | current source | claim status | next action |",
            "|---|---|---|---|",
            evidence_rows,
            "",
            "## Reading Rules",
            "",
            "- `WaveMind leads on quality` means the best checked-in WaveMind row beats the best checked-in non-WaveMind baseline on that benchmark's primary quality metric.",
            "- `Quality tie; WaveMind slower` is still a real limitation. It means retrieval quality matched the baseline, but the current memory layer adds latency.",
            "- `production SLO pass/miss` uses the checked-in SLO gate: recall target, p99 target, requested QPS, current replicas, autoscaling max replicas, and capacity headroom.",
            "- `cost` uses the checked-in benchmark cost model: required replicas, target QPS, replica hourly cost, vector size, and estimated payload storage.",
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
