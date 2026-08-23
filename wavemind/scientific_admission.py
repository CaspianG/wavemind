from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from statistics import quantiles
from typing import Any, Mapping, Sequence

from .evaluation_statistics import paired_cluster_bootstrap
from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    sha256_bytes,
    validate_artifact_integrity,
)
from .scientific_protocol import (
    GIT_SHA_RE,
    REQUIRED_BASELINES,
    REQUIRED_BENCHMARK_FAMILIES,
    REQUIRED_CANDIDATES,
    load_scientific_protocol,
    validate_scientific_protocol,
)


SCIENTIFIC_RUN_SCHEMA = "wavemind.scientific_memory_run.v1"
SCIENTIFIC_ADMISSION_SCHEMA = "wavemind.scientific_memory_admission.v1"
INDEPENDENT_VERIFIERS = {"test", "tool", "environment", "operator"}
MANDATORY_CONTROL_FIELDS = {
    "model_id",
    "model_revision",
    "prompt_bytes",
    "prompt_sha256",
    "embedding_model_id",
    "embedding_model_revision",
    "seed_list",
    "token_budget",
    "hardware_inventory",
    "runtime_lock_sha256",
    "case_order_sha256",
    "latency_budget_ms",
}
REAL_BASELINE_PACKAGES = {
    "mem0-oss": "mem0ai",
    "langgraph": "langgraph",
    "chroma": "chromadb",
    "qdrant-local": "qdrant-client",
}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _number(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _check(
    check_id: str,
    passed: bool,
    *,
    evidence: Any,
    target: Any,
    issue: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "fail",
        "evidence": evidence,
        "target": target,
        "issue": "" if passed else issue,
    }


def _p95(values: Sequence[float]) -> float:
    if not values:
        return float("inf")
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=100, method="inclusive")[94])


def _controls_digest(controls: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(controls)))


