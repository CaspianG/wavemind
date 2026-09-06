from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
FAILURE = (
    ROOT
    / "benchmarks"
    / "scientific_mab_v11_run1_attempt1_infrastructure_failure.json"
)
FAILURE_2 = (
    ROOT
    / "benchmarks"
    / "scientific_mab_v11_run1_attempt2_infrastructure_failure.json"
)
FAILURE_3 = (
    ROOT
    / "benchmarks"
    / "scientific_mab_v11_run1_attempt3_infrastructure_failure.json"
)


def test_v11_partial_attempt_is_retained_without_a_gate_decision():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "infrastructure_failed_no_gate_decision"
    assert payload["failure"]["scientific_gate_evaluated"] is False
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    partial = payload["partial_raw"]
    path = ROOT / partial["path"]
    assert path.stat().st_size == partial["bytes"]
    assert file_sha256(path) == partial["sha256"]
    continuation = payload["continuation_policy"]
    assert continuation["same_logical_run"] is True
    assert continuation["candidate_unchanged"] is True
    assert continuation["attempt1_retained_verbatim"] is True
    assert continuation["attempts_count_as_scientific_runs"] == 1


def test_v11_second_partial_attempt_retains_encoding_failure():
    payload = json.loads(FAILURE_2.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "infrastructure_failed_no_gate_decision"
    assert payload["failure"]["type"] == "UnicodeDecodeError"
    assert payload["failure"]["scientific_gate_evaluated"] is False
    partial = payload["partial_raw"]
    path = ROOT / partial["path"]
    assert path.stat().st_size == partial["bytes"]
    assert file_sha256(path) == partial["sha256"]
    continuation = payload["continuation_policy"]
    assert continuation["same_logical_run"] is True
    assert continuation["environment_only_change"].startswith("PYTHONUTF8=1")
    assert continuation["attempts_count_as_scientific_runs"] == 1


def test_v11_third_attempt_terminates_invalid_harness_without_gate_decision():
    payload = json.loads(FAILURE_3.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "frozen_harness_invalid_no_gate_decision"
    assert payload["failure"]["missing_metric"] == "substring_exact_match"
    assert payload["failure"]["scientific_gate_evaluated"] is False
    partial = payload["partial_raw"]
    path = ROOT / partial["path"]
    assert path.stat().st_size == partial["bytes"]
    assert file_sha256(path) == partial["sha256"]
    terminal = payload["terminal_policy"]
    assert terminal["v11_exact_sha_may_be_changed"] is False
    assert terminal["v11_run_may_continue"] is False
    assert terminal["opened_v11_development_contexts_may_be_reused"] is False
    assert terminal["new_protocol_and_fresh_development_contexts_required"] is True
