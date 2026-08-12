from __future__ import annotations

import json
from pathlib import Path

from wavemind.evaluation_validity_admission import EXPECTED_ROWS, SCHEMA
from wavemind.evidence import (
    commit_relation,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "benchmarks/evaluation_validity_admission_results.json"
MARKDOWN_PATH = ROOT / "benchmarks/EVALUATION_VALIDITY_ADMISSION.md"


def test_checked_evaluation_validity_snapshot_is_consistent_and_fail_closed():
    report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    current_sha = repository_commit(ROOT)
    assert report["schema"] == SCHEMA
    assert validate_artifact_integrity(report) == []
    assert report["status"] == "blocked"
    assert report["admitted"] is False
    assert report["implemented_rows"] == 5
    assert report["required_rows"] == len(EXPECTED_ROWS)
    assert tuple(row["id"] for row in report["rows"]) == EXPECTED_ROWS
    assert commit_relation(ROOT, report["source_sha"], current_sha) in {
        "exact",
        "ancestor",
    }

    exact_row = next(
        row for row in report["rows"] if row["id"] == "exact-sha-integrity"
    )
    manifest = exact_row["evidence"]["source_manifest"]
    assert validate_source_manifest(ROOT, manifest, require_current_files=True) == []

    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    assert "Status: **blocked**" in markdown
    assert "Rows: `5/16` implemented" in markdown
    for row_id in EXPECTED_ROWS:
        assert f"`{row_id}`" in markdown
