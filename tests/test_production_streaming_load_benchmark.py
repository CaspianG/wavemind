import json
import os
import subprocess
import sys
from pathlib import Path


def test_streaming_load_numpy_smoke_and_slo():
    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    payload = run_streaming_load(
        sizes=[256],
        dim=16,
        query_count=8,
        top_k=3,
        seed=7,
        noise=0.01,
        batch_size=64,
        engines=["numpy-streaming"],
    )

    assert payload["scenario"]["name"] == "production_streaming_load_profile"
    assert payload["scenario"]["default_target_sizes"] == [10_000_000, 50_000_000]
    assert payload["scenario"]["target_recall_definition"].startswith("source id")
    row = payload["results"][0]["results"][0]
    assert row["engine"] == "WaveMind numpy-streaming"
    assert row["target_recall_at_k"] == 1.0
    assert row["recall_at_k"] == row["target_recall_at_k"]
    assert row["queries"] == 8
    assert row["slo_status"] in {"pass", "scale_required", "fail"}
    assert row["compute_cost_per_1m_queries_usd"] > 0


def test_streaming_load_skips_unconfigured_service_engines(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    monkeypatch.delenv("WAVEMIND_FAISS_PATH", raising=False)
    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)

    payload = run_streaming_load(
        sizes=[64],
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        engines=["faiss-persisted", "qdrant-service"],
    )

    rows = {row["engine"]: row for row in payload["results"][0]["results"]}
    assert rows["WaveMind faiss-persisted streaming"]["skipped"] is True
    assert "WAVEMIND_FAISS_PATH" in rows["WaveMind faiss-persisted streaming"]["reason"]
    assert rows["Qdrant service streaming"]["skipped"] is True
    assert "WAVEMIND_QDRANT_URL" in rows["Qdrant service streaming"]["reason"]
    assert rows["WaveMind faiss-persisted streaming"]["slo_status"] == "skipped"
    assert rows["Qdrant service streaming"]["cost_status"] == "skipped"


def test_streaming_load_cli_writes_json(tmp_path):
    output = tmp_path / "streaming-load.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_streaming_load_benchmark.py",
            "--sizes",
            "128",
            "--dim",
            "12",
            "--queries",
            "6",
            "--top-k",
            "3",
            "--batch-size",
            "32",
            "--engines",
            "numpy-streaming",
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
    assert payload["scenario"]["name"] == "production_streaming_load_profile"
    assert payload["scenario"]["vector_dim"] == 12
    assert payload["results"][0]["vectors"] == 128
    assert payload["results"][0]["results"][0]["target_recall_at_k"] >= 0.95
