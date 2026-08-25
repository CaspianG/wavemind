from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v13_freeze_binds_exact_sha_before_fresh_outcomes():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v13_candidate_freeze.json")
        .read_text(encoding="utf-8")
    )
    assert validate_artifact_integrity(payload) == []
    sha = payload["candidate_source_sha"]
    for record in payload["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{sha}:{record['path']}"], cwd=ROOT
        )
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
    assert payload["verification_before_freeze"]["failed"] == 0
    assert payload["fresh_v13_development_runs_executed"] == 0
