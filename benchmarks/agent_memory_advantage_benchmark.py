from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import random
import statistics
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceMetrics,
    EvidenceQuery,
    LongMemory,
    cache_encoder_for_dataset,
    compute_evidence_metrics,
    run_chroma_static,
    run_qdrant_static,
    run_static_vector,
)
from benchmarks.memory_os_ab_benchmark import CASES, run_benchmark as run_memory_os_ab
from wavemind.encoders import create_text_encoder


Runner = Callable[[EvidenceDataset, Any, int], EvidenceMetrics]
MEASUREMENT_TRIALS = 5
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260728


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _source_ref() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _bootstrap_ci(
    values: list[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0}
    generator = random.Random(seed)
    means = sorted(
        statistics.mean(generator.choice(values) for _ in values)
        for _ in range(max(1, int(samples)))
    )
    lower_index = min(len(means) - 1, int(len(means) * 0.025))
    upper_index = min(len(means) - 1, int(len(means) * 0.975))
    return {
        "mean": statistics.mean(values),
        "lower": means[lower_index],
        "upper": means[upper_index],
    }


def _paired_ci(
    left: list[float],
    right: list[float],
    *,
    seed_offset: int = 0,
) -> dict[str, float]:
    if len(left) != len(right) or not left:
        raise ValueError("paired confidence interval requires equal non-empty samples")
    return _bootstrap_ci(
        [float(a) - float(b) for a, b in zip(left, right)],
        seed=BOOTSTRAP_SEED + int(seed_offset),
    )


def build_dynamic_dataset() -> EvidenceDataset:
    memories: list[LongMemory] = []
    queries: list[EvidenceQuery] = []
    for case in CASES:
        current_id = f"{case.namespace}::current"
        stale_id = f"{case.namespace}::stale"
        memories.extend(
            [
                LongMemory(
                    id=current_id,
                    text=case.current,
                    namespace=case.namespace,
                    tags=("agent-memory", case.category, "current"),
                ),
                LongMemory(
                    id=stale_id,
                    text=case.stale,
                    namespace=case.namespace,
                    tags=("agent-memory", case.category, "stale"),
                ),
            ]
        )
        queries.append(
            EvidenceQuery(
                id=f"{case.namespace}::query",
                text=case.evaluation_query,
                namespace=case.namespace,
                expected_evidence_ids=(current_id,),
                forbidden_evidence_ids=(stale_id,),
                category=case.category,
            )
        )
    return EvidenceDataset(
        name="wavemind-dynamic-agent-memory-v1",
        memories=memories,
        queries=queries,
    )


def _full_context(
    dataset: EvidenceDataset,
    _encoder: Any,
    _top_k: int,
) -> EvidenceMetrics:
    memories_by_namespace: dict[str, list[LongMemory]] = {}
    for memory in dataset.memories:
        memories_by_namespace.setdefault(memory.namespace, []).append(memory)
    rankings = {
        query.id: [memory.id for memory in memories_by_namespace[query.namespace]]
        for query in dataset.queries
    }
    texts = {
        query.id: [memory.text for memory in memories_by_namespace[query.namespace]]
        for query in dataset.queries
    }
    return compute_evidence_metrics(
        dataset.queries,
        rankings,
        texts,
        [0.0 for _ in dataset.queries],
        sum(
            max(1, int(len(memory.text.split()) * 1.25 + 0.999))
            for memory in dataset.memories
        ),
        2,
        "Full context",
    )


def _no_memory(
    dataset: EvidenceDataset,
    _encoder: Any,
    _top_k: int,
) -> EvidenceMetrics:
    return compute_evidence_metrics(
        dataset.queries,
        {query.id: [] for query in dataset.queries},
        {query.id: [] for query in dataset.queries},
        [0.0 for _ in dataset.queries],
        sum(
            max(1, int(len(memory.text.split()) * 1.25 + 0.999))
            for memory in dataset.memories
        ),
        1,
        "No memory",
    )


def _weighted_category_success(
    values: dict[str, float],
    category_counts: dict[str, int],
) -> float:
    total = sum(category_counts.values())
    if total <= 0:
        return 0.0
    return sum(
        float(values.get(category, 0.0)) * count
        for category, count in category_counts.items()
    ) / total


def _combined_score(
    *,
    task_success: float,
    stale_error: float,
    context_saved: float,
) -> float:
    return (
        0.60 * float(task_success)
        + 0.25 * max(0.0, 1.0 - float(stale_error))
        + 0.15 * float(context_saved)
    )


def _aggregate_trials(
    engine: str,
    trials: list[dict[str, Any]],
    category_counts: dict[str, int],
) -> dict[str, Any]:
    task_values = [float(row["task_success_rate"]) for row in trials]
    stale_values = [float(row["stale_error_rate"]) for row in trials]
    context_values = [float(row["context_budget_saved"]) for row in trials]
    latency_keys = ("p50_latency_ms", "p95_latency_ms", "p99_latency_ms")
    category_names = sorted(category_counts)
    category_trials = {
        category: [
            float(row["category_success"].get(category, 0.0)) for row in trials
        ]
        for category in category_names
    }
    task_success = statistics.mean(task_values)
    stale_error = statistics.mean(stale_values)
    context_saved = statistics.mean(context_values)
    return {
        "engine": engine,
        "status": "pass",
        "measurement_trials": len(trials),
        "task_success_rate": task_success,
        "task_success_ci95": _bootstrap_ci(task_values),
        "stale_error_rate": stale_error,
        "stale_error_ci95": _bootstrap_ci(stale_values, seed=BOOTSTRAP_SEED + 1),
        "context_budget_saved": context_saved,
        "context_budget_saved_ci95": _bootstrap_ci(
            context_values,
            seed=BOOTSTRAP_SEED + 2,
        ),
        "category_success": {
            category: statistics.mean(values)
            for category, values in category_trials.items()
        },
        "category_success_trials": category_trials,
        **{
            key: statistics.median(float(row[key]) for row in trials)
            for key in latency_keys
        },
        "combined_score": _combined_score(
            task_success=task_success,
            stale_error=stale_error,
            context_saved=context_saved,
        ),
        "cost_per_query_usd": 0.0,
        "trial_metrics": trials,
    }


def _metric_trial(
    metrics: EvidenceMetrics,
    category_counts: dict[str, int],
) -> dict[str, Any]:
    values = asdict(metrics)
    values["task_success_rate"] = _weighted_category_success(
        metrics.category_success,
        category_counts,
    )
    values["stale_error_rate"] = max(0.0, 1.0 - metrics.stale_suppression)
    return values


def _run_real_baseline(
    *,
    engine: str,
    runner: Runner,
    dataset: EvidenceDataset,
    encoder: Any,
    category_counts: dict[str, int],
    measurement_trials: int,
) -> dict[str, Any]:
    trials = [
        _metric_trial(runner(dataset, encoder, 1), category_counts)
        for _ in range(measurement_trials)
    ]
    return _aggregate_trials(engine, trials, category_counts)


def _ab_rows(
    ab_payload: dict[str, Any],
    category_counts: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    results = {
        str(row["engine"]): row
        for row in ab_payload.get("results") or []
        if isinstance(row, dict)
    }
    baseline = dict(results["WaveMind baseline"])
    memory_os = dict(results["WaveMind + Memory OS"])

    def build(source: dict[str, Any], engine: str) -> dict[str, Any]:
        trials = []
        category_trials = list(source["trial_category_success"])
        for index, task_success in enumerate(source["trial_task_success_rates"]):
            stale_error = float(source["trial_stale_error_rates"][index])
            context_saved = float(source["context_budget_saved"])
            trials.append(
                {
                    "task_success_rate": float(task_success),
                    "stale_error_rate": stale_error,
                    "context_budget_saved": context_saved,
                    "category_success": dict(category_trials[index]),
                    "p50_latency_ms": float(
                        source["latency_trials_ms"]["p50_latency_ms"][index]
                    ),
                    "p95_latency_ms": float(
                        source["latency_trials_ms"]["p95_latency_ms"][index]
                    ),
                    "p99_latency_ms": float(
                        source["latency_trials_ms"]["p99_latency_ms"][index]
                    ),
                }
            )
        row = _aggregate_trials(engine, trials, category_counts)
        row["execution_mode"] = (
            "memory_os_direct_adaptive"
            if engine == "WaveMind + Memory OS"
            else "wavemind_core"
        )
        return row

    return build(baseline, "WaveMind Core"), build(memory_os, "WaveMind + Memory OS")


def _optional_competitors() -> list[dict[str, Any]]:
    rows = []
    for engine, module in (
        ("Mem0 OSS", "mem0"),
        ("LangMem / LangGraph", "langmem"),
        ("Graphiti", "graphiti_core"),
    ):
        installed = importlib.util.find_spec(module) is not None
        rows.append(
            {
                "engine": engine,
                "status": "skipped",
                "module": module,
                "installed": installed,
                "reason": (
                    "package_detected_but_no_verified_same-protocol_adapter"
                    if installed
                    else "package_not_installed; no imitation substituted"
                ),
                "eligible_for_comparison": False,
            }
        )
    return rows


def run_benchmark(
    *,
    measurement_trials: int = MEASUREMENT_TRIALS,
    include_chroma: bool = True,
    include_qdrant: bool = True,
) -> dict[str, Any]:
    if measurement_trials < 5:
        raise ValueError("measurement_trials must be at least 5")
    dataset = build_dynamic_dataset()
    category_counts = {
        category: sum(1 for query in dataset.queries if query.category == category)
        for category in sorted({query.category for query in dataset.queries})
    }
    protocol_payload = {
        "dataset": dataset.name,
        "memories": [asdict(memory) for memory in dataset.memories],
        "queries": [asdict(query) for query in dataset.queries],
        "measurement_trials": measurement_trials,
        "embedding": "hash-384",
        "top_k": 1,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }
    protocol_hash = hashlib.sha256(
        json.dumps(
            protocol_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    ab_payload = run_memory_os_ab(measurement_trials=measurement_trials)
    wavemind_core, memory_os = _ab_rows(ab_payload, category_counts)
    base_encoder = create_text_encoder(kind="hash", vector_dim=384)
    encoder = cache_encoder_for_dataset(dataset, base_encoder)
    rows = [wavemind_core, memory_os]
    rows.append(
        _run_real_baseline(
            engine="Static vector",
            runner=run_static_vector,
            dataset=dataset,
            encoder=encoder,
            category_counts=category_counts,
            measurement_trials=measurement_trials,
        )
    )
    rows.append(
        _run_real_baseline(
            engine="Full context",
            runner=_full_context,
            dataset=dataset,
            encoder=encoder,
            category_counts=category_counts,
            measurement_trials=measurement_trials,
        )
    )
    rows.append(
        _run_real_baseline(
            engine="No memory",
            runner=_no_memory,
            dataset=dataset,
            encoder=encoder,
            category_counts=category_counts,
            measurement_trials=measurement_trials,
        )
    )

    requested_real_baselines: list[tuple[str, str, Runner, bool]] = [
        ("Chroma static", "chromadb", run_chroma_static, include_chroma),
        ("Qdrant static", "qdrant_client", run_qdrant_static, include_qdrant),
    ]
    skipped: list[dict[str, Any]] = []
    for engine, module, runner, enabled in requested_real_baselines:
        if not enabled:
            skipped.append(
                {
                    "engine": engine,
                    "status": "skipped",
                    "reason": "disabled_by_cli",
                    "eligible_for_comparison": False,
                }
            )
            continue
        if importlib.util.find_spec(module) is None:
            skipped.append(
                {
                    "engine": engine,
                    "status": "skipped",
                    "reason": f"{module}_not_installed; no imitation substituted",
                    "eligible_for_comparison": False,
                }
            )
            continue
        rows.append(
            _run_real_baseline(
                engine=engine,
                runner=runner,
                dataset=dataset,
                encoder=encoder,
                category_counts=category_counts,
                measurement_trials=measurement_trials,
            )
        )

    category_lifts = {}
    for offset, category in enumerate(sorted(category_counts)):
        category_lifts[category] = _paired_ci(
            memory_os["category_success_trials"][category],
            wavemind_core["category_success_trials"][category],
            seed_offset=100 + offset,
        )
    overall_lift = _paired_ci(
        [row["task_success_rate"] for row in memory_os["trial_metrics"]],
        [row["task_success_rate"] for row in wavemind_core["trial_metrics"]],
        seed_offset=200,
    )
    strongest_baseline = max(
        (row for row in rows if row["engine"] != "WaveMind + Memory OS"),
        key=lambda row: float(row["combined_score"]),
    )
    return {
        "schema": "wavemind.agent_memory_advantage_benchmark.v1",
        "generated_at": _utc_now(),
        "source_sha": _source_ref(),
        "status": "pass",
        "protocol": {
            "hash": protocol_hash,
            "dataset": dataset.name,
            "memory_count": len(dataset.memories),
            "query_count": len(dataset.queries),
            "category_case_counts": category_counts,
            "measurement_trials": measurement_trials,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "confidence_level": 0.95,
            "seed": BOOTSTRAP_SEED,
            "same_memories": True,
            "same_queries": True,
            "same_embeddings": True,
            "same_top_k": True,
            "embedding": {
                "kind": "hash",
                "class": type(base_encoder).__name__,
                "vector_dim": int(encoder.vector_dim),
            },
            "hardware": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor(),
            },
            "combined_score": {
                "task_success_weight": 0.60,
                "stale_suppression_weight": 0.25,
                "context_saving_weight": 0.15,
            },
        },
        "results": rows,
        "skipped": [*skipped, *_optional_competitors()],
        "paired_lift": {
            "overall_task_success": overall_lift,
            "categories": category_lifts,
        },
        "strongest_local_baseline": {
            "engine": strongest_baseline["engine"],
            "combined_score": strongest_baseline["combined_score"],
            "memory_os_combined_score": memory_os["combined_score"],
            "combined_lift": (
                float(memory_os["combined_score"])
                - float(strongest_baseline["combined_score"])
            ),
        },
        "claim_boundary": (
            "This controlled sequential benchmark isolates Memory OS policy effects "
            "on knowledge updates and workflow gotchas. Public-dataset execution is "
            "reported separately and cannot be replaced by this fixture."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurement-trials", type=int, default=MEASUREMENT_TRIALS)
    parser.add_argument("--without-chroma", action="store_true")
    parser.add_argument("--without-qdrant", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/agent_memory_advantage_results.json"),
    )
    args = parser.parse_args()
    payload = run_benchmark(
        measurement_trials=args.measurement_trials,
        include_chroma=not args.without_chroma,
        include_qdrant=not args.without_qdrant,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
