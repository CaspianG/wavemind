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


def test_zep_live_adapter_with_fake_client():
    from benchmarks.memory_competitor_benchmark import CHECKS, run_zep

    class FakeMemory:
        def __init__(self):
            self.sessions = {}
            self.deleted = []

        def add_session(self, *, session_id, user_id, metadata):
            self.sessions[session_id] = {"user_id": user_id, "messages": []}

        def add(self, session_id, *, messages):
            self.sessions[session_id]["messages"].extend(messages)

        def search_sessions(self, *, session_ids, text, limit, search_scope, search_type):
            expected = {
                "current city": ["new_city"],
                "current job": ["new_role"],
                "budget": ["budget"],
                "assistant answer": ["style"],
                "temporary login token": ["active_token"],
                "blue-114": [],
            }
            wanted = []
            for needle, ids in expected.items():
                if needle in text:
                    wanted = ids
                    break
            messages = []
            for session_id in session_ids:
                for message in self.sessions[session_id]["messages"]:
                    if message["metadata"]["benchmark_id"] in wanted:
                        messages.append({"message": message})
            return {"results": messages[:limit]}

        def delete(self, session_id):
            self.deleted.append(session_id)

    class FakeClient:
        def __init__(self):
            self.memory = FakeMemory()
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeClient()
    result = run_zep(
        client_factory=lambda: fake,
        message_factory=lambda **kwargs: kwargs,
    )

    assert result["engine"] == "Zep"
    assert result["configured"] is True
    assert result["precision_at_1"] == 1.0
    assert result["precision_at_3"] == 1.0
    assert result["stale_suppression"] == 1.0
    assert len(fake.memory.deleted) >= len({check.namespace for check in CHECKS})
    assert fake.closed is True


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
