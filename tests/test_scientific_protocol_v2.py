from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol_v2,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v2.json"


def test_v2_protocol_is_preregistered_and_preserves_v1_failure():
    payload = load_scientific_protocol(PROTOCOL)

    assert validate_scientific_protocol_v2(payload, project_root=ROOT) == []
    assert payload["immutable_negative_evidence"]["status"] == "failed_experiment"
    assert payload["immutable_negative_evidence"]["may_be_overwritten"] is False
    assert payload["development_gate"]["minimum_independent_clusters_per_family"] == 5


def test_v2_protocol_rejects_fake_interventions_and_threshold_relaxation():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["development_gate"]["minimum_candidate_intervention_coverage"] = 0.0
    changed["development_gate"]["absent_intervention_policy"] = "count as zero"
    changed["admission_gates"]["stale_or_contradiction_error_rate_maximum"] = 0.2

    errors = validate_scientific_protocol_v2(changed, project_root=ROOT)

    assert any("minimum_candidate_intervention_coverage" in error for error in errors)
    assert "v2 absent-intervention fail-closed policy is missing" in errors
    assert any("stale_or_contradiction" in error for error in errors)
    assert "scientific v2 protocol digest mismatch" in errors


def test_v2_protocol_rejects_duplicate_cluster_and_gold_leakage_controls():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["validity_controls"]["duplicate_cluster_detection_required"] = False
    changed["validity_controls"]["gold_fields_exposed_to_candidate"] = [
        "expected_answer"
    ]

    errors = validate_scientific_protocol_v2(changed, project_root=ROOT)

    assert "v2 validity control is missing: duplicate_cluster_detection_required" in errors
    assert "v2 candidate may not inspect gold fields" in errors
