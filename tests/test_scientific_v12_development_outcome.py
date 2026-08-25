from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v12_failed_development_stops_all_later_arms():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v12_development_outcome.json")
        .read_text(encoding="utf-8")
    )
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_development_gate_v12"
    assert payload["run"]["ci95_lower"] == 0.0
    assert payload["run"]["paired_effect_values"] == [0.0] * 7 + [1.0, 1.0, 0.0]
    for evidence in (payload["run"]["artifact"], payload["run"]["raw"]):
        path = ROOT / evidence["path"]
        assert path.stat().st_size == evidence["bytes"]
        assert file_sha256(path) == evidence["sha256"]
    assert all(payload["unexecuted"].values())
    assert payload["post_outcome_policy"]["thresholds_may_be_relaxed"] is False
