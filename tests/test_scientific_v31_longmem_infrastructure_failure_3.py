from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_3.json"


def test_v31_longmem_third_failure_is_system_oom_before_outcomes():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "infrastructure_failed_before_outcomes"
    assert payload["infrastructure_failure_sequence"] == 3
    assert payload["logical_full_run_count"] == 1
    failure = payload["failure"]
    assert failure["type"] == "WindowsVirtualMemoryExhaustion"
    assert failure["python_pid"] == 15588
    assert failure["peak_observed_python_virtual_allocation_bytes"] == 29787037696
    assert failure["python_traceback_emitted"] is False
    assert failure["supervising_codex_app_crashed"] is True
    assert failure["candidate_or_threshold_failure"] is False
    assert failure["scientific_gate_evaluated"] is False
    state = payload["observed_state"]
    assert state["answers_generated"] is False
    assert state["outcome_scores_opened"] is False
    assert state["per_question_files"] == 0
    assert state["aggregated_metrics_files"] == 0


def test_v31_longmem_third_failure_binds_windows_and_tokenizer_evidence():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    events = payload["windows_event_evidence"]

    assert events["resource_event_ids"] == [33211, 33215]
    assert events["python_allocations_bytes"] == [27802656768, 29787037696]
    assert any(
        "codex.exe" in str(row["Message"]).lower()
        for row in events["collateral_application_events"]
    )
    tokenizer = payload["resolved_official_tokenizer"]
    assert tokenizer["repository"] == "Qwen/Qwen3.5-9B"
    assert tokenizer["snapshot_revision"] == (
        "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    )
    assert tokenizer["reader_or_evaluator_model_changed"] is False
    assert tokenizer["files"]


def test_v31_longmem_third_failure_allows_only_shared_backend_serialization():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    policy = payload["continuation_policy"]

    assert policy["same_logical_run_required"] is True
    assert policy["candidate_unchanged_required"] is True
    assert policy["thresholds_unchanged_required"] is True
    assert policy["worker_counts_unchanged_required"] is True
    assert policy["attempts_count_as_scientific_runs"] == 1
    assert "Serialize only calls into the shared candidate backend" in policy[
        "permitted_harness_change"
    ]
