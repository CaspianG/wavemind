from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol_v6,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v6.json"


def test_v6_protocol_freezes_operation_aware_candidate_and_unchanged_gates():
    payload = load_scientific_protocol(PROTOCOL)

    assert validate_scientific_protocol_v6(payload, project_root=ROOT) == []
    assert payload["frozen_parameters"]["source_recency_bonus"] == 0.0
    assert payload["frozen_development_sample"][
        "required_repeats_on_exact_source_sha"
    ] == 3


def test_v6_protocol_rejects_tombstone_or_gate_change():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["candidate"]["tombstone_policy"] = "ordinary retrieval"
    changed["development_gate"]["minimum_candidate_intervention_coverage"] = 0.0

    errors = validate_scientific_protocol_v6(changed, project_root=ROOT)

    assert any("tombstone rule" in error for error in errors)
    assert "v6 development gates differ from frozen v5 gates" in errors
    assert "scientific v6 protocol digest mismatch" in errors
