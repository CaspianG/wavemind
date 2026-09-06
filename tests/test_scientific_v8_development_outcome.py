from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v8_failed_development_gate_retains_regression_and_later_gates():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v8_development_outcome.json").read_text(
            encoding="utf-8"
        )
    )

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_development_gate_v8"
    development = payload["memoryagentbench_development"]
    assert development["paired_effect_values"] == [0.0, 1.0, -1.0, 0.0, 0.0]
    assert development["ci95_lower"] == -0.6
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
