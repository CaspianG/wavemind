from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_8.json"


def test_eighth_failure_is_pre_aggregate_parser_infrastructure_evidence():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_during_second_arm_scoring_before_aggregate"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure"]["type"] == "UnacceptedLeadingBinaryReasonFormat"
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    assert payload["failure"]["scientific_gate_evaluated"] is False
    assert payload["observed_state"]["completed_official_arms"] == ["candidate_web_small"]
    assert payload["observed_state"]["completed_reader_outputs_in_failed_arm"] == 240
    assert payload["observed_state"]["completed_scoring_rows_in_failed_arm"] == 7
    assert payload["observed_state"]["failed_arm_aggregate_exists"] is False
    assert payload["observed_state"]["outcome_scores_opened_by_operator"] is False


def test_eighth_failure_allows_only_unambiguous_leading_binary_compatibility():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    boundary = payload["required_fix_boundary"]

    assert boundary["accepted_compatibility_pattern"] == "^[01]\\s*,\\s*reason\\s*:\\s*\\S"
    assert boundary["existing_parser_attempted_first"] is True
    assert boundary["returned_label_identical_to_leading_binary"] is True
    assert boundary["ambiguous_or_unlabelled_text_must_still_fail"] is True
    assert boundary["candidate_source_sha_unchanged_required"] is True
    assert boundary[
        "prompts_models_thresholds_workers_question_order_and_gate_unchanged_required"
    ] is True
