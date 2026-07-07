import json
import subprocess
import sys
from pathlib import Path


def test_production_readiness_gate_reports_current_blockers():
    from benchmarks.production_readiness_gate import evaluate_production_readiness

    payload = evaluate_production_readiness()
    criteria = {row["id"]: row for row in payload["criteria"]}

    assert payload["schema"] == "wavemind.production_readiness.v1"
    assert payload["summary"]["pass_count"] >= 14
    assert payload["summary"]["action_required_count"] == 0
    assert payload["summary"]["fail_count"] == 0
    assert payload["overall_status"] == "pass"
    assert criteria["agent_coherence_quality"]["status"] == "pass"
    assert "agent task success" in criteria["agent_coherence_quality"]["requirement"]
    assert "Chroma static" in criteria["agent_coherence_quality"]["evidence"]
    assert "stale error 0.000" in criteria["agent_coherence_quality"]["evidence"]
    assert "context saved 0.931" in criteria["agent_coherence_quality"]["evidence"]
    assert criteria["longmemeval_answer_quality"]["status"] == "pass"
    assert "improves final answers" in criteria["longmemeval_answer_quality"]["requirement"]
    assert "queries 50" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "token F1 0.333" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "answered 0.520" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "grounded 0.520" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "supported 1.000" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "unsupported 0.000" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "faithful 1.000" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "Chroma F1 0.170" in criteria["longmemeval_answer_quality"]["evidence"]
    assert "Qdrant F1 0.170" in criteria["longmemeval_answer_quality"]["evidence"]
    assert criteria["production_100k_slo_cost"]["status"] == "pass"
    assert criteria["production_1m_slo"]["status"] == "pass"
    assert criteria["production_1m_query_depth"]["status"] == "pass"
    assert criteria["persisted_ann_integrity"]["status"] == "pass"
    assert "normalized-vector checksum" in criteria["persisted_ann_integrity"]["requirement"]
    assert "matching-id stale vectors" in criteria["persisted_ann_integrity"]["evidence"]
    assert criteria["vectordbbench_custom_dataset"]["status"] == "pass"
    assert "train/test/neighbors/scalar-label parquet" in criteria["vectordbbench_custom_dataset"]["requirement"]
    assert "vectors 10000" in criteria["vectordbbench_custom_dataset"]["evidence"]
    assert criteria["cluster_ha_placement"]["status"] == "pass"
    assert criteria["cluster_autoscale_planner"]["status"] == "pass"
    assert "required node count" in criteria["cluster_autoscale_planner"]["requirement"]
    assert criteria["control_plane_consensus"]["status"] == "pass"
    assert "majority leadership lease" in criteria["control_plane_consensus"]["requirement"]
    assert "minority blocked True" in criteria["control_plane_consensus"]["evidence"]
    assert criteria["hundred_million_capacity_envelope"]["status"] == "pass"
    assert "100M-memory" in criteria["hundred_million_capacity_envelope"]["title"]
    assert "100000000 memories" in criteria["hundred_million_capacity_envelope"]["evidence"]
    assert criteria["operator_autoscaling_repair"]["status"] == "pass"
    assert "capacity-aware replica reconciliation" in criteria["operator_autoscaling_repair"]["requirement"]
    assert "status conditions" in criteria["operator_autoscaling_repair"]["requirement"]
    assert "control-plane consensus safety" in criteria["operator_autoscaling_repair"]["requirement"]
    assert "required" in criteria["operator_autoscaling_repair"]["evidence"]
    assert "status Ready" in criteria["operator_autoscaling_repair"]["evidence"]
    assert "control-plane True" in criteria["operator_autoscaling_repair"]["evidence"]
    assert criteria["serverless_externalized_state"]["status"] == "pass"
    assert "operational SLO/cold-start/cost profile" in criteria["serverless_externalized_state"]["requirement"]
    assert "observed-telemetry contract" in criteria["serverless_externalized_state"]["requirement"]
    assert "required replicas 4" in criteria["serverless_externalized_state"]["evidence"]
    assert "cold start 1220.0 ms" in criteria["serverless_externalized_state"]["evidence"]
    assert "observed source loopback-api-capacity-estimate" in criteria["serverless_externalized_state"]["evidence"]
    assert "observed replicas" in criteria["serverless_externalized_state"]["evidence"]
    assert "observed pool rps" in criteria["serverless_externalized_state"]["evidence"]
    assert "observed errors 0.0" in criteria["serverless_externalized_state"]["evidence"]
    assert criteria["memory_os_worker"]["status"] == "pass"
    assert "predictive prewarm" in criteria["memory_os_worker"]["requirement"]
    assert "usage-pattern priority boosts" in criteria["memory_os_worker"]["requirement"]
    assert "explicit user recall feedback" in criteria["memory_os_worker"]["requirement"]
    assert "adaptive forgetting" in criteria["memory_os_worker"]["requirement"]
    assert "priority predictions" in criteria["memory_os_worker"]["evidence"]
    assert "predictive warmed" in criteria["memory_os_worker"]["evidence"]
    assert "feedback events" in criteria["memory_os_worker"]["evidence"]
    assert "forgetting demotions" in criteria["memory_os_worker"]["evidence"]
    assert "production architecture advice" in criteria["memory_os_worker"]["requirement"]
    assert "architecture architecture_required" in criteria["memory_os_worker"]["evidence"]
    assert criteria["query_vector_cache"]["status"] == "pass"
    assert "encoded query vectors" in criteria["query_vector_cache"]["requirement"]
    assert "local encode calls 1" in criteria["query_vector_cache"]["evidence"]
    assert criteria["api_batch_query"]["status"] == "pass"
    assert "Batch query API" in criteria["api_batch_query"]["title"]
    assert "HTTP requests 100 -> 1" in criteria["api_batch_query"]["evidence"]
    assert criteria["shared_rate_limiter"]["status"] == "pass"
    assert "one shared request budget" in criteria["shared_rate_limiter"]["requirement"]
    assert "limited 1" in criteria["shared_rate_limiter"]["evidence"]
    assert criteria["redis_shared_cache_memory_os"]["status"] == "pass"
    assert "shareable across workers" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert "architecture advice" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert "useful/not-useful recall feedback" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert "predictive warmed" in criteria["redis_shared_cache_memory_os"]["evidence"]
    assert "feedback events" in criteria["redis_shared_cache_memory_os"]["evidence"]
    assert "architecture architecture_required" in criteria["redis_shared_cache_memory_os"]["evidence"]
    assert criteria["api_cache_mutation_safety"]["status"] == "pass"
    assert "feedback" in criteria["api_cache_mutation_safety"]["requirement"]
    assert "feedback invalidation True" in criteria["api_cache_mutation_safety"]["evidence"]
    assert criteria["batch_recall_feedback"]["status"] == "pass"
    assert "feedback in batches" in criteria["batch_recall_feedback"]["requirement"]
    assert "accepted 2" in criteria["batch_recall_feedback"]["evidence"]
    assert "rejected 1" in criteria["batch_recall_feedback"]["evidence"]
    assert "cache invalidated True" in criteria["batch_recall_feedback"]["evidence"]
    assert criteria["real_redis_api_load_ci"]["status"] == "pass"
    assert "multiple uvicorn workers" in criteria["real_redis_api_load_ci"]["requirement"]
    assert "batch feedback" in criteria["real_redis_api_load_ci"]["requirement"]
    assert "success_rate 1.0" in criteria["real_redis_api_load_ci"]["evidence"]
    assert "batch accepted 2" in criteria["real_redis_api_load_ci"]["evidence"]
    assert "batch rejected 1" in criteria["real_redis_api_load_ci"]["evidence"]
    assert "batch cache invalidated True" in criteria["real_redis_api_load_ci"]["evidence"]
    assert criteria["real_local_http_cluster_ci"]["status"] == "pass"
    assert "multiple real localhost WaveMind API processes" in criteria["real_local_http_cluster_ci"]["requirement"]
    assert "health True" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert "degraded 0" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert "slo True" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert criteria["real_http_active_active_ci"]["status"] == "pass"
    assert "real WaveMind API region processes" in criteria["real_http_active_active_ci"]["requirement"]
    assert "regions 3" in criteria["real_http_active_active_ci"]["evidence"]
    assert "convergence 1.0" in criteria["real_http_active_active_ci"]["evidence"]
    assert "delete suppression 1.0" in criteria["real_http_active_active_ci"]["evidence"]
    assert "final noop 0" in criteria["real_http_active_active_ci"]["evidence"]
    assert "slo True" in criteria["real_http_active_active_ci"]["evidence"]
    assert criteria["distributed_http_shard_transport"]["status"] == "pass"
    assert criteria["sustained_http_cluster_load"]["status"] == "pass"
    assert "mixed write/query/failover" in criteria["sustained_http_cluster_load"]["requirement"]
    assert "success 1.0" in criteria["sustained_http_cluster_load"]["evidence"]
    assert criteria["replicated_runtime_loss"]["status"] == "pass"
    assert "concurrent read/write traffic" in criteria["replicated_runtime_loss"]["requirement"]
    assert "concurrent hit rate" in criteria["replicated_runtime_loss"]["evidence"]
    assert criteria["active_active_field_crdt"]["status"] == "pass"
    assert "Multi-region memory deltas" in criteria["active_active_field_crdt"]["requirement"]
    assert "sustained regions 3" in criteria["active_active_field_crdt"]["evidence"]
    assert "sustained convergence 1.0" in criteria["active_active_field_crdt"]["evidence"]
    assert "sustained delete suppression 1.0" in criteria["active_active_field_crdt"]["evidence"]
    assert "HTTP service-region convergence 1.0" in criteria["active_active_field_crdt"]["evidence"]
    assert "HTTP final no-op imports 0" in criteria["active_active_field_crdt"]["evidence"]
    assert "actor watermarks" in criteria["active_active_field_crdt"]["requirement"]
    assert "replication lag" in criteria["active_active_field_crdt"]["requirement"]
    assert "watermarks 3" in criteria["active_active_field_crdt"]["evidence"]
    assert "watermark health pass" in criteria["active_active_field_crdt"]["evidence"]
    assert "missing detected True" in criteria["active_active_field_crdt"]["evidence"]
    assert "lag detected True" in criteria["active_active_field_crdt"]["evidence"]
    assert criteria["backup_restore_dr"]["status"] == "pass"
    assert "point-in-time recovery" in criteria["backup_restore_dr"]["requirement"]
    assert "append-only mutation journal" in criteria["backup_restore_dr"]["requirement"]
    assert "PITR full True" in criteria["backup_restore_dr"]["evidence"]
    assert "PITR point True" in criteria["backup_restore_dr"]["evidence"]
    assert "journal entries" in criteria["backup_restore_dr"]["evidence"]
    assert "Postgres PITR" in criteria["backup_restore_dr"]["requirement"]
    assert "Postgres PITR ready" in criteria["backup_restore_dr"]["evidence"]
    assert "commands 7" in criteria["backup_restore_dr"]["evidence"]
    assert criteria["structured_multimodal_payloads"]["status"] == "pass"
    assert "3D assets" in criteria["structured_multimodal_payloads"]["requirement"]
    assert "shared cross-modal embedding space" in criteria["structured_multimodal_payloads"]["requirement"]
    assert "externally computed multimodal vectors" in criteria["structured_multimodal_payloads"]["requirement"]
    assert "video" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "graph" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "cross-modal precision@1 1.0" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "vectors persisted 1.0" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "precomputed precision@1 1.0" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "provenance 1.0" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "content-addressed object-store manifests" in criteria["structured_multimodal_payloads"]["requirement"]
    assert "asset manifest verified True" in criteria["structured_multimodal_payloads"]["evidence"]
    assert "asset provenance 1" in criteria["structured_multimodal_payloads"]["evidence"]
    assert criteria["ten_million_load_profile"]["status"] == "pass"
    assert criteria["pgvector_tuning_path"]["status"] == "pass"
    assert "iterative HNSW recall@10 >= 0.95" in criteria["pgvector_tuning_path"]["requirement"]
    assert "iterative recall 0.97" in criteria["pgvector_tuning_path"]["evidence"]
    assert "exact recall 1.0" in criteria["pgvector_tuning_path"]["evidence"]
    assert criteria["qdrant_streaming_path"]["status"] == "pass"
    assert "memory-bounded streaming runner" in criteria["qdrant_streaming_path"]["requirement"]
    assert "smoke recall 1" in criteria["qdrant_streaming_path"]["evidence"]
    assert "missing_env:WAVEMIND_QDRANT_URL" in criteria["qdrant_streaming_path"]["evidence"]
    assert criteria["qdrant_streaming_1m_slo"]["status"] == "pass"
    assert "1M vectors" in criteria["qdrant_streaming_1m_slo"]["requirement"]
    assert "cold p99" in criteria["qdrant_streaming_1m_slo"]["evidence"]
    assert "tuned p99" in criteria["qdrant_streaming_1m_slo"]["evidence"]
    assert "SLO pass" in criteria["qdrant_streaming_1m_slo"]["evidence"]
    assert criteria["pgvector_streaming_path"]["status"] == "pass"
    assert "memory-bounded streaming runner" in criteria["pgvector_streaming_path"]["requirement"]
    assert "smoke recall 1" in criteria["pgvector_streaming_path"]["evidence"]
    assert "missing_env:WAVEMIND_PGVECTOR_DSN" in criteria["pgvector_streaming_path"]["evidence"]
    assert criteria["fifty_million_streaming_preflight"]["status"] == "pass"
    assert "not a completed benchmark" in criteria["fifty_million_streaming_preflight"]["requirement"]
    assert "50000000" not in criteria["fifty_million_streaming_preflight"]["evidence"]
    assert "index" in criteria["fifty_million_streaming_preflight"]["evidence"]
    assert "missing_env:WAVEMIND_FAISS_IVFPQ_PATH" in criteria["fifty_million_streaming_preflight"]["evidence"]
    assert criteria["architecture_advisor_preflight"]["status"] == "pass"
    assert "10M production targets" in criteria["architecture_advisor_preflight"]["requirement"]
    external = {row["id"]: row for row in payload["external_evidence"]}
    assert external["memory_competitor_adapters"]["status"] == "action_required"
    assert external["external_http_cluster_load"]["status"] == "pass"
    cluster_evidence = external["external_http_cluster_load"]["evidence"]
    assert "deployment " in cluster_evidence
    assert "environment local-loopback" in cluster_evidence
    assert "source loopback-api-processes" in cluster_evidence
    assert "namespaces 32" in cluster_evidence
    assert "success 1.0" in cluster_evidence
    assert "failover 1.0" in cluster_evidence
    assert "p99" in cluster_evidence
    assert external["external_http_active_active"]["status"] == "action_required"
    assert "no checked-in external HTTP active-active region result" in external["external_http_active_active"]["evidence"]