def validate_scientific_run(
    payload: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCIENTIFIC_RUN_SCHEMA:
        errors.append("scientific run schema is invalid")
    if payload.get("phase") != "held-out-admission":
        errors.append("scientific run is not held-out admission evidence")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("scientific run source_sha does not match exact admission SHA")
    if payload.get("protocol_digest") != protocol.get("protocol_digest"):
        errors.append("scientific run protocol digest mismatch")
    candidate_id = payload.get("candidate_id")
    if candidate_id not in REQUIRED_CANDIDATES:
        errors.append("scientific run candidate was not preregistered")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("scientific run_id is missing")
    if not isinstance(payload.get("seed"), int):
        errors.append("scientific run seed must be an integer")

    controls = payload.get("controls")
    if not isinstance(controls, Mapping):
        errors.append("scientific run controls are missing")
    else:
        missing_controls = sorted(MANDATORY_CONTROL_FIELDS - set(controls))
        if missing_controls:
            errors.append(
                "scientific run controls are incomplete: "
                + ", ".join(missing_controls)
            )
        for field in ("prompt_sha256", "runtime_lock_sha256", "case_order_sha256"):
            if field in controls and not _is_sha256(controls[field]):
                errors.append(f"scientific control {field} is not sha256")
        if controls.get("seed_list") != sorted(controls.get("seed_list") or []):
            errors.append("scientific control seed_list must be sorted")

    baselines = payload.get("baselines_executed")
    if not isinstance(baselines, list) or set(baselines) != REQUIRED_BASELINES:
        errors.append("scientific run did not execute the exact frozen baseline set")
    packages = payload.get("package_metadata")
    if not isinstance(packages, Mapping):
        errors.append("scientific run package metadata is missing")
    else:
        for baseline_id, package_name in REAL_BASELINE_PACKAGES.items():
            metadata = packages.get(baseline_id)
            if not isinstance(metadata, Mapping):
                errors.append(f"real baseline package metadata missing: {baseline_id}")
                continue
            if metadata.get("package") != package_name:
                errors.append(f"real baseline package identity mismatch: {baseline_id}")
            version = metadata.get("version")
            if not isinstance(version, str) or not version or version == "unknown":
                errors.append(f"real baseline exact version missing: {baseline_id}")
            if baseline_id in {"mem0-oss", "langgraph"} and not GIT_SHA_RE.fullmatch(
                str(metadata.get("source_revision") or "")
            ):
                errors.append(f"real baseline source revision missing: {baseline_id}")
            if metadata.get("execution") != "real-local-package":
                errors.append(f"real baseline was not executed locally: {baseline_id}")

    rows = payload.get("raw_rows")
    if not isinstance(rows, list) or not rows:
        errors.append("scientific run has no raw per-case evidence")
        return errors
    for index, row in enumerate(rows):
        prefix = f"raw row {index}"
        if not isinstance(row, Mapping):
            errors.append(f"{prefix} is invalid")
            continue
        if row.get("benchmark_family") not in REQUIRED_BENCHMARK_FAMILIES:
            errors.append(f"{prefix} benchmark family is invalid")
        if not str(row.get("case_id") or ""):
            errors.append(f"{prefix} case_id is missing")
        if _number(row.get("full_context_tokens"), default=-1.0) <= 0:
            errors.append(f"{prefix} full_context_tokens must be positive")
        verification = row.get("verification")
        if not isinstance(verification, Mapping):
            errors.append(f"{prefix} independent verification is missing")
        else:
            if verification.get("source") not in INDEPENDENT_VERIFIERS:
                errors.append(f"{prefix} verifier is not independent")
            if not _is_sha256(verification.get("receipt_digest")):
                errors.append(f"{prefix} influence receipt digest is invalid")
            if not _is_sha256(verification.get("evidence_digest")):
                errors.append(f"{prefix} verifier evidence digest is invalid")
        arms = row.get("arms")
        required_arms = REQUIRED_BASELINES | {str(candidate_id)}
        if not isinstance(arms, Mapping) or set(arms) != required_arms:
            errors.append(f"{prefix} does not contain every frozen arm")
            continue
        for arm_id, arm in arms.items():
            if not isinstance(arm, Mapping):
                errors.append(f"{prefix} arm is invalid: {arm_id}")
                continue
            success = _number(arm.get("task_success"), default=-1.0)
            if not 0.0 <= success <= 1.0:
                errors.append(f"{prefix} task_success is invalid: {arm_id}")
            for field in (
                "repeated_errors",
                "stale_or_contradiction_errors",
                "false_verified_promotions",
                "context_tokens",
                "runtime_ms",
            ):
                if _number(arm.get(field), default=-1.0) < 0:
                    errors.append(f"{prefix} {field} is invalid: {arm_id}")

    ablations = payload.get("ablation_rows")
    if not isinstance(ablations, list):
        errors.append("scientific run ablation rows are missing")
    else:
        required_ablations = set(protocol["evaluation"]["required_ablations"])
        seen = {
            str(row.get("ablation_id"))
            for row in ablations
            if isinstance(row, Mapping)
        }
        if seen != required_ablations:
            errors.append("scientific run ablation set is incomplete or changed")
        for index, row in enumerate(ablations):
            if not isinstance(row, Mapping):
                errors.append(f"ablation row {index} is invalid")
                continue
            if row.get("benchmark_family") not in REQUIRED_BENCHMARK_FAMILIES:
                errors.append(f"ablation row {index} benchmark family is invalid")
            if not str(row.get("case_id") or ""):
                errors.append(f"ablation row {index} case_id is missing")
            for field in ("with_component_success", "without_component_success"):
                value = _number(row.get(field), default=-1.0)
                if not 0.0 <= value <= 1.0:
                    errors.append(f"ablation row {index} {field} is invalid")
    return errors


def _strongest_baseline(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, float]]:
    totals: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for baseline_id in REQUIRED_BASELINES:
            totals[baseline_id].append(_number(row["arms"][baseline_id]["task_success"]))
    means = {
        baseline_id: sum(values) / len(values)
        for baseline_id, values in totals.items()
        if values
    }
    strongest = min(
        (baseline_id for baseline_id in means),
        key=lambda baseline_id: (-means[baseline_id], baseline_id),
    )
    return strongest, means


