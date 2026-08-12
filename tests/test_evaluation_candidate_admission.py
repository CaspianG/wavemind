from __future__ import annotations

import json
from pathlib import Path

from wavemind.evaluation_candidate_admission import (
    SCHEMA,
    run_correction_operational_checks,
    validate_candidate_admission,
)
from wavemind.evidence import attach_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_operational_correction_checks_are_fail_closed(tmp_path: Path):
    checks = run_correction_operational_checks(tmp_path)
    assert checks
    assert all(checks.values())


def test_checked_candidate_admission_is_consistent_and_integrity_protected():
    path = ROOT / "benchmarks/evaluation_candidate1_admission_results.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert validate_candidate_admission(
        payload,
        project_root=ROOT,
        require_current_files=True,
    ) == []


def test_candidate_admission_rejects_failed_row_even_with_fresh_integrity():
    payload = attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "status": "passed",
            "admitted": True,
            "checks": [{"id": "gate", "status": "failed"}],
            "source_manifest": {
                "schema": "wavemind.source_manifest.v1",
                "algorithm": "sha256",
                "files": [{"path": "missing", "sha256": "0" * 64}],
                "digest": "wrong",
            },
        }
    )
    errors = validate_candidate_admission(
        payload,
        project_root=ROOT,
        require_current_files=False,
    )
    assert "candidate admission status disagrees with checks" in errors
    assert "candidate admission verdict disagrees with checks" in errors
