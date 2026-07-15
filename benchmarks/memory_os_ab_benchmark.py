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
    current: str
    stale: str
    observed_query: str
    evaluation_query: str


CASES = (
    AdaptiveCase("role", "The current role is crypto trader.", "The previous role is product manager.", "what is the current role?", "what does the user do?"),
    AdaptiveCase("city", "The current city is Lisbon.", "The previous city is Berlin.", "what is the current city?", "where does the user live?"),
    AdaptiveCase("budget", "The current budget is 2000 dollars.", "The previous budget is 50 dollars.", "what is the current budget?", "how much can the user spend?"),
    AdaptiveCase("style", "The preferred answer style is concise.", "The previous answer style was detailed.", "what answer style is preferred?", "how should I answer?"),
    AdaptiveCase("project", "The active project is WaveMind.", "The previous project was Garden Notes.", "what is the active project?", "which project matters?"),
    AdaptiveCase("token", "The valid token is green 772.", "The expired token was blue 114.", "which token is valid?", "what login token should be used?"),
    AdaptiveCase("language", "The current coding language is Rust.", "The previous coding language was Python.", "what is the current coding language?", "what language does the user code in?"),
    AdaptiveCase("exchange", "The current exchange is Kraken.", "The previous exchange was Binance.", "what is the current exchange?", "where does the user trade?"),
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


def _protocol_hash(*, observed_repetitions: int, evaluation_repetitions: int) -> str:
    payload = {
        "cases": [asdict(case) for case in CASES],
        "observed_repetitions": observed_repetitions,
        "evaluation_repetitions": evaluation_repetitions,
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
            for repetition in range(evaluation_repetitions):
                for case in CASES:
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
                    if repetition == 0:
                        cold_latencies.append(latency)
                    selected_id = results[0].id if results else None
                    successes.append(selected_id == current_ids[case.namespace])
                    stale_errors.append(selected_id == stale_ids[case.namespace])

            cache_stats = cache.stats()
            return {
                "engine": "WaveMind + Memory OS" if use_memory_os else "WaveMind baseline",
                "task_success_rate": statistics.mean(successes),
                "stale_error_rate": statistics.mean(stale_errors),
                "avg_latency_ms": statistics.mean(latencies),
                "p95_latency_ms": _percentile(latencies, 0.95),
                "cold_p95_latency_ms": _percentile(cold_latencies, 0.95),
                "steady_p95_latency_ms": _percentile(latencies[len(CASES) :], 0.95),
                "query_count": len(latencies),
                "context_items_per_query": 1,
                "cache_hits": cache_stats.hits,
                "cache_misses": cache_stats.misses,
                "priority_predictions": sum(int(report.get("priority_predictions") or 0) for report in worker_reports),
                "forgetting_demotions": sum(int(report.get("forgetting_demotions") or 0) for report in worker_reports),
                "worker_runs": len(worker_reports),
            }
        finally:
            memory.close()


def run_benchmark(
    *,
    observed_repetitions: int = 8,
    evaluation_repetitions: int = 25,
) -> dict[str, Any]:
    if observed_repetitions < 2:
        raise ValueError("observed_repetitions must be at least 2")
    if evaluation_repetitions < 2:
        raise ValueError("evaluation_repetitions must be at least 2")
    protocol_hash = _protocol_hash(
        observed_repetitions=observed_repetitions,
        evaluation_repetitions=evaluation_repetitions,
    )
    results = [
        _run_variant(
            use_memory_os=False,
            observed_repetitions=observed_repetitions,
            evaluation_repetitions=evaluation_repetitions,
        ),
        _run_variant(
            use_memory_os=True,
            observed_repetitions=observed_repetitions,
            evaluation_repetitions=evaluation_repetitions,
        ),
    ]
    return {
        "schema": "wavemind.memory_os_ab_benchmark.v1",
        "generated_at": _utc_now(),
        "source_ref": _source_ref(),
        "protocol": {
            "hash": protocol_hash,
            "workload": "sequential_adaptive_recall",
            "case_count": len(CASES),
            "observed_repetitions": observed_repetitions,
            "evaluation_repetitions": evaluation_repetitions,
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
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_ab_results.json"),
    )
    args = parser.parse_args()
    payload = run_benchmark(
        observed_repetitions=args.observed_repetitions,
        evaluation_repetitions=args.evaluation_repetitions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
