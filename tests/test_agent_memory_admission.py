from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wavemind.agent_memory_admission import (
    ADVANTAGE_ARTIFACT,
    PUBLIC_ARTIFACTS,
    evaluate_agent_memory_advantage_admission,
    render_agent_memory_advantage_admission_markdown,
)


SHA = "a" * 40


def _write_json(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _advantage_payload() -> dict:
    return {
        "schema": "wavemind.agent_memory_advantage_benchmark.v1",
        "status": "pass",
        "source_sha": SHA,
        "protocol": {
            "measurement_trials": 5,
            "bootstrap_samples": 10_000,
            "confidence_level": 0.95,
            "same_memories": True,
            "same_queries": True,
            "same_embeddings": True,
            "same_top_k": True,
        },
        "results": [
            {
                "engine": "WaveMind Core",
                "status": "pass",
                "task_success_rate": 0.70,
                "stale_error_rate": 0.20,
                "context_budget_saved": 0.50,
                "p95_latency_ms": 10.0,
                "combined_score": 0.70,
            },
            {
                "engine": "WaveMind + Memory OS",
                "status": "pass",
                "task_success_rate": 0.90,
                "stale_error_rate": 0.01,
                "context_budget_saved": 0.55,
                "p95_latency_ms": 11.0,
                "combined_score": 0.87,
            },
            {
                "engine": "Chroma static",
                "status": "pass",
                "task_success_rate": 0.65,
                "stale_error_rate": 0.30,
                "context_budget_saved": 0.50,
                "p95_latency_ms": 2.0,
                "combined_score": 0.65,
            },
        ],
        "paired_lift": {
            "categories": {
                "knowledge_update": {"mean": 0.2, "lower": 0.1, "upper": 0.3},
                "workflow_gotcha": {"mean": 0.3, "lower": 0.2, "upper": 0.4},
            }
        },
        "strongest_local_baseline": {
            "engine": "WaveMind Core",
            "combined_score": 0.70,
            "memory_os_combined_score": 0.87,
            "combined_lift": 0.17,
        },
    }


def _public_payload(query_count: int) -> dict:
    return {
        "source_sha": SHA,
        "scenario": {"queries": query_count},
        "results": [
            {
                "engine": "WaveMind",
                "precision_at_1": 0.70,
            },
            {
                "engine": "WaveMind + Memory OS",
                "precision_at_1": 0.70,
                "execution_mode": "memory_os_direct_feedback_free",
                "worker_runs": 10,
                "worker_errors": 0,
            },
        ],
    }


def _write_passing_evidence(root: Path) -> None:
    _write_json(root, ADVANTAGE_ARTIFACT, _advantage_payload())
    for artifact, min_queries in PUBLIC_ARTIFACTS.values():
        _write_json(root, artifact, _public_payload(min_queries))


def test_admission_blocks_without_required_artifacts(tmp_path):
    payload = evaluate_agent_memory_advantage_admission(
        tmp_path,
        expected_source_sha=SHA,
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["summary"]["public_benchmarks_passed"] == 0
    assert any("missing required artifact" in issue for issue in payload["issues"])


def test_admission_requires_real_static_baseline_and_direct_public_execution(
    tmp_path,
):
    _write_passing_evidence(tmp_path)
    advantage = _advantage_payload()
    advantage["results"] = [
        row for row in advantage["results"] if row["engine"] != "Chroma static"
    ]
    _write_json(tmp_path, ADVANTAGE_ARTIFACT, advantage)
    locomo_path, locomo_queries = PUBLIC_ARTIFACTS["locomo"]
    locomo = _public_payload(locomo_queries)
    locomo["results"][1]["worker_runs"] = 0
    _write_json(tmp_path, locomo_path, locomo)

    payload = evaluate_agent_memory_advantage_admission(
        tmp_path,
        expected_source_sha=SHA,
    )

    assert payload["status"] == "blocked"
    failed = {check["id"] for check in payload["checks"] if not check["passed"]}
    assert "real-static-baseline" in failed
    assert "public-locomo" in failed


def test_admission_admits_complete_same_sha_evidence(tmp_path):
    _write_passing_evidence(tmp_path)

    payload = evaluate_agent_memory_advantage_admission(
        tmp_path,
        expected_source_sha=SHA,
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["public_benchmarks_passed"] == 3
    assert payload["issues"] == []
    markdown = render_agent_memory_advantage_admission_markdown(payload)
    assert "# WaveMind Agent Memory Advantage Admission" in markdown
    assert "Direct public benchmarks: **3/3**" in markdown


def test_admission_rejects_latency_or_source_regression(tmp_path):
    _write_passing_evidence(tmp_path)
    advantage = _advantage_payload()
    advantage["source_sha"] = "b" * 40
    advantage["results"][1]["p95_latency_ms"] = 13.0
    _write_json(tmp_path, ADVANTAGE_ARTIFACT, advantage)

    payload = evaluate_agent_memory_advantage_admission(
        tmp_path,
        expected_source_sha=SHA,
    )

    failed = {check["id"] for check in payload["checks"] if not check["passed"]}
    assert "advantage-source-sha" in failed
    assert "latency" in failed


def test_cli_writes_admission_artifacts_and_enforces_blocked_exit(tmp_path):
    output = tmp_path / "out.json"
    markdown = tmp_path / "out.md"
    command = [
        sys.executable,
        "-m",
        "wavemind.cli",
        "agent-memory-advantage-admission",
        "--root",
        str(tmp_path),
        "--expected-source-sha",
        SHA,
        "--write-artifacts",
        "--fail-on-blocked",
        "--output",
        str(output),
        "--markdown-output",
        str(markdown),
        "--json",
    ]

    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "blocked"
    assert json.loads(output.read_text(encoding="utf-8"))["admitted"] is False
    assert "# WaveMind Agent Memory Advantage Admission" in markdown.read_text(
        encoding="utf-8"
    )
