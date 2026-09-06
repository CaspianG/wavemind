from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
OUTCOME = ROOT / "benchmarks" / "scientific_v10_development_outcome.json"


def test_v10_development_outcome_retains_six_exact_sha_passing_runs():
    payload = json.loads(OUTCOME.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_development_gate_v10"
    assert payload["candidate_source_sha"] == (
        "47b68e366aab9ce07b659c61a51c81d634b3fff2"
    )
    assert payload["required_independent_families"] == 2
    assert payload["passing_independent_families"] == 2
    assert payload["all_required_runs_pass"] is True
    assert payload["final_split_touched"] is False
    assert payload["admission_arms_executed"] == []
    assert set(payload["families"]) == {
        "memops_adjacent_operation",
        "memops_longitudinal_operation",
    }
    for family in payload["families"].values():
        assert family["required_runs"] == family["passing_runs"] == 3
        assert family["all_runs_pass"] is True
        for run in family["runs"]:
            assert run["gate_pass"] is True
            assert run["statistics"]["cluster_count"] == 5
            assert run["statistics"]["ci_lower"] > 0.0
            for evidence in (run["artifact"], run["raw"]):
                path = ROOT / evidence["path"]
                assert path.stat().st_size == evidence["bytes"]
                assert file_sha256(path) == evidence["sha256"]
