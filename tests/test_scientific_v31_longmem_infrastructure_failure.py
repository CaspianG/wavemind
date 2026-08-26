from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure.json"


def test_v31_longmem_failure_is_pre_outcome_and_preserved():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "infrastructure_failed_before_outcomes"
    assert payload["logical_full_run_count"] == 1
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert payload["original_harness_commit"] == (
        "8d5052b94dea2cdc2db020208800577e3267ab3c"
    )
    assert payload["failure"]["scientific_gate_evaluated"] is False
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    state = payload["observed_state"]
    assert state["completed_official_arms"] == []
    assert state["answers_generated"] is False
    assert state["outcome_scores_opened"] is False
    assert state["per_question_files"] == 0
    assert state["aggregated_metrics_files"] == 0
    assert state["marker_completed"] is False
    for key in ("marker", "run_args"):
        record = state[key]
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]


def test_v31_longmem_failure_allows_only_same_run_synchronization_fix():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    policy = payload["continuation_policy"]

    assert policy["authorized_by_preregistered_plan"] is True
    assert policy["same_logical_run_required"] is True
    assert policy["partial_retained_verbatim_required"] is True
    assert policy["candidate_unchanged_required"] is True
    assert policy["data_unchanged_required"] is True
    assert policy["prompts_unchanged_required"] is True
    assert policy["model_unchanged_required"] is True
    assert policy["thresholds_unchanged_required"] is True
    assert policy["order_unchanged_required"] is True
    assert policy["deterministic_parameters_unchanged_required"] is True
    assert policy["attempts_count_as_scientific_runs"] == 1
    assert "Synchronize" in policy["permitted_change"]
