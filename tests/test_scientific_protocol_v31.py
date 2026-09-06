from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]


def _protocol(version: int) -> dict:
    return json.loads(
        (ROOT / "benchmarks" / f"scientific_memory_protocol_v{version}.json").read_text(
            encoding="utf-8"
        )
    )


def test_v31_protocol_freezes_operation_routed_fresh_gate():
    protocol = _protocol(31)
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert protocol["candidate"]["frozen_before_first_v31_outcome"] is True
    assert protocol["frozen_parameters"]["memops_candidate_mode_by_operation"] == {
        "TrajectoryOps": "target-scoped-operation-agent-v16"
    }
    memops = protocol["frozen_development_gate"]["families"][
        "memops_longitudinal_operation"
    ]
    assert memops["subjects"] == [
        "A01",
        "B01",
        "C01",
        "D10",
        "E01",
        "F06",
        "A02",
        "B10",
        "C04",
        "D11",
    ]
    assert memops["expected_case_count"] == 42
    assert sum(memops["manifest_operation_file_counts"].values()) == 42
    assert not set(memops["subjects"]).intersection(
        protocol["frozen_admission"]["memops_final_subjects"]
    )


def test_v31_keeps_v27_performance_thresholds():
    v27 = _protocol(27)
    v31 = _protocol(31)
    for key in (
        "required_reproducible_runs",
        "minimum_independent_clusters_per_family",
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than",
        "minimum_intervention_coverage",
        "stop_on_first_failed_required_run",
    ):
        assert v31["frozen_development_gate"][key] == v27["frozen_development_gate"][key]


def test_v31_records_opened_composition_without_treating_it_as_gate():
    evidence = _protocol(31)["opened_compositional_evidence"]
    assert evidence["official_gate_decision"] is False
    assert evidence["fresh_confirmation_required"] is True
    assert evidence["trajectory_case_id"] == "D02_trajectory_ops_q2"
    assert evidence["trajectory_treatment_score"] == 1.0
    assert evidence["forget_case_id"] == "F17_forget_q8"
    assert evidence["forget_treatment_score"] == 1.0
