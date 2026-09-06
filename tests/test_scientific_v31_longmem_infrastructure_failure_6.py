from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_6.json"


def test_v31_sixth_failure_is_pre_outcome_infrastructure_evidence():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "safety_aborted_before_outcomes"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure"]["type"] == "UnoptimizedFallbackRankedSelector"
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    assert payload["failure"]["scientific_gate_evaluated"] is False
    assert payload["observed_state"]["completed_prompt_rows"] == 0
    assert payload["observed_state"]["answers_generated"] is False
    assert payload["observed_state"]["outcome_scores_opened"] is False


def test_v31_sixth_failure_binds_stack_and_safe_resource_plateau():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    stack = payload["read_only_stack_snapshot"]
    telemetry = payload["resource_telemetry"]

    assert stack["waiting_prompt_workers"] == 3
    assert stack["active_prompt_workers"] == 1
    assert any("_select_ranked_memories" in frame for frame in stack["active_frames"])
    assert stack["question_text_or_answer_emitted"] is False
    assert telemetry["plateau_observed"] is True
    assert telemetry["maximum_observed_private_gib"] < 5.0
    assert telemetry["prompt_rows_completed"] == 0


def test_v31_sixth_failure_allows_only_exact_fallback_streaming_fix():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    boundary = payload["required_fix_boundary"]

    assert "only fallback _select_ranked_memories" in boundary["permitted_change"]
    assert "ranking tuples" in boundary["must_preserve"]
    assert "selection relevance and reason" in boundary["must_preserve"]
    assert boundary["candidate_source_sha_unchanged_required"] is True
    assert boundary["prompts_models_thresholds_workers_scoring_unchanged_required"] is True
