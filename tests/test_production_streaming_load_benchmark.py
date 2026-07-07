import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


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
    monkeypatch.delenv("WAVEMIND_FAISS_IVFPQ_PATH", raising=False)
    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)

    payload = run_streaming_load(
        sizes=[64],
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        engines=["faiss-persisted", "faiss-ivfpq-persisted", "qdrant-service"],
    )

    rows = {row["engine"]: row for row in payload["results"][0]["results"]}
    assert rows["WaveMind faiss-persisted streaming"]["skipped"] is True
    assert "WAVEMIND_FAISS_PATH" in rows["WaveMind faiss-persisted streaming"]["reason"]
    assert rows["WaveMind faiss-ivfpq-persisted streaming"]["skipped"] is True
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in rows["WaveMind faiss-ivfpq-persisted streaming"]["reason"]
    assert rows["Qdrant service streaming"]["skipped"] is True
    assert "WAVEMIND_QDRANT_URL" in rows["Qdrant service streaming"]["reason"]
    assert rows["WaveMind faiss-persisted streaming"]["slo_status"] == "skipped"
    assert rows["WaveMind faiss-ivfpq-persisted streaming"]["cost_status"] == "skipped"
    assert rows["Qdrant service streaming"]["cost_status"] == "skipped"


def test_streaming_load_faiss_ivfpq_smoke(tmp_path, monkeypatch):
    pytest.importorskip("faiss")

    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    index_path = tmp_path / "streaming-ivfpq.faiss"
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_PATH", str(index_path))
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NLIST", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_M", "2")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NBITS", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NPROBE", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", "12000")

    payload = run_streaming_load(
        sizes=[1024],
        dim=8,
        query_count=16,
        top_k=10,
        seed=13,
        noise=0.0,
        batch_size=256,
        engines=["faiss-ivfpq-persisted"],
    )

    row = payload["results"][0]["results"][0]
    assert row["engine"] == "WaveMind faiss-ivfpq-persisted streaming"
    assert row["faiss_index"] == "IndexIVFPQ"
    assert row["target_recall_at_k"] >= 0.95
    assert row["ivfpq_nprobe"] == 8
    assert index_path.exists()


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


def test_streaming_load_plan_only_estimates_50m_without_generating_vectors(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_FAISS_IVFPQ_PATH", raising=False)

    payload = plan_streaming_load(
        sizes=[50_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["faiss-ivfpq-persisted"],
        output_path=Path("benchmarks/production_streaming_load_50m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_ivfpq_50m_results.json"),
    )

    assert payload["schema"] == "wavemind.production_streaming_load_plan.v1"
    assert payload["scenario"]["plan_only"] is True
    assert payload["scenario"]["sizes"] == [50_000_000]
    assert payload["status"] == "action_required"
    row = payload["plans"][0]
    assert row["vectors"] == 50_000_000
    assert row["engine"] == "WaveMind faiss-ivfpq-persisted streaming"
    assert row["estimated_index_gb"] > 0
    assert row["estimated_index_gb"] < row["estimated_application_storage_gb"]
    assert row["required_local_free_gb"] > row["estimated_index_gb"]
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in row["required_env"]
    assert "missing_env:WAVEMIND_FAISS_IVFPQ_PATH" in row["blockers"]
    assert "--sizes 50000000" in row["command"]
    assert "--engines faiss-ivfpq-persisted" in row["command"]
    assert "--output benchmarks" in row["command"]
    assert "production_streaming_load_ivfpq_50m_results.json" in row["command"]
    assert row["claim_boundary"].startswith("preflight only")


def test_streaming_load_plan_only_cli_writes_json(tmp_path):
    output = tmp_path / "streaming-load-plan.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("WAVEMIND_FAISS_IVFPQ_PATH", None)

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_streaming_load_benchmark.py",
            "--plan-only",
            "--sizes",
            "50000000",
            "--dim",
            "128",
            "--queries",
            "100",
            "--top-k",
            "10",
            "--batch-size",
            "100000",
            "--engines",
            "faiss-ivfpq-persisted",
            "--output",
            str(output),
            "--planned-result-output",
            "benchmarks/production_streaming_load_ivfpq_50m_results.json",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "wavemind.production_streaming_load_plan.v1"
    assert payload["plans"][0]["vectors"] == 50_000_000
    assert payload["plans"][0]["status"] == "action_required"
    assert "production_streaming_load_ivfpq_50m_results.json" in payload["plans"][0]["command"]
