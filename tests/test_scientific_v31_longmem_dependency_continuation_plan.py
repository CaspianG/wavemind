from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = (
    ROOT / "benchmarks" / "scientific_v31_longmem_dependency_continuation_plan.json"
)


def test_v31_longmem_dependency_continuation_is_pre_outcome_and_exact():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == (
        "preregistered_dependency_continuation_before_outcome"
    )
    assert payload["logical_full_run_count"] == 1
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert payload["fixed_harness_commit"] == (
        "303d06138fd205a36ea15473c13d0aa71fe4b150"
    )
    failure = payload["second_infrastructure_failure"]
    assert failure["outcome_scores_opened"] is False
    assert failure["scientific_gate_evaluated"] is False
    change = payload["environment_change"]
    assert change["package"] == "pillow"
    assert change["resolved_version"] == "12.3.0"
    assert change["installed_package_count"] == 1
    assert change["import_verified"] is True
    assert change["candidate_files_changed"] == 0
    assert change["harness_files_changed"] == 0
    assert [row["environment_relative_path"] for row in change["distribution_files"]] == [
        "Lib/site-packages/pillow-12.3.0.dist-info/METADATA",
        "Lib/site-packages/pillow-12.3.0.dist-info/WHEEL",
        "Lib/site-packages/pillow-12.3.0.dist-info/RECORD",
    ]


def test_v31_longmem_dependency_continuation_keeps_scientific_semantics():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    invariants = payload["semantic_invariants"]
    execution = payload["continuation_execution"]

    assert invariants["question_count"] == 451
    assert invariants["model"] == "mistral:7b"
    assert invariants["prompt_build_max_workers"] == 4
    assert invariants["reader_max_concurrent_requests"] == 4
    assert invariants["thresholds_unchanged"] is True
    assert execution["same_marker_required"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["second_partial_must_be_retained"] is True
    assert execution["fresh_scientific_run_forbidden"] is True
