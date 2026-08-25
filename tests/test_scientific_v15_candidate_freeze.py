from __future__ import annotations

import json
import subprocess
from pathlib import Path

from wavemind.evidence import sha256_bytes, canonical_json_bytes, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v15_freeze_binds_exact_sha_files_and_zero_fresh_outcomes():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v15_candidate_freeze.json")
        .read_text(encoding="utf-8")
    )
    assert validate_artifact_integrity(payload) == []
    assert payload["fresh_v15_development_runs_executed"] == 0
    assert payload["post_outcome_source_changes_forbidden"] is True

    sha = payload["candidate_source_sha"]
    for record in payload["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{sha}:{record['path']}"], cwd=ROOT
        )
        assert sha256_bytes(content) == record["sha256"]

    protocol = json.loads(
        subprocess.check_output(
            ["git", "show", f"{sha}:benchmarks/scientific_memory_protocol_v15.json"],
            cwd=ROOT,
        ).decode("utf-8")
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert digest == payload["protocol_digest"]
