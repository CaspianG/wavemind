from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import random
import statistics
import subprocess
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceMetrics,
    EvidenceQuery,
    LongMemory,
    cache_encoder_for_dataset,
    run_chroma_static,
    run_qdrant_static,
)
from benchmarks.public_memory_competitors import (
    run_langgraph_store_evidence,
    run_mem0_evidence,
)
from benchmarks.verified_experience_benchmark import (
    DATASET_REVISION,
    DOMAINS,
    REPEATS,
    ExecutableStateVerifier,
    _ci95,
    _evaluate_mode,
    _runtime,
    _safety_checks,
    _train,
    dataset_fingerprint,
    frozen_tasks,
)
from wavemind import __version__
from wavemind.encoders import create_text_encoder
from wavemind.experience import ExperienceStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "wavemind.competitive_task_benchmark.v1"
DATASET_NAME = "wavemind-verified-experience-competitive-v1"
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260817
Runner = Callable[[EvidenceDataset, Any, int], EvidenceMetrics]


ENGINE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "engine": "Chroma static",
        "modules": ("chromadb",),
        "package": "chromadb",
        "runner": run_chroma_static,
        "embedding_profile": "shared:hash-384",
        "provenance_mode": "memory.id",
    },
    {
        "engine": "Qdrant static",
        "modules": ("qdrant_client",),
        "package": "qdrant-client",
        "runner": run_qdrant_static,
        "embedding_profile": "shared:hash-384",
        "provenance_mode": "memory.id",
    },
    {
        "engine": "LangGraph BaseStore",
        "modules": ("langgraph",),
        "package": "langgraph",
        "runner": run_langgraph_store_evidence,
        "embedding_profile": "shared:hash-384",
        "provenance_mode": "value.evidence_id",
    },
    {
        "engine": "Mem0 OSS",
        "modules": ("mem0", "fastembed", "qdrant_client"),
        "package": "mem0ai",
        "runner": run_mem0_evidence,
        "embedding_profile": "native:fastembed",
        "provenance_mode": "metadata.evidence_id",
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repository_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _bootstrap_ci(values: list[float], *, seed: int) -> dict[str, Any]:
    if not values:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "observations": 0}
    generator = random.Random(seed)
    means = sorted(
        statistics.fmean(generator.choice(values) for _ in values)
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "mean": statistics.fmean(values),
        "lower": means[int(len(means) * 0.025)],
        "upper": means[min(len(means) - 1, int(len(means) * 0.975))],
        "observations": len(values),
    }


