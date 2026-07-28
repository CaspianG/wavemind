from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wavemind.experience_quality_admission import (
    ARTIFACT,
    DATASET_FINGERPRINT,
    DATASET_REVISION,
    evaluate_experience_quality_admission,
    render_experience_quality_admission_markdown,
)


SHA = "a" * 40


def _payload() -> dict:
    held_out_ids = [f"held-{index:02d}" for index in range(30)]
    rows = [
        {"request_id": request_id, "success": True}
        for request_id in held_out_ids
    ]
    return {
        "schema": "wavemind.experienced_work_agent_benchmark.v1",
        "status": "pass",
        "source_sha": SHA,
        "dataset": {
            "revision": DATASET_REVISION,
            "fingerprint_sha256": DATASET_FINGERPRINT,
            "training_trajectories": 60,
            "held_out_tasks": 30,
            "held_out_ids": held_out_ids,
            "split_frozen_before_training": True,
            "metadata_leakage": False,
        },
        "protocol": {
            "same_held_out_tasks": True,
            "same_runtime_verifiers": True,
            "same_tool_implementations": True,
            "no_paid_api": True,
            "experience_promotion_gates": True,
            "core_top_k": 3,
        },
        "training": {
            "successful": 48,
            "failed": 12,
            "active_strategies": 6,
        },
        "uplift": {
            "task_success_absolute": 0.20,
            "repeated_error_relative_reduction": 0.50,
            "tool_step_relative_reduction": 0.25,
            "context_token_relative_reduction": 0.35,
            "p95_latency_regression": 0.20,
        },
        "checks": [{"id": "product", "passed": True}],
        "held_out_results": {
            "cold": rows,
            "core": rows,
            "experience": rows,
        },
    }


def _write(root: Path, payload: dict) -> None:
    path = root / ARTIFACT
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_admission_accepts_complete_frozen_evidence(tmp_path) -> None:
    _write(tmp_path, _payload())

    result = evaluate_experience_quality_admission(
        tmp_path,
        expected_source_sha=SHA,
    )

    assert result["status"] == "admitted"
    assert result["admitted"] is True
    assert result["summary"]["checks_passed"] == 12
    assert result["issues"] == []
    assert "Status: **admitted**" in (
        render_experience_quality_admission_markdown(result)
    )


def test_admission_rejects_leakage_latency_and_row_mismatch(tmp_path) -> None:
    payload = _payload()
    payload["dataset"]["metadata_leakage"] = True
    payload["uplift"]["p95_latency_regression"] = 0.21
    payload["held_out_results"]["core"] = payload["held_out_results"]["core"][:-1]
    _write(tmp_path, payload)

    result = evaluate_experience_quality_admission(tmp_path)

    failed = {check["id"] for check in result["checks"] if not check["passed"]}
    assert result["status"] == "blocked"
    assert {"frozen-split", "p95-latency", "held-out-parity"} <= failed


def test_admission_requires_artifact_and_exact_source_sha(tmp_path) -> None:
    missing = evaluate_experience_quality_admission(tmp_path)
    assert missing["status"] == "blocked"
    assert missing["checks"][0]["id"] == "artifact"

    _write(tmp_path, _payload())
    mismatch = evaluate_experience_quality_admission(
        tmp_path,
        expected_source_sha="b" * 40,
    )
    assert "source-sha" in {
        check["id"] for check in mismatch["checks"] if not check["passed"]
    }


def test_cli_writes_admission_artifacts_and_fails_when_blocked(tmp_path) -> None:
    output = tmp_path / "admission.json"
    markdown = tmp_path / "admission.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind.cli",
            "experience-quality-admission",
            "--root",
            str(tmp_path),
            "--write-artifacts",
            "--fail-on-blocked",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "blocked"
    assert json.loads(output.read_text(encoding="utf-8"))["admitted"] is False
    assert "# Experienced Work Agent Admission" in markdown.read_text(
        encoding="utf-8"
    )
