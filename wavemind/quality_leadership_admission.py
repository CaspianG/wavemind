from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    canonical_json_bytes,
    repository_commit,
    sha256_bytes,
    validate_artifact_integrity,
    validate_source_manifest,
)


QUALITY_LEADERSHIP_PROTOCOL_SCHEMA = "wavemind.quality_leadership_protocol.v1"
QUALITY_LEADERSHIP_RESULTS_SCHEMA = "wavemind.quality_leadership_results.v1"
QUALITY_LEADERSHIP_ADMISSION_SCHEMA = "wavemind.quality_leadership_admission.v1"
QUALITY_LEADERSHIP_PER_QUERY_SCHEMA = "wavemind.quality_leadership_per_query.v1"
QUALITY_LEADERSHIP_SPLIT_MANIFEST_SCHEMA = "wavemind.quality_leadership_split_manifest.v1"
PROTOCOL_REVISION = "quality-leadership-v1-20260810"
FROZEN_V1_DATASET_REVISION = "quality-leadership-freeze-v1-20260810"
FROZEN_V1_DEVELOPMENT_SPLIT_SHA256 = (
    "e4345094922637414bec7f69a15cea9207380b1795b39eb53270da99b89965a2"
)
FROZEN_V1_DEVELOPMENT_CASE_COUNT = 18
FROZEN_V1_DEVELOPMENT_CATEGORIES = {
    "knowledge_update": 9,
    "preference_update": 1,
    "state_tracking": 2,
    "workflow_gotcha": 6,
}

DEFAULT_PROTOCOL_PATH = Path("benchmarks/quality_leadership_protocol.json")
DEFAULT_RESULTS_PATH = Path("benchmarks/quality_leadership_results.json")
DEFAULT_PER_QUERY_PATH = Path("benchmarks/quality_leadership_per_query.jsonl")
DEFAULT_ADMISSION_PATH = Path("benchmarks/quality_leadership_admission_results.json")
DEFAULT_ADMISSION_MARKDOWN_PATH = Path("benchmarks/QUALITY_LEADERSHIP_ADMISSION.md")
DEFAULT_AGENT_MEMORY_DIAGNOSTIC_PATH = Path("benchmarks/agent_memory_advantage_results.json")
GOAL4_ARTIFACT_PATH = Path("benchmarks/goal4_quality_experiment_results.json")

GOAL4_HISTORICAL_DECISION_SHA = "4959dbfda325bf7bab979861b93e276472e8bbfb"
GOAL4_EXPECTED = {
    "full451": {
        "core_task_success_rate": 0.18625277161862527,
        "memory_os_task_success_rate": 0.18181818181818182,
        "task_success_uplift": -0.00443458980044345,
        "improved_category_count": 3,
        "context_token_reduction_vs_core": 0.4099552226942337,
        "p95_latency_delta_ms": 1.5909000067040324,
    },
    "untouched419": {
        "core_task_success_rate": 0.18854415274463007,
        "memory_os_task_success_rate": 0.1766109785202864,
        "task_success_uplift": -0.011933174224343673,
    },
}
GOAL4_FAILED_CHECKS = {
    "full451_task_success_uplift",
    "full451_improved_categories",
    "untouched419_task_success_uplift",
    "final_dev32_task_success_uplift",
    "final_dev32_improved_categories",
}

QUALITY_THRESHOLDS = {
    "longmemeval_v2_quality_min": 0.18,
    "memory_os_uplift_over_core_min": 0.01,
    "improved_categories_min": 4,
    "context_reduction_min": 0.35,
    "stale_contradiction_error_rate_max": 0.02,
    "p95_overhead_ms_max": 5.0,
    "p95_overhead_ratio_max": 0.20,
    "dynamic_category_lift_min_count": 2,
    "backend_recall_loss_max": 0.01,
    "measurement_runs_min": 5,
    "confidence_level": 0.95,
    "verdict_fingerprint_repetitions": 3,
}

REQUIRED_LOCAL_COMPETITORS = {
    "static_chroma_or_qdrant",
    "mem0_oss",
    "langmem_or_langgraph",
}

QUALITY_SOURCE_PATHS = [
    "wavemind/core.py",
    "wavemind/cli.py",
    "wavemind/experience.py",
    "wavemind/experience_compiler.py",
    "wavemind/experience_runtime.py",
    "wavemind/memory_os_admission.py",
    "wavemind/agent_memory_admission.py",
    "wavemind/workspace_experience_admission.py",
    "wavemind/quality_leadership_admission.py",
    "benchmarks/goal4_quality_experiment_results.json",
    "benchmarks/quality_leadership_freeze_protocol.py",
    "benchmarks/quality_leadership_admission.py",
    "benchmarks/quality_leadership_results.py",
    "benchmarks/agent_memory_advantage_benchmark.py",
    "benchmarks/longmemeval_v2_memory_benchmark.py",
    "benchmarks/locomo_memory_benchmark.py",
    "benchmarks/longmemeval_memory_benchmark.py",
]


