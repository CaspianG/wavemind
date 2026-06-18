import json
import os
import subprocess
import sys
from pathlib import Path


def test_agent_memory_scenario_has_requested_shape():
    from benchmarks.agent_memory_benchmark import build_agent_memory_scenario

    scenario = build_agent_memory_scenario()
    fact_ids = {fact.id for fact in scenario.facts}

    assert len(scenario.facts) == 200
    assert len(scenario.queries) == 50
    assert len(fact_ids) == 200
    assert all(query.expected_id in fact_ids for query in scenario.queries)
    assert any("бюджет" in query.text.lower() for query in scenario.queries)
    assert any("зовут" in query.text.lower() for query in scenario.queries)


def test_agent_memory_metrics_use_expected_fact_in_top_k():
    from benchmarks.agent_memory_benchmark import AgentQuery, compute_metrics

    queries = [
        AgentQuery(id="q1", text="как зовут пользователя?", expected_id="fact_name"),
        AgentQuery(id="q2", text="что знаем про бюджет?", expected_id="fact_budget"),
    ]
    rankings = {
        "q1": ["fact_name", "fact_role", "fact_budget"],
        "q2": ["fact_role", "fact_budget", "fact_name"],
    }

    metrics = compute_metrics(queries, rankings, [1.0, 3.0])

    assert metrics.precision_at_1 == 0.5
    assert metrics.precision_at_3 == 1.0
    assert metrics.avg_latency_ms == 2.0


def test_agent_memory_benchmark_cli_writes_json_for_wavemind(tmp_path):
    output = tmp_path / "agent-memory-result.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/agent_memory_benchmark.py",
            "--engines",
            "wavemind",
            "--facts",
            "20",
            "--queries",
            "5",
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

    assert payload["scenario"]["facts"] == 20
    assert payload["scenario"]["queries"] == 5
    assert payload["results"][0]["engine"] == "WaveMind"
    assert "precision_at_1" in payload["results"][0]
    assert "avg_latency_ms" in payload["results"][0]
