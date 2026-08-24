from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol_v4,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v4.json"


def test_v4_protocol_removes_only_redundant_evaluation_indexing():
    payload = load_scientific_protocol(PROTOCOL)

    assert validate_scientific_protocol_v4(payload, project_root=ROOT) == []
    assert payload["frozen_parameters"]["evaluation_legacy_vector_indexing"] is False
    assert payload["immutable_negative_evidence"]["v3_status"].endswith(
        "runtime_budget"
    )


def test_v4_protocol_rejects_reenabled_index_or_weaker_gate():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["frozen_parameters"]["evaluation_legacy_vector_indexing"] = True
    changed["development_gate"]["minimum_independent_clusters_per_family"] = 1

    errors = validate_scientific_protocol_v4(changed, project_root=ROOT)

    assert any("evaluation_legacy_vector_indexing" in error for error in errors)
    assert "v4 development gates differ from frozen v3 gates" in errors
    assert "scientific v4 protocol digest mismatch" in errors
