import json
import subprocess
import sys
from pathlib import Path

from wavemind.memory_os_evolution import (
    MEMORY_OS_EVOLUTION_SCHEMA,
    render_memory_os_policy_evolution_markdown,
    run_memory_os_policy_evolution,
)


def test_memory_os_policy_evolution_detects_repeated_policy_history():
    payload = run_memory_os_policy_evolution(
        namespace="tenant:evolution-test",
        cycles=3,
        query_repetitions=1,
        target_memories=2_000_000,
        namespace_count=4096,
        node_count=4,
        target_qps=1000,
        target_p99_ms=80,
        observed_p99_ms=220,
    )

    assert payload["schema"] == MEMORY_OS_EVOLUTION_SCHEMA
    assert payload["status"] == "pass"
    assert payload["ok"] is True
    assert payload["summary"]["decision_coverage_rate"] == 1.0
    assert payload["summary"]["repeated_required_cycle_count"] >= 2
    assert payload["summary"]["history_suggestion_count"] >= 1
    assert payload["summary"]["escalation_action_count"] >= 1
    assert "scale-policy" in payload["summary"]["scheduler_policy_escalation_ids"]
    assert payload["summary"]["scheduler_history_previous_runs"] >= 3
    assert "prefetch-policy" in payload["summary"]["stable_ok_ids"]
    assert payload["summary"]["prewarm_warmed"] >= 1
    assert payload["summary"]["predictive_prefetch_warmed"] >= 1
    assert payload["summary"]["priority_predictions"] >= 1
    assert payload["schedule_plan"]["effective_cache_mode"] == "redis"
    assert "memory-os" in payload["schedule_plan"]["enabled_task_ids"]
    assert "policy evolution" in payload["claim_boundary"].lower()


def test_memory_os_policy_evolution_markdown_includes_cycle_table():
    payload = run_memory_os_policy_evolution(cycles=3)

    markdown = render_memory_os_policy_evolution_markdown(payload)

    assert "# WaveMind Memory OS Policy Evolution" in markdown
    assert "scheduler escalations" in markdown
    assert "| cycle | policy | repeated required | stable ok | actions |" in markdown
    assert "scale-policy" in markdown


def test_memory_os_policy_evolution_cli_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "memory_os_policy_evolution_results.json"
    markdown = tmp_path / "MEMORY_OS_POLICY_EVOLUTION.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "memory-os-evolution",
            "--cycles",
            "3",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    stdout_payload = json.loads(result.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "pass"
    assert file_payload["schema"] == MEMORY_OS_EVOLUTION_SCHEMA
    assert "WaveMind Memory OS Policy Evolution" in markdown.read_text(encoding="utf-8")


def test_memory_os_policy_evolution_cli_fail_gate_passes_when_green(tmp_path):
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "memory-os-evolution",
            "--cycles",
            "3",
            "--fail-on-action-required",
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "pass"
