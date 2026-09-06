from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v7_failed_development_gate_is_retained_without_spending_later_gates():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v7_development_outcome.json").read_text(
            encoding="utf-8"
        )
    )

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_development_gate_v7"
    assert payload["failed_gate"] == (
        "memoryagentbench_development_positive_uplift_lcb_run_1"
    )
    development = payload["memoryagentbench_development"]
    assert development["positive_count"] == 2
    assert development["zero_count"] == 9
    assert development["negative_count"] == 0
    assert development["ci95_lower"] == 0.0
    assert development["intervention_coverage"] == 1.0
    assert development["production_case_count"] == 0
    assert development["promoted_memory_ids"] == []
    for evidence in (development["artifact"], development["raw"]):
        path = ROOT / evidence["path"]
        assert path.stat().st_size == evidence["bytes"]
        assert file_sha256(path) == evidence["sha256"]

    unopened = payload["unopened_evidence"]
    assert all(
        value is False
        for key, value in unopened.items()
        if key.endswith("_executed") or key.endswith("_downloaded")
    )
