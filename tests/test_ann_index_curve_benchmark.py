import json
import os
import subprocess
import sys
from pathlib import Path


def test_ann_curve_runner_produces_exact_numpy_result():
    from benchmarks.ann_index_curve_benchmark import run_benchmark

    payload = run_benchmark(
        sizes=[40],
        dim=16,
        query_count=5,
        top_k=3,
        seed=7,
        engines=["numpy"],
        noise=0.01,
    )

    assert payload["scenario"]["name"] == "ann_index_curve"
    result = payload["results"][0]["results"][0]
    assert result["engine"] == "WaveMind numpy"
    assert result["recall_at_k"] == 1.0
    assert result["avg_latency_ms"] >= 0.0
    assert result["build_ms"] >= 0.0


def test_ann_curve_runner_produces_quantized_result():
    from benchmarks.ann_index_curve_benchmark import run_benchmark

    payload = run_benchmark(
        sizes=[40],
        dim=16,
        query_count=5,
        top_k=3,
        seed=7,
        engines=["quantized"],
        noise=0.01,
    )

    result = payload["results"][0]["results"][0]
    assert result["engine"] == "WaveMind quantized"
    assert result["recall_at_k"] >= 0.8
    assert result["avg_latency_ms"] >= 0.0
    assert result["build_ms"] >= 0.0


def test_ann_curve_runner_reports_missing_optional_faiss_without_fallback():
    from benchmarks.ann_index_curve_benchmark import run_benchmark

    payload = run_benchmark(
        sizes=[40],
        dim=16,
        query_count=5,
        top_k=3,
        seed=7,
        engines=["faiss"],
        noise=0.01,
    )

    result = payload["results"][0]["results"][0]
    assert result["engine"] == "WaveMind faiss"
    if result.get("skipped"):
        assert "faiss" in result["reason"].lower()
    else:
        assert result["recall_at_k"] == 1.0
        assert result["avg_latency_ms"] >= 0.0


def test_ann_curve_runner_reports_missing_pgvector_dsn_without_fallback(monkeypatch):
    from benchmarks.ann_index_curve_benchmark import run_benchmark

    monkeypatch.delenv("WAVEMIND_PGVECTOR_DSN", raising=False)
    payload = run_benchmark(
        sizes=[40],
        dim=16,
        query_count=5,
        top_k=3,
        seed=7,
        engines=["pgvector"],
        noise=0.01,
    )

    result = payload["results"][0]["results"][0]
    assert result["engine"] == "WaveMind pgvector"
    assert result["skipped"] is True
    assert "WAVEMIND_PGVECTOR_DSN" in result["reason"]


def test_ann_curve_runner_reports_missing_qdrant_service_url(monkeypatch):
    from benchmarks.ann_index_curve_benchmark import run_benchmark

    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)
    payload = run_benchmark(
        sizes=[40],
        dim=16,
        query_count=5,
        top_k=3,
        seed=7,
        engines=["qdrant-service"],
        noise=0.01,
    )

    result = payload["results"][0]["results"][0]
    assert result["engine"] == "Qdrant service"
    assert result["skipped"] is True
    assert "WAVEMIND_QDRANT_URL" in result["reason"]


def test_ann_curve_cli_writes_json(tmp_path):
    output = tmp_path / "ann.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/ann_index_curve_benchmark.py",
            "--sizes",
            "40",
            "--dim",
            "16",
            "--queries",
            "5",
            "--top-k",
            "3",
            "--engines",
            "numpy",
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

    assert payload["scenario"]["sizes"] == [40]
    assert payload["results"][0]["vectors"] == 40