def quality_leadership_protocol_manifest(*, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    source_sha = _repository_commit(root_path)
    payload: dict[str, Any] = {
        "schema": QUALITY_LEADERSHIP_PROTOCOL_SCHEMA,
        "revision": PROTOCOL_REVISION,
        "status": "gap_audit",
        "generated_at": _utc_now(),
        "source_sha": source_sha,
        "source_manifest": build_source_manifest(root_path, QUALITY_SOURCE_PATHS),
        "historical_regression_evidence": {
            "artifact": GOAL4_ARTIFACT_PATH.as_posix(),
            "status": "required_preserved_failed_experiment",
            "decision_sha": GOAL4_HISTORICAL_DECISION_SHA,
            "role": "historical_regression_evidence_only_not_development_or_heldout",
            "full451": GOAL4_EXPECTED["full451"],
            "untouched419": GOAL4_EXPECTED["untouched419"],
        },
        "new_quality_dataset": {
            "state": "required_before_heldout",
            "development_split": "required_before_tuning",
            "held_out_split": "required_untouched_after_protocol_freeze",
            "minimum_repeats": QUALITY_THRESHOLDS["measurement_runs_min"],
            "leakage_controls": [
                "old full451 and untouched419 are forbidden tuning sets",
                "held-out rows cannot be used for error analysis before final verdict",
                "dataset ids, filenames, or metadata cannot encode answers",
            ],
        },
        "thresholds": dict(QUALITY_THRESHOLDS),
        "competitors": {
            "required_local": sorted(REQUIRED_LOCAL_COMPETITORS),
            "optional_if_fully_local": ["graphiti"],
            "forbidden": [
                "self-simulated competitor",
                "proprietary external service as mandatory evidence",
                "unverified marketing proxy",
            ],
        },
        "go_no_go": {
            "dev_gate_required_before_full_run": True,
            "max_architecture_candidates_before_blocked": 2,
            "single_held_out_run_after_freeze": True,
            "user_approval_required_before_gpu_heavy_full_run": True,
        },
        "claim_boundary": (
            "This protocol is a quality-leadership recovery gate. Until it is frozen "
            "with a new independent development/held-out split and passing exact-SHA "
            "evidence, it authorizes no public best, SOTA, or universal quality claim."
        ),
    }
    return attach_artifact_integrity(payload)


def quality_leadership_not_run_results(*, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    source_sha = _repository_commit(root_path)
    payload: dict[str, Any] = {
        "schema": QUALITY_LEADERSHIP_RESULTS_SCHEMA,
        "status": "not_run",
        "admitted": False,
        "generated_at": _utc_now(),
        "source_sha": source_sha,
        "protocol_revision": PROTOCOL_REVISION,
        "development_gate": {
            "status": "not_run",
            "reason": "new frozen development split is required before tuning",
        },
        "held_out_gate": {
            "status": "not_opened",
            "reason": "held-out is forbidden until protocol freeze and development go/no-go",
        },
        "runs": [],
        "competitor_runs": [],
        "metrics": {},
        "historical_goal4_failure": {
            "artifact": GOAL4_ARTIFACT_PATH.as_posix(),
            "status": "preserved_failed_experiment",
            "must_not_be_used_for_tuning": True,
        },
        "source_manifest": build_source_manifest(root_path, QUALITY_SOURCE_PATHS),
        "claim_boundary": (
            "No quality-leadership result has been run for this protocol yet. "
            "The checked-in payload is a fail-closed placeholder, not evidence of uplift."
        ),
    }
    return attach_artifact_integrity(payload)


def quality_leadership_results_from_diagnostics(
    *,
    root: str | Path = ".",
    agent_memory_path: str | Path = DEFAULT_AGENT_MEMORY_DIAGNOSTIC_PATH,
) -> dict[str, Any]:
    root_path = Path(root)
    source_sha = _repository_commit(root_path)
    agent_path = _resolve(root_path, agent_memory_path)
    agent_artifact = _artifact_path(root_path, agent_memory_path)
    agent_payload = _load_json(agent_path)
    agent_errors = _validate_agent_memory_diagnostic(
        agent_payload,
        expected_source_sha=source_sha,
    )
    metrics = _metrics_from_agent_memory(agent_payload)
    competitor_runs = _competitors_from_agent_memory(agent_payload)
    gate_errors = list(agent_errors)
    if metrics.get("memory_os_uplift_over_core") is None:
        gate_errors.append("memory_os_uplift_over_core missing")
    elif float(metrics["memory_os_uplift_over_core"]) < QUALITY_THRESHOLDS["memory_os_uplift_over_core_min"]:
        gate_errors.append("memory_os_uplift_over_core below threshold")
    if int(metrics.get("improved_category_count") or 0) < QUALITY_THRESHOLDS["improved_categories_min"]:
        gate_errors.append("improved_category_count below threshold")
    category_analysis = metrics.get("category_improvement_analysis")
    if (
        isinstance(category_analysis, Mapping)
        and _as_int(category_analysis.get("improvement_ceiling_over_core"))
        < QUALITY_THRESHOLDS["improved_categories_min"]
    ):
        gate_errors.append("category_improvement_ceiling below threshold")
    if metrics.get("context_reduction") is None:
        gate_errors.append("context_reduction missing")
    elif float(metrics["context_reduction"]) < QUALITY_THRESHOLDS["context_reduction_min"]:
        gate_errors.append("context_reduction below threshold")
    if metrics.get("stale_contradiction_error_rate") is None:
        gate_errors.append("stale_contradiction_error_rate missing")
    elif float(metrics["stale_contradiction_error_rate"]) > QUALITY_THRESHOLDS["stale_contradiction_error_rate_max"]:
        gate_errors.append("stale_contradiction_error_rate above threshold")
    if metrics.get("p95_overhead_ms") is None or metrics.get("p95_overhead_ratio") is None:
        gate_errors.append("latency overhead metrics missing")
    elif float(metrics["p95_overhead_ms"]) > QUALITY_THRESHOLDS["p95_overhead_ms_max"] or float(metrics["p95_overhead_ratio"]) > QUALITY_THRESHOLDS["p95_overhead_ratio_max"]:
        gate_errors.append("latency overhead exceeds threshold")
    missing_competitors = sorted(REQUIRED_LOCAL_COMPETITORS - {
        str(row.get("family"))
        for row in competitor_runs
        if row.get("status") == "pass"
        and row.get("simulated") is not True
        and row.get("eligible_for_comparison") is True
        and row.get("embedding_comparable") is True
    })
    if missing_competitors:
        gate_errors.append(f"missing real local competitors: {', '.join(missing_competitors)}")
    if "longmemeval_v2_quality" not in metrics:
        gate_errors.append("LongMemEval-V2 quality gate has not been run on this protocol")

    payload: dict[str, Any] = {
        "schema": QUALITY_LEADERSHIP_RESULTS_SCHEMA,
        "status": "development_passed" if not gate_errors else "development_blocked",
        "admitted": False,
        "generated_at": _utc_now(),
        "source_sha": source_sha,
        "protocol_revision": PROTOCOL_REVISION,
        "development_gate": {
            "status": "passed" if not gate_errors else "blocked",
            "diagnostic": agent_artifact,
            "errors": gate_errors,
        },
        "held_out_gate": {
            "status": "not_opened",
            "reason": "held-out is forbidden until protocol freeze and development go/no-go",
        },
        "measurement_runs": metrics.get("measurement_runs", 0),
        "confidence_level": metrics.get("confidence_level"),
        "confidence_intervals": metrics.get("confidence_intervals"),
        "runs": [
            {
                "id": "controlled-sequential-agent-memory",
                "artifact": agent_artifact,
                "status": "pass" if not agent_errors else "blocked",
                "source_sha": agent_payload.get("source_sha") if isinstance(agent_payload, Mapping) else None,
                "claim_boundary": (
                    "Bounded development diagnostic only; it cannot replace public "
                    "held-out quality evidence or real competitor execution."
                ),
            }
        ],
        "competitor_runs": competitor_runs,
        "metrics": metrics,
        "blocker_taxonomy": _development_blocker_taxonomy(metrics, gate_errors),
        "historical_goal4_failure": {
            "artifact": GOAL4_ARTIFACT_PATH.as_posix(),
            "status": "preserved_failed_experiment",
            "must_not_be_used_for_tuning": True,
        },
        "source_manifest": build_source_manifest(root_path, QUALITY_SOURCE_PATHS),
        "claim_boundary": (
            "Development diagnostic evidence only. A blocked development gate forbids "
            "heavy/full held-out execution and forbids public quality-leadership claims."
        ),
    }
    return attach_artifact_integrity(payload)


def quality_leadership_per_query_header(*, root: str | Path = ".") -> dict[str, Any]:
    return {
        "schema": QUALITY_LEADERSHIP_PER_QUERY_SCHEMA,
        "status": "not_run",
        "source_sha": _repository_commit(Path(root)),
        "protocol_revision": PROTOCOL_REVISION,
        "query_count": 0,
        "claim_boundary": "No per-query quality-leadership evidence has been run.",
    }


def evaluate_quality_leadership_admission(
    *,
    root: str | Path = ".",
    expected_source_sha: str | None = None,
    protocol_path: str | Path | None = None,
    results_path: str | Path | None = None,
    per_query_path: str | Path | None = None,
    safe_product_path: str | Path | None = None,
    workspace_experience_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    source_sha = _repository_commit(root_path)
    expected_sha = expected_source_sha or source_sha
    protocol_file = _resolve(root_path, protocol_path or DEFAULT_PROTOCOL_PATH)
    results_file = _resolve(root_path, results_path or DEFAULT_RESULTS_PATH)
    per_query_file = _resolve(root_path, per_query_path or DEFAULT_PER_QUERY_PATH)
    safe_file = _resolve(root_path, safe_product_path or Path("benchmarks/safe_product_admission_results.json"))
    workspace_file = _resolve(
        root_path,
        workspace_experience_path or Path("benchmarks/workspace_experience_admission_results.json"),
    )

    protocol_payload = _load_json(protocol_file)
    results_payload = _load_json(results_file)
    per_query_header, per_query_error = _load_per_query_header(per_query_file)
    goal4_payload = _load_json(root_path / GOAL4_ARTIFACT_PATH)
    safe_payload = _load_json(safe_file)
    workspace_payload = _load_json(workspace_file)

    protocol_errors = _validate_protocol(
        protocol_payload,
        root=root_path,
        expected_source_sha=expected_sha,
    )
    protocol_frozen_errors = _validate_protocol_frozen(protocol_payload)
    results_errors = _validate_results(
        results_payload,
        root=root_path,
        expected_source_sha=expected_sha,
    )
    if protocol_errors:
        protocol_frozen_errors.append(
            "protocol snapshot is not current; cannot treat frozen protocol as current evidence"
        )
    else:
        protocol_frozen_errors.extend(
            _validate_frozen_protocol_against_development_evidence(
                results_payload,
                expected_source_sha=expected_sha,
            )
        )
    goal4_errors = validate_goal4_failure_artifact(goal4_payload)
    safe_errors = _validate_safe_product(
        safe_payload,
        root=root_path,
        expected_source_sha=expected_sha,
    )
    workspace_errors = _validate_workspace_experience(
        workspace_payload,
        expected_source_sha=expected_sha,
    )
    per_query_errors = _validate_per_query(
        per_query_header,
        per_query_error,
        expected_source_sha=expected_sha,
    )

    rows = [
        _row(
            "source-sha-exact",
            "Admission is evaluated against the exact current source SHA.",
            "implemented" if source_sha == expected_sha else "failed",
            "git rev-parse HEAD",
            "tests/test_quality_leadership_admission.py",
            details={"source_sha": source_sha, "expected_source_sha": expected_sha},
        ),
        _row(
            "goal4-failure-preserved",
            "The public Goal 4 failed experiment remains visible and internally consistent.",
            "implemented" if not goal4_errors else "failed",
            GOAL4_ARTIFACT_PATH.as_posix(),
            "tests/test_goal4_quality_experiment.py",
            details={"errors": goal4_errors},
        ),
        _row(
            "protocol-snapshot-current",
            "Quality-leadership protocol snapshot has integrity and current source manifest.",
            _protocol_snapshot_status(protocol_errors),
            DEFAULT_PROTOCOL_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details={"errors": protocol_errors},
        ),
        _row(
            "protocol-frozen-before-heldout",
            "A new independent protocol, dataset split, thresholds, and hashes are frozen before held-out.",
            "implemented" if not protocol_frozen_errors else "blocked",
            DEFAULT_PROTOCOL_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details={"errors": protocol_frozen_errors},
        ),
        _row(
            "safe-product-current",
            "Safe Product admission remains admitted for this exact source SHA.",
            "implemented" if not safe_errors else "required_current",
            "benchmarks/safe_product_admission_results.json",
            ".github/workflows/safe-product.yml",
            details={"errors": safe_errors},
        ),
        _row(
            "workspace-experience-current",
            "Workspace Experience admission remains admitted for this exact source SHA.",
            "implemented" if not workspace_errors else "required_current",
            "benchmarks/workspace_experience_admission_results.json",
            ".github/workflows/safe-product.yml",
            details={"errors": workspace_errors},
        ),
        _row(
            "results-artifact-current",
            "Quality-leadership results artifact is current, signed, and not using historical tuning data.",
            "implemented" if not results_errors else "blocked",
            DEFAULT_RESULTS_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details={"errors": results_errors},
        ),
        _metric_row(
            "development-go-no-go",
            "Bounded development benchmark passes before any heavy or full held-out run.",
            results_payload,
            "development_gate",
            target="passed",
            artifact_errors=results_errors,
        ),
        _metric_row(
            "heldout-opened-once",
            "The new held-out split is opened exactly once after protocol freeze.",
            results_payload,
            "held_out_gate",
            target="passed",
            artifact_errors=results_errors,
        ),
        _threshold_row(
            "longmemeval-v2-quality",
            "Isolated LongMemEval-V2 quality meets the preregistered floor.",
            results_payload,
            "longmemeval_v2_quality",
            QUALITY_THRESHOLDS["longmemeval_v2_quality_min"],
            comparison=">=",
            artifact_errors=results_errors,
        ),
        _threshold_row(
            "memory-os-uplift-over-core",
            "Memory OS beats WaveMind Core on task success by the required margin.",
            results_payload,
            "memory_os_uplift_over_core",
            QUALITY_THRESHOLDS["memory_os_uplift_over_core_min"],
            comparison=">=",
            artifact_errors=results_errors,
        ),
        _threshold_row(
            "category-improvements",
            "At least four preregistered categories improve.",
            results_payload,
            "improved_category_count",
            QUALITY_THRESHOLDS["improved_categories_min"],
            comparison=">=",
            extra_details_key="category_improvement_analysis",
            artifact_errors=results_errors,
        ),
        _threshold_row(
            "context-reduction",
            "Context tokens drop by at least 35 percent.",
            results_payload,
            "context_reduction",
            QUALITY_THRESHOLDS["context_reduction_min"],
            comparison=">=",
            artifact_errors=results_errors,
        ),
        _threshold_row(
            "stale-contradiction-control",
            "Stale and contradiction error rate stays below two percent.",
            results_payload,
            "stale_contradiction_error_rate",
            QUALITY_THRESHOLDS["stale_contradiction_error_rate_max"],
            comparison="<=",
            artifact_errors=results_errors,
        ),
        _latency_row(results_payload, artifact_errors=results_errors),
        _row(
            "locomo-longmemeval-dynamic-categories",
            "LoCoMo and LongMemEval have no significant overall regression and positive lift in at least two dynamic categories.",
            _artifact_dependent_status(
                results_errors,
                _dynamic_public_status(results_payload),
            ),
            DEFAULT_RESULTS_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details=_with_artifact_errors(
                _dynamic_public_details(results_payload),
                results_errors,
            ),
        ),
        _row(
            "real-local-competitors",
            "Runnable local competitors are real packages/runs, not simulated baselines.",
            _artifact_dependent_status(
                results_errors,
                _competitor_status(results_payload),
            ),
            DEFAULT_RESULTS_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details=_with_artifact_errors(
                _competitor_details(results_payload),
                results_errors,
            ),
        ),
        _threshold_row(
            "backend-recall-loss",
            "Candidate engine recall loss stays within the ANN policy budget.",
            results_payload,
            "backend_recall_loss",
            QUALITY_THRESHOLDS["backend_recall_loss_max"],
            comparison="<=",
            artifact_errors=results_errors,
        ),
        _row(
            "five-run-confidence-intervals",
            "All mandatory results have at least five runs and 95 percent confidence intervals.",
            _artifact_dependent_status(
                results_errors,
                _confidence_status(results_payload),
            ),
            DEFAULT_RESULTS_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details=_with_artifact_errors(
                _confidence_details(results_payload),
                results_errors,
            ),
        ),
        _row(
            "verdict-fingerprint-stability",
            "Three consecutive runs on one SHA produce the same verdict fingerprint.",
            _artifact_dependent_status(
                results_errors,
                _fingerprint_status(results_payload),
            ),
            DEFAULT_RESULTS_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details=_with_artifact_errors(
                _fingerprint_details(results_payload),
                results_errors,
            ),
        ),
        _row(
            "per-query-artifact",
            "Per-query JSONL exists and belongs to the exact source SHA.",
            "implemented" if not per_query_errors else "blocked",
            DEFAULT_PER_QUERY_PATH.as_posix(),
            "tests/test_quality_leadership_admission.py",
            details={"errors": per_query_errors},
        ),
        _row(
            "public-claims-fresh",
            "README, Roadmap, benchmark brief, and leaderboard claims map only to admitted fresh evidence.",
            "blocked",
            "README.md / docs/ROADMAP.md / docs/BENCHMARK_BRIEF.md",
            "tests/test_quality_leadership_admission.py",
            details={
                "reason": (
                    "Quality leadership claim is intentionally disabled until all "
                    "admission rows are implemented on exact-main evidence."
                )
            },
        ),
    ]

    mandatory_rows = [row for row in rows if row["status"] != "historical"]
    admitted = all(row["status"] == "implemented" for row in mandatory_rows)
    summary = {
        "implemented": sum(row["status"] == "implemented" for row in rows),
        "blocked": sum(row["status"] == "blocked" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "required_current": sum(row["status"] == "required_current" for row in rows),
        "historical": sum(row["status"] == "historical" for row in rows),
        "total": len(rows),
    }
    payload: dict[str, Any] = {
        "schema": QUALITY_LEADERSHIP_ADMISSION_SCHEMA,
        "status": "admitted" if admitted else "blocked",
        "admitted": admitted,
        "generated_at": _utc_now(),
        "source_sha": source_sha,
        "expected_source_sha": expected_sha,
        "protocol_revision": PROTOCOL_REVISION,
        "summary": summary,
        "rows": rows,
        "source_manifest": build_source_manifest(root_path, QUALITY_SOURCE_PATHS),
        "artifacts": {
            "protocol": DEFAULT_PROTOCOL_PATH.as_posix(),
            "results": DEFAULT_RESULTS_PATH.as_posix(),
            "per_query": DEFAULT_PER_QUERY_PATH.as_posix(),
            "admission": DEFAULT_ADMISSION_PATH.as_posix(),
            "markdown": DEFAULT_ADMISSION_MARKDOWN_PATH.as_posix(),
        },
        "next_actions": _next_actions(rows),
        "claim_boundary": (
            "Quality leadership is blocked until a new frozen protocol, bounded "
            "development gate, single untouched held-out run, real local competitors, "
            "current Safe Product and Workspace Experience evidence, and exact-main "
            "CI evidence all pass. The historical Goal 4 failure remains public."
        ),
    }
    return attach_artifact_integrity(payload)


def write_quality_leadership_artifacts(
    *,
    root: str | Path = ".",
    expected_source_sha: str | None = None,
    protocol_output: str | Path = DEFAULT_PROTOCOL_PATH,
    results_output: str | Path = DEFAULT_RESULTS_PATH,
    per_query_output: str | Path = DEFAULT_PER_QUERY_PATH,
    admission_output: str | Path = DEFAULT_ADMISSION_PATH,
    markdown_output: str | Path = DEFAULT_ADMISSION_MARKDOWN_PATH,
    safe_product_path: str | Path | None = None,
    workspace_experience_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    protocol_path = _resolve(root_path, protocol_output)
    results_path = _resolve(root_path, results_output)
    per_query_path = _resolve(root_path, per_query_output)
    admission_path = _resolve(root_path, admission_output)
    markdown_path = _resolve(root_path, markdown_output)
    _write_json(protocol_path, quality_leadership_protocol_manifest(root=root_path))
    _write_json(results_path, quality_leadership_not_run_results(root=root_path))
    _write_text(
        per_query_path,
        json.dumps(
            quality_leadership_per_query_header(root=root_path),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
    )
    payload = evaluate_quality_leadership_admission(
        root=root_path,
        expected_source_sha=expected_source_sha,
        protocol_path=protocol_path,
        results_path=results_path,
        per_query_path=per_query_path,
        safe_product_path=safe_product_path,
        workspace_experience_path=workspace_experience_path,
    )
    _write_json(admission_path, payload)
    _write_text(markdown_path, render_quality_leadership_admission_markdown(payload))
    return payload


def write_quality_leadership_development_results(
    *,
    root: str | Path = ".",
    agent_memory_path: str | Path = DEFAULT_AGENT_MEMORY_DIAGNOSTIC_PATH,
    results_output: str | Path = DEFAULT_RESULTS_PATH,
    per_query_output: str | Path = DEFAULT_PER_QUERY_PATH,
    admission_output: str | Path = DEFAULT_ADMISSION_PATH,
    markdown_output: str | Path = DEFAULT_ADMISSION_MARKDOWN_PATH,
    expected_source_sha: str | None = None,
    safe_product_path: str | Path | None = None,
    workspace_experience_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    results_path = _resolve(root_path, results_output)
    per_query_path = _resolve(root_path, per_query_output)
    admission_path = _resolve(root_path, admission_output)
    markdown_path = _resolve(root_path, markdown_output)
    _write_json(
        results_path,
        quality_leadership_results_from_diagnostics(
            root=root_path,
            agent_memory_path=agent_memory_path,
        ),
    )
    _write_text(
        per_query_path,
        json.dumps(
            quality_leadership_per_query_header(root=root_path),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
    )
    payload = evaluate_quality_leadership_admission(
        root=root_path,
        expected_source_sha=expected_source_sha,
        results_path=results_path,
        per_query_path=per_query_path,
        safe_product_path=safe_product_path,
        workspace_experience_path=workspace_experience_path,
    )
    _write_json(admission_path, payload)
    _write_text(markdown_path, render_quality_leadership_admission_markdown(payload))
    return payload


def render_quality_leadership_admission_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Quality Leadership Admission",
        "",
        f"Status: **{payload['status']}**",
        f"Source SHA: `{payload.get('source_sha')}`",
        f"Protocol: `{payload.get('protocol_revision')}`",
        (
            "Rows: "
            f"**{summary['implemented']}/{summary['total']} implemented**, "
            f"{summary['blocked']} blocked, "
            f"{summary['required_current']} required-current, "
            f"{summary['failed']} failed"
        ),
        "",
        "| Row | Status | Artifact | Test |",
        "|---|---:|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| `{row['id']}` | `{row['status']}` | `{row['artifact']}` | `{row['test']}` |"
        )
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.extend(["", "## Claim Boundary", "", str(payload["claim_boundary"]), ""])
    return "\n".join(lines)


def validate_goal4_failure_artifact(payload: Mapping[str, Any] | None) -> list[str]:
    if payload is None:
        return [f"missing {GOAL4_ARTIFACT_PATH.as_posix()}"]
    errors: list[str] = []
    if payload.get("schema") != "wavemind.goal4_quality_experiment.v1":
        errors.append("Goal 4 artifact schema mismatch")
    if payload.get("status") != "failed_experiment" or payload.get("admitted") is not False:
        errors.append("Goal 4 artifact must remain a non-admitted failed_experiment")
    if payload.get("decision_sha") != GOAL4_HISTORICAL_DECISION_SHA:
        errors.append("Goal 4 decision SHA changed")
    if set(payload.get("failed_checks") or []) != GOAL4_FAILED_CHECKS:
        errors.append("Goal 4 failed_checks changed")
    for section, expected_values in GOAL4_EXPECTED.items():
        observed = payload.get(section)
        if not isinstance(observed, Mapping):
            errors.append(f"Goal 4 {section} section missing")
            continue
        for key, expected in expected_values.items():
            actual = observed.get(key)
            if isinstance(expected, float):
                if not _same_float(actual, expected):
                    errors.append(f"Goal 4 {section}.{key} changed")
            elif actual != expected:
                errors.append(f"Goal 4 {section}.{key} changed")
    boundary = str(payload.get("claim_boundary") or "")
    if "must not be presented as agent-quality admission" not in boundary:
        errors.append("Goal 4 claim boundary was weakened")
    return errors


def _validate_protocol(
    payload: Mapping[str, Any] | None,
    *,
    root: Path,
    expected_source_sha: str,
) -> list[str]:
    if payload is None:
        return [f"missing {DEFAULT_PROTOCOL_PATH.as_posix()}"]
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != QUALITY_LEADERSHIP_PROTOCOL_SCHEMA:
        errors.append("quality leadership protocol schema mismatch")
    if payload.get("revision") != PROTOCOL_REVISION:
        errors.append("quality leadership protocol revision mismatch")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("quality leadership protocol source SHA mismatch")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("quality leadership protocol source manifest missing")
    else:
        errors.extend(validate_source_manifest(root, manifest, require_current_files=True))
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        errors.append("quality leadership thresholds missing")
    else:
        for key, expected in QUALITY_THRESHOLDS.items():
            actual = thresholds.get(key)
            if isinstance(expected, float):
                if not _same_float(actual, expected):
                    errors.append(f"quality leadership threshold changed: {key}")
            elif actual != expected:
                errors.append(f"quality leadership threshold changed: {key}")
    historical = payload.get("historical_regression_evidence")
    if not isinstance(historical, Mapping):
        errors.append("historical Goal 4 regression evidence missing from protocol")
    elif historical.get("role") != "historical_regression_evidence_only_not_development_or_heldout":
        errors.append("historical Goal 4 evidence cannot be used as development or held-out data")
    return errors


def _protocol_snapshot_status(errors: list[str]) -> str:
    if not errors:
        return "implemented"
    if errors == ["quality leadership protocol source SHA mismatch"]:
        return "blocked"
    return "failed"


def _validate_protocol_frozen(payload: Mapping[str, Any] | None) -> list[str]:
    if payload is None:
        return ["protocol artifact is missing"]
    errors: list[str] = []
    if payload.get("status") != "frozen_before_heldout":
        errors.append("protocol status is not frozen_before_heldout")
    dataset = payload.get("new_quality_dataset")
    if not isinstance(dataset, Mapping):
        errors.append("new quality dataset manifest missing")
        return errors
    if dataset.get("schema") != QUALITY_LEADERSHIP_SPLIT_MANIFEST_SCHEMA:
        errors.append("new quality dataset schema mismatch")
    if dataset.get("state") != "frozen_before_heldout":
        errors.append("new quality dataset state is not frozen_before_heldout")
    for key in ("development_split_sha256", "held_out_split_sha256", "licenses", "dataset_revisions"):
        if not dataset.get(key):
            errors.append(f"new quality dataset {key} missing")
    if not isinstance(dataset.get("licenses"), Mapping) or not dataset.get("licenses"):
        errors.append("new quality dataset licenses must be a non-empty mapping")
    if not isinstance(dataset.get("dataset_revisions"), Mapping) or not dataset.get("dataset_revisions"):
        errors.append("new quality dataset dataset_revisions must be a non-empty mapping")
    if dataset.get("held_out_viewed") not in {False, "false"}:
        errors.append("held-out split must be unviewed at protocol freeze")
    development_split = dataset.get("development_split")
    held_out_split = dataset.get("held_out_split")
    split_errors, split_digests = _validate_quality_split_pair(
        development_split,
        held_out_split,
    )
    errors.extend(split_errors)
    expected_dev_digest = split_digests.get("development")
    expected_heldout_digest = split_digests.get("held_out")
    if expected_dev_digest and dataset.get("development_split_sha256") != expected_dev_digest:
        errors.append("new quality dataset development_split_sha256 mismatch")
    if expected_heldout_digest and dataset.get("held_out_split_sha256") != expected_heldout_digest:
        errors.append("new quality dataset held_out_split_sha256 mismatch")
    if dataset.get("revision") == FROZEN_V1_DATASET_REVISION:
        errors.extend(
            _validate_frozen_v1_development_split(
                development_split,
                declared_digest=dataset.get("development_split_sha256"),
                computed_digest=expected_dev_digest,
            )
        )
    return errors


def _validate_frozen_v1_development_split(
    split: Any,
    *,
    declared_digest: Any,
    computed_digest: str | None,
) -> list[str]:
    errors: list[str] = []
    if declared_digest != FROZEN_V1_DEVELOPMENT_SPLIT_SHA256:
        errors.append("frozen v1 development_split_sha256 differs from preregistered split")
    if computed_digest and computed_digest != FROZEN_V1_DEVELOPMENT_SPLIT_SHA256:
        errors.append("frozen v1 development split content differs from preregistered split")
    if not isinstance(split, Mapping):
        return errors
    if _as_int(split.get("case_count")) != FROZEN_V1_DEVELOPMENT_CASE_COUNT:
        errors.append("frozen v1 development split case_count changed")
    categories = split.get("categories")
    if dict(categories or {}) != FROZEN_V1_DEVELOPMENT_CATEGORIES:
        errors.append("frozen v1 development split categories changed")
    return errors


def _validate_frozen_protocol_against_development_evidence(
    results_payload: Mapping[str, Any] | None,
    *,
    expected_source_sha: str,
) -> list[str]:
    if not isinstance(results_payload, Mapping):
        return []
    if results_payload.get("source_sha") != expected_source_sha:
        return []
    metrics = results_payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return []
    analysis = metrics.get("category_improvement_analysis")
    if not isinstance(analysis, Mapping):
        return []
    ceiling = _as_int(analysis.get("improvement_ceiling_over_core"))
    target = QUALITY_THRESHOLDS["improved_categories_min"]
    if ceiling >= target:
        return []
    return [
        (
            "bounded development evidence proves frozen development split "
            f"category improvement ceiling below threshold: {ceiling} < {target}"
        )
    ]


def _validate_quality_split_pair(
    development_split: Any,
    held_out_split: Any,
) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    digests: dict[str, str] = {}
    if not isinstance(development_split, Mapping):
        errors.append("new quality dataset development_split manifest missing")
    else:
        errors.extend(
            _validate_quality_split(
                development_split,
                name="development",
                expected_role="development",
                require_unviewed=False,
            )
        )
        digests["development"] = _quality_split_digest(development_split)
    if not isinstance(held_out_split, Mapping):
        errors.append("new quality dataset held_out_split manifest missing")
    else:
        errors.extend(
            _validate_quality_split(
                held_out_split,
                name="held_out",
                expected_role="held_out",
                require_unviewed=True,
            )
        )
        digests["held_out"] = _quality_split_digest(held_out_split)
    if isinstance(development_split, Mapping) and isinstance(held_out_split, Mapping):
        development_ids = _split_fingerprints(development_split)
        held_out_ids = _split_fingerprints(held_out_split)
        overlap = sorted(development_ids & held_out_ids)
        if overlap:
            errors.append(
                "new quality dataset development/held-out overlap: "
                + ", ".join(overlap[:5])
            )
        forbidden_sources = {
            "benchmarks/goal4_quality_experiment_results.json",
            "full451",
            "untouched419",
            GOAL4_HISTORICAL_DECISION_SHA,
        }
        heldout_source = canonical_json_bytes(
            {
                "id": held_out_split.get("id"),
                "primary_sources": held_out_split.get("primary_sources"),
                "case_fingerprints": held_out_split.get("case_fingerprints"),
            }
        ).decode("utf-8")
        if any(source in heldout_source for source in forbidden_sources):
            errors.append("new quality held-out split reuses historical Goal 4 evidence")
    return errors, digests


def _validate_quality_split(
    split: Mapping[str, Any],
    *,
    name: str,
    expected_role: str,
    require_unviewed: bool,
) -> list[str]:
    errors: list[str] = []
    if split.get("role") != expected_role:
        errors.append(f"new quality dataset {name}_split role mismatch")
    case_count = _as_int(split.get("case_count"))
    if case_count <= 0:
        errors.append(f"new quality dataset {name}_split case_count missing")
    categories = split.get("categories")
    if not isinstance(categories, Mapping) or not categories:
        errors.append(f"new quality dataset {name}_split categories missing")
    primary_sources = split.get("primary_sources")
    if not isinstance(primary_sources, list) or not primary_sources:
        errors.append(f"new quality dataset {name}_split primary_sources missing")
    fingerprints = _split_fingerprints(split)
    if len(fingerprints) != case_count:
        errors.append(f"new quality dataset {name}_split fingerprint count mismatch")
    if require_unviewed and split.get("view_status") not in {"unopened", "not_opened"}:
        errors.append(f"new quality dataset {name}_split is not unopened")
    return errors


def _quality_split_digest(split: Mapping[str, Any]) -> str:
    digest_payload = {
        key: value
        for key, value in split.items()
        if key not in {"sha256", "digest", "generated_at"}
    }
    return sha256_bytes(canonical_json_bytes(digest_payload))


def _split_fingerprints(split: Mapping[str, Any]) -> set[str]:
    rows = split.get("case_fingerprints")
    if not isinstance(rows, list):
        return set()
    fingerprints: set[str] = set()
    for row in rows:
        if isinstance(row, str) and row:
            fingerprints.add(row)
        elif isinstance(row, Mapping) and row.get("fingerprint"):
            fingerprints.add(str(row["fingerprint"]))
    return fingerprints


def _validate_results(
    payload: Mapping[str, Any] | None,
    *,
    root: Path,
    expected_source_sha: str,
) -> list[str]:
    if payload is None:
        return [f"missing {DEFAULT_RESULTS_PATH.as_posix()}"]
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != QUALITY_LEADERSHIP_RESULTS_SCHEMA:
        errors.append("quality leadership results schema mismatch")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("quality leadership results source SHA mismatch")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("quality leadership results source manifest missing")
    else:
        errors.extend(validate_source_manifest(root, manifest, require_current_files=True))
    historical = payload.get("historical_goal4_failure")
    if isinstance(historical, Mapping) and historical.get("must_not_be_used_for_tuning") is not True:
        errors.append("results allow historical Goal 4 data for tuning")
    return errors


def _validate_agent_memory_diagnostic(
    payload: Mapping[str, Any] | None,
    *,
    expected_source_sha: str,
) -> list[str]:
    if payload is None:
        return [f"missing {DEFAULT_AGENT_MEMORY_DIAGNOSTIC_PATH.as_posix()}"]
    errors: list[str] = []
    if payload.get("schema") != "wavemind.agent_memory_advantage_benchmark.v1":
        errors.append("agent-memory diagnostic schema mismatch")
    if payload.get("status") != "pass":
        errors.append("agent-memory diagnostic did not pass")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("agent-memory diagnostic source SHA mismatch")
    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping):
        errors.append("agent-memory diagnostic protocol missing")
    else:
        if int(protocol.get("measurement_trials") or 0) < QUALITY_THRESHOLDS["measurement_runs_min"]:
            errors.append("agent-memory diagnostic has too few measurement trials")
        if not _same_float(protocol.get("confidence_level"), QUALITY_THRESHOLDS["confidence_level"]):
            errors.append("agent-memory diagnostic confidence level is not 0.95")
    return errors


def _metrics_from_agent_memory(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    core = _engine_row(payload, "WaveMind Core")
    memory_os = _engine_row(payload, "WaveMind + Memory OS")
    protocol = payload.get("protocol") if isinstance(payload.get("protocol"), Mapping) else {}
    paired = payload.get("paired_lift") if isinstance(payload.get("paired_lift"), Mapping) else {}
    categories = paired.get("categories") if isinstance(paired.get("categories"), Mapping) else {}
    improved = [
        category
        for category, interval in categories.items()
        if isinstance(interval, Mapping) and _compare(interval.get("lower"), 0.0, ">=") and float(interval.get("lower") or 0.0) > 0.0
    ]
    core_task = _float_or_none(core.get("task_success_rate"))
    memory_os_task = _float_or_none(memory_os.get("task_success_rate"))
    core_p95 = _float_or_none(core.get("p95_latency_ms"))
    memory_os_p95 = _float_or_none(memory_os.get("p95_latency_ms"))
    p95_delta = (
        memory_os_p95 - core_p95
        if memory_os_p95 is not None and core_p95 is not None
        else None
    )
    p95_ratio = p95_delta / core_p95 if p95_delta is not None and core_p95 and core_p95 > 0 else None
    confidence_intervals = {
        "task_success": memory_os.get("task_success_ci95"),
        "stale_error": memory_os.get("stale_error_ci95"),
        "context_reduction": memory_os.get("context_budget_saved_ci95"),
        "paired_overall": paired.get("overall_task_success"),
        "paired_categories": categories,
    }
    metrics: dict[str, Any] = {
        "measurement_runs": protocol.get("measurement_trials"),
        "confidence_level": protocol.get("confidence_level"),
        "confidence_intervals": confidence_intervals,
        "memory_os_uplift_over_core": (
            memory_os_task - core_task
            if memory_os_task is not None and core_task is not None
            else None
        ),
        "improved_category_count": len(improved),
        "improved_categories": sorted(improved),
        "context_reduction": _float_or_none(memory_os.get("context_budget_saved")),
        "stale_contradiction_error_rate": _float_or_none(memory_os.get("stale_error_rate")),
        "p95_overhead_ms": p95_delta,
        "p95_overhead_ratio": p95_ratio,
        "controlled_core_task_success": core_task,
        "controlled_memory_os_task_success": memory_os_task,
        "category_improvement_analysis": _category_improvement_analysis(
            core,
            memory_os,
            categories,
        ),
    }
    return metrics


def _category_improvement_analysis(
    core: Mapping[str, Any],
    memory_os: Mapping[str, Any],
    paired_categories: Mapping[str, Any],
) -> dict[str, Any]:
    core_success = (
        core.get("category_success")
        if isinstance(core.get("category_success"), Mapping)
        else {}
    )
    memory_os_success = (
        memory_os.get("category_success")
        if isinstance(memory_os.get("category_success"), Mapping)
        else {}
    )
    categories = sorted(
        set(str(category) for category in core_success)
        | set(str(category) for category in memory_os_success)
        | set(str(category) for category in paired_categories)
    )
    improved: list[str] = []
    improvable: list[str] = []
    baseline_ceiling_categories: list[str] = []
    details: dict[str, dict[str, Any]] = {}
    for category in categories:
        core_value = _float_or_none(core_success.get(category))
        memory_os_value = _float_or_none(memory_os_success.get(category))
        interval = paired_categories.get(category)
        lower = (
            _float_or_none(interval.get("lower"))
            if isinstance(interval, Mapping)
            else None
        )
        if lower is not None and lower > 0.0:
            improved.append(category)
        is_improvable = core_value is None or core_value < 1.0
        if is_improvable:
            improvable.append(category)
            reason = "improvable"
        else:
            baseline_ceiling_categories.append(category)
            reason = "core_already_at_ceiling"
        details[category] = {
            "core_success": core_value,
            "memory_os_success": memory_os_value,
            "paired_lift_lower": lower,
            "improvable_over_core": is_improvable,
            "improved": category in improved,
            "reason": reason,
        }
    target = QUALITY_THRESHOLDS["improved_categories_min"]
    ceiling = len(improvable)
    return {
        "target": target,
        "observed_improved_categories": improved,
        "improvement_ceiling_over_core": ceiling,
        "baseline_ceiling_categories": baseline_ceiling_categories,
        "category_details": details,
        "methodology_status": (
            "blocked_unsatisfiable_without_split_change_or_baseline_degradation"
            if categories and ceiling < target
            else "measurable"
        ),
        "claim_boundary": (
            "A category where Core already has 1.0 success cannot show a "
            "strictly positive Memory OS-over-Core lift without changing the "
            "frozen split or degrading the baseline."
        ),
    }


def _development_blocker_taxonomy(
    metrics: Mapping[str, Any],
    gate_errors: list[str],
) -> dict[str, Any]:
    category_analysis = metrics.get("category_improvement_analysis")
    blockers: list[dict[str, Any]] = []
    if (
        isinstance(category_analysis, Mapping)
        and _as_int(category_analysis.get("improvement_ceiling_over_core"))
        < QUALITY_THRESHOLDS["improved_categories_min"]
    ):
        blockers.append(
            {
                "id": "category_improvement_ceiling",
                "status": "blocked",
                "reason": (
                    "the frozen development split cannot demonstrate four "
                    "strictly positive category improvements over Core because "
                    "Core is already perfect in some categories"
                ),
                "analysis": category_analysis,
                "allowed_next_step": (
                    "pre-register a genuinely new independent protocol/split "
                    "or record this architecture lane as blocked; do not tune "
                    "or refreeze using viewed results"
                ),
            }
        )
    if "LongMemEval-V2 quality gate has not been run on this protocol" in gate_errors:
        blockers.append(
            {
                "id": "longmemeval_v2_quality_not_run",
                "status": "blocked",
                "reason": "public-quality gate is absent for this protocol",
                "allowed_next_step": (
                    "run only after bounded development go/no-go passes and "
                    "the user explicitly approves any heavy workload"
                ),
            }
        )
    return {
        "status": "blocked" if gate_errors else "clear",
        "candidate": "candidate-1",
        "gate_errors": list(gate_errors),
        "blockers": blockers,
        "held_out_policy": (
            "not_opened; remains forbidden while development gate is blocked"
        ),
    }


def _competitors_from_agent_memory(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    rows: list[dict[str, Any]] = []
    family_by_engine = {
        "Chroma static": "static_chroma_or_qdrant",
        "Qdrant static": "static_chroma_or_qdrant",
        "Mem0 OSS": "mem0_oss",
        "LangMem / LangGraph": "langmem_or_langgraph",
        "LangGraph persistent memory": "langmem_or_langgraph",
    }
    for row in payload.get("results") or []:
        if not isinstance(row, Mapping):
            continue
        engine = str(row.get("engine") or "")
        family = family_by_engine.get(engine)
        if not family:
            continue
        eligible = row.get("eligible_for_comparison") is True
        base_embedding_comparable = (
            row.get("embedding_comparable") is True
            and row.get("same_embedding_as_wavemind") is True
        )
        runtime_proof = row.get("embedding_runtime_proof")
        embedding_comparable = base_embedding_comparable and _same_embedding_runtime_proof(
            engine,
            runtime_proof,
        )
        rows.append(
            {
                "engine": engine,
                "family": family,
                "status": row.get("status", "pass"),
                "eligible_for_comparison": eligible,
                "embedding_comparable": embedding_comparable,
                "embedding_runtime_proof": runtime_proof,
                "simulated": False,
                "task_success_rate": row.get("task_success_rate"),
                "p95_latency_ms": row.get("p95_latency_ms"),
                "reason": (
                    row.get("reason")
                    if eligible and embedding_comparable
                    else _competitor_non_comparable_reason(
                        engine,
                        base_embedding_comparable=base_embedding_comparable,
                        runtime_proof=runtime_proof,
                    )
                ),
            }
        )
    for row in payload.get("skipped") or []:
        if not isinstance(row, Mapping):
            continue
        engine = str(row.get("engine") or "")
        family = family_by_engine.get(engine)
        if not family:
            continue
        rows.append(
            {
                "engine": engine,
                "family": family,
                "status": "skipped",
                "eligible_for_comparison": False,
                "embedding_comparable": False,
                "simulated": False,
                "reason": row.get("reason"),
            }
        )
    return rows


def _same_embedding_runtime_proof(
    engine: str,
    runtime_proof: Any,
) -> bool:
    if engine != "Mem0 OSS":
        return True
    if not isinstance(runtime_proof, Mapping):
        return False
    return (
        runtime_proof.get("provider") == "wavemind-shared"
        and runtime_proof.get("kind") == "hash"
        and _as_int(runtime_proof.get("vector_dim")) == 384
        and runtime_proof.get("matches_shared_encoder") is True
        and runtime_proof.get("used_for_ingest_and_search") is True
        and _as_int(runtime_proof.get("embed_calls")) >= _as_int(
            runtime_proof.get("expected_min_calls")
        )
    )


def _competitor_non_comparable_reason(
    engine: str,
    *,
    base_embedding_comparable: bool,
    runtime_proof: Any,
) -> str:
    if not base_embedding_comparable:
        return "competitor row lacks same-embedding comparability proof"
    if engine == "Mem0 OSS" and not _same_embedding_runtime_proof(engine, runtime_proof):
        return "Mem0 row lacks runtime proof that ingest/search used the shared hash-384 encoder"
    return "competitor row is not eligible for comparison"


def _validate_safe_product(
    payload: Mapping[str, Any] | None,
    *,
    root: Path,
    expected_source_sha: str,
) -> list[str]:
    if payload is None:
        return ["safe product artifact missing"]
    from .safe_product_admission import validate_safe_product_artifact

    return validate_safe_product_artifact(
        payload,
        project_root=root,
        expected_source_sha=expected_source_sha,
    )


def _validate_workspace_experience(
    payload: Mapping[str, Any] | None,
    *,
    expected_source_sha: str,
) -> list[str]:
    if payload is None:
        return ["workspace experience artifact missing"]
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != "wavemind.workspace_experience_admission.v1":
        errors.append("workspace experience admission schema mismatch")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("workspace experience source SHA mismatch")
    if payload.get("status") != "admitted" or payload.get("admitted") is not True:
        errors.append("workspace experience status is not admitted")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("workspace experience rows are missing")
    elif any(
        isinstance(row, Mapping) and row.get("status") in {"blocked", "failed", "required_current"}
        for row in rows
    ):
        errors.append("workspace experience contains blocked, failed, or required-current rows")
    return errors


def _load_per_query_header(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, f"missing {DEFAULT_PER_QUERY_PATH.as_posix()}"
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError) as exc:
        return None, f"cannot read per-query header: {exc}"
    try:
        payload = json.loads(first)
    except json.JSONDecodeError as exc:
        return None, f"per-query header is invalid JSON: {exc}"
    return payload if isinstance(payload, dict) else None, None


def _validate_per_query(
    payload: Mapping[str, Any] | None,
    load_error: str | None,
    *,
    expected_source_sha: str,
) -> list[str]:
    errors: list[str] = []
    if load_error:
        errors.append(load_error)
    if payload is None:
        return errors or ["per-query header missing"]
    if payload.get("schema") != QUALITY_LEADERSHIP_PER_QUERY_SCHEMA:
        errors.append("per-query schema mismatch")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("per-query source SHA mismatch")
    return errors


def _metric_row(
    row_id: str,
    requirement: str,
    payload: Mapping[str, Any] | None,
    key: str,
    *,
    target: str,
    artifact_errors: list[str] | None = None,
) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, Mapping) else None
    status = "blocked"
    if not artifact_errors and isinstance(value, Mapping) and value.get("status") == target:
        status = "implemented"
    return _row(
        row_id,
        requirement,
        status,
        DEFAULT_RESULTS_PATH.as_posix(),
        "tests/test_quality_leadership_admission.py",
        details=_with_artifact_errors(
            {"observed": value, "target_status": target},
            artifact_errors,
        ),
    )


def _threshold_row(
    row_id: str,
    requirement: str,
    payload: Mapping[str, Any] | None,
    metric: str,
    target: float,
    *,
    comparison: str,
    extra_details_key: str | None = None,
    artifact_errors: list[str] | None = None,
) -> dict[str, Any]:
    metrics = payload.get("metrics") if isinstance(payload, Mapping) else {}
    value = metrics.get(metric) if isinstance(metrics, Mapping) else None
    passed = not artifact_errors and _compare(value, target, comparison)
    details: dict[str, Any] = {
        "metric": metric,
        "observed": value,
        "target": target,
        "comparison": comparison,
    }
    if extra_details_key and isinstance(metrics, Mapping):
        extra = metrics.get(extra_details_key)
        if extra is not None:
            details[extra_details_key] = extra
    return _row(
        row_id,
        requirement,
        "implemented" if passed else "blocked",
        DEFAULT_RESULTS_PATH.as_posix(),
        "tests/test_quality_leadership_admission.py",
        details=_with_artifact_errors(details, artifact_errors),
    )


def _artifact_dependent_status(
    artifact_errors: list[str] | None,
    status: str,
) -> str:
    if artifact_errors and status == "implemented":
        return "blocked"
    return status


def _with_artifact_errors(
    details: Mapping[str, Any],
    artifact_errors: list[str] | None,
) -> dict[str, Any]:
    payload = dict(details)
    if artifact_errors:
        payload["artifact_errors"] = list(artifact_errors)
    return payload


def _latency_row(
    payload: Mapping[str, Any] | None,
    *,
    artifact_errors: list[str] | None = None,
) -> dict[str, Any]:
    metrics = payload.get("metrics") if isinstance(payload, Mapping) else {}
    if not isinstance(metrics, Mapping):
        metrics = {}
    delta = metrics.get("p95_overhead_ms")
    ratio = metrics.get("p95_overhead_ratio")
    passed = (
        not artifact_errors
        and _compare(delta, QUALITY_THRESHOLDS["p95_overhead_ms_max"], "<=")
        and _compare(
            ratio,
            QUALITY_THRESHOLDS["p95_overhead_ratio_max"],
            "<=",
        )
    )
    return _row(
        "latency-budget",
        "p95 overhead is below both absolute and relative budgets.",
        "implemented" if passed else "blocked",
        DEFAULT_RESULTS_PATH.as_posix(),
        "tests/test_quality_leadership_admission.py",
        details=_with_artifact_errors(
            {
                "p95_overhead_ms": delta,
                "p95_overhead_ratio": ratio,
                "targets": {
                    "p95_overhead_ms": QUALITY_THRESHOLDS["p95_overhead_ms_max"],
                    "p95_overhead_ratio": QUALITY_THRESHOLDS["p95_overhead_ratio_max"],
                },
            },
            artifact_errors,
        ),
    )


def _dynamic_public_status(payload: Mapping[str, Any] | None) -> str:
    details = _dynamic_public_details(payload)
    if details["locomo_no_regression"] and details["longmemeval_no_regression"] and details["positive_dynamic_categories"] >= 2:
        return "implemented"
    return "blocked"


def _dynamic_public_details(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    metrics = payload.get("metrics") if isinstance(payload, Mapping) else {}
    if not isinstance(metrics, Mapping):
        metrics = {}
    return {
        "locomo_no_regression": metrics.get("locomo_no_significant_regression") is True,
        "longmemeval_no_regression": metrics.get("longmemeval_no_significant_regression") is True,
        "positive_dynamic_categories": int(metrics.get("positive_dynamic_category_count") or 0),
    }


def _competitor_status(payload: Mapping[str, Any] | None) -> str:
    details = _competitor_details(payload)
    return (
        "implemented"
        if not details["missing"]
        and not details["simulated"]
        and not details["non_comparable"]
        else "blocked"
    )


def _competitor_details(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = payload.get("competitor_runs") if isinstance(payload, Mapping) else []
    observed: set[str] = set()
    simulated: list[str] = []
    non_comparable: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            family = str(row.get("family") or "")
            if (
                row.get("status") == "pass"
                and row.get("simulated") is not True
                and row.get("eligible_for_comparison") is True
                and row.get("embedding_comparable") is True
            ):
                observed.add(family)
            elif row.get("status") == "pass" and family:
                non_comparable.append(family)
            if row.get("simulated") is True:
                simulated.append(family or str(row.get("engine") or "unknown"))
    missing = sorted(REQUIRED_LOCAL_COMPETITORS - observed)
    return {
        "observed": sorted(observed),
        "missing": missing,
        "simulated": simulated,
        "non_comparable": sorted(set(non_comparable)),
    }


def _confidence_status(payload: Mapping[str, Any] | None) -> str:
    details = _confidence_details(payload)
    return "implemented" if not details["errors"] else "blocked"


def _confidence_details(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"errors": ["results artifact missing"]}
    runs = int(payload.get("measurement_runs") or 0)
    confidence = payload.get("confidence_level")
    errors: list[str] = []
    if runs < QUALITY_THRESHOLDS["measurement_runs_min"]:
        errors.append("measurement runs below required minimum")
    if not _same_float(confidence, QUALITY_THRESHOLDS["confidence_level"]):
        errors.append("confidence level is not 0.95")
    if not payload.get("confidence_intervals"):
        errors.append("confidence intervals missing")
    return {"measurement_runs": runs, "confidence_level": confidence, "errors": errors}


def _fingerprint_status(payload: Mapping[str, Any] | None) -> str:
    return "implemented" if not _fingerprint_details(payload)["errors"] else "blocked"


def _fingerprint_details(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"errors": ["results artifact missing"]}
    fingerprints = payload.get("verdict_fingerprints")
    errors: list[str] = []
    if not isinstance(fingerprints, list) or len(fingerprints) < QUALITY_THRESHOLDS["verdict_fingerprint_repetitions"]:
        errors.append("not enough verdict fingerprints")
        return {"fingerprints": fingerprints, "errors": errors}
    first = fingerprints[0]
    if any(value != first for value in fingerprints[: QUALITY_THRESHOLDS["verdict_fingerprint_repetitions"]]):
        errors.append("verdict fingerprints are not identical")
    return {"fingerprints": fingerprints, "errors": errors}


def _row(
    row_id: str,
    requirement: str,
    status: str,
    artifact: str,
    test: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": row_id,
        "requirement": requirement,
        "status": status,
        "artifact": artifact,
        "test": test,
    }
    if details is not None:
        row["details"] = details
    return row


def _engine_row(payload: Mapping[str, Any], engine: str) -> dict[str, Any]:
    for row in payload.get("results") or []:
        if isinstance(row, Mapping) and row.get("engine") == engine:
            return dict(row)
    return {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _next_actions(rows: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    statuses = {row["id"]: row["status"] for row in rows}
    if statuses.get("protocol-frozen-before-heldout") != "implemented":
        actions.append("Freeze a new independent quality-leadership development/held-out protocol before tuning.")
    if statuses.get("development-go-no-go") != "implemented":
        actions.append("Run a bounded development benchmark and stop unless the go/no-go gate passes.")
    if statuses.get("real-local-competitors") != "implemented":
        actions.append("Run real local Chroma/Qdrant, Mem0 OSS, and LangMem/LangGraph comparators on the same protocol.")
    if statuses.get("safe-product-current") != "implemented" or statuses.get("workspace-experience-current") != "implemented":
        actions.append("Use exact-current CI artifacts for Safe Product and Workspace Experience on the final SHA.")
    if statuses.get("heldout-opened-once") != "implemented":
        actions.append("Open the new held-out split exactly once only after protocol freeze and dev go/no-go.")
    return actions


def _compare(value: Any, target: float, comparison: str) -> bool:
    try:
        observed = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(observed):
        return False
    if comparison == ">=":
        return observed >= target
    if comparison == "<=":
        return observed <= target
    raise ValueError(f"unsupported comparison: {comparison}")


def _same_float(value: Any, expected: float) -> bool:
    try:
        actual = float(value)
    except (TypeError, ValueError):
        return False
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _repository_commit(root: Path) -> str:
    return repository_commit(root)


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _artifact_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
