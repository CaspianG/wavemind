from __future__ import annotations

import json
import subprocess
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v16_freeze_binds_every_executable_runner_file_at_exact_sha():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v16_candidate_freeze.json")
        .read_text(encoding="utf-8")
    )
    assert validate_artifact_integrity(payload) == []
    assert payload["fresh_v16_development_runs_executed"] == 0
    assert payload["post_outcome_source_changes_forbidden"] is True
    assert len(payload["files"]) == 10
    sha = payload["candidate_source_sha"]
    for record in payload["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{sha}:{record['path']}"], cwd=ROOT
        )
        assert sha256_bytes(content) == record["sha256"]
    protocol = json.loads(
        subprocess.check_output(
            ["git", "show", f"{sha}:benchmarks/scientific_memory_protocol_v16.json"],
            cwd=ROOT,
        ).decode("utf-8")
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert digest == payload["protocol_digest"]
