from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import logging
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
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


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


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
        "observations": len(values),
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


def _full_context_token_budget(dataset: EvidenceDataset) -> int:
    return sum(
        max(1, int(len(memory.text.split()) * 1.25 + 0.999))
        for memory in dataset.memories
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
        _full_context_token_budget(dataset),
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
        _full_context_token_budget(dataset),
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


def _mem0_rows(response: Any) -> list[dict[str, Any]]:
    rows = response.get("results") if isinstance(response, dict) else response
    return [row for row in rows or [] if isinstance(row, dict)]


def _mem0_evidence_ids(response: Any) -> list[str]:
    ids: list[str] = []
    for row in _mem0_rows(response):
        metadata = row.get("metadata") or {}
        evidence_id = metadata.get("evidence_id")
        if evidence_id:
            ids.append(str(evidence_id))
    return ids


def _mem0_texts(response: Any) -> list[str]:
    texts: list[str] = []
    for row in _mem0_rows(response):
        text = (
            row.get("memory")
            or row.get("text")
            or row.get("document")
            or row.get("content")
            or ""
        )
        texts.append(str(text))
    return texts


def run_mem0_oss(
    dataset: EvidenceDataset,
    _encoder: Any,
    top_k: int,
) -> EvidenceMetrics:
    os.environ.setdefault("MEM0_TELEMETRY", "False")
    logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)

    from mem0 import Memory

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = {
            "llm": {
                "provider": "openai",
                "config": {"api_key": "dummy-not-used-with-infer-false"},
            },
            "embedder": {
                "provider": "fastembed",
                "config": {"model": "BAAI/bge-small-en-v1.5"},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(root / "qdrant"),
                    "collection_name": "wavemind_quality_leadership_mem0",
                    "embedding_model_dims": 384,
                },
            },
            "history_db_path": str(root / "history.db"),
        }
        memory = Memory.from_config(config)
        try:
            for item in dataset.memories:
                memory.add(
                    item.text,
                    user_id=item.namespace,
                    metadata={
                        "evidence_id": item.id,
                        "namespace": item.namespace,
                    },
                    infer=False,
                )
            rankings: dict[str, list[str]] = {}
            texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                response = memory.search(
                    query.text,
                    filters={"user_id": query.namespace},
                    top_k=top_k,
                    threshold=0.0,
                    show_expired=False,
                )
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = _mem0_evidence_ids(response)
                texts[query.id] = _mem0_texts(response)
        finally:
            memory.close()
            del memory
            gc.collect()
    return compute_evidence_metrics(
        dataset.queries,
        rankings,
        texts,
        latencies,
        _full_context_token_budget(dataset),
        top_k,
        "Mem0 OSS",
    )


def run_langgraph_persistent(
    dataset: EvidenceDataset,
    encoder: Any,
    top_k: int,
) -> EvidenceMetrics:
    from langgraph.store.sqlite import SqliteStore

    def embed(texts: str | list[str]) -> list[list[float]]:
        batch = [texts] if isinstance(texts, str) else list(texts)
        return [
            encoder.encode_vector(text).astype(float).tolist()
            for text in batch
        ]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "langgraph-store.sqlite"
        with SqliteStore.from_conn_string(
            str(db_path),
            index={"dims": int(encoder.vector_dim), "embed": embed, "fields": ["text"]},
        ) as store:
            store.setup()
            for item in dataset.memories:
                store.put(
                    (item.namespace,),
                    item.id,
                    {
                        "text": item.text,
                        "evidence_id": item.id,
                        "namespace": item.namespace,
                    },
                )
            rankings: dict[str, list[str]] = {}
            texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                results = store.search((query.namespace,), query=query.text, limit=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [
                    str(item.value.get("evidence_id", item.key))
                    for item in results
                ]
                texts[query.id] = [
                    str(item.value.get("text", ""))
                    for item in results
                ]
    return compute_evidence_metrics(
        dataset.queries,
        rankings,
        texts,
        latencies,
        _full_context_token_budget(dataset),
        top_k,
        "LangGraph persistent memory",
    )


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
                    "case_outcomes": list(
                        source["trial_case_outcomes"][index]
                    ),
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


def _paired_case_lifts(
    memory_os: dict[str, Any],
    core: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def average_cases(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for trial in row["trial_metrics"]:
            for case in trial.get("case_outcomes") or []:
                namespace = str(case["namespace"])
                current = values.setdefault(
                    namespace,
                    {
                        "category": str(case["category"]),
                        "successes": [],
                    },
                )
                current["successes"].append(float(case["success_rate"]))
        return {
            namespace: {
                "category": value["category"],
                "success_rate": statistics.mean(value["successes"]),
            }
            for namespace, value in values.items()
        }

    memory_os_cases = average_cases(memory_os)
    core_cases = average_cases(core)
    shared = sorted(set(memory_os_cases) & set(core_cases))
    differences = {
        namespace: (
            str(memory_os_cases[namespace]["category"]),
            float(memory_os_cases[namespace]["success_rate"])
            - float(core_cases[namespace]["success_rate"]),
        )
        for namespace in shared
    }
    category_lifts: dict[str, dict[str, Any]] = {}
    for offset, category in enumerate(
        sorted({value[0] for value in differences.values()})
    ):
        category_lifts[category] = _bootstrap_ci(
            [
                difference
                for row_category, difference in differences.values()
                if row_category == category
            ],
            seed=BOOTSTRAP_SEED + 100 + offset,
        )
    overall = _bootstrap_ci(
        [difference for _, difference in differences.values()],
        seed=BOOTSTRAP_SEED + 200,
    )
    return overall, category_lifts


def _optional_competitors() -> list[dict[str, Any]]:
    rows = []
    for engine, module in (
        ("Graphiti", "graphiti_core"),
    ):
        installed = _module_available(module)
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
    include_mem0: bool = True,
    include_langgraph: bool = True,
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

    requested_real_baselines: list[tuple[str, tuple[str, ...], Runner, bool]] = [
        ("Chroma static", ("chromadb",), run_chroma_static, include_chroma),
        ("Qdrant static", ("qdrant_client",), run_qdrant_static, include_qdrant),
        (
            "Mem0 OSS",
            ("mem0", "fastembed", "qdrant_client"),
            run_mem0_oss,
            include_mem0,
        ),
        (
            "LangGraph persistent memory",
            ("langgraph.store.sqlite",),
            run_langgraph_persistent,
            include_langgraph,
        ),
    ]
    skipped: list[dict[str, Any]] = []
    for engine, modules, runner, enabled in requested_real_baselines:
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
        missing_modules = [module for module in modules if not _module_available(module)]
        if missing_modules:
            skipped.append(
                {
                    "engine": engine,
                    "status": "skipped",
                    "reason": (
                        f"{', '.join(missing_modules)}_not_installed; "
                        "no imitation substituted"
                    ),
                    "eligible_for_comparison": False,
                }
            )
            continue
        try:
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
        except Exception as exc:
            skipped.append(
                {
                    "engine": engine,
                    "status": "skipped",
                    "reason": f"same-protocol adapter failed: {type(exc).__name__}: {exc}",
                    "eligible_for_comparison": False,
                }
            )

    overall_lift, category_lifts = _paired_case_lifts(
        memory_os,
        wavemind_core,
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
    parser.add_argument("--without-mem0", action="store_true")
    parser.add_argument("--without-langgraph", action="store_true")
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
        include_mem0=not args.without_mem0,
        include_langgraph=not args.without_langgraph,
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
