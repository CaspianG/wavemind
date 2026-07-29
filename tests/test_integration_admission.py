from __future__ import annotations

import json
import re
from pathlib import Path

import wavemind.integration_admission as admission
from wavemind.integration_admission import (
    INTEGRATION_ADMISSION_SCHEMA,
    INTEGRATION_SUITE_FINGERPRINT,
    evaluate_integration_admission,
    render_integration_admission_markdown,
)


def _case(case_id: str) -> dict:
    evidence: dict = {}
    if case_id == "provider-semantic-parity":
        evidence = {"parity": 1.0, "surface_count": 5}
    elif case_id == "portable-bundle-parity":
        evidence = {"parity": 1.0, "idempotent": True}
    elif case_id == "typescript-packed-live-contract":
        evidence = {
            "packed_install": True,
            "live_memory_lifecycle": True,
            "safe_retry": True,
            "mutation_not_retried": True,
            "cancellation": True,
            "concurrent_explanations": 16,
        }
    return {
        "id": case_id,
        "passed": True,
        "status": "pass",
        "evidence": evidence,
        "issue": "",
    }


def _passing_suite(_root: Path, _source_sha: str) -> dict:
    return {
        "status": "admitted",
        "cases": [_case(case_id) for case_id in admission._REQUIRED_CASES],
        "skipped": [],
        "total_seconds": 1.0,
    }


def _available_environment() -> dict:
    payload = {
        "python": "3.11.0",
        "implementation": "CPython",
        "platform": "test",
        "node": "v22.0.0",
        "npm": "10.0.0",
        "provider_modules": {
            module: True for module in admission._REQUIRED_MODULES
        },
        "fingerprint_sha256": "a" * 64,
    }
    return payload


def test_integration_admission_passes_frozen_three_run_gate(monkeypatch):
    monkeypatch.setattr(admission, "_run_suite", _passing_suite)
    monkeypatch.setattr(admission, "_environment", _available_environment)
    source_sha = "b" * 40

    payload = evaluate_integration_admission(
        source_sha=source_sha,
        expected_source_sha=source_sha,
    )

    assert payload["schema"] == INTEGRATION_ADMISSION_SCHEMA
    assert payload["status"] == "admitted"
    assert re.fullmatch(r"[0-9a-f]{40}", payload["source_sha"])
    assert payload["suite"]["fingerprint_sha256"] == (
        INTEGRATION_SUITE_FINGERPRINT
    )
    assert payload["admitted"] is True
    assert payload["suite"]["fingerprint_sha256"] == (
        INTEGRATION_SUITE_FINGERPRINT
    )
    assert payload["summary"]["checks_passed"] == 10
    assert payload["summary"]["checks_total"] == 10
    assert payload["summary"]["case_count"] == 11
    assert payload["summary"]["provider_parity"] == 1.0
    assert payload["summary"]["portable_parity"] == 1.0
    assert len(payload["consecutive_runs"]) == 3
    assert len(
        {
            row["verdict_fingerprint"]
            for row in payload["consecutive_runs"]
        }
    ) == 1
    assert payload["skipped"] == []
    assert len(payload["per_case"]) == 11
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        payload["environment"]["fingerprint_sha256"],
    )
    json.dumps(payload, allow_nan=False)


def test_integration_admission_blocks_source_mismatch(monkeypatch):
    monkeypatch.setattr(admission, "_run_suite", _passing_suite)
    monkeypatch.setattr(admission, "_environment", _available_environment)

    payload = evaluate_integration_admission(
        source_sha="a" * 40,
        expected_source_sha="b" * 40,
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert "source SHA" in payload["issues"][0]


def test_integration_admission_blocks_nondeterministic_verdict(monkeypatch):
    run = 0

    def alternating(root: Path, source_sha: str) -> dict:
        nonlocal run
        payload = _passing_suite(root, source_sha)
        if run == 1:
            payload["cases"][0] = {
                **payload["cases"][0],
                "passed": False,
                "status": "action_required",
            }
            payload["status"] = "blocked"
        run += 1
        return payload

    monkeypatch.setattr(admission, "_run_suite", alternating)
    monkeypatch.setattr(admission, "_environment", _available_environment)

    payload = evaluate_integration_admission(source_sha="c" * 40)

    assert payload["status"] == "blocked"
    assert any(
        check["id"] == "deterministic-verdict" and not check["passed"]
        for check in payload["checks"]
    )


def test_integration_admission_markdown_reports_boundary(monkeypatch):
    monkeypatch.setattr(admission, "_run_suite", _passing_suite)
    monkeypatch.setattr(admission, "_environment", _available_environment)
    payload = evaluate_integration_admission(source_sha="d" * 40)

    rendered = render_integration_admission_markdown(payload)

    assert "# WaveMind Integration Admission" in rendered
    assert "Provider semantic parity: **1.000**" in rendered
    assert payload["claim_boundary"] in rendered


def test_required_ci_runs_exact_sha_integration_admission():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "python -m wavemind integration-admission" in workflow
    assert '--expected-source-sha "${GITHUB_SHA}"' in workflow
    assert "--fail-on-blocked" in workflow
    assert "integration-admission-${{ github.sha }}" in workflow


def test_checked_integration_admission_artifact_is_admitted():
    payload = json.loads(
        Path("benchmarks/integration_admission_results.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["schema"] == INTEGRATION_ADMISSION_SCHEMA
    assert payload["status"] == "admitted"
    assert payload["summary"]["checks_passed"] == 10
    assert payload["summary"]["case_count"] == 11
    assert payload["summary"]["provider_parity"] == 1.0
    assert payload["summary"]["portable_parity"] == 1.0
    assert payload["skipped"] == []
