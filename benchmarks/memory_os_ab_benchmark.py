from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HotMemoryCache, MemoryOSWorker, WaveMind, query_with_cache
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class AdaptiveCase:
    namespace: str
    category: str
    current: str
    stale: str
    observed_query: str
    evaluation_query: str


CASES = (
    AdaptiveCase("role", "knowledge_update", "The current role is crypto trader.", "The previous role is product manager.", "what is the current role?", "what does the user do?"),
    AdaptiveCase("city", "knowledge_update", "The current city is Lisbon.", "The previous city is Berlin.", "what is the current city?", "where does the user live?"),
    AdaptiveCase("budget", "knowledge_update", "The current budget is 2000 dollars.", "The previous budget is 50 dollars.", "what is the current budget?", "how much can the user spend?"),
    AdaptiveCase("style", "preference_update", "The preferred answer style is concise.", "The previous answer style was detailed.", "what answer style is preferred?", "how should I answer?"),
    AdaptiveCase("project", "state_tracking", "The active project is WaveMind.", "The previous project was Garden Notes.", "what is the active project?", "which project matters?"),
    AdaptiveCase("token", "state_tracking", "The valid token is green 772.", "The expired token was blue 114.", "which token is valid?", "what login token should be used?"),
    AdaptiveCase("language", "knowledge_update", "The current coding language is Rust.", "The previous coding language was Python.", "what is the current coding language?", "what language does the user code in?"),
    AdaptiveCase("exchange", "knowledge_update", "The current exchange is Kraken.", "The previous exchange was Binance.", "what is the current exchange?", "where does the user trade?"),
    AdaptiveCase("updated-budget", "knowledge_update", "The current project budget is 2000 dollars.", "The previous project budget was 50 dollars.", "what is the current project budget?", "is the project budget still 50 dollars?"),
    AdaptiveCase("updated-region", "knowledge_update", "The current service region is Warsaw.", "The previous service region was Dublin.", "what is the current service region?", "is the service still hosted in Dublin?"),
    AdaptiveCase("updated-owner", "knowledge_update", "The current incident owner is Alice.", "The previous incident owner was Bob.", "who is the current incident owner?", "does Bob still own the incident?"),
    AdaptiveCase("updated-port", "knowledge_update", "The current API port is 8081.", "The previous API port was 3000.", "what is the current API port?", "does the API still use port 3000?"),
    AdaptiveCase("backup-rule", "workflow_gotcha", "The active rule requires checksum validation before restoring a backup.", "The obsolete rule allows restoring a backup without checksum validation.", "what is the active rule?", "can the agent restore a backup without checksum validation?"),
    AdaptiveCase("merge-rule", "workflow_gotcha", "The active deployment rule requires tests before merging.", "The obsolete deployment rule allows merging without tests.", "what is the active deployment rule?", "can a change be merged without tests?"),
    AdaptiveCase("token-rule", "workflow_gotcha", "The active security rule requires token rotation before reconnecting.", "The obsolete security rule allows reconnecting without token rotation.", "what is the active security rule?", "can the agent reconnect without token rotation?"),
    AdaptiveCase("recovery-rule", "workflow_gotcha", "The active recovery rule requires snapshot verification before replay.", "The obsolete recovery rule allows replay without snapshot verification.", "what is the active recovery rule?", "can recovery replay without snapshot verification?"),
    AdaptiveCase("release-rule", "workflow_gotcha", "The active release rule requires artifact checksums before publishing.", "The obsolete release rule allows publishing without artifact checksums.", "what is the active release rule?", "can the release publish without artifact checksums?"),
    AdaptiveCase("migration-rule", "workflow_gotcha", "The active database rule requires a backup before migration.", "The obsolete database rule allows migration without a backup.", "what is the active database rule?", "can the database migrate without a backup?"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile))
    return float(ordered[index])


def _estimate_tokens(text: str) -> int:
    words = [word for word in str(text).replace("\n", " ").split(" ") if word]
    return max(1, int(len(words) * 1.25 + 0.999))


