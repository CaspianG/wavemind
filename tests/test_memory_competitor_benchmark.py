import json
import os
import subprocess
import sys
from pathlib import Path


def test_memory_competitor_profile_runs_wavemind_and_reports_missing_adapters():
    from benchmarks.memory_competitor_benchmark import run_benchmark

    payload = run_benchmark(["wavemind", "mem0", "zep", "langgraph"])

    assert payload["scenario"]["name"] == "memory_competitor_adapter_profile"
    results = {result["engine"]: result for result in payload["results"]}
    assert results["WaveMind"]["precision_at_1"] >= 0.8
    assert results["WaveMind"]["stale_suppression"] >= 0.8
    assert "Mem0" in results
    assert "Zep" in results
    assert "LangGraph persistent memory" in results
    assert results["Mem0"].get("skipped") in {True, None}


def test_memory_competitor_cli_writes_json(tmp_path):
    output = tmp_path / "memory-competitors.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/memory_competitor_benchmark.py",
            "--engines",
            "wavemind",
            "mem0",
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
    assert payload["scenario"]["checks"] == 6
    assert payload["results"][0]["engine"] == "WaveMind"
    assert payload["results"][1]["engine"] == "Mem0"
