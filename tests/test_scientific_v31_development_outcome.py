from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import recorded_file_matches, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
OUTCOME = ROOT / "benchmarks" / "scientific_v31_development_outcome.json"


def test_v31_development_outcome_binds_six_exact_sha_passing_runs():
    payload = json.loads(OUTCOME.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_development_gate_v31"
    assert payload["candidate_id"] == "operation-routed-target-state-agent-v31"
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert payload["protocol_digest"] == (
        "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
    )
    assert payload["required_independent_families"] == 2
    assert payload["passing_independent_families"] == 2
    assert payload["required_reproducible_runs_per_family"] == 3
    assert payload["all_required_runs_pass"] is True
    assert payload["final_split_touched"] is False
    assert payload["admission_arms_executed"] == []
    assert payload["admission_permitted_next"] is True
    assert set(payload["families"]) == {
        "memoryagentbench_summarization",
        "memops_longitudinal_operation",
    }
    assert [
        run["case_count"]
        for run in payload["families"]["memoryagentbench_summarization"]["runs"]
    ] == [10, 10, 10]
    assert [
        run["case_count"]
        for run in payload["families"]["memops_longitudinal_operation"]["runs"]
    ] == [42, 42, 42]
    for family in payload["families"].values():
        assert family["required_runs"] == family["passing_runs"] == 3
        assert family["all_runs_pass"] is True
        assert [run["run_number"] for run in family["runs"]] == [1, 2, 3]
        for run in family["runs"]:
            assert run["gate_pass"] is True
            assert run["statistics"]["cluster_count"] == 10
            assert run["statistics"]["ci_lower"] > 0.0
            assert run["statistics"]["repeats"] == 2000
            assert run["statistics"]["seed"] == 17
            assert run["statistics"]["confidence_level"] == 0.95
            assert all(run["gate_checks"].values())
            for evidence in (run["artifact"], run["raw"]):
                path = ROOT / evidence["path"]
                assert recorded_file_matches(
                    path, size=evidence["bytes"], sha256=evidence["sha256"]
                )
