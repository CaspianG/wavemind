from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.quality_leadership_admission import (
    DEFAULT_PROTOCOL_PATH,
    GOAL4_ARTIFACT_PATH,
    QUALITY_THRESHOLDS,
    evaluate_quality_leadership_admission,
    quality_leadership_results_from_diagnostics,
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


def _source_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _agent_memory_payload(*, source_sha: str | None = None) -> dict:
    source = source_sha or _source_sha()
    return {
        "schema": "wavemind.agent_memory_advantage_benchmark.v1",
        "status": "pass",
        "source_sha": source,
        "protocol": {
            "measurement_trials": 5,
            "confidence_level": 0.95,
        },
        "results": [
            {
                "engine": "WaveMind Core",
                "status": "pass",
                "task_success_rate": 0.40,
                "stale_error_rate": 0.60,
                "context_budget_saved": 0.50,
                "p95_latency_ms": 10.0,
            },
            {
                "engine": "WaveMind + Memory OS",
                "status": "pass",
                "task_success_rate": 0.80,
                "task_success_ci95": {"lower": 0.70, "upper": 0.90},
                "stale_error_rate": 0.01,
                "stale_error_ci95": {"lower": 0.0, "upper": 0.02},
                "context_budget_saved": 0.40,
                "context_budget_saved_ci95": {"lower": 0.35, "upper": 0.45},
                "p95_latency_ms": 11.0,
            },
        ],
        "skipped": [
            {
                "engine": "Chroma static",
                "status": "skipped",
                "reason": "chromadb_not_installed",
            },
            {
                "engine": "Qdrant static",
                "status": "skipped",
                "reason": "qdrant_client_not_installed",
            },
            {
                "engine": "Mem0 OSS",
                "status": "skipped",
                "reason": "package_not_installed",
            },
            {
                "engine": "LangMem / LangGraph",
                "status": "skipped",
                "reason": "package_not_installed",
            },
        ],
        "paired_lift": {
            "overall_task_success": {"lower": 0.20, "upper": 0.60},
            "categories": {
                "knowledge_update": {"lower": 0.10, "upper": 0.50},
                "workflow_gotcha": {"lower": 0.20, "upper": 0.80},
                "state_tracking": {"lower": 0.0, "upper": 0.10},
            },
        },
    }


def test_checked_in_quality_leadership_admission_blocks_without_new_evidence() -> None:
    payload = evaluate_quality_leadership_admission(root=PROJECT_ROOT)
    rows = {row["id"]: row for row in payload["rows"]}

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert rows["goal4-failure-preserved"]["status"] == "implemented"
    assert rows["protocol-frozen-before-heldout"]["status"] == "blocked"
    assert rows["development-go-no-go"]["status"] == "blocked"
    assert rows["heldout-opened-once"]["status"] == "blocked"


def test_development_results_extract_metrics_but_keep_gate_blocked(tmp_path: Path) -> None:
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(_agent_memory_payload()), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert payload["status"] == "development_blocked"
    assert payload["development_gate"]["status"] == "blocked"
    assert payload["metrics"]["memory_os_uplift_over_core"] == pytest.approx(0.40)
    assert payload["metrics"]["improved_category_count"] == 2
    assert "missing real local competitors" in " ".join(
        payload["development_gate"]["errors"]
    )


def test_development_results_reject_wrong_source_diagnostic(tmp_path: Path) -> None:
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(
        json.dumps(_agent_memory_payload(source_sha="0" * 40)),
        encoding="utf-8",
    )

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert payload["development_gate"]["status"] == "blocked"
    assert any(
        "source SHA mismatch" in error
        for error in payload["development_gate"]["errors"]
    )


def test_development_results_recognizes_real_competitor_families(tmp_path: Path) -> None:
    source = _agent_memory_payload()
    source["results"].extend(
        [
            {
                "engine": "Chroma static",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.40,
                "p95_latency_ms": 2.0,
            },
            {
                "engine": "Mem0 OSS",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.35,
                "p95_latency_ms": 5.0,
            },
            {
                "engine": "LangGraph persistent memory",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.30,
                "p95_latency_ms": 3.0,
            },
        ]
    )
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(source), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert "missing real local competitors" not in " ".join(
        payload["development_gate"]["errors"]
    )


def test_development_results_rejects_competitor_without_same_embedding_proof(
    tmp_path: Path,
) -> None:
    source = _agent_memory_payload()
    source["results"].extend(
        [
            {
                "engine": "Chroma static",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.40,
                "p95_latency_ms": 2.0,
            },
            {
                "engine": "Mem0 OSS",
                "status": "pass",
                "task_success_rate": 0.35,
                "p95_latency_ms": 5.0,
            },
            {
                "engine": "LangGraph persistent memory",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.30,
                "p95_latency_ms": 3.0,
            },
        ]
    )
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(source), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    errors = " ".join(payload["development_gate"]["errors"])
    assert "missing real local competitors" in errors
    assert "mem0_oss" in payload["competitor_runs"][1]["family"]
    assert payload["competitor_runs"][1]["embedding_comparable"] is False


def test_in_repo_development_diagnostic_path_stays_relative() -> None:
    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path="benchmarks/quality_leadership_agent_memory_advantage_dev.json",
    )

    assert (
        payload["development_gate"]["diagnostic"]
        == "benchmarks/quality_leadership_agent_memory_advantage_dev.json"
    )
    assert (
        payload["runs"][0]["artifact"]
        == "benchmarks/quality_leadership_agent_memory_advantage_dev.json"
    )


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
