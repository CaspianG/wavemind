import json
import os
import subprocess
import sys
from pathlib import Path


def test_production_load_runner_reports_preflight_and_skips_unconfigured_services(monkeypatch):
    from benchmarks.production_load_benchmark import run_production_load

    monkeypatch.delenv("WAVEMIND_FAISS_PATH", raising=False)
    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)
    monkeypatch.delenv("WAVEMIND_PGVECTOR_DSN", raising=False)

    payload = run_production_load(
        sizes=[32],
        dim=8,
        query_count=4,
        top_k=3,
        seed=11,
        engines=[
            "faiss-persisted",
            "qdrant-service",
            "pgvector",
            "pgvector-exact",
            "pgvector-iterative",
        ],
        noise=0.01,
        output_path=Path("benchmarks/production_load_results.json"),
    )

    assert payload["scenario"]["name"] == "production_load_profile"
    assert payload["scenario"]["default_target_sizes"] == [100000, 1000000]
    assert payload["scenario"]["cost_model"]["replica_hourly_cost_usd"] == 0.25
    assert "preflight" in payload
    results = {result["engine"]: result for result in payload["results"][0]["results"]}
    assert results["WaveMind faiss-persisted"]["skipped"] is True
    assert "WAVEMIND_FAISS_PATH" in results["WaveMind faiss-persisted"]["reason"]
    assert results["WaveMind faiss-persisted"]["slo_status"] == "skipped"
    assert results["WaveMind faiss-persisted"]["cost_status"] == "skipped"
    assert results["Qdrant service"]["skipped"] is True
    assert "WAVEMIND_QDRANT_URL" in results["Qdrant service"]["reason"]
    assert results["Qdrant service"]["slo_status"] == "skipped"
    assert results["WaveMind pgvector"]["skipped"] is True
    assert "WAVEMIND_PGVECTOR_DSN" in results["WaveMind pgvector"]["reason"]
    assert results["WaveMind pgvector"]["slo_status"] == "skipped"
    assert results["WaveMind pgvector-exact"]["skipped"] is True
    assert "WAVEMIND_PGVECTOR_DSN" in results["WaveMind pgvector-exact"]["reason"]
    assert results["WaveMind pgvector-exact"]["slo_status"] == "skipped"
    assert results["WaveMind pgvector-iterative"]["skipped"] is True
    assert "WAVEMIND_PGVECTOR_DSN" in results["WaveMind pgvector-iterative"]["reason"]
    assert results["WaveMind pgvector-iterative"]["slo_status"] == "skipped"
    assert payload["results"][0]["slo"][0]["status"] == "skipped"
    assert payload["results"][0]["cost"][0]["cost_status"] == "skipped"


def test_production_load_slo_gate_classifies_pass_scale_and_fail():
    from benchmarks.production_load_benchmark import evaluate_cost_result, evaluate_slo_result
    from wavemind import ProductionCostTarget, ProductionSLOTarget

    target = ProductionSLOTarget(
        target_recall_at_k=0.95,
        target_p99_ms=100.0,
        target_qps=100.0,
        replicas=3,
        autoscaling_max_replicas=24,
        capacity_headroom=0.70,
    )
    passing = evaluate_slo_result(
        {
            "engine": "fast",
            "recall_at_k": 0.99,
            "avg_latency_ms": 10.0,
            "p99_latency_ms": 40.0,
        },
        target=target,
    )
    assert passing["status"] == "pass"
    assert passing["required_replicas"] == 2
    passing_cost = evaluate_cost_result(
        passing,
        memory_count=100_000,
        vector_dim=128,
        target=ProductionCostTarget(replica_hourly_cost_usd=0.25),
    )
    assert passing_cost["cost_status"] == "valid_slo"
    assert passing_cost["compute_cost_per_1m_queries_usd"] > 0

    scale_required = evaluate_slo_result(
        {
            "engine": "capacity-bound",
            "recall_at_k": 0.99,
            "avg_latency_ms": 50.0,
            "p99_latency_ms": 80.0,
        },
        target=target,
    )
    assert scale_required["status"] == "scale_required"
    assert scale_required["required_replicas"] > 3

    failing = evaluate_slo_result(
        {
            "engine": "not-production-ready",
            "recall_at_k": 0.90,
            "avg_latency_ms": 120.0,
            "p99_latency_ms": 240.0,
        },
        target=ProductionSLOTarget(
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=100.0,
            replicas=3,
            autoscaling_max_replicas=10,
            capacity_headroom=0.70,
        ),
    )
    assert failing["status"] == "fail"
    failing_cost = evaluate_cost_result(
        failing,
        memory_count=1_000_000,
        vector_dim=128,
        target=ProductionCostTarget(replica_hourly_cost_usd=0.25),
    )
    assert failing_cost["cost_status"] == "invalid_slo"
    assert failing["blocking_reasons"] == (
        "recall_below_target",
        "p99_above_target",
        "autoscaling_capacity_below_target_qps",
    )


def test_production_load_cli_writes_json(tmp_path):
    output = tmp_path / "production-load.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_load_benchmark.py",
            "--sizes",
            "32",
            "--dim",
            "8",
            "--queries",
            "4",
            "--top-k",
            "3",
            "--engines",
            "quantized",
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
    assert payload["scenario"]["name"] == "production_load_profile"
    assert payload["scenario"]["slo_targets"]["target_qps"] == 100.0
    assert payload["scenario"]["cost_model"]["storage_gb_monthly_cost_usd"] == 0.1
    assert payload["results"][0]["vectors"] == 32
    assert payload["results"][0]["results"][0]["engine"] == "WaveMind quantized"
    assert payload["results"][0]["results"][0]["slo_status"] in {
        "pass",
        "scale_required",
        "fail",
    }
    assert payload["results"][0]["slo"][0]["engine"] == "WaveMind quantized"
    assert payload["results"][0]["cost"][0]["engine"] == "WaveMind quantized"
    assert payload["results"][0]["results"][0]["compute_cost_per_1m_queries_usd"] > 0
