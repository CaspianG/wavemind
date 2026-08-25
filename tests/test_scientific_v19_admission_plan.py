from __future__ import annotations

import json
import subprocess
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v19_admission_plan.json"


def test_v19_admission_is_frozen_before_any_final_outcome():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_before_first_v19_final_outcome"
    assert payload["candidate"]["source_sha"] == (
        "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
    )
    assert payload["authorization_evidence"]["all_six_required_runs_passed"] is True
    assert payload["stage_order"]["stop_on_first_failure"] is True
    assert payload["stage_order"]["arms"] == [
        "memoryagentbench_final",
        "memops_final",
        "longmemeval_v2_small_full",
    ]
    assert payload["held_out_state_at_preregistration"] == {
        "memoryagentbench_final_outcomes_opened": False,
        "memops_final_outcomes_opened": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_runs": 0,
    }
    assert len(payload["frozen_samples"]["memoryagentbench"]["unit_ids"]) == 10
    assert len(payload["frozen_samples"]["memops"]["subjects"]) == 5
    assert payload["frozen_samples"]["longmemeval_v2"]["question_count"] == 451
    for record in payload["execution_harness"]["files"]:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]


def test_v19_admission_harness_files_exist_at_bound_source_commit():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    commit = payload["execution_harness"]["source_commit"]
    for record in payload["execution_harness"]["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{commit}:{record['path']}"], cwd=ROOT
        )
        import hashlib

        assert hashlib.sha256(content).hexdigest() == record["sha256"]
