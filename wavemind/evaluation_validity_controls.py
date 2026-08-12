from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    canonical_json_bytes,
    execution_environment,
    repository_commit,
    sha256_bytes,
    utc_now,
)
from .evaluation_statistics import paired_cluster_bootstrap, plan_primary_metrics


SCHEMA = "wavemind.evaluation_validity_controls.v1"
SOURCE_PATHS = (
    "wavemind/evaluation_statistics.py",
    "wavemind/evaluation_validity_controls.py",
    "benchmarks/evaluation_validity_controls.py",
    "tests/test_evaluation_validity_controls.py",
    "tests/test_evaluation_statistics.py",
)

PRIMARY_METRIC_SPECIFICATIONS = (
    {
        "id": "workflow-pass-at-1",
        "cluster_unit": "task",
        "baseline_rate": 0.35,
        "minimum_detectable_effect": 0.10,
    },
    {
        "id": "memory-answer-quality",
        "cluster_unit": "conversation",
        "baseline_rate": 0.45,
        "minimum_detectable_effect": 0.08,
    },
    {
        "id": "lifecycle-correctness",
        "cluster_unit": "trajectory",
        "baseline_rate": 0.55,
        "minimum_detectable_effect": 0.10,
    },
)


@dataclass(frozen=True)
class ControlCase:
    case_id: str
    cluster_id: str
    scorer: str
    expected: Any


CASES = (
    ControlCase(
        "retrieval-substring", "conversation-a", "substring_exact_match", "beta"
    ),
    ControlCase("answer-exact", "conversation-b", "exact_match", "current-policy"),
    ControlCase("recommendation-top5", "conversation-c", "recall_at_5", "item-7"),
    ControlCase(
        "lifecycle-update",
        "trajectory-a",
        "structured_exact",
        {"state": "updated", "version": 2},
    ),
    ControlCase(
        "workflow-final-state",
        "trajectory-b",
        "structured_exact",
        {"tests": "passed", "exit_code": 0},
    ),
    ControlCase("temporal-answer", "conversation-d", "exact_match", "after-update"),
)


SYSTEM_OUTPUTS: dict[str, dict[str, Any]] = {
    "oracle": {
        "retrieval-substring": "alpha beta gamma",
        "answer-exact": "current-policy",
        "recommendation-top5": ["item-7", "item-3"],
        "lifecycle-update": {"state": "updated", "version": 2},
        "workflow-final-state": {"tests": "passed", "exit_code": 0},
        "temporal-answer": "after-update",
    },
    "strong_valid_baseline": {
        "retrieval-substring": "alpha beta gamma",
        "answer-exact": "current-policy",
        "recommendation-top5": ["item-7", "item-3"],
        "lifecycle-update": {"state": "updated", "version": 2},
        "workflow-final-state": {"tests": "failed", "exit_code": 1},
        "temporal-answer": "before-update",
    },
    "random": {
        "retrieval-substring": "unrelated",
        "answer-exact": "unrelated",
        "recommendation-top5": ["item-2", "item-9"],
        "lifecycle-update": {"state": "old", "version": 1},
        "workflow-final-state": {"tests": "failed", "exit_code": 1},
        "temporal-answer": "after-update",
    },
    "no_memory": {
        "retrieval-substring": None,
        "answer-exact": None,
        "recommendation-top5": [],
        "lifecycle-update": None,
        "workflow-final-state": None,
        "temporal-answer": None,
    },
}

SAFETY_PROBES = {
    "clean": {"stale": False, "wrong_namespace": False, "deleted": False},
    "stale_poison": {"stale": True, "wrong_namespace": False, "deleted": False},
    "namespace_poison": {"stale": False, "wrong_namespace": True, "deleted": False},
    "deleted_poison": {"stale": False, "wrong_namespace": False, "deleted": True},
}


def _score(case: ControlCase, output: Any) -> float:
    if case.scorer == "substring_exact_match":
        return float(isinstance(output, str) and str(case.expected) in output)
    if case.scorer == "exact_match":
        return float(output == case.expected)
    if case.scorer == "recall_at_5":
        values = (
            output
            if isinstance(output, Sequence) and not isinstance(output, str)
            else []
        )
        return float(case.expected in list(values)[:5])
    if case.scorer == "structured_exact":
        return float(output == case.expected)
    raise ValueError(f"unsupported control scorer: {case.scorer}")


