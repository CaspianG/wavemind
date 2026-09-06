from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol_v3,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v3.json"


def test_v3_protocol_freezes_hierarchical_units_and_negative_history():
    payload = load_scientific_protocol(PROTOCOL)

    assert validate_scientific_protocol_v3(payload, project_root=ROOT) == []
    assert payload["immutable_negative_evidence"]["v2_status"] == "failed_experiment_v2"
    assert "^Document [0-9]+:" in payload["candidate"]["document_segmentation"]


def test_v3_protocol_rejects_segmentation_or_gate_changes():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["candidate"]["document_segmentation"] = "split however scores best"
    changed["development_gate"]["minimum_independent_clusters_per_family"] = 1

    errors = validate_scientific_protocol_v3(changed, project_root=ROOT)

    assert "scientific v3 structural segmentation changed" in errors
    assert any("minimum_independent_clusters" in error for error in errors)
    assert "scientific v3 protocol digest mismatch" in errors
