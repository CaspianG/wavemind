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
    assert criteria["production_100k_slo_cost"]["status"] == "pass"
    assert criteria["production_1m_slo"]["status"] == "pass"
    assert criteria["production_1m_query_depth"]["status"] == "pass"
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
    assert "required" in criteria["operator_autoscaling_repair"]["evidence"]
    assert "status Ready" in criteria["operator_autoscaling_repair"]["evidence"]
    assert criteria["memory_os_worker"]["status"] == "pass"
    assert "predictive prewarm" in criteria["memory_os_worker"]["requirement"]
    assert "usage-pattern priority boosts" in criteria["memory_os_worker"]["requirement"]
    assert "adaptive forgetting" in criteria["memory_os_worker"]["requirement"]
    assert "priority predictions" in criteria["memory_os_worker"]["evidence"]
    assert "predictive warmed" in criteria["memory_os_worker"]["evidence"]
    assert "forgetting demotions" in criteria["memory_os_worker"]["evidence"]
    assert "production architecture advice" in criteria["memory_os_worker"]["requirement"]
    assert "architecture architecture_required" in criteria["memory_os_worker"]["evidence"]
    assert criteria["query_vector_cache"]["status"] == "pass"
    assert "encoded query vectors" in criteria["query_vector_cache"]["requirement"]
    assert "local encode calls 1" in criteria["query_vector_cache"]["evidence"]
    assert criteria["shared_rate_limiter"]["status"] == "pass"
    assert "one shared request budget" in criteria["shared_rate_limiter"]["requirement"]
    assert "limited 1" in criteria["shared_rate_limiter"]["evidence"]
    assert criteria["redis_shared_cache_memory_os"]["status"] == "pass"
    assert "shareable across workers" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert "architecture advice" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert "predictive warmed" in criteria["redis_shared_cache_memory_os"]["evidence"]
    assert "architecture architecture_required" in criteria["redis_shared_cache_memory_os"]["evidence"]
    assert criteria["api_cache_mutation_safety"]["status"] == "pass"
    assert "cannot leave stale cached recall" in criteria["api_cache_mutation_safety"]["requirement"]
    assert criteria["real_redis_api_load_ci"]["status"] == "pass"
    assert "multiple uvicorn workers" in criteria["real_redis_api_load_ci"]["requirement"]
    assert "success_rate 1.0" in criteria["real_redis_api_load_ci"]["evidence"]
    assert criteria["real_local_http_cluster_ci"]["status"] == "pass"
    assert "multiple real localhost WaveMind API processes" in criteria["real_local_http_cluster_ci"]["requirement"]
    assert "health True" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert "degraded 0" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert "slo True" in criteria["real_local_http_cluster_ci"]["evidence"]
    assert criteria["distributed_http_shard_transport"]["status"] == "pass"
    assert criteria["sustained_http_cluster_load"]["status"] == "pass"
    assert "mixed write/query/failover" in criteria["sustained_http_cluster_load"]["requirement"]
    assert "success 1.0" in criteria["sustained_http_cluster_load"]["evidence"]
    assert criteria["replicated_runtime_loss"]["status"] == "pass"
    assert "concurrent read/write traffic" in criteria["replicated_runtime_loss"]["requirement"]
    assert "concurrent hit rate" in criteria["replicated_runtime_loss"]["evidence"]
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
    assert criteria["ten_million_load_profile"]["status"] == "pass"
    assert criteria["architecture_advisor_preflight"]["status"] == "pass"
    assert "10M production targets" in criteria["architecture_advisor_preflight"]["requirement"]
    assert payload["external_evidence"][0]["id"] == "memory_competitor_adapters"
    assert payload["external_evidence"][0]["status"] == "action_required"


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
    assert payload["summary"]["total_criteria"] == 28
    assert "# WaveMind Production Readiness Gate" in report
    assert "100k service-backed load profile passes SLO and cost gate" in report
    assert "VectorDBBench custom dataset export is reproducible" in report
    assert "Cluster autoscaler plans node additions within headroom" in report
    assert "Control-plane consensus blocks split-brain config changes" in report
    assert "Query-vector cache avoids repeated encoder work" in report
    assert "Redis-compatible shared rate limiter works across workers" in report
    assert "Redis-compatible shared cache and Memory OS prewarm work" in report
    assert "API cache does not serve stale memory after mutations" in report
    assert "Real Redis multi-process API load passes SLO" in report
    assert "Real local HTTP cluster smoke passes SLO" in report
    assert "Sustained HTTP cluster load survives failover and repair" in report
    assert "Architecture advisor blocks unsafe large production growth" in report
    assert "Non-Gating External Evidence" in report
