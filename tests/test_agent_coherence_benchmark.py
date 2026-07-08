import json
import subprocess
import sys
from pathlib import Path

from benchmarks.agent_coherence_benchmark import (
    build_agent_coherence_scenario,
    compute_agent_metrics,
    run_benchmark,
)


def test_agent_coherence_scenario_contains_dynamic_memory_tasks():
    scenario = build_agent_coherence_scenario(memory_count=80)
    categories = {task.category for task in scenario.tasks}

    assert len(scenario.memories) == 80
    assert len(scenario.tasks) >= 10
    assert {"correction", "ttl", "namespace", "personalization"}.issubset(categories)
    assert any(memory.ttl_seconds == 0 for memory in scenario.memories)
    assert any(memory.namespace == "agent-b" for memory in scenario.memories)


def test_agent_metrics_track_success_stale_errors_and_context_savings():
    scenario = build_agent_coherence_scenario(memory_count=40)
    namespace_by_id = {memory.id: memory.namespace for memory in scenario.memories}
    rankings = {
        task.id: list(task.expected_ids or ())[:1]
        for task in scenario.tasks
    }
    for task in scenario.tasks:
        if task.id == "t05_expired":
            rankings[task.id] = ["expired_token"]
    returned_texts = {
        task.id: ["compact evidence text"]
        for task in scenario.tasks
    }

    metrics = compute_agent_metrics(
        scenario=scenario,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=[1.0 for _ in scenario.tasks],
        top_k=5,
        engine="test",
        namespace_by_id=namespace_by_id,
    )

    assert metrics.task_success_rate < 1.0
    assert metrics.stale_error_rate > 0.0
    assert metrics.context_budget_saved > 0.5
    assert metrics.coherent_turns >= 1


def test_agent_coherence_benchmark_wave_outperforms_static_on_agent_tasks():
    payload = run_benchmark(
        engines=["wavemind", "static"],
        memory_count=80,
        encoder_kind="hash",
        top_k=5,
    )
    results = {row["engine"]: row for row in payload["results"]}

    assert payload["schema"] == "wavemind.agent_coherence_benchmark.v1"
    assert payload["generated_at"].endswith("Z")
    assert results["WaveMind"]["task_success_rate"] >= results["Static vector"]["task_success_rate"]
    assert results["WaveMind"]["stale_error_rate"] <= results["Static vector"]["stale_error_rate"]
    assert results["WaveMind"]["context_budget_saved"] >= 0.5


def test_agent_coherence_benchmark_memory_os_reports_agent_quality_signals():
    payload = run_benchmark(
        engines=["wavemind-memory-os", "static"],
        memory_count=80,
        encoder_kind="hash",
        top_k=5,
    )
    results = {row["engine"]: row for row in payload["results"]}
    memory_os = results["WaveMind + Memory OS"]["memory_os"]

    assert results["WaveMind + Memory OS"]["task_success_rate"] >= results["Static vector"]["task_success_rate"]
    assert results["WaveMind + Memory OS"]["stale_error_rate"] <= results["Static vector"]["stale_error_rate"]
    assert results["WaveMind + Memory OS"]["context_budget_saved"] >= 0.5
    assert memory_os["worker_ok"] is True
    assert memory_os["scanned_events"] >= 4
    assert memory_os["prewarm_warmed"] >= 1
    assert memory_os["predictive_prefetch_generated"] >= 1
    assert memory_os["predictive_prefetch_warmed"] >= 1
    assert memory_os["priority_predictions"] >= 1
    assert memory_os["cache_hits"] >= 1
    assert memory_os["cache_hit_rate"] > 0.0
    assert memory_os["policy_status"] in {"ok", "watch", "action_required", "architecture_required"}
    assert "prewarm_cache" in memory_os["actions"]


def test_agent_coherence_cli_writes_json(tmp_path):
    output = tmp_path / "agent_coherence.json"
    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/agent_coherence_benchmark.py",
            "--memories",
            "80",
            "--engines",
            "wavemind",
            "wavemind-memory-os",
            "static",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "task success" in completed.stdout
    assert payload["generated_at"].endswith("Z")
    assert payload["scenario"]["name"] == "agent_coherence"
    assert {row["engine"] for row in payload["results"]} == {
        "WaveMind",
        "WaveMind + Memory OS",
        "Static vector",
    }
    memory_os = next(
        row["memory_os"]
        for row in payload["results"]
        if row["engine"] == "WaveMind + Memory OS"
    )
    assert memory_os["worker_ok"] is True
