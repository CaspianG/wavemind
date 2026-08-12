from __future__ import annotations

from pathlib import Path

from wavemind.evaluation_judges import (
    build_evaluation_judge_policy,
    validate_evaluation_judge_policy,
)
from wavemind.evidence import attach_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def _resign(payload: dict) -> dict:
    payload.pop("integrity", None)
    return attach_artifact_integrity(payload)


def test_active_deterministic_lanes_need_no_fake_llm_judge():
    report = build_evaluation_judge_policy(project_root=ROOT)
    assert (
        validate_evaluation_judge_policy(
            report,
            project_root=ROOT,
            expected_source_sha=report["source_sha"],
        )
        == []
    )
    assert report["llm_judges"] == []
    assert all(
        scorer["llm_judge_required"] is False
        for scorer in report["active_primary_scorers"]
    )
    assert len(report["excluded_native_judge_lanes"]) >= 4


def test_required_uncalibrated_llm_judge_blocks_policy():
    report = build_evaluation_judge_policy(project_root=ROOT)
    report["active_primary_scorers"][0]["llm_judge_required"] = True
    errors = validate_evaluation_judge_policy(
        _resign(report),
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )
    assert any("required LLM judge is missing" in error for error in errors)


def test_llm_judge_missing_calibration_fields_blocks_policy():
    report = build_evaluation_judge_policy(project_root=ROOT)
    family = report["active_primary_scorers"][0]["family"]
    report["active_primary_scorers"][0]["llm_judge_required"] = True
    report["llm_judges"] = [{"family": family, "model_revision": "model@sha"}]
    errors = validate_evaluation_judge_policy(
        _resign(report),
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )
    assert any("fields are missing" in error for error in errors)


def test_below_threshold_or_single_run_judge_blocks_policy():
    report = build_evaluation_judge_policy(project_root=ROOT)
    family = report["active_primary_scorers"][0]["family"]
    report["active_primary_scorers"][0]["llm_judge_required"] = True
    report["llm_judges"] = [
        {
            "family": family,
            "model_revision": "model@sha",
            "prompt_sha256": "a" * 64,
            "temperature": 0,
            "seed": 17,
            "calibration_set_sha256": "b" * 64,
            "agreement_metric": "cohens_kappa",
            "agreement_value": 0.5,
            "minimum_agreement": 0.8,
            "repeat_count": 1,
        }
    ]
    errors = validate_evaluation_judge_policy(
        _resign(report),
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )
    assert any("agreement is below threshold" in error for error in errors)
    assert any("repeat count is below three" in error for error in errors)


def test_judge_policy_rejects_tampering_and_soft_fallback():
    report = build_evaluation_judge_policy(project_root=ROOT)
    report["policy"]["unavailable_judge_action"] = "skip_and_continue"
    errors = validate_evaluation_judge_policy(
        report,
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )
    assert "artifact payload digest mismatch" in errors
    assert "unavailable judges do not fail closed" in errors
