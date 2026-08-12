from __future__ import annotations

import json
from pathlib import Path

import pytest

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
HYPOTHESIS = ROOT / "benchmarks/evaluation_hypothesis_stateful_correction_v1.json"
BASELINE = ROOT / "benchmarks/evaluation_lifecycle_diagnostic_v3_results.json"
PROTOCOL = ROOT / "benchmarks/evaluation_development_protocol_v2.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_stateful_correction_hypothesis_is_integrity_protected_and_development_only():
    hypothesis = _json(HYPOTHESIS)
    assert validate_artifact_integrity(hypothesis) == []
    assert hypothesis["status"] == "preregistered"
    assert hypothesis["stop_rule"]["heldout_access"] == "forbidden"
    assert hypothesis["candidate_number"] == 1


def test_hypothesis_thresholds_are_derived_from_frozen_protocol_and_baseline():
    hypothesis = _json(HYPOTHESIS)
    baseline = _json(BASELINE)
    protocol = _json(PROTOCOL)
    assert hypothesis["protocol"]["payload_sha256"] == protocol["integrity"][
        "payload_sha256"
    ]
    assert hypothesis["baseline"]["payload_sha256"] == baseline["integrity"][
        "payload_sha256"
    ]
    core = baseline["summary"]["wavemind_core"]
    gates = protocol["bounded_go_no_go"]
    acceptance = hypothesis["acceptance"]
    assert acceptance["minimum_operation_state_transition"] == pytest.approx(
        core["operation_state_transition"] + gates["minimum_primary_point_lift"]
    )
    assert acceptance["maximum_context_characters_mean"] == pytest.approx(
        core["context_characters_mean"]
        * (1.0 + gates["maximum_context_regression"])
    )
    assert acceptance["maximum_warm_p95_ms"] == pytest.approx(
        core["latency_ms"]["p95"]
        * (1.0 + gates["maximum_warm_p95_latency_regression"])
    )


def test_hypothesis_targets_exactly_the_observed_update_failures():
    hypothesis = _json(HYPOTHESIS)
    expected = {
        (row["case_id"], row["target_id"])
        for row in hypothesis["expected_affected_rows"]
    }
    assert len(expected) == 10
    assert {row["operation_type"] for row in hypothesis["expected_affected_rows"]} == {
        "Update",
        "TrajectoryOps",
    }
    assert hypothesis["expected_unaffected_strata"] == [
        "Remember",
        "Forget",
        "Reflect",
    ]