def _build_competitive_dataset() -> tuple[
    EvidenceDataset,
    dict[str, tuple[str, ...]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    namespace = "competitive-task-training"
    with tempfile.TemporaryDirectory(prefix="wavemind-competitive-training-") as tmp:
        runtime = _runtime(Path(tmp) / "experience.sqlite3", namespace)
        training = _train(runtime, namespace)
        records = runtime.store.list(
            namespace=namespace,
            status=ExperienceStatus.ACTIVE,
            limit=100,
        )
        memories: list[LongMemory] = []
        plans: dict[str, tuple[str, ...]] = {}
        by_domain: dict[str, str] = {}
        for record in records:
            domains = tuple(record.applicability.domains)
            if len(domains) != 1:
                raise RuntimeError("competitive procedure must have one domain")
            domain = domains[0]
            memories.append(
                LongMemory(
                    id=record.id,
                    text=record.content,
                    namespace=domain,
                    tags=("verified-experience", "procedure", domain),
                )
            )
            plans[record.id] = tuple(
                str(value) for value in record.metadata.get("tool_plan") or ()
            )
            by_domain[domain] = record.id
        tasks = frozen_tasks()
        candidate_mode = _evaluate_mode(
            "selective_verified_compact",
            runtime,
            namespace,
            tasks,
        )
        safety = _safety_checks(runtime, namespace)
        runtime.store.close()

        queries = []
        for task in tasks:
            procedure_id = by_domain[task.domain]
            queries.append(
                EvidenceQuery(
                    id=task.id,
                    text=task.query,
                    namespace=task.domain,
                    expected_evidence_ids=(
                        (procedure_id,) if task.experience_needed else ()
                    ),
                    forbidden_evidence_ids=(
                        () if task.experience_needed else (procedure_id,)
                    ),
                    category=(
                        f"{task.domain}:"
                        f"{'hard' if task.experience_needed else 'routine'}"
                    ),
                )
            )
    return (
        EvidenceDataset(name=DATASET_NAME, memories=memories, queries=queries),
        plans,
        training,
        candidate_mode,
        safety,
    )


def _mean_case_success(mode: dict[str, Any]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for repeat in mode["repeats"]:
        for case in repeat["case_outcomes"]:
            values.setdefault(str(case["task_id"]), []).append(
                1.0 if case["success"] else 0.0
            )
    return {key: statistics.fmean(rows) for key, rows in values.items()}


def _native_row(
    mode: dict[str, Any],
    safety: dict[str, Any],
    *,
    held_out_tasks: int,
) -> dict[str, Any]:
    return {
        "engine": "WaveMind Verified Experience",
        "status": "pass",
        "execution_mode": "verified_experience_compact_packet",
        "system_version": __version__,
        "embedding_profile": "shared:hash-384",
        "provenance_mode": "ExperiencePacket.citations",
        "measurement_trials": len(mode["repeats"]),
        "task_success": mode["task_success"],
        "repeated_error_rate": mode["repeated_error_rate"],
        "context_tokens": mode["context_tokens"],
        "unnecessary_intervention_rate": mode["unnecessary_intervention_rate"],
        "p95_latency_ms": mode["p95_latency_ms"],
        "failed_task_attempts": round(
            (1.0 - float(mode["task_success"]["mean"])) * held_out_tasks,
            6,
        ),
        "paid_api_cost_usd": 0.0,
        "domains": mode["domains"],
        "case_success": _mean_case_success(mode),
        "trial_metrics": mode["repeats"],
        "safety": safety,
    }


def _evaluate_retrieval_trial(
    metrics: EvidenceMetrics,
    *,
    plans: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    tasks = {task.id: task for task in frozen_tasks()}
    successes = 0
    hard_failures = 0
    interventions = 0
    unnecessary = 0
    domain_values: dict[str, list[float]] = {domain: [] for domain in DOMAINS}
    case_rows: list[dict[str, Any]] = []
    for retrieval in metrics.case_outcomes:
        task = tasks[str(retrieval["query_id"])]
        returned = tuple(str(value) for value in retrieval["returned_evidence_ids"])
        injected = bool(returned)
        plan = plans.get(returned[0], ()) if returned else task.fallback_plan
        environment = ExecutableStateVerifier(task.expected_plan)
        for tool_name in plan:
            environment.call(tool_name)
        success = environment.verify()
        successes += int(success)
        hard_failures += int(task.experience_needed and not success)
        interventions += int(injected)
        unnecessary += int(injected and not task.experience_needed)
        domain_values[task.domain].append(1.0 if success else 0.0)
        case_rows.append(
            {
                "task_id": task.id,
                "domain": task.domain,
                "task_type": task.task_type,
                "experience_needed": task.experience_needed,
                "injected": injected,
                "returned_evidence_ids": returned,
                "success": success,
            }
        )
    hard_count = sum(task.experience_needed for task in tasks.values())
    return {
        "task_success": successes / len(tasks),
        "repeated_error_rate": hard_failures / hard_count,
        "context_tokens": int(metrics.context_tokens_returned),
        "interventions": interventions,
        "unnecessary_intervention_rate": unnecessary / max(1, interventions),
        "p95_latency_ms": float(metrics.p95_latency_ms),
        "domain_success": {
            domain: statistics.fmean(values) for domain, values in domain_values.items()
        },
        "case_outcomes": case_rows,
        "ingest_total_ms": float(metrics.ingest_total_ms),
    }


def _baseline_row(
    engine: str,
    runner: Runner,
    dataset: EvidenceDataset,
    encoder: Any,
    plans: dict[str, tuple[str, ...]],
    *,
    repeats: int,
    system_version: str,
    embedding_profile: str,
    provenance_mode: str,
) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    observed_metadata: dict[str, Any] = {}
    for _ in range(repeats):
        metrics = runner(dataset, encoder, 1)
        trials.append(_evaluate_retrieval_trial(metrics, plans=plans))
        values = asdict(metrics)
        for key in ("system_version", "embedding_profile", "provenance_mode"):
            if values.get(key):
                observed_metadata[key] = values[key]
    task_values = [row["task_success"] for row in trials]
    error_values = [row["repeated_error_rate"] for row in trials]
    context_values = [row["context_tokens"] for row in trials]
    unnecessary_values = [row["unnecessary_intervention_rate"] for row in trials]
    case_values: dict[str, list[float]] = {}
    domain_values: dict[str, list[float]] = {domain: [] for domain in DOMAINS}
    for trial in trials:
        for case in trial["case_outcomes"]:
            case_values.setdefault(case["task_id"], []).append(
                1.0 if case["success"] else 0.0
            )
        for domain, value in trial["domain_success"].items():
            domain_values[domain].append(float(value))
    return {
        "engine": engine,
        "status": "pass",
        "execution_mode": "task_native_retrieved_procedure",
        "system_version": observed_metadata.get("system_version", system_version),
        "embedding_profile": observed_metadata.get(
            "embedding_profile", embedding_profile
        ),
        "provenance_mode": observed_metadata.get("provenance_mode", provenance_mode),
        "measurement_trials": repeats,
        "task_success": _ci95(task_values, bounded=True),
        "repeated_error_rate": _ci95(error_values, bounded=True),
        "context_tokens": _ci95(context_values),
        "unnecessary_intervention_rate": _ci95(
            unnecessary_values,
            bounded=True,
        ),
        "p95_latency_ms": statistics.median(row["p95_latency_ms"] for row in trials),
        "failed_task_attempts": statistics.fmean(
            (1.0 - row["task_success"]) * len(dataset.queries) for row in trials
        ),
        "paid_api_cost_usd": 0.0,
        "ingest_total_ms": statistics.median(row["ingest_total_ms"] for row in trials),
        "domains": {
            domain: {"task_success": _ci95(values, bounded=True)}
            for domain, values in domain_values.items()
        },
        "case_success": {
            task_id: statistics.fmean(values) for task_id, values in case_values.items()
        },
        "trial_metrics": trials,
    }


def _paired_lift(
    candidate: dict[str, Any], baseline: dict[str, Any], seed: int
) -> dict[str, Any]:
    candidate_cases = candidate["case_success"]
    baseline_cases = baseline["case_success"]
    shared = sorted(set(candidate_cases) & set(baseline_cases))
    return _bootstrap_ci(
        [float(candidate_cases[key]) - float(baseline_cases[key]) for key in shared],
        seed=seed,
    )


def _strongest_competitor(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rows,
        key=lambda row: (
            float(row["task_success"]["mean"]),
            -float(row["repeated_error_rate"]["mean"]),
            -float(row["unnecessary_intervention_rate"]["mean"]),
            -float(row["context_tokens"]["mean"]),
            -float(row["p95_latency_ms"]),
        ),
    )


def run_benchmark(
    *,
    source_sha: str | None = None,
    repeats: int = REPEATS,
    runners: dict[str, Runner] | None = None,
) -> dict[str, Any]:
    if repeats < 5:
        raise ValueError("repeats must be at least 5")
    exact_sha = source_sha or _repository_sha()
    dataset, plans, training, candidate_mode, safety = _build_competitive_dataset()
    base_encoder = create_text_encoder(kind="hash", vector_dim=384)
    encoder = cache_encoder_for_dataset(dataset, base_encoder)
    candidate = _native_row(
        candidate_mode,
        safety,
        held_out_tasks=len(dataset.queries),
    )
    competitor_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    supplied = runners or {}
    for spec in ENGINE_SPECS:
        engine = str(spec["engine"])
        runner = supplied.get(engine)
        missing = [
            module
            for module in spec["modules"]
            if importlib.util.find_spec(module) is None
        ]
        if runner is None and missing:
            skipped.append(
                {
                    "engine": engine,
                    "status": "skipped",
                    "reason": f"missing packages: {', '.join(missing)}; no imitation substituted",
                    "eligible_for_admission": False,
                }
            )
            continue
        runner = runner or spec["runner"]
        competitor_rows.append(
            _baseline_row(
                engine,
                runner,
                dataset,
                encoder,
                plans,
                repeats=repeats,
                system_version=_package_version(str(spec["package"])),
                embedding_profile=str(spec["embedding_profile"]),
                provenance_mode=str(spec["provenance_mode"]),
            )
        )
    paired = {
        row["engine"]: _paired_lift(candidate, row, BOOTSTRAP_SEED + index)
        for index, row in enumerate(competitor_rows)
    }
    strongest = _strongest_competitor(competitor_rows) if competitor_rows else None
    protocol = {
        "dataset": DATASET_NAME,
        "dataset_revision": DATASET_REVISION,
        "task_fingerprint_sha256": dataset_fingerprint(),
        "corpus_fingerprint_sha256": _canonical_hash(
            {
                "memories": [asdict(memory) for memory in dataset.memories],
                "queries": [asdict(query) for query in dataset.queries],
            }
        ),
        "held_out_tasks": len(dataset.queries),
        "hard_tasks": sum(
            bool(query.expected_evidence_ids) for query in dataset.queries
        ),
        "routine_tasks": sum(
            not query.expected_evidence_ids for query in dataset.queries
        ),
        "domains": list(DOMAINS),
        "repeats": repeats,
        "top_k": 1,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "same_tasks": True,
        "same_procedure_corpus": True,
        "same_executable_state_verifier": True,
        "same_top_k": True,
        "same_namespace_routing": True,
        "same_shared_embedding_where_supported": True,
        "native_embedding_exception": "Mem0 OSS uses its documented FastEmbed path",
        "split_frozen_before_evaluation": True,
        "answer_metadata_visible_to_agent": False,
        "hardware": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
    }
    protocol["hash"] = _canonical_hash(protocol)
    return {
        "schema": SCHEMA,
        "status": "complete" if not skipped else "blocked",
        "generated_at": _utc_now(),
        "source_sha": exact_sha,
        "protocol": protocol,
        "training": training,
        "candidate": candidate,
        "competitors": competitor_rows,
        "skipped": skipped,
        "paired_task_success_lift": paired,
        "strongest_competitor": (
            {
                "engine": strongest["engine"],
                "task_success": strongest["task_success"]["mean"],
                "context_tokens": strongest["context_tokens"]["mean"],
                "p95_latency_ms": strongest["p95_latency_ms"],
            }
            if strongest
            else None
        ),
        "claim_boundary": (
            "This exact-protocol benchmark executes retrieved procedures against "
            "150 deterministic held-out state verifiers. It measures this frozen "
            "coding/support/operations-style workflow family, not universal memory "
            "quality, hosted scale, answer generation, or willingness to pay."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", default=None)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/competitive_task_benchmark_results.json"),
    )
    args = parser.parse_args(argv)
    payload = run_benchmark(source_sha=args.source_sha, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
