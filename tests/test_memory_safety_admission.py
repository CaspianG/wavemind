from __future__ import annotations

import json
import re
import subprocess
import sys

from wavemind.memory_safety_admission import (
    MEMORY_SAFETY_ADMISSION_SCHEMA,
    MEMORY_SAFETY_SUITE_FINGERPRINT,
    evaluate_memory_safety_admission,
    render_memory_safety_admission_markdown,
)


def test_memory_safety_admission_passes_frozen_three_run_gate():
    source_sha = "a" * 40
    payload = evaluate_memory_safety_admission(
        source_sha=source_sha,
        expected_source_sha=source_sha,
    )

    assert payload["schema"] == MEMORY_SAFETY_ADMISSION_SCHEMA
    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["source_sha"] == source_sha
    assert payload["suite"]["fingerprint_sha256"] == (
        MEMORY_SAFETY_SUITE_FINGERPRINT
    )
    assert payload["summary"]["checks_passed"] == 10
    assert payload["summary"]["checks_total"] == 10
    assert payload["summary"]["attack_case_count"] == 375
    assert payload["summary"]["attack_success_rate"] == 0.0
    assert payload["summary"]["benign_acceptance_rate"] == 1.0
    assert payload["summary"]["rollback_parity"] == 1.0
    assert payload["summary"]["provenance_coverage"] == 1.0
    assert len(payload["consecutive_runs"]) == 3
    assert len(
        {
            row["verdict_fingerprint"]
            for row in payload["consecutive_runs"]
        }
    ) == 1
    assert payload["skipped"] == []
    assert len(payload["per_case"]) == 400
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        payload["environment"]["fingerprint_sha256"],
    )
    json.dumps(payload, allow_nan=False)


def test_memory_safety_admission_blocks_source_mismatch():
    payload = evaluate_memory_safety_admission(
        source_sha="a" * 40,
        expected_source_sha="b" * 40,
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert "source SHA" in payload["issues"][0]


def test_memory_safety_admission_markdown_reports_boundary():
    payload = evaluate_memory_safety_admission(source_sha="c" * 40)

    rendered = render_memory_safety_admission_markdown(payload)

    assert "# WaveMind Memory Safety Admission" in rendered
    assert "Attack cases: **375**" in rendered
    assert payload["claim_boundary"] in rendered


def test_memory_safety_admission_cli_writes_strict_artifacts(tmp_path):
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
    ).strip()
    output = tmp_path / "safety.json"
    markdown = tmp_path / "safety.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "memory-safety-admission",
            "--expected-source-sha",
            source_sha,
            "--write-artifacts",
            "--fail-on-blocked",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "admitted"
    assert payload["source_sha"] == source_sha
    assert json.loads(result.stdout)["admitted"] is True
    assert "Memory Safety Admission" in markdown.read_text(encoding="utf-8")
