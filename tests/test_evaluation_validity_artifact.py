from __future__ import annotations

import json
from pathlib import Path

from wavemind.evaluation_validity_admission import EXPECTED_ROWS, SCHEMA
from wavemind.evaluation_validity_controls import SCHEMA as CONTROLS_SCHEMA
from wavemind.evaluation_splits import validate_evaluation_split_manifest
from wavemind.evaluation_judges import validate_evaluation_judge_policy
from wavemind.evidence import (
    commit_relation,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "benchmarks/evaluation_validity_admission_results.json"
MARKDOWN_PATH = ROOT / "benchmarks/EVALUATION_VALIDITY_ADMISSION.md"
CONTROLS_PATH = ROOT / "benchmarks/evaluation_validity_controls_results.json"
SPLIT_PATH = ROOT / "benchmarks/evaluation_split_manifest_results.json"
JUDGE_PATH = ROOT / "benchmarks/evaluation_judge_policy_results.json"


def test_checked_evaluation_validity_snapshot_is_consistent_and_fail_closed():
    report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    current_sha = repository_commit(ROOT)
    assert report["schema"] == SCHEMA
    assert validate_artifact_integrity(report) == []
    assert report["status"] == "blocked"
    assert report["admitted"] is False
    assert report["implemented_rows"] == 15
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
    assert "Rows: `15/16` implemented" in markdown
    for row_id in EXPECTED_ROWS:
        assert f"`{row_id}`" in markdown


def test_checked_control_evidence_is_complete_current_and_not_product_proof():
    report = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
    assert report["schema"] == CONTROLS_SCHEMA
    assert validate_artifact_integrity(report) == []
    assert (
        validate_source_manifest(
            ROOT, report["source_manifest"], require_current_files=True
        )
        == []
    )
    assert report["deterministic_verdict"]["repeat_count"] == 3
    assert report["per_case_completeness"]["filtered_rows"] == 0
    assert report["positive_controls"]["passed"] is True
    assert report["negative_controls"]["passed"] is True
    assert report["metric_range"]["passed"] is True
    assert report["power_and_mde"]["passed"] is True
    assert report["paired_clustered_statistics"]["passed"] is True
    assert "do not prove WaveMind product quality" in report["claim_boundary"]


def test_checked_split_manifest_has_real_pinned_units_and_zero_overlap():
    report = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    assert (
        validate_evaluation_split_manifest(
            report,
            project_root=ROOT,
            expected_source_sha=report["source_sha"],
        )
        == []
    )
    assert len(report["units"]) == 853
    assert report["counts"] == {
        "state-bench": {"development": 240, "validation": 60, "final": 150},
        "memops": {"development": 240, "validation": 82, "final": 81},
    }
    assert all(not values for values in report["overlaps"].values())
    assert report["subject_split_breaches"] == []
    assert "No benchmark was executed" in report["claim_boundary"]


def test_checked_judge_policy_excludes_uncalibrated_native_lanes():
    report = json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    assert (
        validate_evaluation_judge_policy(
            report,
            project_root=ROOT,
            expected_source_sha=report["source_sha"],
        )
        == []
    )
    assert report["llm_judges"] == []
    assert len(report["active_primary_scorers"]) == 2
    assert all(
        scorer["llm_judge_required"] is False
        for scorer in report["active_primary_scorers"]
    )
    assert len(report["excluded_native_judge_lanes"]) >= 4
