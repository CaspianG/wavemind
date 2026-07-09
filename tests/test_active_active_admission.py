import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_active_active_admission,
    render_active_active_admission_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS",
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON",
    ):
        env.pop(key, None)
    return env


def test_active_active_admission_blocks_without_external_region_evidence():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=False,
        env={},
    )

    assert payload["schema"] == "wavemind.active_active_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "external_active_active_evidence_required"
    assert payload["required_evidence"]["id"] == "external_http_active_active"
    assert payload["required_evidence"]["status"] == "action_required"
    assert payload["required_evidence"]["artifact"] == (
        "benchmarks/external_http_active_active_results.json"
    )
    assert "WAVEMIND_ACTIVE_ACTIVE_REGIONS" in payload["summary"]["missing_env"]
    assert any("strict_status=action_required" in item for item in payload["issues"])


def test_active_active_admission_allows_plan_only_reporting():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "action_required"
    assert payload["summary"]["preflight_status"] == "action_required"
    assert payload["next_actions"]


def test_active_active_admission_markdown_documents_claim_boundary():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )
    markdown = render_active_active_admission_markdown(payload)

    assert "# WaveMind Active-Active Admission" in markdown
    assert "remote multi-region active-active" in markdown
    assert "benchmarks/external_http_active_active_results.json" in markdown
    assert "Local loopback profiles" in markdown


def test_active_active_admission_cli_writes_artifacts(tmp_path):
    output = tmp_path / "active-active.json"
    markdown_output = tmp_path / "active-active.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "active-active-admission",
            "--root",
            str(PROJECT_ROOT),
            "--allow-plan-only",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "plan_only"
    assert file_payload["schema"] == "wavemind.active_active_admission.v1"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Active-Active Admission"
    )


def test_active_active_admission_cli_fail_on_blocked_exits_nonzero(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "active-active-admission",
            "--root",
            str(PROJECT_ROOT),
            "--fail-on-blocked",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