def test_production_readiness_gate_cli_writes_json_and_markdown(tmp_path):
    output = tmp_path / "readiness.json"
    markdown = tmp_path / "readiness.md"
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/production_readiness_gate.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = markdown.read_text(encoding="utf-8")

    assert "pass" in completed.stdout
    assert payload["summary"]["total_criteria"] == 39
    assert "# WaveMind Production Readiness Gate" in report
    assert "Agent coherence benchmark proves behavioral lift" in report
    assert "LongMemEval answer generation beats static RAG baselines" in report
    assert "100k service-backed load profile passes SLO and cost gate" in report
    assert "VectorDBBench custom dataset export is reproducible" in report
    assert "Cluster autoscaler plans node additions within headroom" in report
    assert "Control-plane consensus blocks split-brain config changes" in report
    assert "Query-vector cache avoids repeated encoder work" in report
    assert "Batch query API amortizes service recall overhead" in report
    assert "Redis-compatible shared rate limiter works across workers" in report
    assert "Redis-compatible shared cache and Memory OS prewarm work" in report
    assert "transition hit True" in report
    assert "API cache does not serve stale memory after mutations" in report
    assert "Batch recall feedback updates priority, audit, and cache" in report
    assert "Real Redis multi-process API load passes SLO" in report
    assert "Real local HTTP cluster smoke passes SLO" in report
    assert "Sustained HTTP cluster load survives failover and repair" in report
    assert "Active-active sync and field-state CRDT converge" in report
    assert "Postgres PITR ready" in report
    assert "pgvector exact and iterative service profile passes 50k tuning gate" in report
    assert "50M streaming load run has a checked preflight contract" in report
    assert "Qdrant streaming 1M tuned profile passes recall, p99, and cost gate" in report
    assert "pgvector streaming runner has service smoke and 10M preflight" in report
    assert "Architecture advisor blocks unsafe large production growth" in report
    assert "Non-Gating External Evidence" in report
    assert "External HTTP service-node load evidence" in report
    assert "External HTTP active-active region evidence" in report
