from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
OUTCOME = ROOT / "benchmarks" / "scientific_v19_development_outcome.json"


def test_v19_development_outcome_binds_six_exact_sha_passing_runs():
    payload = json.loads(OUTCOME.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_development_gate_v19"
    assert payload["candidate_id"] == "targeted-dual-coverage-agent-v19"
    assert payload["candidate_source_sha"] == (
        "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
    )
    assert payload["protocol_digest"] == (
        "443d8a461b10969756579eb6af3e05d7b909d30369fb286b2a582aa8efaef684"
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
    for family in payload["families"].values():
        assert family["required_runs"] == family["passing_runs"] == 3
        assert family["all_runs_pass"] is True
        assert [run["run_number"] for run in family["runs"]] == [1, 2, 3]
        for run in family["runs"]:
            assert run["gate_pass"] is True
            assert run["statistics"]["cluster_count"] >= 5
            assert run["statistics"]["ci_lower"] > 0.0
            assert run["statistics"]["repeats"] == 2000
            assert run["statistics"]["seed"] == 17
            assert all(run["gate_checks"].values())
            for evidence in (run["artifact"], run["raw"]):
                path = ROOT / evidence["path"]
                assert path.stat().st_size == evidence["bytes"]
                assert file_sha256(path) == evidence["sha256"]