def _candidate_metrics(
    candidate_id: str,
    runs: Sequence[Mapping[str, Any]],
    *,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [row for run in runs for row in run["raw_rows"]]
    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["benchmark_family"])].append(row)
    family_results: dict[str, Any] = {}
    for family_id in sorted(by_family):
        family_rows = by_family[family_id]
        strongest, baseline_means = _strongest_baseline(family_rows)
        paired_rows = [
            {
                "case_cluster": str(row["case_id"]),
                "baseline": _number(row["arms"][strongest]["task_success"]),
                "candidate": _number(row["arms"][candidate_id]["task_success"]),
            }
            for row in family_rows
        ]
        interval = paired_cluster_bootstrap(
            paired_rows,
            cluster_key="case_cluster",
            baseline_key="baseline",
            treatment_key="candidate",
            repeats=int(protocol["evaluation"]["bootstrap_repeats"]),
            seed=int(protocol["evaluation"]["bootstrap_seed"]),
            confidence_level=float(protocol["evaluation"]["confidence_level"]),
        )
        category_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for row in family_rows:
            category_pairs[str(row.get("category") or "uncategorized")].append(
                (
                    _number(row["arms"][strongest]["task_success"]),
                    _number(row["arms"][candidate_id]["task_success"]),
                )
            )
        improved_categories = sorted(
            category
            for category, pairs in category_pairs.items()
            if sum(candidate - baseline for baseline, candidate in pairs) / len(pairs)
            > 0.0
        )
        family_results[family_id] = {
            "strongest_baseline": strongest,
            "baseline_task_success_means": baseline_means,
            "paired_uplift": interval,
            "improved_categories": improved_categories,
            "raw_case_rows": len(family_rows),
        }

    comparator_by_family = {
        family: result["strongest_baseline"]
        for family, result in family_results.items()
    }
    baseline_repeated = 0.0
    candidate_repeated = 0.0
    stale_errors = 0.0
    false_promotions = 0.0
    candidate_context = 0.0
    full_context = 0.0
    runtimes: list[float] = []
    for row in rows:
        family = str(row["benchmark_family"])
        baseline_arm = row["arms"][comparator_by_family[family]]
        candidate_arm = row["arms"][candidate_id]
        baseline_repeated += _number(baseline_arm["repeated_errors"])
        candidate_repeated += _number(candidate_arm["repeated_errors"])
        stale_errors += _number(candidate_arm["stale_or_contradiction_errors"])
        false_promotions += _number(candidate_arm["false_verified_promotions"])
        candidate_context += _number(candidate_arm["context_tokens"])
        full_context += _number(row["full_context_tokens"])
        runtimes.append(_number(candidate_arm["runtime_ms"], default=float("inf")))
    repeated_reduction = (
        (baseline_repeated - candidate_repeated) / baseline_repeated
        if baseline_repeated > 0
        else 0.0
    )
    stale_rate = stale_errors / len(rows) if rows else 1.0
    context_reduction = (
        1.0 - candidate_context / full_context if full_context > 0 else 0.0
    )
    latency_budget = min(
        _number(run["controls"]["latency_budget_ms"], default=0.0) for run in runs
    )
    p95_runtime = _p95(runtimes)

    run_reproducibility: list[dict[str, Any]] = []
    for run in runs:
        positive = 0
        available = 0
        run_rows = run["raw_rows"]
        for family in sorted(REQUIRED_BENCHMARK_FAMILIES - {"longmemeval-v2"}):
            selected = [row for row in run_rows if row["benchmark_family"] == family]
            if len({str(row["case_id"]) for row in selected}) < 2:
                continue
            available += 1
            strongest, _ = _strongest_baseline(selected)
            interval = paired_cluster_bootstrap(
                [
                    {
                        "case": str(row["case_id"]),
                        "b": _number(row["arms"][strongest]["task_success"]),
                        "c": _number(row["arms"][candidate_id]["task_success"]),
                    }
                    for row in selected
                ],
                cluster_key="case",
                baseline_key="b",
                treatment_key="c",
                repeats=int(protocol["evaluation"]["bootstrap_repeats"]),
                seed=int(protocol["evaluation"]["bootstrap_seed"]),
                confidence_level=float(protocol["evaluation"]["confidence_level"]),
            )
            positive += int(interval["ci_lower"] > 0.0)
        run_reproducibility.append(
            {
                "run_id": run["run_id"],
                "available_non_longmem_families": available,
                "positive_uplift_lcb_families": positive,
                "passed": available == 3 and positive >= 2,
            }
        )

    positive_families = sum(
        result["paired_uplift"]["ci_lower"] > 0.0
        for result in family_results.values()
    )
    longmem = family_results.get("longmemeval-v2", {})
    longmem_uplift = _number((longmem.get("paired_uplift") or {}).get("mean_difference"))
    longmem_categories = len(longmem.get("improved_categories") or [])
    improved_families = {
        family
        for family, result in family_results.items()
        if result["paired_uplift"]["mean_difference"] > 0.0
    }
    required_ablations = set(protocol["evaluation"]["required_ablations"])
    ablation_coverage: dict[str, list[str]] = {}
    for family in sorted(improved_families):
        present = {
            str(row["ablation_id"])
            for run in runs
            for row in run["ablation_rows"]
            if row["benchmark_family"] == family
        }
        ablation_coverage[family] = sorted(present)
    complete_ablations = all(
        set(present) == required_ablations for present in ablation_coverage.values()
    )
    return {
        "family_results": family_results,
        "positive_uplift_lcb_families": positive_families,
        "longmemeval_v2_uplift": longmem_uplift,
        "longmemeval_v2_improved_categories": longmem_categories,
        "repeated_error_reduction": repeated_reduction,
        "stale_or_contradiction_error_rate": stale_rate,
        "false_verified_promotions": int(false_promotions),
        "context_reduction_vs_full_context": context_reduction,
        "runtime_p95_ms": p95_runtime,
        "runtime_budget_ms": latency_budget,
        "run_reproducibility": run_reproducibility,
        "ablation_coverage": ablation_coverage,
        "complete_ablation_coverage": complete_ablations,
        "raw_case_rows": len(rows),
    }


