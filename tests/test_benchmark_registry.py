import json
import os
import subprocess
import sys
from pathlib import Path


def test_benchmark_matrix_contains_implemented_and_public_benchmarks():
    from benchmarks.benchmark_registry import build_benchmark_matrix

    payload = build_benchmark_matrix()
    entries = {entry["id"]: entry for entry in payload["benchmarks"]}

    assert payload["schema"] == "wavemind.benchmark_matrix.v1"
    assert payload["generated_at"].endswith("Z")
    assert isinstance(payload["source_ref"], str)
    assert payload["refresh_profile"]
    assert entries["agent_memory_static_chroma"]["status"] == "implemented"
    assert entries["dynamic_memory_policy"]["status"] == "implemented"
    assert entries["field_memory_dynamics"]["status"] == "implemented"
    assert entries["long_memory_evidence_synthetic"]["status"] == "implemented"
    assert "Static vector" in entries["long_memory_evidence_synthetic"]["competitors"]
    assert entries["beir_style_open_retrieval"]["status"] == "implemented"
    assert "Qdrant" in entries["beir_style_open_retrieval"]["competitors"]
    assert entries["beir_style_open_retrieval"]["current"]["WaveMind"]["ndcg_at_k"] > 0
    assert entries["locomo_evidence_retrieval"]["status"] == "implemented"
    assert entries["locomo_evidence_retrieval"]["current"]["WaveMind"]["evidence_recall_at_k"] > 0
    assert entries["beir"]["status"] == "planned"
    assert entries["miracl_ru"]["category"] == "multilingual-retrieval"
    assert entries["vectordbbench"]["category"] == "vector-db"
    assert entries["vectordbbench"]["status"] == "runner-ready"
    assert entries["vectordbbench"]["current"]["WaveMind custom dataset export"]["status"] == "ready"
    assert entries["vectordbbench"]["current"]["WaveMind custom dataset export"]["vectors"] == 10000
    assert entries["longmemeval_evidence_retrieval"]["status"] == "implemented"
    assert entries["ann_index_curve"]["status"] == "implemented"
    assert entries["production_load_profile_100k"]["status"] == "implemented"
    assert entries["production_load_profile_100k"]["current"]["Qdrant service"]["recall_at_k"] >= 0.9
    assert entries["production_load_profile_100k"]["current"]["Qdrant service"]["slo_status"] == "pass"
    assert entries["production_load_profile_100k"]["current"]["Qdrant service"]["slo_required_replicas"] >= 1
    assert (
        entries["production_load_profile_100k"]["current"]["Qdrant service"][
            "compute_cost_per_1m_queries_usd"
        ]
        > 0
    )
    assert (
        entries["production_load_profile_100k"]["current"]["Qdrant service"][
            "monthly_total_cost_at_target_qps_usd"
        ]
        > 0
    )
    assert entries["production_load_profile_1m"]["status"] == "implemented"
    assert entries["production_load_profile_1m"]["current"]["WaveMind faiss-persisted"]["recall_at_k"] == 1.0
    assert entries["production_load_profile_1m"]["current"]["WaveMind faiss-persisted"]["p99_latency_ms"] < 100.0
    assert entries["production_load_profile_1m"]["current"]["WaveMind faiss-persisted"]["cost_status"] == "valid_slo"
    assert entries["production_load_profile_1m"]["current"]["Qdrant service"]["recall_at_k"] > 0
    assert entries["production_load_profile_1m"]["current"]["Qdrant service"]["slo_status"] == "fail"
    assert (
        entries["production_load_profile_1m"]["current"]["Qdrant service"][
            "cost_status"
        ]
        == "invalid_slo"
    )
    assert entries["production_load_qdrant_1m_ef_sweep"]["current"]["hnsw_ef=2048"]["slo_status"] == "fail"
    assert entries["production_streaming_load_runner"]["status"] == "implemented"
    streaming = entries["production_streaming_load_runner"]["current"]["10k smoke / WaveMind numpy-streaming"]
    assert streaming["target_recall_at_k"] >= 0.95
    assert streaming["slo_status"] in {"pass", "scale_required", "fail"}
    ten_million = entries["production_streaming_load_runner"]["current"][
        "10M compressed / WaveMind faiss-ivfpq-persisted streaming"
    ]
    assert ten_million["target_recall_at_k"] >= 0.95
    assert ten_million["p99_latency_ms"] < 100.0
    assert ten_million["cost_status"] == "valid_slo"
    assert entries["production_readiness_gate"]["status"] == "implemented"
    readiness = entries["production_readiness_gate"]["current"]["WaveMind production readiness"]
    assert readiness["overall_status"] == "pass"
    assert readiness["readiness_score"] == 1.0
    assert readiness["action_required_count"] == 0
    assert entries["local_http_cluster_smoke"]["status"] == "implemented"
    local_http = entries["local_http_cluster_smoke"]["current"]["WaveMind local HTTP cluster smoke"]
    assert local_http["success_rate"] == 1.0
    assert local_http["slo_pass"] is True
    assert local_http["read_fanout"] == 1
    serverless = entries["scale_readiness"]["current"]["WaveMind serverless plan"]
    assert serverless["scale_to_zero"] is True
    assert serverless["uses_postgres"] is True
    assert serverless["valid_keda_scale_target"] is True
    structured = entries["scale_readiness"]["current"]["WaveMind structured payloads"]
    assert structured["cross_modal_precision_at_1"] == 1.0
    assert structured["cross_modal_provenance_rate"] == 1.0
    assert structured["cross_modal_embedding_dim"] >= 64
    assert structured["cross_modal_vectors_persisted_rate"] == 1.0
    assert structured["precomputed_vector_precision_at_1"] == 1.0
    assert structured["precomputed_vector_persisted_rate"] == 1.0
    assert structured["precomputed_vector_embedding_dim"] == 4
    assert entries["memory_competitor_adapter_profile"]["status"] == "implemented"
    assert entries["memory_competitor_adapter_profile"]["current"]["WaveMind"]["stale_suppression"] >= 0.8
    assert entries["longmemeval_answer_generation"]["status"] == "implemented"
    assert entries["longmemeval_answer_generation"]["current"]["WaveMind + qwen2.5:1.5b"]["queries"] == 50
    assert entries["lmeb"]["source_url"].startswith("https://")


def test_benchmark_registry_cli_writes_machine_readable_json(tmp_path):
    output = tmp_path / "benchmark-matrix.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/benchmark_registry.py",
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

    assert payload["schema"] == "wavemind.benchmark_matrix.v1"
    assert any(entry["id"] == "ragbench" for entry in payload["benchmarks"])
    assert any(entry["status"] == "implemented" for entry in payload["benchmarks"])
    assert any(entry["status"] == "planned" for entry in payload["benchmarks"])
