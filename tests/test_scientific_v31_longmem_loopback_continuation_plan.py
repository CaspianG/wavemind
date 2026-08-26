from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_continuation_plan.json"


def test_loopback_continuation_is_preregistered_before_outcomes():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_loopback_bypass_continuation_before_outcome"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure_evidence"]["completed_prompt_rows"] == 240
    assert payload["failure_evidence"]["answers_generated"] is False
    assert payload["failure_evidence"]["outcome_scores_opened"] is False
    assert payload["synthetic_transport_probe"]["benchmark_prompt_read"] is False
    assert payload["synthetic_transport_probe"]["scores_opened"] is False


def test_loopback_continuation_bypasses_proxy_without_changing_science():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    remediation = payload["operational_remediation"]
    frozen = payload["frozen_invariants"]

    assert remediation["environment"]["NO_PROXY"] == "127.0.0.1,localhost"
    assert remediation["environment"]["OLLAMA_CONTEXT_LENGTH"] == "32768"
    assert remediation["environment"]["OLLAMA_NUM_PARALLEL"] == "1"
    assert remediation["scientific_effect"] == "transport_and_serving_reliability_only"
    assert frozen["candidate_source_sha"] == "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    assert frozen["fallback_harness_commit"] == "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
    assert frozen["model_digest"] == "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
    assert frozen["context_window"] == 32768
    assert frozen["reader_max_concurrent_requests"] == 4
    assert frozen["prompts_unchanged"] is True
    assert frozen["thresholds_unchanged"] is True
    assert frozen["scoring_unchanged"] is True


def test_loopback_continuation_preserves_logical_run_and_retains_partial():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    execution = payload["continuation_execution"]

    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["retained_partial_count_before_continuation"] == 6
    assert execution["current_partial_must_be_retained_on_restart"] is True
    assert execution["restart_first_incomplete_arm"] == "candidate_web_small"
    assert execution["fresh_scientific_run_forbidden"] is True
