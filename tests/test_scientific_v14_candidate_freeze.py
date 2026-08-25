from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v14_freeze_binds_exact_sha_files_and_zero_fresh_outcomes():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v14_candidate_freeze.json")
        .read_text(encoding="utf-8")
    )

    assert validate_artifact_integrity(payload) == []
    assert payload["candidate_source_sha"] == (
        "17c97fecbb9c8ce8349d1045f1fdc131d595684b"
    )
    assert payload["protocol_digest"] == (
        "e8de1b5a67e790a6bc45dd2b0802b76ccbe60dafcbea7a61c59762fd7f9fafe3"
    )
    assert payload["fresh_v14_development_runs_executed"] == 0
    assert payload["post_outcome_source_changes_forbidden"] is True
    assert payload["verification_before_freeze"]["failed"] == 0
    for item in payload["files"]:
        assert file_sha256(ROOT / item["path"]) == item["sha256"]
