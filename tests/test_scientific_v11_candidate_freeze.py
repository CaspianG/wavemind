from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "benchmarks" / "scientific_v11_candidate_freeze.json"


def test_v11_candidate_freeze_binds_exact_git_blobs_before_fresh_outcomes():
    payload = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "frozen_before_fresh_development"
    sha = payload["candidate_source_sha"]
    subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=ROOT,
        check=True,
    )
    for record in payload["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{sha}:{record['path']}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
    assert payload["verification_before_freeze"]["failed"] == 0
    assert payload["evidence_state"] == {
        "fresh_v11_development_runs_executed": 0,
        "fresh_v11_mab_final_executed": False,
        "memops_final_executed": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_runs": 0,
    }
    assert payload["post_outcome_source_changes_forbidden"] is True