def _evaluate_system(system_id: str, outputs: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for case in CASES:
        output = outputs.get(case.case_id)
        rows.append(
            {
                "case_id": case.case_id,
                "cluster_id": case.cluster_id,
                "scorer": case.scorer,
                "output": output,
                "score": _score(case, output),
                "status": "completed",
            }
        )
    return {
        "system": system_id,
        "case_count": len(rows),
        "completed_count": sum(row["status"] == "completed" for row in rows),
        "mean_score": sum(row["score"] for row in rows) / len(rows),
        "rows": rows,
    }


def _safety_metrics(probe: Mapping[str, bool]) -> dict[str, float]:
    return {
        "stale_leakage": float(bool(probe.get("stale"))),
        "namespace_leakage": float(bool(probe.get("wrong_namespace"))),
        "deleted_evidence_resurfacing": float(bool(probe.get("deleted"))),
    }


def _control_payload() -> dict[str, Any]:
    systems = {
        system_id: _evaluate_system(system_id, outputs)
        for system_id, outputs in SYSTEM_OUTPUTS.items()
    }
    safety = {
        probe_id: _safety_metrics(probe) for probe_id, probe in SAFETY_PROBES.items()
    }
    scores = {system_id: result["mean_score"] for system_id, result in systems.items()}
    positive_passed = scores["oracle"] == 1.0
    negative_passed = (
        scores["random"] < scores["strong_valid_baseline"]
        and scores["no_memory"] == 0.0
    )
    ordering_passed = (
        scores["oracle"]
        > scores["strong_valid_baseline"]
        > scores["random"]
        > scores["no_memory"]
    )
    target_metrics = {
        "stale_poison": "stale_leakage",
        "namespace_poison": "namespace_leakage",
        "deleted_poison": "deleted_evidence_resurfacing",
    }
    poison_isolation = True
    for probe_id, target in target_metrics.items():
        for metric, value in safety[probe_id].items():
            expected = 1.0 if metric == target else 0.0
            poison_isolation = poison_isolation and value == expected
    all_rows = [row for result in systems.values() for row in result["rows"]]
    expected_rows = len(CASES) * len(SYSTEM_OUTPUTS)
    paired_rows = []
    for case in CASES:
        paired_rows.append(
            {
                "cluster_id": case.cluster_id,
                "baseline": next(
                    row["score"]
                    for row in systems["strong_valid_baseline"]["rows"]
                    if row["case_id"] == case.case_id
                ),
                "treatment": next(
                    row["score"]
                    for row in systems["oracle"]["rows"]
                    if row["case_id"] == case.case_id
                ),
            }
        )
    bootstrap = paired_cluster_bootstrap(
        paired_rows,
        cluster_key="cluster_id",
        baseline_key="baseline",
        treatment_key="treatment",
        repeats=1000,
        seed=17,
    )
    power_plans = plan_primary_metrics(PRIMARY_METRIC_SPECIFICATIONS)
    return {
        "systems": systems,
        "safety_probes": safety,
        "positive_controls": {
            "passed": positive_passed,
            "oracle_score": scores["oracle"],
            "expected": 1.0,
        },
        "negative_controls": {
            "passed": negative_passed and poison_isolation,
            "random_score": scores["random"],
            "no_memory_score": scores["no_memory"],
            "poison_isolation": poison_isolation,
        },
        "control_ordering": {
            "passed": ordering_passed and poison_isolation,
            "scores": scores,
            "required_order": "oracle > strong_valid_baseline > random > no_memory",
        },
        "metric_range": {
            "passed": scores["no_memory"] == 0.0
            and scores["oracle"] == 1.0
            and (1.0 - scores["strong_valid_baseline"]) >= 0.10,
            "observed_floor": scores["no_memory"],
            "observed_ceiling": scores["oracle"],
            "strong_baseline": scores["strong_valid_baseline"],
            "minimum_preregistered_lift": 0.10,
            "headroom": 1.0 - scores["strong_valid_baseline"],
        },
        "power_and_mde": {
            "passed": all(
                plan["required_independent_clusters"] > 0 and plan["cluster_unit"]
                for plan in power_plans
            ),
            "plans": power_plans,
            "correction_policy": "holm",
        },
        "paired_clustered_statistics": {
            "passed": bootstrap["paired"]
            and bootstrap["cluster_key"] == "cluster_id"
            and bootstrap["cluster_count"] >= 2,
            "diagnostic": bootstrap,
        },
        "per_case_completeness": {
            "passed": len(all_rows) == expected_rows
            and all(row["status"] == "completed" for row in all_rows),
            "expected_rows": expected_rows,
            "observed_rows": len(all_rows),
            "filtered_rows": 0,
            "missing_rows": 0,
        },
        "claim_boundary": (
            "Synthetic deterministic controls validate scorer ordering, poison isolation, "
            "and evidence completeness. They do not prove WaveMind product quality."
        ),
    }


def run_evaluation_validity_controls(*, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    repeats = [_control_payload() for _ in range(3)]
    fingerprints = [sha256_bytes(canonical_json_bytes(payload)) for payload in repeats]
    payload = repeats[0]
    payload["deterministic_verdict"] = {
        "passed": len(set(fingerprints)) == 1,
        "repeat_count": len(fingerprints),
        "fingerprints": fingerprints,
    }
    payload.update(
        {
            "schema": SCHEMA,
            "generated_at": utc_now(),
            "source_sha": repository_commit(root),
            "source_manifest": build_source_manifest(root, SOURCE_PATHS),
            "environment": execution_environment(
                profile="evaluation-validity-controls"
            ),
        }
    )
    return attach_artifact_integrity(payload)
