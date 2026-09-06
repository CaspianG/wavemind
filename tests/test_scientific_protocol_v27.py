from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]


def test_v27_protocol_freezes_operation_adaptive_fresh_gate():
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v27.json").read_text(
            encoding="utf-8"
        )
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert protocol["candidate"]["frozen_before_first_v27_outcome"] is True
    assert protocol["frozen_parameters"]["memops_question_selection"] == (
        "operation-adaptive-v7"
    )
    memops = protocol["frozen_development_gate"]["families"][
        "memops_longitudinal_operation"
    ]
    assert memops["subjects"] == ["A04", "C03", "D02", "E13", "F17"]
    assert memops["manifest_operation_file_counts"] == {
        "A04": 4,
        "C03": 4,
        "D02": 4,
        "E13": 4,
        "F17": 5,
    }
    assert memops["expected_case_count"] == 21
    assert protocol["immutable_v25_development_evidence"]["failed_run_may_be_rerun"] is False
    assert protocol["opened_v26_diagnostic"]["diagnostic_gate_pass"] is True


def test_v27_keeps_v25_performance_thresholds():
    v25 = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v25.json").read_text(
            encoding="utf-8"
        )
    )
    v27 = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v27.json").read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "required_reproducible_runs",
        "minimum_independent_clusters_per_family",
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than",
        "minimum_intervention_coverage",
        "stop_on_first_failed_required_run",
    ):
        assert v27["frozen_development_gate"][key] == v25["frozen_development_gate"][key]
