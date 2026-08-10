from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wavemind.quality_leadership_admission import (
    DEFAULT_PROTOCOL_PATH,
    GOAL4_ARTIFACT_PATH,
    QUALITY_THRESHOLDS,
    evaluate_quality_leadership_admission,
    quality_leadership_protocol_manifest,
    validate_goal4_failure_artifact,
)
from wavemind.evidence import attach_artifact_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_goal4_artifact(root: Path) -> None:
    target = root / GOAL4_ARTIFACT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (PROJECT_ROOT / GOAL4_ARTIFACT_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def test_checked_in_quality_leadership_admission_blocks_without_new_evidence() -> None:
    payload = evaluate_quality_leadership_admission(root=PROJECT_ROOT)
    rows = {row["id"]: row for row in payload["rows"]}

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert rows["goal4-failure-preserved"]["status"] == "implemented"
    assert rows["protocol-frozen-before-heldout"]["status"] == "blocked"
    assert rows["development-go-no-go"]["status"] == "blocked"
    assert rows["heldout-opened-once"]["status"] == "blocked"


def test_goal4_failure_validation_rejects_false_success() -> None:
    payload = json.loads(
        (PROJECT_ROOT / GOAL4_ARTIFACT_PATH).read_text(encoding="utf-8")
    )
    payload["status"] = "admitted"
    payload["admitted"] = True

    errors = validate_goal4_failure_artifact(payload)

    assert any("failed_experiment" in error for error in errors)


def test_protocol_threshold_weakening_blocks_admission(tmp_path: Path) -> None:
    protocol = quality_leadership_protocol_manifest(root=PROJECT_ROOT)
    protocol["thresholds"]["memory_os_uplift_over_core_min"] = 0.0
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-snapshot-current"]
    assert row["status"] == "failed"
    assert any("threshold changed" in error for error in row["details"]["errors"])


def test_historical_goal4_cannot_be_declared_tuning_data(tmp_path: Path) -> None:
    protocol = quality_leadership_protocol_manifest(root=PROJECT_ROOT)
    protocol["historical_regression_evidence"]["role"] = "development"
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-snapshot-current"]
    assert row["status"] == "failed"
    assert any("historical Goal 4 evidence" in error for error in row["details"]["errors"])


def test_cli_writes_quality_leadership_artifacts_and_blocks(tmp_path: Path) -> None:
    output = tmp_path / "admission.json"
    markdown = tmp_path / "admission.md"
    protocol = tmp_path / "protocol.json"
    results = tmp_path / "results.json"
    per_query = tmp_path / "per_query.jsonl"
    command = [
        sys.executable,
        "-m",
        "wavemind.cli",
        "quality-leadership-admission",
        "--root",
        str(PROJECT_ROOT),
        "--write-artifacts",
        "--fail-on-blocked",
        "--protocol-output",
        str(protocol),
        "--results-output",
        str(results),
        "--per-query-output",
        str(per_query),
        "--output",
        str(output),
        "--markdown-output",
        str(markdown),
        "--json",
    ]

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "blocked"
    assert json.loads(output.read_text(encoding="utf-8"))["admitted"] is False
    assert "# Quality Leadership Admission" in markdown.read_text(encoding="utf-8")
    assert json.loads(protocol.read_text(encoding="utf-8"))["thresholds"] == QUALITY_THRESHOLDS
    assert per_query.read_text(encoding="utf-8").splitlines()[0]


def test_benchmark_wrapper_requires_admitted_exit_code(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/quality_leadership_admission.py",
            "--output",
            str(tmp_path / "admission.json"),
            "--markdown-output",
            str(tmp_path / "admission.md"),
            "--protocol-output",
            str(tmp_path / "protocol.json"),
            "--results-output",
            str(tmp_path / "results.json"),
            "--per-query-output",
            str(tmp_path / "per_query.jsonl"),
            "--require-admitted",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "blocked"
