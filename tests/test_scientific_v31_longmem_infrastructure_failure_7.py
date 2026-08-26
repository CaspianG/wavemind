from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_7.json"


def test_seventh_failure_is_pre_answer_infrastructure_evidence():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_before_first_reader_answer"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure"]["type"] == "SystemProxyLoopbackInterception"
    assert payload["failure"]["candidate_or_threshold_failure"] is False
    assert payload["failure"]["scientific_gate_evaluated"] is False
    assert payload["observed_state"]["completed_prompt_rows"] == 240
    assert payload["observed_state"]["answers_generated"] is False
    assert payload["observed_state"]["outcome_scores_opened"] is False


def test_seventh_failure_binds_reproduced_transport_contrast():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    probe = payload["diagnostic_probe"]

    assert probe["scope"] == "infrastructure_only_synthetic_text"
    assert probe["inherited_transport_status"] == 503
    assert probe["direct_transport_status"] == 200
    assert probe["no_proxy_concurrent_statuses"] == [200, 200, 200, 200]
    assert probe["benchmark_prompt_or_answer_used"] is False


def test_seventh_failure_allows_only_loopback_transport_remediation():
    payload = json.loads(FAILURE.read_text(encoding="utf-8"))
    boundary = payload["required_fix_boundary"]

    assert any("system proxy" in item for item in boundary["permitted_changes"])
    assert boundary["candidate_source_sha_unchanged_required"] is True
    assert boundary["harness_commit_unchanged_required"] is True
    assert (
        boundary[
            "prompts_models_thresholds_client_workers_question_order_scoring_unchanged_required"
        ]
        is True
    )