def _protocol_hash(
    *,
    observed_repetitions: int,
    evaluation_repetitions: int,
    cold_repetitions: int,
    measurement_trials: int,
) -> str:
    payload = {
        "cases": [asdict(case) for case in CASES],
        "observed_repetitions": observed_repetitions,
        "evaluation_repetitions": evaluation_repetitions,
        "cold_repetitions": cold_repetitions,
        "measurement_trials": measurement_trials,
        "latency_aggregation": "median_of_trial_p95",
        "execution_order": "alternating_baseline_memory_os",
        "top_k": 1,
        "priority_weight": 0.7,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _create_memory(path: Path) -> WaveMind:
    return WaveMind(
        db_path=path,
        encoder=create_text_encoder(kind="hash", vector_dim=384),
        index_kind="numpy",
        score_threshold=0.0,
        evolve_on_feed=0,
        vector_weight=0.62,
        field_weight=0.04,
        priority_weight=0.70,
        lexical_weight=0.42,
        short_query_lexical_weight=1.8,
        rerank_k=20,
        persist_access_on_query=False,
        query_feedback_strength=0.0,
        audit_queries=True,
    )


def _run_variant(
    *,
    use_memory_os: bool,
    observed_repetitions: int,
    evaluation_repetitions: int,
    cold_repetitions: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        memory = _create_memory(Path(temporary_directory) / "adaptive.sqlite3")
        cache = HotMemoryCache(capacity=64, ttl_seconds=120)
        current_ids: dict[str, int] = {}
        stale_ids: dict[str, int] = {}
        worker_reports: list[dict[str, Any]] = []
        try:
            for case in CASES:
                current_ids[case.namespace] = memory.remember(case.current, namespace=case.namespace)
                stale_ids[case.namespace] = memory.remember(case.stale, namespace=case.namespace)
                for _ in range(observed_repetitions):
                    memory.query(case.observed_query, namespace=case.namespace, top_k=1)

            if use_memory_os:
                for case in CASES:
                    report = MemoryOSWorker(memory, cache).run_once(
                        namespace=case.namespace,
                        min_frequency=2,
                        max_hot_queries=4,
                        top_k=1,
                        consolidate_steps=0,
                        consolidate_concepts=False,
                        adaptive_forgetting=True,
                        forgetting_min_age_seconds=0.0,
                        forgetting_priority_decay=0.30,
                        forgetting_max_access_count=0,
                        priority_boost_per_hit=0.30,
                        max_priority_boost=3.0,
                    )
                    worker_reports.append(report.as_dict())

            latencies: list[float] = []
            cold_latencies: list[float] = []
            successes: list[bool] = []
            stale_errors: list[bool] = []
            returned_context_tokens = 0
            case_successes: dict[str, list[bool]] = {
                case.namespace: [] for case in CASES
            }
            case_stale_errors: dict[str, list[bool]] = {
                case.namespace: [] for case in CASES
            }
            for repetition in range(evaluation_repetitions):
                for case in CASES:
                    if use_memory_os and repetition < cold_repetitions:
                        cache.invalidate_namespace(case.namespace)
                    started = time.perf_counter()
                    if use_memory_os:
                        results = query_with_cache(
                            memory,
                            cache,
                            case.evaluation_query,
                            namespace=case.namespace,
                            top_k=1,
                        )
                    else:
                        results = memory.query(
                            case.evaluation_query,
                            namespace=case.namespace,
                            top_k=1,
                        )
                    latency = (time.perf_counter() - started) * 1000.0
                    latencies.append(latency)
                    if repetition < cold_repetitions:
                        cold_latencies.append(latency)
                    selected_id = results[0].id if results else None
                    success = selected_id == current_ids[case.namespace]
                    stale_error = selected_id == stale_ids[case.namespace]
                    successes.append(success)
                    stale_errors.append(stale_error)
                    case_successes[case.namespace].append(success)
                    case_stale_errors[case.namespace].append(stale_error)
                    if results:
                        returned_context_tokens += _estimate_tokens(results[0].text)

            cache_stats = cache.stats()
            full_context_tokens = evaluation_repetitions * sum(
                _estimate_tokens(case.current) + _estimate_tokens(case.stale)
                for case in CASES
            )
            case_outcomes = [
                {
                    "namespace": case.namespace,
                    "category": case.category,
                    "success_rate": statistics.mean(case_successes[case.namespace]),
                    "stale_error_rate": statistics.mean(
                        case_stale_errors[case.namespace]
                    ),
                }
                for case in CASES
            ]
            category_success: dict[str, float] = {}
            category_stale_error: dict[str, float] = {}
            for category in sorted({case.category for case in CASES}):
                rows = [row for row in case_outcomes if row["category"] == category]
                category_success[category] = statistics.mean(
                    float(row["success_rate"]) for row in rows
                )
                category_stale_error[category] = statistics.mean(
                    float(row["stale_error_rate"]) for row in rows
                )
            return {
                "engine": "WaveMind + Memory OS" if use_memory_os else "WaveMind baseline",
                "task_success_rate": statistics.mean(successes),
                "stale_error_rate": statistics.mean(stale_errors),
                "avg_latency_ms": statistics.mean(latencies),
                "p50_latency_ms": _percentile(latencies, 0.50),
                "p95_latency_ms": _percentile(latencies, 0.95),
                "p99_latency_ms": _percentile(latencies, 0.99),
                "cold_p95_latency_ms": _percentile(cold_latencies, 0.95),
                "steady_p95_latency_ms": _percentile(
                    latencies[cold_repetitions * len(CASES) :],
                    0.95,
                ),
                "query_count": len(latencies),
                "context_items_per_query": 1,
                "context_tokens_returned": returned_context_tokens,
                "full_context_tokens": full_context_tokens,
                "context_budget_saved": (
                    max(0.0, 1.0 - returned_context_tokens / full_context_tokens)
                    if full_context_tokens
                    else 0.0
                ),
                "case_outcomes": case_outcomes,
                "category_success": category_success,
                "category_stale_error": category_stale_error,
                "cache_hits": cache_stats.hits,
                "cache_misses": cache_stats.misses,
                "priority_predictions": sum(int(report.get("priority_predictions") or 0) for report in worker_reports),
                "forgetting_demotions": sum(int(report.get("forgetting_demotions") or 0) for report in worker_reports),
                "worker_runs": len(worker_reports),
            }
        finally:
            memory.close()


def _aggregate_variant(trials: list[dict[str, Any]]) -> dict[str, Any]:
    if not trials:
        raise ValueError("at least one benchmark trial is required")
    total_queries = sum(int(trial["query_count"]) for trial in trials)
    latency_keys = (
        "avg_latency_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "cold_p95_latency_ms",
        "steady_p95_latency_ms",
    )
    payload: dict[str, Any] = {
        "engine": trials[0]["engine"],
        "task_success_rate": sum(
            float(trial["task_success_rate"]) * int(trial["query_count"])
            for trial in trials
        )
        / total_queries,
        "stale_error_rate": sum(
            float(trial["stale_error_rate"]) * int(trial["query_count"])
            for trial in trials
        )
        / total_queries,
        "query_count": total_queries,
        "queries_per_trial": int(trials[0]["query_count"]),
        "measurement_trials": len(trials),
        "context_items_per_query": int(trials[0]["context_items_per_query"]),
        "cache_hits": sum(int(trial["cache_hits"]) for trial in trials),
        "cache_misses": sum(int(trial["cache_misses"]) for trial in trials),
        "priority_predictions": sum(int(trial["priority_predictions"]) for trial in trials),
        "forgetting_demotions": sum(int(trial["forgetting_demotions"]) for trial in trials),
        "worker_runs": sum(int(trial["worker_runs"]) for trial in trials),
        "context_tokens_returned": sum(
            int(trial["context_tokens_returned"]) for trial in trials
        ),
        "full_context_tokens": sum(
            int(trial["full_context_tokens"]) for trial in trials
        ),
        "trial_task_success_rates": [
            float(trial["task_success_rate"]) for trial in trials
        ],
        "trial_stale_error_rates": [
            float(trial["stale_error_rate"]) for trial in trials
        ],
        "trial_category_success": [
            dict(trial["category_success"]) for trial in trials
        ],
        "latency_trials_ms": {
            key: [float(trial[key]) for trial in trials] for key in latency_keys
        },
    }
    payload["context_budget_saved"] = max(
        0.0,
        1.0
        - float(payload["context_tokens_returned"])
        / max(1, int(payload["full_context_tokens"])),
    )
    payload["category_success"] = {
        category: statistics.mean(
            float(trial["category_success"][category]) for trial in trials
        )
        for category in sorted(trials[0]["category_success"])
    }
    payload["category_stale_error"] = {
        category: statistics.mean(
            float(trial["category_stale_error"][category]) for trial in trials
        )
        for category in sorted(trials[0]["category_stale_error"])
    }
    payload["case_outcomes"] = list(trials[0]["case_outcomes"])
    for key in latency_keys:
        payload[key] = statistics.median(float(trial[key]) for trial in trials)
    return payload


def run_benchmark(
    *,
    observed_repetitions: int = 8,
    evaluation_repetitions: int = 25,
    cold_repetitions: int = 10,
    measurement_trials: int = 5,
) -> dict[str, Any]:
    if observed_repetitions < 2:
        raise ValueError("observed_repetitions must be at least 2")
    if evaluation_repetitions < 2:
        raise ValueError("evaluation_repetitions must be at least 2")
    if cold_repetitions < 1:
        raise ValueError("cold_repetitions must be positive")
    if cold_repetitions >= evaluation_repetitions:
        raise ValueError("cold_repetitions must be lower than evaluation_repetitions")
    if measurement_trials < 1:
        raise ValueError("measurement_trials must be positive")
    protocol_hash = _protocol_hash(
        observed_repetitions=observed_repetitions,
        evaluation_repetitions=evaluation_repetitions,
        cold_repetitions=cold_repetitions,
        measurement_trials=measurement_trials,
    )
    trials: dict[bool, list[dict[str, Any]]] = {False: [], True: []}
    for trial_index in range(measurement_trials):
        # Alternate execution order so machine warm-up or temporary load cannot
        # systematically favor either side of the A/B comparison.
        order = (False, True) if trial_index % 2 == 0 else (True, False)
        for use_memory_os in order:
            trials[use_memory_os].append(
                _run_variant(
                    use_memory_os=use_memory_os,
                    observed_repetitions=observed_repetitions,
                    evaluation_repetitions=evaluation_repetitions,
                    cold_repetitions=cold_repetitions,
                )
            )
    results = [_aggregate_variant(trials[False]), _aggregate_variant(trials[True])]
    return {
        "schema": "wavemind.memory_os_ab_benchmark.v1",
        "generated_at": _utc_now(),
        "source_ref": _source_ref(),
        "protocol": {
            "hash": protocol_hash,
            "workload": "sequential_adaptive_recall",
            "case_count": len(CASES),
            "categories": sorted({case.category for case in CASES}),
            "category_case_counts": {
                category: sum(1 for case in CASES if case.category == category)
                for category in sorted({case.category for case in CASES})
            },
            "observed_repetitions": observed_repetitions,
            "evaluation_repetitions": evaluation_repetitions,
            "cold_repetitions": cold_repetitions,
            "measurement_trials": measurement_trials,
            "latency_aggregation": "median_of_trial_p95",
            "execution_order": "alternating_baseline_memory_os",
            "same_memories": True,
            "same_observed_queries": True,
            "same_evaluation_queries": True,
            "difference": "Memory OS worker policies and hot-query cache only",
        },
        "claim_boundary": (
            "This direct A/B uses identical memories and sequential query histories. "
            "It measures the incremental effect of Memory OS adaptation over WaveMind baseline."
        ),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed-repetitions", type=int, default=8)
    parser.add_argument("--evaluation-repetitions", type=int, default=25)
    parser.add_argument("--cold-repetitions", type=int, default=10)
    parser.add_argument("--measurement-trials", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_ab_results.json"),
    )
    args = parser.parse_args()
    payload = run_benchmark(
        observed_repetitions=args.observed_repetitions,
        evaluation_repetitions=args.evaluation_repetitions,
        cold_repetitions=args.cold_repetitions,
        measurement_trials=args.measurement_trials,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
