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
    assert entries["agent_coherence_quality"]["status"] == "implemented"
    assert entries["agent_coherence_quality"]["current"]["WaveMind"]["task_success_rate"] >= 0.8
    assert entries["agent_coherence_quality"]["current"]["WaveMind"]["stale_error_rate"] == 0.0
    assert entries["agent_coherence_quality"]["current"]["Static vector"]["stale_error_rate"] > 0.0
    assert "Chroma static" in entries["agent_coherence_quality"]["competitors"]
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
    assert entries["production_pgvector_tuning_profile"]["status"] == "implemented"
    pgvector_tuning = entries["production_pgvector_tuning_profile"]["current"]
    assert pgvector_tuning["WaveMind pgvector-exact"]["recall_at_k"] == 1.0
    assert pgvector_tuning["WaveMind pgvector-exact"]["p99_latency_ms"] < 100.0
    assert pgvector_tuning["WaveMind pgvector-iterative"]["recall_at_k"] >= 0.95
    assert pgvector_tuning["WaveMind pgvector-iterative"]["p99_latency_ms"] < 100.0
    assert pgvector_tuning["WaveMind pgvector-iterative"]["pgvector_variant"] == "pgvector-iterative"
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
    fifty_million_plan = entries["production_streaming_load_runner"]["current"][
        "50M preflight / WaveMind faiss-ivfpq-persisted streaming"
    ]
    assert fifty_million_plan["status"] == "action_required"
    assert fifty_million_plan["estimated_index_gb"] > 0
    assert fifty_million_plan["estimated_application_storage_gb"] > fifty_million_plan["estimated_index_gb"]
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in fifty_million_plan["missing_env"]
    qdrant_smoke = entries["production_streaming_load_runner"]["current"][
        "Qdrant smoke / Qdrant service streaming"
    ]
    assert qdrant_smoke["target_recall_at_k"] >= 0.95
    assert qdrant_smoke["p99_latency_ms"] < 100.0
    qdrant_plan = entries["production_streaming_load_runner"]["current"][
        "10M Qdrant preflight / Qdrant service streaming"
    ]
    assert qdrant_plan["status"] == "action_required"
    assert qdrant_plan["estimated_index_gb"] == 0.0
    assert "WAVEMIND_QDRANT_URL" in qdrant_plan["missing_env"]
    qdrant_sharded_plan = entries["production_streaming_load_runner"]["current"][
        "10M Qdrant sharded preflight / Qdrant sharded service streaming"
    ]
    assert qdrant_sharded_plan["status"] == "action_required"
    assert qdrant_sharded_plan["estimated_index_gb"] == 0.0
    assert "WAVEMIND_QDRANT_URLS" in qdrant_sharded_plan["missing_env"]
    assert "horizontally sharded Qdrant" in qdrant_sharded_plan["index_mode"]
    qdrant_sharded_100m_plan = entries["production_streaming_load_runner"][
        "current"
    ][
        "100M Qdrant sharded preflight / Qdrant sharded service streaming"
    ]
    assert qdrant_sharded_100m_plan["status"] == "action_required"
    assert qdrant_sharded_100m_plan["vectors"] == 100_000_000
    assert "WAVEMIND_QDRANT_URLS" in qdrant_sharded_100m_plan["missing_env"]
    assert "horizontally sharded Qdrant" in qdrant_sharded_100m_plan["index_mode"]
    qdrant_1m = entries["production_streaming_load_runner"]["current"][
        "1M Qdrant cold / Qdrant service streaming"
    ]
    assert qdrant_1m["target_recall_at_k"] >= 0.95
    assert qdrant_1m["p99_latency_ms"] > 100.0
    qdrant_1m_tuned = entries["production_streaming_load_runner"]["current"][
        "1M Qdrant tuned / Qdrant service streaming"
    ]
    assert qdrant_1m_tuned["target_recall_at_k"] >= 0.95
    assert qdrant_1m_tuned["p99_latency_ms"] < 100.0
    assert qdrant_1m_tuned["slo_status"] == "pass"
    qdrant_sharded_smoke = entries["production_streaming_load_runner"]["current"][
        "Qdrant sharded smoke / Qdrant sharded service streaming"
    ]
    assert qdrant_sharded_smoke["target_recall_at_k"] >= 0.95
    assert qdrant_sharded_smoke["p99_latency_ms"] < 100.0
    assert qdrant_sharded_smoke["slo_status"] == "pass"
    assert qdrant_sharded_smoke["shard_count"] == 2
    pgvector_smoke = entries["production_streaming_load_runner"]["current"][
        "pgvector smoke / WaveMind pgvector streaming"
    ]
    assert pgvector_smoke["target_recall_at_k"] >= 0.95
    assert pgvector_smoke["p99_latency_ms"] < 100.0
    pgvector_plan = entries["production_streaming_load_runner"]["current"][
        "10M pgvector preflight / WaveMind pgvector streaming"
    ]
    assert pgvector_plan["status"] == "action_required"
    assert pgvector_plan["estimated_index_gb"] == 0.0
    assert "WAVEMIND_PGVECTOR_DSN" in pgvector_plan["missing_env"]
    assert "100M" in entries["production_streaming_load_runner"]["dataset"]
    assert "production-streaming-load.yml" in entries["production_streaming_load_runner"]["next_step"]
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
    local_active_active = entries["local_http_active_active_smoke"]["current"][
        "WaveMind real HTTP active-active service-region sync"
    ]
    assert local_active_active["region_count"] == 3
    assert local_active_active["convergence_rate"] == 1.0
    assert local_active_active["delete_suppression_rate"] == 1.0
    assert local_active_active["success_rate"] == 1.0
    assert local_active_active["final_noop_records_imported"] == 0
    assert local_active_active["slo_pass"] is True
    external_http = entries["external_http_cluster_load_runner"]["current"][
        "WaveMind external HTTP cluster load"
    ]
    assert external_http["success_rate"] == 1.0
    assert external_http["failover_hit_rate"] == 1.0
    assert external_http["slo_pass"] is True
    assert external_http["namespaces"] == 32
    assert external_http["read_fanout"] == 1
    external_active_active = entries["external_http_active_active_runner"]["current"][
        "WaveMind real HTTP active-active service-region sync"
    ]
    assert external_active_active["status"] == "action_required"
    assert "real region URLs" in external_active_active["reason"]
    serverless = entries["scale_readiness"]["current"]["WaveMind serverless plan"]
    assert serverless["scale_to_zero"] is True
    assert serverless["uses_postgres"] is True
    assert serverless["valid_keda_scale_target"] is True
    serverless_ops = entries["scale_readiness"]["current"]["WaveMind serverless operational profile"]
    assert serverless_ops["slo_pass"] is True
    assert serverless_ops["external_state_ok"] is True
    assert serverless_ops["scale_to_zero_safe"] is True
    assert serverless_ops["cold_start_budget_ok"] is True
    assert serverless_ops["required_replicas"] == 4
    assert serverless_ops["burst_capacity_rps"] == 256000.0
    assert serverless_ops["cost_ok"] is True
    assert serverless_ops["observed_telemetry_source"] == "loopback-api-capacity-estimate"
    assert serverless_ops["observed_slo_pass"] is True
    assert serverless_ops["observed_requests_per_second"] >= 3040.0
    assert serverless_ops["observed_p99_request_ms"] <= 500.0
    assert serverless_ops["observed_max_replicas"] <= 256
    assert serverless_ops["observed_measured_replicas"] >= 4
    assert serverless_ops["observed_measured_pool_requests_per_second"] > 0.0
    structured = entries["scale_readiness"]["current"]["WaveMind structured payloads"]
    assert structured["cross_modal_precision_at_1"] == 1.0
    assert structured["cross_modal_provenance_rate"] == 1.0
    assert structured["cross_modal_embedding_dim"] >= 64
    assert structured["cross_modal_vectors_persisted_rate"] == 1.0
    assert structured["precomputed_vector_precision_at_1"] == 1.0
    assert structured["precomputed_vector_persisted_rate"] == 1.0
    assert structured["precomputed_vector_embedding_dim"] == 4
    active_active = entries["scale_readiness"]["current"]["WaveMind sustained active-active sync"]
    assert active_active["regions"] == 3
    assert active_active["namespaces"] == 3
    assert active_active["writes"] == 18
    assert active_active["pair_syncs"] == 90
    assert active_active["convergence_rate"] == 1.0
    assert active_active["delete_suppression_rate"] == 1.0
    assert active_active["success_rate"] == 1.0
    assert active_active["final_noop_records_imported"] == 0
    http_active_active = entries["scale_readiness"]["current"]["WaveMind HTTP active-active service-region sync"]
    assert http_active_active["service_boundary"] == "FastAPI TestClient"
    assert http_active_active["regions"] == 3
    assert http_active_active["namespaces"] == 2
    assert http_active_active["convergence_rate"] == 1.0
    assert http_active_active["delete_suppression_rate"] == 1.0
    assert http_active_active["success_rate"] == 1.0
    assert http_active_active["final_noop_records_imported"] == 0
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
