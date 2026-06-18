import json
import os
import subprocess
import sys
from pathlib import Path


def test_dynamic_memory_scenario_exercises_memory_behaviors():
    from benchmarks.dynamic_memory_benchmark import build_dynamic_memory_scenario

    scenario = build_dynamic_memory_scenario(memory_count=200)
    categories = {check.category for check in scenario.checks}

    assert len(scenario.memories) == 200
    assert len(scenario.checks) >= 8
    assert {"hot_memory", "ttl", "correction", "namespace"}.issubset(categories)
    assert any(memory.ttl_seconds == 0 for memory in scenario.memories)
    assert any(memory.priority >= 5 for memory in scenario.memories)
    assert any(check.forbidden_ids for check in scenario.checks)


def test_dynamic_memory_metrics_track_expected_and_forbidden_results():
    from benchmarks.dynamic_memory_benchmark import DynamicCheck, compute_dynamic_metrics

    checks = [
        DynamicCheck(
            id="q_hot",
            category="hot_memory",
            text="How should the assistant answer?",
            namespace="agent-a",
            expected_id="style_hot",
        ),
        DynamicCheck(
            id="q_ttl",
            category="ttl",
            text="What temporary token is still valid?",
            namespace="agent-a",
            expected_id=None,
            forbidden_ids=("expired_token",),
        ),
    ]
    rankings = {
        "q_hot": ["style_hot", "style_cold"],
        "q_ttl": ["unrelated_fact"],
    }

    metrics = compute_dynamic_metrics(checks, rankings, [2.0, 4.0], engine="unit")

    assert metrics.precision_at_1 == 1.0
    assert metrics.precision_at_3 == 1.0
    assert metrics.suppression_rate == 1.0
    assert metrics.category_success["hot_memory"] == 1.0
    assert metrics.category_success["ttl"] == 1.0
    assert metrics.avg_latency_ms == 3.0


def test_dynamic_memory_benchmark_cli_writes_json_for_wavemind(tmp_path):
    output = tmp_path / "dynamic-memory-result.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/dynamic_memory_benchmark.py",
            "--engines",
            "wavemind",
            "--memories",
            "40",
            "--output",
            str(output),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["scenario"]["name"] == "dynamic_agent_memory"
    assert payload["scenario"]["memories"] == 40
    assert payload["results"][0]["engine"] == "WaveMind"
    assert "suppression_rate" in payload["results"][0]
    assert "category_success" in payload["results"][0]
