from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]


def test_v25_protocol_freezes_manifest_exhaustive_five_cluster_gate():
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v25.json").read_text(
            encoding="utf-8"
        )
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert protocol["candidate"]["frozen_before_first_v25_outcome"] is True
    memops = protocol["frozen_development_gate"]["families"][
        "memops_longitudinal_operation"
    ]
    assert memops["subjects"] == ["A06", "B30", "C02", "E07", "F16"]
    assert memops["manifest_operation_file_counts"] == {
        "A06": 5,
        "B30": 4,
        "C02": 4,
        "E07": 4,
        "F16": 5,
    }
    assert memops["expected_case_count"] == 22
    assert memops["required_manifest_exhaustive_files"] is True
    assert protocol["immutable_v24_preflight_evidence"]["benchmark_invocations"] == 0
    assert len(
        protocol["frozen_development_gate"]["families"][
            "memoryagentbench_summarization"
        ]["unit_ids"]
    ) == 10


def test_v25_keeps_performance_thresholds_from_v24():
    v24 = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v24.json").read_text(
            encoding="utf-8"
        )
    )
    v25 = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v25.json").read_text(
            encoding="utf-8"
        )
    )
    assert v25["frozen_development_gate"]["required_reproducible_runs"] == v24[
        "frozen_development_gate"
    ]["required_reproducible_runs"]
    assert v25["frozen_development_gate"][
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    ] == v24["frozen_development_gate"][
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    ]
    assert v25["frozen_development_gate"]["minimum_intervention_coverage"] == v24[
        "frozen_development_gate"
    ]["minimum_intervention_coverage"]
