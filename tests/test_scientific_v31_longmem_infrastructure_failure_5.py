from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_5.json"


def test_v31_fifth_failure_is_missing_official_dependency_before_outcomes():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "safety_aborted_before_outcomes"
    assert payload["infrastructure_failure_sequence"] == 5
    assert payload["logical_full_run_count"] == 1
    failure = payload["failure"]
    assert failure["type"] == "MissingOfficialTorchvisionDependency"
    assert failure["operator_interrupt_sent"] is True
    assert "requires the Torchvision library" in failure["processor_error"]["message"]
    assert failure["candidate_or_threshold_failure"] is False
    assert failure["scientific_gate_evaluated"] is False
    state = payload["observed_state"]
    assert state["completed_prompt_rows"] == 0
    assert state["answers_generated"] is False
    assert state["outcome_scores_opened"] is False


def test_v31_fifth_failure_phase_probe_localizes_processor_initialization():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    probe = payload["phase_probe"]

    assert probe["question_chars"] == 214
    assert probe["question_has_image"] is False
    assert probe["optimized_recall_seconds"] < 30.0
    assert probe["context_items"] == 15
    assert probe["context_chars"] == 32364
    assert probe["context_estimated_tokens"] == 8095
    assert probe["chain_errors"] == []


def test_v31_fifth_failure_allows_only_compatible_torchvision_install():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    dependency = payload["official_dependency_evidence"]
    policy = payload["continuation_policy"]

    assert dependency["torchvision_declared"] is True
    assert dependency["installed_torch_version"] == "2.13.0+cpu"
    assert dependency["installed_torchvision_at_failure"] is False
    assert dependency["dry_run_compatible_torchvision"] == "0.28.0"
    assert dependency["dry_run_packages_to_install"] == 1
    assert dependency["dry_run_existing_torch_change"] is False
    assert policy["same_logical_run_required"] is True
    assert policy["candidate_unchanged_required"] is True
    assert policy["harness_unchanged_required"] is True
    assert policy["attempts_count_as_scientific_runs"] == 1
