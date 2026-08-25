from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol_v5,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v5.json"


def test_v5_protocol_freezes_atomic_batch_without_weaker_gates():
    payload = load_scientific_protocol(PROTOCOL)

    assert validate_scientific_protocol_v5(payload, project_root=ROOT) == []
    assert payload["frozen_parameters"]["event_batch_transaction_count_per_context"] == 1
    assert payload["validity_controls"]["batch_rollback_test_required"] is True


def test_v5_protocol_rejects_partial_transaction_or_gate_change():
    payload = load_scientific_protocol(PROTOCOL)
    changed = copy.deepcopy(payload)
    changed["candidate"]["atomic_batch"] = "insert rows individually"
    changed["development_gate"]["minimum_candidate_intervention_coverage"] = 0.0

    errors = validate_scientific_protocol_v5(changed, project_root=ROOT)

    assert any("atomic rule" in error for error in errors)
    assert "v5 development gates differ from frozen v4 gates" in errors
    assert "scientific v5 protocol digest mismatch" in errors
