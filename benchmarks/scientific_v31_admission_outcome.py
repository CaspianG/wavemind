from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import (  # noqa: E402
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)


CANDIDATE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
OFFICIAL_SHA = "2cc8c540bdb87fe6761629b585e727e1c4704520"
DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"
PLAN = ROOT / "benchmarks" / "scientific_v31_admission_plan.json"
MAB_RESULT = ROOT / "benchmarks" / "scientific_mab_v31_final_results.json"
MEMOPS_RESULT = ROOT / "benchmarks" / "scientific_memops_v31_final_results.json"
LONGMEM_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_admission_outcome.json"
DOMAINS = ("web", "enterprise")
ARMS = ("no_retrieval", "candidate")
EXPECTED_COUNTS = {"web": 240, "enterprise": 211}
COMBINED_CATEGORY = {
    "static": "static",
    "static-abs": "static",
    "dynamic": "dynamic",
    "dynamic-abs": "dynamic",
    "procedure": "procedure",
    "procedure-abs": "procedure",
    "gotchas": "gotchas",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _load_valid(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    errors = validate_artifact_integrity(payload)
    if errors:
        raise RuntimeError(f"invalid artifact integrity: {path}: {errors}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _raw_record(artifact: Mapping[str, Any]) -> dict[str, object]:
    raw = artifact.get("raw_output")
    if not isinstance(raw, Mapping):
        raise RuntimeError("final artifact is missing raw_output")
    path = Path(str(raw.get("path") or ""))
    if not path.is_file() or file_sha256(path) != raw.get("sha256"):
        raise RuntimeError(f"raw evidence hash mismatch: {path}")
    return _record(path)


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise RuntimeError(f"{label} must be numeric, not bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"{label} must be finite")
    return result


def _p95(values: Sequence[float]) -> float:
    if not values:
        raise RuntimeError("cannot compute p95 over an empty sequence")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise RuntimeError("cannot compute mean over an empty sequence")
    return sum(values) / len(values)


def _validate_arm(
    *,
    domain: str,
    arm: str,
    metrics: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    expected = EXPECTED_COUNTS[domain]
    overall = metrics.get("overall")
    if not isinstance(overall, Mapping):
        raise RuntimeError(f"{domain}/{arm} aggregate is missing overall")
    if overall.get("count_all_questions") != expected or len(rows) != expected:
        raise RuntimeError(f"{domain}/{arm} question count mismatch")
    question_ids = [str(row.get("question_id") or "") for row in rows]
    if any(not question_id for question_id in question_ids):
        raise RuntimeError(f"{domain}/{arm} contains an empty question ID")
    if len(set(question_ids)) != expected:
        raise RuntimeError(f"{domain}/{arm} question IDs are not unique")
    raw_scores = [
        _finite_number(row.get("score"), label=f"{domain}/{arm} score")
        for row in rows
    ]
    if any(score not in {0.0, 1.0} for score in raw_scores):
        raise RuntimeError(f"{domain}/{arm} contains a non-binary official score")
    aggregate_score = _finite_number(
        overall.get("overall_full_set"),
        label=f"{domain}/{arm} aggregate score",
    )
    if not math.isclose(_mean(raw_scores), aggregate_score, abs_tol=1e-12):
        raise RuntimeError(f"{domain}/{arm} raw/aggregate score mismatch")
    durations = [
        _finite_number(
            row.get("memory_query_duration_seconds"),
            label=f"{domain}/{arm} memory query duration",
        )
        for row in rows
    ]
    memory_query = metrics.get("memory_query")
    if not isinstance(memory_query, Mapping):
        raise RuntimeError(f"{domain}/{arm} aggregate is missing memory_query")
    aggregate_p95 = _finite_number(
        memory_query.get("p95_seconds"),
        label=f"{domain}/{arm} aggregate p95",
    )
    if not math.isclose(_p95(durations), aggregate_p95, abs_tol=1e-12):
        raise RuntimeError(f"{domain}/{arm} raw/aggregate p95 mismatch")


def derive_longmem_metrics(
    rows_by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    baseline_rows = list(rows_by_arm["no_retrieval"])
    candidate_rows = list(rows_by_arm["candidate"])
    baseline = {str(row["question_id"]): row for row in baseline_rows}
    candidate = {str(row["question_id"]): row for row in candidate_rows}
    if set(baseline) != set(candidate):
        raise RuntimeError("LongMemEval candidate/control question IDs differ")
    if len(candidate) != 451:
        raise RuntimeError("LongMemEval paired question count must be 451")

    paired = [(baseline[question_id], candidate[question_id]) for question_id in sorted(candidate)]
    baseline_scores = [
        _finite_number(left["score"], label="baseline score") for left, _ in paired
    ]
    candidate_scores = [
        _finite_number(right["score"], label="candidate score") for _, right in paired
    ]
    baseline_overall = _mean(baseline_scores)
    candidate_overall = _mean(candidate_scores)

    category_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for left, right in paired:
        left_category = COMBINED_CATEGORY.get(str(left.get("category") or ""))
        right_category = COMBINED_CATEGORY.get(str(right.get("category") or ""))
        if left_category is None or left_category != right_category:
            raise RuntimeError("LongMemEval candidate/control categories differ")
        category_pairs[left_category].append(
            (
                _finite_number(left["score"], label="baseline category score"),
                _finite_number(right["score"], label="candidate category score"),
            )
        )
    if set(category_pairs) != {"static", "dynamic", "procedure", "gotchas"}:
        raise RuntimeError("LongMemEval combined category set mismatch")
    category_metrics = {
        category: {
            "count": len(pairs),
            "baseline": _mean([left for left, _ in pairs]),
            "candidate": _mean([right for _, right in pairs]),
            "uplift": _mean([right - left for left, right in pairs]),
        }
        for category, pairs in sorted(category_pairs.items())
    }
    improved_categories = sorted(
        category
        for category, metrics in category_metrics.items()
        if metrics["uplift"] > 0.0
    )

    selected_tokens = 0.0
    full_context_tokens = 0.0
    durations: list[float] = []
    for _, row in paired:
        metadata = row.get("memory_post_query_metadata")
        if not isinstance(metadata, Mapping):
            raise RuntimeError("candidate row is missing memory post-query metadata")
        selected = _finite_number(
            metadata.get("selected_estimated_tokens"),
            label="selected estimated tokens",
        )
        full = _finite_number(
            metadata.get("full_context_estimated_tokens"),
            label="full-context estimated tokens",
        )
        if selected < 0.0 or full <= 0.0 or selected > full:
            raise RuntimeError("candidate context token evidence is invalid")
        selected_tokens += selected
        full_context_tokens += full
        durations.append(
            _finite_number(
                row.get("memory_query_duration_seconds"),
                label="candidate memory query duration",
            )
        )

    return {
        "paired_question_count": len(paired),
        "baseline_overall": baseline_overall,
        "candidate_overall": candidate_overall,
        "uplift": candidate_overall - baseline_overall,
        "category_metrics": category_metrics,
        "improved_categories": improved_categories,
        "improved_category_count": len(improved_categories),
        "selected_estimated_tokens": selected_tokens,
        "full_context_estimated_tokens": full_context_tokens,
        "context_reduction_vs_full_context": 1.0 - selected_tokens / full_context_tokens,
        "runtime_p95_seconds": _p95(durations),
        "paired_no_retrieval_ablation_complete": True,
        "repeated_error_reduction": {
            "verifiable": False,
            "value": None,
            "reason": (
                "The frozen v31 plan did not preregister an operational mapping from "
                "official LongMemEval-V2 rows to repeated_errors."
            ),
        },
        "stale_or_contradiction_error_rate": {
            "verifiable": False,
            "value": None,
            "reason": (
                "The official retained rows contain binary correctness but no "
                "independently scored stale_or_contradiction_error field, and v31 "
                "did not preregister a substitute mapping."
            ),
        },
    }


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


def main() -> int:
    plan = _load_valid(PLAN)
    mab = _load_valid(MAB_RESULT)
    memops = _load_valid(MEMOPS_RESULT)
    if plan["candidate"]["source_sha"] != CANDIDATE_SHA:
        raise RuntimeError("v31 admission plan candidate SHA mismatch")
    protocol_digest = str(plan["protocol"]["protocol_digest"])
    if mab.get("candidate_source_sha") != CANDIDATE_SHA:
        raise RuntimeError("v31 MAB candidate SHA mismatch")
    if memops.get("source_sha") != CANDIDATE_SHA:
        raise RuntimeError("v31 MemOps candidate SHA mismatch")
    if mab.get("protocol_digest") != protocol_digest:
        raise RuntimeError("v31 MAB protocol mismatch")
    if memops.get("protocol_digest") != protocol_digest:
        raise RuntimeError("v31 MemOps protocol mismatch")
    if mab.get("status") != "pass" or mab.get("gate_pass") is not True:
        raise RuntimeError("v31 outcome requires retained MAB final pass")
    if memops.get("status") != "pass" or memops.get("gate_pass") is not True:
        raise RuntimeError("v31 outcome requires retained MemOps final pass")

    marker_path = LONGMEM_ROOT / "full_run_marker.json"
    marker = _load_json(marker_path)
    required_marker = {
        "status": "completed",
        "logical_full_run_count": 1,
        "candidate_source_sha": CANDIDATE_SHA,
        "official_repository_sha": OFFICIAL_SHA,
        "protocol_digest": protocol_digest,
        "dataset_revision": DATASET_REVISION,
        "tier": "small",
        "question_counts": EXPECTED_COUNTS,
    }
    for key, expected in required_marker.items():
        if marker.get(key) != expected:
            raise RuntimeError(f"LongMemEval marker mismatch: {key}")

    rows_by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    longmem_artifacts: dict[str, Any] = {}
    for domain in DOMAINS:
        for arm in ARMS:
            arm_name = f"{arm}_{domain}_small"
            arm_root = LONGMEM_ROOT / arm_name
            metrics_path = arm_root / "aggregated_metrics.json"
            raw_path = arm_root / "per_question.jsonl"
            metrics = _load_json(metrics_path)
            rows = _read_jsonl(raw_path)
            _validate_arm(domain=domain, arm=arm, metrics=metrics, rows=rows)
            rows_by_arm[arm].extend(rows)
            longmem_artifacts[arm_name] = {
                "aggregate": _record(metrics_path),
                "raw": _record(raw_path),
            }

    metrics = derive_longmem_metrics(rows_by_arm)
    frozen = plan["frozen_gates"]["longmemeval_v2"]
    checks = [
        _check(
            "longmemeval-v2-uplift",
            metrics["uplift"] >= frozen["uplift_minimum"],
            evidence=metrics["uplift"],
            target=frozen["uplift_minimum"],
            issue="LongMemEval-V2 uplift is below the frozen minimum",
        ),
        _check(
            "longmemeval-v2-improved-categories",
            metrics["improved_category_count"] >= frozen["improved_categories_minimum"],
            evidence=metrics["improved_categories"],
            target=frozen["improved_categories_minimum"],
            issue="LongMemEval-V2 did not improve four combined categories",
        ),
        _check(
            "repeated-error-reduction",
            False,
            evidence=metrics["repeated_error_reduction"],
            target=frozen["repeated_error_reduction_minimum"],
            issue="the repeated-error gate is not verifiable from preregistered evidence",
        ),
        _check(
            "stale-or-contradiction-error-rate",
            False,
            evidence=metrics["stale_or_contradiction_error_rate"],
            target=frozen["stale_or_contradiction_error_rate_maximum"],
            issue=(
                "the stale-or-contradiction gate is not verifiable from "
                "preregistered evidence"
            ),
        ),
        _check(
            "context-reduction-vs-full-context",
            metrics["context_reduction_vs_full_context"]
            >= frozen["context_reduction_vs_full_context_minimum"],
            evidence=metrics["context_reduction_vs_full_context"],
            target=frozen["context_reduction_vs_full_context_minimum"],
            issue="candidate context reduction is below the frozen minimum",
        ),
        _check(
            "runtime-p95-budget",
            metrics["runtime_p95_seconds"] <= 1.0,
            evidence=metrics["runtime_p95_seconds"],
            target=1.0,
            issue="candidate memory-query p95 exceeds the frozen 1000 ms budget",
        ),
        _check(
            "paired-no-retrieval-ablation",
            metrics["paired_no_retrieval_ablation_complete"],
            evidence=metrics["paired_question_count"],
            target=451,
            issue="candidate improvements lack the frozen paired no-retrieval ablation",
        ),
    ]
    admitted = all(check["passed"] for check in checks)
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_admission_outcome.v1",
            "status": "passed_admission_v31" if admitted else "failed_admission_v31",
            "candidate_id": plan["candidate"]["id"],
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": protocol_digest,
            "admission_plan": {
                **_record(PLAN),
                "payload_sha256": plan["integrity"]["payload_sha256"],
            },
            "memoryagentbench_final": {
                "status": "pass",
                "artifact": _record(MAB_RESULT),
                "raw": _raw_record(mab),
                "gate_checks": mab["gate_checks"],
            },
            "memops_final": {
                "status": "pass",
                "artifact": _record(MEMOPS_RESULT),
                "raw": _raw_record(memops),
                "gate_checks": memops["gate_checks"],
            },
            "longmemeval_v2_final": {
                "status": "pass" if admitted else "failed_final",
                "marker": _record(marker_path),
                "artifacts": longmem_artifacts,
                "metrics": metrics,
                "gate_checks": checks,
            },
            "all_frozen_gates_passed": admitted,
            "post_outcome_policy": {
                "v31_candidate_changes_forbidden": True,
                "v31_held_out_rows_may_be_used_for_future_tuning": False,
                "thresholds_may_be_relaxed": False,
                "repeat_v31_full_run_forbidden": True,
                "future_candidates_require_new_preregistration": True,
            },
            "claim_boundary": (
                "Only a true all-gates pass would authorize the bounded v31 claim. "
                "A failed or unverified gate forbids 100%-pass, SOTA, production, "
                "universal, and revolutionary claims."
            ),
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
