from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v24_preflight_invalidity_precedes_any_benchmark_execution():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v24_preflight_outcome.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "invalid_before_execution"
    assert payload["benchmark_invocations"] == 0
    assert payload["fresh_development_cases_executed"] == 0
    assert payload["model_calls"] == 0
    assert payload["final_split_touched"] is False
    assert payload["replacement_within_v24_forbidden"] is True