def evaluate_scientific_memory_admission(
    run_payloads: Sequence[Mapping[str, Any]],
    *,
    protocol_path: str | Path,
    project_root: str | Path,
    expected_source_sha: str,
) -> dict[str, Any]:
    protocol = load_scientific_protocol(protocol_path)
    protocol_errors = validate_scientific_protocol(protocol, project_root=project_root)
    source_sha_valid = bool(GIT_SHA_RE.fullmatch(expected_source_sha))
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    run_errors: dict[str, list[str]] = {}
    for index, run in enumerate(run_payloads):
        errors = validate_scientific_run(
            run,
            protocol=protocol,
            expected_source_sha=expected_source_sha,
        )
        key = str(run.get("run_id") or f"run-{index}")
        if errors:
            run_errors[key] = errors
        candidate_id = str(run.get("candidate_id") or "")
        if candidate_id in REQUIRED_CANDIDATES:
            groups[candidate_id].append(run)

    candidate_results: dict[str, Any] = {}
    gates = protocol["admission_gates"]
    for candidate_id in REQUIRED_CANDIDATES:
        runs = groups.get(candidate_id, [])
        structural_checks = [
            _check(
                "three-reproducible-runs",
                len(runs) == protocol["evaluation"]["required_reproducible_runs"]
                and len({run.get("run_id") for run in runs}) == len(runs)
                and len({run.get("seed") for run in runs}) == len(runs),
                evidence={
                    "runs": len(runs),
                    "run_ids": [run.get("run_id") for run in runs],
                    "seeds": [run.get("seed") for run in runs],
                },
                target=protocol["evaluation"]["required_reproducible_runs"],
                issue="candidate does not have exactly three unique reproducible runs",
            )
        ]
        valid_group = (
            not protocol_errors
            and source_sha_valid
            and len(runs) == 3
            and all(str(run.get("run_id")) not in run_errors for run in runs)
        )
        if valid_group:
            controls = {_controls_digest(run["controls"]) for run in runs}
            non_longmem_coverage = all(
                REQUIRED_BENCHMARK_FAMILIES - {"longmemeval-v2"}
                <= {str(row["benchmark_family"]) for row in run["raw_rows"]}
                for run in runs
            )
            longmem_full_runs = sum(bool(run.get("longmemeval_v2_full_run")) for run in runs)
            union_families = {
                str(row["benchmark_family"])
                for run in runs
                for row in run["raw_rows"]
            }
            structural_checks.extend(
                [
                    _check(
                        "identical-common-controls",
                        len(controls) == 1,
                        evidence=sorted(controls),
                        target="one canonical controls digest",
                        issue="common controls changed between reproducible runs",
                    ),
                    _check(
                        "official-family-coverage",
                        non_longmem_coverage
                        and union_families == REQUIRED_BENCHMARK_FAMILIES,
                        evidence=sorted(union_families),
                        target=sorted(REQUIRED_BENCHMARK_FAMILIES),
                        issue="official benchmark family coverage is incomplete",
                    ),
                    _check(
                        "one-shot-longmemeval-v2",
                        longmem_full_runs == 1,
                        evidence=longmem_full_runs,
                        target=1,
                        issue="full LongMemEval-V2 must be executed exactly once",
                    ),
                ]
            )
        else:
            structural_checks.append(
                _check(
                    "valid-run-evidence",
                    False,
                    evidence={"protocol_errors": protocol_errors, "run_errors": run_errors},
                    target="all preregistered run artifacts valid",
                    issue="candidate run evidence is missing or invalid",
                )
            )

        metrics: dict[str, Any] = {}
        metric_checks: list[dict[str, Any]] = []
        if valid_group and all(check["passed"] for check in structural_checks):
            metrics = _candidate_metrics(candidate_id, runs, protocol=protocol)
            metric_checks = [
                _check(
                    "positive-uplift-families",
                    metrics["positive_uplift_lcb_families"]
                    >= gates["independent_benchmark_families_with_positive_uplift_lcb"],
                    evidence=metrics["positive_uplift_lcb_families"],
                    target=gates[
                        "independent_benchmark_families_with_positive_uplift_lcb"
                    ],
                    issue="positive paired uplift is not proven on two benchmark families",
                ),
                _check(
                    "three-run-reproducibility",
                    all(row["passed"] for row in metrics["run_reproducibility"]),
                    evidence=metrics["run_reproducibility"],
                    target="every run proves positive LCB on >=2 non-LongMemEval families",
                    issue="positive uplift did not reproduce across all three runs",
                ),
                _check(
                    "longmemeval-v2-uplift",
                    metrics["longmemeval_v2_uplift"]
                    >= gates["longmemeval_v2_uplift_minimum"],
                    evidence=metrics["longmemeval_v2_uplift"],
                    target=gates["longmemeval_v2_uplift_minimum"],
                    issue="LongMemEval-V2 uplift is below the frozen minimum",
                ),
                _check(
                    "longmemeval-v2-categories",
                    metrics["longmemeval_v2_improved_categories"]
                    >= gates["longmemeval_v2_improved_categories_minimum"],
                    evidence=metrics["longmemeval_v2_improved_categories"],
                    target=gates["longmemeval_v2_improved_categories_minimum"],
                    issue="LongMemEval-V2 did not improve four categories",
                ),
                _check(
                    "repeated-error-reduction",
                    metrics["repeated_error_reduction"]
                    >= gates["repeated_error_reduction_minimum"],
                    evidence=metrics["repeated_error_reduction"],
                    target=gates["repeated_error_reduction_minimum"],
                    issue="repeated-error reduction is below the frozen minimum",
                ),
                _check(
                    "stale-or-contradiction-error-rate",
                    metrics["stale_or_contradiction_error_rate"]
                    <= gates["stale_or_contradiction_error_rate_maximum"],
                    evidence=metrics["stale_or_contradiction_error_rate"],
                    target=gates["stale_or_contradiction_error_rate_maximum"],
                    issue="stale or contradiction error rate exceeds the frozen maximum",
                ),
                _check(
                    "false-verified-promotions",
                    metrics["false_verified_promotions"]
                    <= gates["false_verified_promotions_maximum"],
                    evidence=metrics["false_verified_promotions"],
                    target=gates["false_verified_promotions_maximum"],
                    issue="a false verified promotion occurred",
                ),
                _check(
                    "context-reduction",
                    metrics["context_reduction_vs_full_context"]
                    >= gates["context_reduction_vs_full_context_minimum"],
                    evidence=metrics["context_reduction_vs_full_context"],
                    target=gates["context_reduction_vs_full_context_minimum"],
                    issue="context reduction is below the frozen minimum",
                ),
                _check(
                    "runtime-p95-budget",
                    metrics["runtime_p95_ms"] <= metrics["runtime_budget_ms"],
                    evidence=metrics["runtime_p95_ms"],
                    target=metrics["runtime_budget_ms"],
                    issue="candidate runtime p95 exceeds the frozen budget",
                ),
                _check(
                    "complete-ablation-coverage",
                    metrics["complete_ablation_coverage"],
                    evidence=metrics["ablation_coverage"],
                    target=protocol["evaluation"]["required_ablations"],
                    issue="an improved family lacks a required ablation",
                ),
            ]
        checks = structural_checks + metric_checks
        admitted = bool(checks) and all(check["passed"] for check in checks)
        candidate_results[candidate_id] = {
            "status": "admitted" if admitted else "failed_experiment",
            "admitted": admitted,
            "checks": checks,
            "metrics": metrics,
            "issues": [check["issue"] for check in checks if not check["passed"]],
        }

    admitted_candidates = sorted(
        candidate_id
        for candidate_id, result in candidate_results.items()
        if result["admitted"]
    )
    payload = {
        "schema": SCIENTIFIC_ADMISSION_SCHEMA,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_digest": protocol.get("protocol_digest"),
        "baseline_source_sha": protocol.get("baseline_source_sha"),
        "source_sha": expected_source_sha,
        "status": "admitted" if admitted_candidates else "failed_experiment",
        "admitted": bool(admitted_candidates),
        "admitted_candidates": admitted_candidates,
        "candidate_results": candidate_results,
        "protocol_errors": protocol_errors,
        "run_errors": run_errors,
        "claim_boundary": (
            "Public WaveField descriptions and WaveMind Connect remain unchanged "
            "unless this exact-SHA artifact is admitted."
        ),
    }
    return attach_artifact_integrity(payload)


def render_scientific_memory_admission_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Scientific Memory Admission",
        "",
        f"- Status: **{payload.get('status')}**",
        f"- Evaluated HEAD SHA: `{payload.get('source_sha')}`",
        f"- Frozen baseline SHA: `{payload.get('baseline_source_sha')}`",
        f"- Protocol digest: `{payload.get('protocol_digest')}`",
        "",
        "| Candidate | Status | Passed checks | Total checks |",
        "|---|---:|---:|---:|",
    ]
    for candidate_id, result in (payload.get("candidate_results") or {}).items():
        checks = result.get("checks") or []
        passed = sum(bool(check.get("passed")) for check in checks)
        lines.append(
            f"| `{candidate_id}` | {result.get('status')} | {passed} | {len(checks)} |"
        )
    lines.extend(["", f"> {payload.get('claim_boundary')}", ""])
    return "\n".join(lines)
