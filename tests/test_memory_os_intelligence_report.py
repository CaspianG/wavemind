import json
import subprocess
import sys
from pathlib import Path


def test_memory_os_intelligence_report_generates_gate_artifacts(tmp_path):
    output = tmp_path / "memory_os_intelligence_results.json"
    markdown_output = tmp_path / "MEMORY_OS_INTELLIGENCE.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/memory_os_intelligence_report.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")

    assert payload["schema"] == "wavemind.memory_os_intelligence_report.v1"
    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["passed_check_count"] == payload["summary"]["check_count"]
    assert payload["summary"]["worker_ok"] is True
    assert payload["summary"]["hot_queries"] >= 2
    assert payload["summary"]["prewarm_warmed"] >= 2
    assert payload["summary"]["predictive_prefetch_warmed"] >= 6
    assert payload["summary"]["transition_prefetch_hit"] is True
    assert payload["summary"]["priority_predictions"] >= 2
    assert payload["summary"]["forgetting_demotions"] >= 1
    assert payload["summary"]["concepts_created"] >= 1
    assert payload["summary"]["concept_recall"] is True
    assert payload["summary"]["policy_decision_count"] >= 6
    assert payload["summary"]["execution_safe_to_run"] is True
    assert payload["summary"]["execution_requires_shared_cache"] is True
    assert payload["summary"]["execution_requires_distributed_lock"] is True
    assert payload["summary"]["redis_memory_os_cross_worker_hit"] is True
    assert payload["summary"]["redis_memory_os_busy_lock_skipped"] is True
    assert payload["summary"]["agent_task_success_rate"] >= 0.9
    assert payload["summary"]["agent_stale_error_rate"] <= 0.05
    assert payload["summary"]["agent_context_budget_saved"] >= 0.9
    assert payload["summary"]["canary_status"] == "pass"
    assert payload["summary"]["canary_admitted"] is True
    assert payload["summary"]["admission_status"] == "plan_only"
    assert payload["summary"]["admission_blocker_count"] >= 1
    assert "distributed lock" in payload["claim_boundary"]
    assert all(check["pass"] for check in payload["checks"])
    assert "# WaveMind Memory OS Intelligence Report" in markdown
    assert "Predictive prefetch" in markdown
    assert "production admission remains plan-only" in markdown


def test_checked_in_memory_os_intelligence_report_is_machine_readable():
    payload = json.loads(
        Path("benchmarks/memory_os_intelligence_results.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = Path("benchmarks/MEMORY_OS_INTELLIGENCE.md").read_text(
        encoding="utf-8"
    )

    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["passed_check_count"] == payload["summary"]["check_count"]
    assert payload["summary"]["admission_status"] == "plan_only"
    assert "shared Redis" in payload["claim_boundary"]
    assert "Memory OS canary passes" in markdown
