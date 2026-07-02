import json
import os
import subprocess
import sys
from pathlib import Path


def test_crypto_synthetic_scenario_shape():
    from benchmarks.crypto_pattern_benchmark import build_synthetic_crypto_scenario

    scenario = build_synthetic_crypto_scenario(history_count=50, query_count=20)

    assert len(scenario.memories) == 50
    assert len(scenario.queries) == 20
    assert {item.direction for item in scenario.memories} == {"up", "down", "flat"}
    assert all("future_direction" not in query.text for query in scenario.queries)


def test_crypto_metrics_reward_direction_matches():
    from benchmarks.crypto_pattern_benchmark import build_synthetic_crypto_scenario, compute_metrics

    scenario = build_synthetic_crypto_scenario(history_count=20, query_count=5)
    rankings = {}
    for query in scenario.queries:
        match = next(item.id for item in scenario.memories if item.family == query.expected_family)
        rankings[query.id] = [match]

    metrics = compute_metrics(scenario, rankings, [1.0, 2.0, 3.0, 4.0, 5.0], "test")

    assert metrics.direction_accuracy_at_1 == 1.0
    assert metrics.family_accuracy_at_1 == 1.0
    assert metrics.mean_abs_return_error_bps >= 0.0


def test_crypto_pattern_benchmark_cli_writes_json(tmp_path):
    output = tmp_path / "crypto-patterns.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_pattern_benchmark.py",
            "--engines",
            "wavemind",
            "static",
            "--history",
            "40",
            "--queries",
            "10",
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

    assert payload["scenario"]["name"] == "synthetic_crypto_patterns"
    assert payload["scenario"]["note"].startswith("Synthetic")
    assert [result["engine"] for result in payload["results"]] == ["WaveMind", "Static vector"]
    assert "direction_accuracy_at_1" in payload["results"][0]

