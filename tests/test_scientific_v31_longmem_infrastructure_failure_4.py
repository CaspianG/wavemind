from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_4.json"


def test_v31_fourth_failure_is_controlled_pre_outcome_safety_abort():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "safety_aborted_before_outcomes"
    assert payload["infrastructure_failure_sequence"] == 4
    assert payload["logical_full_run_count"] == 1
    assert payload["failure"]["type"] == "ControlledMemorySafetyAbort"
    assert payload["failure"]["operator_interrupt_sent"] is True
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    assert payload["failure"]["scientific_gate_evaluated"] is False
    state = payload["observed_state"]
    assert state["completed_prompt_rows"] == 0
    assert state["answers_generated"] is False
    assert state["outcome_scores_opened"] is False


def test_v31_fourth_failure_binds_monotonic_memory_and_scratch_scale():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    telemetry = payload["resource_telemetry"]
    scratch = payload["scratch_evidence"]

    private = [row["private_gib"] for row in telemetry["samples"]]
    assert private == sorted(private)
    assert private == [6.17, 9.43, 11.99]
    assert telemetry["private_memory_growth_gib"] == 5.82
    assert telemetry["growth_plateau_observed"] is False
    assert scratch["event_count"] == 28768
    assert scratch["event_json_bytes"] == 97046543
    assert scratch["max_sequence"] == 28768
    assert scratch["all_definitions_registered_before_selection"] is True


def test_v31_fourth_failure_requires_exact_streaming_overlap_equivalence():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    policy = payload["continuation_policy"]

    assert policy["same_logical_run_required"] is True
    assert policy["candidate_unchanged_required"] is True
    assert policy["thresholds_unchanged_required"] is True
    assert policy["worker_counts_unchanged_required"] is True
    assert policy["attempts_count_as_scientific_runs"] == 1
    assert "exact same query-token intersections" in policy[
        "permitted_harness_change"
    ]
