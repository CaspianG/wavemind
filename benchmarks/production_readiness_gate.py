from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.http_cluster_load_benchmark import validate_external_cluster_payload
from benchmarks.local_http_active_active_smoke import validate_external_active_active_payload
from wavemind import advise_memory_architecture


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_json(path)


def _engine_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(result["engine"]): result
        for result in payload.get("results", [])
        if "engine" in result
    }


def _size_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for size_result in payload.get("results", []):
        for result in size_result.get("results", []):
            if "engine" in result:
                rows[str(result["engine"])] = result
    return rows


def _criterion(
    *,
    criterion_id: str,
    title: str,
    status: str,
    requirement: str,
    evidence: str,
    next_step: str,
) -> dict[str, str]:
    if status not in {"pass", "action_required", "fail"}:
        raise ValueError("status must be pass, action_required, or fail")
    return {
        "id": criterion_id,
        "title": title,
        "status": status,
        "requirement": requirement,
        "evidence": evidence,
        "next_step": next_step,
    }


def _load_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    benchmark_dir = root / "benchmarks"
    return {
        "audit": _load_json(benchmark_dir / "benchmark_artifact_audit.json"),
        "agent_coherence": _load_json(benchmark_dir / "agent_coherence_results.json"),
        "longmemeval_answer": _load_json(benchmark_dir / "longmemeval_answer_qwen25_1_5b_50_results.json"),
        "load_100k": _load_json(benchmark_dir / "production_load_qdrant_100k_tuned_results.json"),
        "load_1m": _load_json(benchmark_dir / "production_load_qdrant_1m_tuned_results.json"),
        "load_1m_faiss": _load_json(benchmark_dir / "production_load_faiss_1m_results.json"),
        "load_1m_ef": _load_json(benchmark_dir / "production_load_qdrant_1m_ef_sweep_results.json"),
        "pgvector_tuning": _load_json(benchmark_dir / "production_pgvector_tuning_results.json"),
        "load_10m": _load_optional_json(benchmark_dir / "production_load_10m_results.json"),
        "load_10m_streaming": _load_optional_json(benchmark_dir / "production_streaming_load_ivfpq_10m_results.json"),
        "load_50m_plan": _load_optional_json(benchmark_dir / "production_streaming_load_50m_plan.json"),
        "qdrant_streaming_smoke": _load_optional_json(benchmark_dir / "production_streaming_load_qdrant_smoke_results.json"),
        "qdrant_streaming_1m": _load_optional_json(benchmark_dir / "production_streaming_load_qdrant_1m_results.json"),
        "qdrant_streaming_1m_tuned": _load_optional_json(benchmark_dir / "production_streaming_load_qdrant_1m_tuned_results.json"),
        "qdrant_streaming_10m_plan": _load_optional_json(benchmark_dir / "production_streaming_load_qdrant_10m_plan.json"),
        "pgvector_streaming_smoke": _load_optional_json(benchmark_dir / "production_streaming_load_pgvector_smoke_results.json"),
        "pgvector_streaming_10m_plan": _load_optional_json(benchmark_dir / "production_streaming_load_pgvector_10m_plan.json"),
        "postgres_pitr": _load_optional_json(benchmark_dir / "postgres_pitr_plan.json"),
        "scale": _load_json(benchmark_dir / "scale_readiness_results.json"),
        "redis_api_load": _load_optional_json(benchmark_dir / "redis_api_load_results.json"),
        "local_http_cluster": _load_optional_json(benchmark_dir / "local_http_cluster_smoke_results.json"),
        "local_http_active_active": _load_optional_json(
            benchmark_dir / "local_http_active_active_smoke_results.json"
        ),
        "external_http_cluster": _load_optional_json(benchmark_dir / "http_cluster_load_results.json"),
        "external_http_active_active": _load_optional_json(
            benchmark_dir / "external_http_active_active_results.json"
        ),
        "competitors": _load_json(benchmark_dir / "memory_competitor_results.json"),
        "vectordbbench_dataset": _load_optional_json(benchmark_dir / "vectordbbench_dataset_manifest.json"),
    }


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def evaluate_production_readiness(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    artifacts = _load_artifacts(root)
    full_check_workflow = _read_optional_text(root / ".github" / "workflows" / "full-check.yml")
    index_source = _read_optional_text(root / "wavemind" / "indexes.py")
    index_tests = _read_optional_text(root / "tests" / "test_indexes_encoders.py")
    persisted_ann_integrity_pass = (
        "_vector_snapshot_checksum" in index_source
        and "vector_checksum" in index_source
        and "checksum_algorithm" in index_source
        and "test_faiss_persisted_index_rebuilds_when_vector_checksum_differs" in index_tests
        and "loaded_from_persisted is False" in index_tests
    )
    redis_api_load_script_exists = (root / "benchmarks" / "redis_api_load_benchmark.py").exists()
    redis_api_load_ci_configured = (
        redis_api_load_script_exists
        and "redis-api-load:" in full_check_workflow
        and "image: redis:7-alpine" in full_check_workflow
        and "benchmarks/redis_api_load_benchmark.py" in full_check_workflow
        and "--batch-size" in full_check_workflow
        and "--fail-on-slo" in full_check_workflow
    )
    redis_api_load = artifacts["redis_api_load"]
    redis_api_load_pass = (
        redis_api_load_ci_configured
        and redis_api_load.get("ok")
        and redis_api_load.get("shared_cache_visible_across_processes")
        and redis_api_load.get("shared_fresh_cache_visible_across_processes")
        and redis_api_load.get("cache_invalidated_on_remember")
        and redis_api_load.get("stale_prevented_after_remember")
        and int(redis_api_load.get("batch_feedback_accepted", 0)) >= 2
        and int(redis_api_load.get("batch_feedback_rejected", 0)) >= 1
        and redis_api_load.get("batch_feedback_shared_cache_visible")
        and redis_api_load.get("batch_feedback_cache_invalidated")
        and redis_api_load.get("batch_feedback_stale_prevented")
        and int(redis_api_load.get("batch_feedback_audit_events", 0)) >= 2
        and float(redis_api_load.get("batch_feedback_positive_priority_delta", 0.0)) > 0.0
        and float(redis_api_load.get("batch_feedback_negative_priority_delta", 0.0)) < 0.0
        and redis_api_load.get("cache_invalidated_on_forget")
        and redis_api_load.get("stale_prevented_after_forget")
        and float(redis_api_load.get("success_rate", 0.0)) >= 1.0
        and float(redis_api_load.get("p99_latency_ms", float("inf"))) <= 1000.0
        and redis_api_load.get("batch_query_success")
        and redis_api_load.get("batch_query_individual_success")
        and int(redis_api_load.get("batch_query_individual_http_requests", 0)) >= 10
        and int(redis_api_load.get("batch_query_batch_http_requests", 999999)) == 1
        and float(redis_api_load.get("batch_query_request_reduction_ratio", 0.0)) >= 0.9
        and float(redis_api_load.get("batch_query_individual_vector_hits", 0.0))
        >= int(redis_api_load.get("batch_query_size", 999999))
        and float(redis_api_load.get("batch_query_batch_vector_hits", 0.0))
        >= int(redis_api_load.get("batch_query_size", 999999))
        and float(redis_api_load.get("batch_query_batch_p99_ms", float("inf"))) <= 1000.0
        and int(redis_api_load.get("workers", 0)) >= 2
    )
    local_http_cluster_script_exists = (root / "benchmarks" / "local_http_cluster_smoke.py").exists()
    local_http_cluster_ci_configured = (
        local_http_cluster_script_exists
        and "local-http-cluster-smoke:" in full_check_workflow
        and "benchmarks/local_http_cluster_smoke.py" in full_check_workflow
        and "--fail-on-slo" in full_check_workflow
    )
    local_http_cluster = _engine_results(artifacts["local_http_cluster"]).get(
        "WaveMind local HTTP cluster smoke",
        {},
    )
    local_http_cluster_pass = (
        local_http_cluster_ci_configured
        and int(local_http_cluster.get("nodes", 0)) >= 4
        and int(local_http_cluster.get("replication_factor", 0)) >= 3
        and int(local_http_cluster.get("read_fanout", 0)) == 1
        and float(local_http_cluster.get("success_rate", 0.0)) >= 1.0
        and float(local_http_cluster.get("write_success_rate", 0.0)) >= 1.0
        and float(local_http_cluster.get("query_hit_rate", 0.0)) >= 1.0
        and float(local_http_cluster.get("failover_hit_rate", 0.0)) >= 1.0
        and float(local_http_cluster.get("forget_success_rate", 0.0)) >= 1.0
        and float(local_http_cluster.get("delete_suppression_rate", 0.0)) >= 1.0
        and local_http_cluster.get("repair_ok")
        and int(local_http_cluster.get("repair_repaired_total", 0)) >= 1
        and local_http_cluster.get("repaired_replica")
        and local_http_cluster.get("cluster_health_ok")
        and int(local_http_cluster.get("healthy_nodes", 0))
        == int(local_http_cluster.get("nodes", 0))
        and int(local_http_cluster.get("degraded_nodes", 1)) == 0
        and int(local_http_cluster.get("unavailable_nodes", 1)) == 0
        and local_http_cluster.get("slo_pass")
        and float(local_http_cluster.get("p99_operation_ms", float("inf"))) <= 1000.0
    )
    local_http_active_active_script_exists = (
        root / "benchmarks" / "local_http_active_active_smoke.py"
    ).exists()
    local_http_active_active_ci_configured = (
        local_http_active_active_script_exists
        and "local-http-active-active-smoke:" in full_check_workflow
        and "benchmarks/local_http_active_active_smoke.py" in full_check_workflow
        and "--fail-on-slo" in full_check_workflow
    )
    local_http_active_active = _engine_results(artifacts["local_http_active_active"]).get(
        "WaveMind real HTTP active-active service-region sync",
        {},
    )
    local_http_active_active_pass = (
        local_http_active_active_ci_configured
        and int(local_http_active_active.get("region_count", 0)) >= 3
        and int(local_http_active_active.get("namespaces", 0)) >= 2
        and int(local_http_active_active.get("pair_syncs", 0)) >= 12
        and int(local_http_active_active.get("cursor_count", 0)) >= 6
        and float(local_http_active_active.get("convergence_rate", 0.0)) >= 1.0
        and float(local_http_active_active.get("delete_suppression_rate", 0.0)) >= 1.0
        and float(local_http_active_active.get("success_rate", 0.0)) >= 1.0
        and int(local_http_active_active.get("failed_pairs", 1)) == 0
        and int(local_http_active_active.get("final_noop_records_imported", 1)) == 0
        and int(local_http_active_active.get("final_noop_failed_pairs", 1)) == 0
        and local_http_active_active.get("slo_pass")
        and float(local_http_active_active.get("p99_operation_ms", float("inf"))) <= 1500.0
    )
    audit = artifacts["audit"]
    agent_coherence = _engine_results(artifacts["agent_coherence"])
    agent_wavemind = agent_coherence.get("WaveMind", {})
    agent_static = agent_coherence.get("Static vector", {})
    agent_chroma = agent_coherence.get("Chroma static", {})
    agent_success = float(agent_wavemind.get("task_success_rate", 0.0))
    static_success = float(agent_static.get("task_success_rate", 0.0))
    chroma_success = float(agent_chroma.get("task_success_rate", 0.0))
    agent_stale_error = float(agent_wavemind.get("stale_error_rate", 1.0))
    agent_context_saved = float(agent_wavemind.get("context_budget_saved", 0.0))
    agent_coherent_turn_rate = float(agent_wavemind.get("coherent_turn_rate", 0.0))
    agent_latency = float(agent_wavemind.get("avg_latency_ms", float("inf")))
    agent_quality_pass = (
        agent_success >= 0.85
        and float(agent_wavemind.get("decision_success_at_1", 0.0)) >= 0.75
        and agent_stale_error <= 0.05
        and agent_context_saved >= 0.85
        and agent_coherent_turn_rate >= 0.60
        and agent_latency <= 10.0
        and agent_success >= static_success + 0.20
        and agent_success >= chroma_success + 0.20
    )
    answer_generation = _engine_results(artifacts["longmemeval_answer"])
    answer_wavemind = answer_generation.get("WaveMind", {})
    answer_chroma = answer_generation.get("Chroma static", {})
    answer_qdrant = answer_generation.get("Qdrant static", {})
    answer_queries = int(answer_wavemind.get("queries", 0))
    answer_exact = float(answer_wavemind.get("exact_match", 0.0))
    answer_contains = float(answer_wavemind.get("contains_answer", 0.0))
    answer_token_f1 = float(answer_wavemind.get("token_f1", 0.0))
    answer_answered = float(answer_wavemind.get("answered_rate", 0.0))
    answer_abstention = float(answer_wavemind.get("abstention_rate", 1.0))
    answer_grounded = float(answer_wavemind.get("grounded_answer_rate", 0.0))
    answer_supported = float(answer_wavemind.get("supported_answer_rate", 0.0))
    answer_unsupported = float(answer_wavemind.get("unsupported_answer_rate", 1.0))
    answer_faithfulness = float(answer_wavemind.get("faithfulness_rate", 0.0))
    answer_evidence_recall = float(answer_wavemind.get("evidence_recall_at_k", 0.0))
    answer_retrieval_ms = float(answer_wavemind.get("avg_retrieval_ms", float("inf")))
    chroma_token_f1 = float(answer_chroma.get("token_f1", 0.0))
    qdrant_token_f1 = float(answer_qdrant.get("token_f1", 0.0))
    chroma_contains = float(answer_chroma.get("contains_answer", 0.0))
    qdrant_contains = float(answer_qdrant.get("contains_answer", 0.0))
    chroma_grounded = float(answer_chroma.get("grounded_answer_rate", 0.0))
    qdrant_grounded = float(answer_qdrant.get("grounded_answer_rate", 0.0))
    answer_quality_pass = (
        answer_wavemind.get("provider") == "ollama"
        and answer_wavemind.get("model") == "qwen2.5:1.5b"
        and answer_queries >= 50
        and answer_exact >= 0.20
        and answer_contains >= 0.35
        and answer_token_f1 >= 0.30
        and answer_answered >= 0.35
        and answer_grounded >= 0.50
        and answer_supported >= 0.95
        and answer_unsupported <= 0.05
        and answer_faithfulness >= 0.95
        and answer_abstention <= 0.60
        and answer_evidence_recall >= 0.85
        and answer_retrieval_ms <= 50.0
        and answer_token_f1 >= chroma_token_f1 + 0.10
        and answer_token_f1 >= qdrant_token_f1 + 0.10
        and answer_contains >= chroma_contains + 0.15
        and answer_contains >= qdrant_contains + 0.15
        and answer_grounded >= chroma_grounded + 0.10
        and answer_grounded >= qdrant_grounded + 0.10
    )
    load_100k = _size_results(artifacts["load_100k"]).get("Qdrant service", {})
    load_1m_qdrant = _size_results(artifacts["load_1m"]).get("Qdrant service", {})
    load_1m_faiss = _size_results(artifacts["load_1m_faiss"]).get("WaveMind faiss-persisted", {})
    load_10m_payloads = [
        artifacts["load_10m"],
        artifacts["load_10m_streaming"],
    ]
    load_10m_candidates = [
        result
        for payload in load_10m_payloads
        for size_result in payload.get("results", [])
        if int(size_result.get("vectors", 0)) >= 10_000_000
        for result in size_result.get("results", [])
        if not result.get("skipped")
    ]
    load_10m = max(
        load_10m_candidates,
        key=lambda row: (
            float(row.get("recall_at_k", 0.0)) >= 0.95,
            float(row.get("p99_latency_ms", float("inf"))) <= 100.0,
            row.get("cost_status") == "valid_slo",
            float(row.get("recall_at_k", 0.0)),
            -float(row.get("p99_latency_ms", float("inf"))),
        ),
        default={},
    )
    load_10m_pass = (
        bool(load_10m)
        and float(load_10m.get("recall_at_k", 0.0)) >= 0.95
        and float(load_10m.get("p99_latency_ms", float("inf"))) <= 100.0
        and load_10m.get("cost_status") == "valid_slo"
    )
    pgvector_tuning_rows = _size_results(artifacts["pgvector_tuning"])
    pgvector_exact = pgvector_tuning_rows.get("WaveMind pgvector-exact", {})
    pgvector_iterative = pgvector_tuning_rows.get("WaveMind pgvector-iterative", {})
    pgvector_reference = pgvector_tuning_rows.get("Qdrant service", {})
    pgvector_latest_size = int(
        (artifacts["pgvector_tuning"].get("results") or [{}])[-1].get("vectors", 0)
    )
    pgvector_tuning_pass = (
        pgvector_latest_size >= 50_000
        and int(pgvector_exact.get("queries", 0)) >= 100
        and int(pgvector_iterative.get("queries", 0)) >= 100
        and float(pgvector_exact.get("recall_at_k", 0.0)) >= 1.0
        and float(pgvector_exact.get("p99_latency_ms", float("inf"))) <= 100.0
        and float(pgvector_iterative.get("recall_at_k", 0.0)) >= 0.95
        and float(pgvector_iterative.get("p99_latency_ms", float("inf"))) <= 100.0
        and float(pgvector_reference.get("recall_at_k", 0.0)) >= 0.95
    )
    load_50m_plan = artifacts["load_50m_plan"]
    load_50m_plan_rows = [
        row
        for row in load_50m_plan.get("plans", [])
        if isinstance(row, dict)
    ]
    load_50m_plan_row = load_50m_plan_rows[0] if load_50m_plan_rows else {}
    load_50m_plan_pass = (
        load_50m_plan.get("schema") == "wavemind.production_streaming_load_plan.v1"
        and load_50m_plan.get("scenario", {}).get("plan_only") is True
        and int(load_50m_plan.get("scenario", {}).get("sizes", [0])[0]) >= 50_000_000
        and load_50m_plan_row.get("engine") == "WaveMind faiss-ivfpq-persisted streaming"
        and int(load_50m_plan_row.get("vectors", 0)) >= 50_000_000
        and float(load_50m_plan_row.get("estimated_index_gb", 0.0)) > 0.0
        and float(load_50m_plan_row.get("estimated_application_storage_gb", 0.0))
        > float(load_50m_plan_row.get("estimated_index_gb", 0.0))
        and "production_streaming_load_ivfpq_50m_results.json"
        in str(load_50m_plan_row.get("command", ""))
        and str(load_50m_plan_row.get("claim_boundary", "")).startswith("preflight only")
        and load_50m_plan_row.get("status") in {"ready", "action_required"}
    )
    qdrant_streaming_smoke = _size_results(artifacts["qdrant_streaming_smoke"]).get(
        "Qdrant service streaming",
        {},
    )
    qdrant_streaming_plan = artifacts["qdrant_streaming_10m_plan"]
    qdrant_streaming_plan_rows = [
        row
        for row in qdrant_streaming_plan.get("plans", [])
        if isinstance(row, dict)
    ]
    qdrant_streaming_plan_row = (
        qdrant_streaming_plan_rows[0] if qdrant_streaming_plan_rows else {}
    )
    qdrant_streaming_pass = (
        bool(qdrant_streaming_smoke)
        and int(qdrant_streaming_smoke.get("vectors", 0)) >= 1000
        and int(qdrant_streaming_smoke.get("queries", 0)) >= 20
        and float(qdrant_streaming_smoke.get("recall_at_k", 0.0)) >= 0.95
        and float(qdrant_streaming_smoke.get("p99_latency_ms", float("inf"))) <= 100.0
        and qdrant_streaming_smoke.get("cost_status") == "valid_slo"
        and qdrant_streaming_plan.get("schema") == "wavemind.production_streaming_load_plan.v1"
        and qdrant_streaming_plan.get("scenario", {}).get("plan_only") is True
        and int(qdrant_streaming_plan.get("scenario", {}).get("sizes", [0])[0]) >= 10_000_000
        and qdrant_streaming_plan_row.get("engine") == "Qdrant service streaming"
        and int(qdrant_streaming_plan_row.get("vectors", 0)) >= 10_000_000
        and float(qdrant_streaming_plan_row.get("estimated_index_gb", 1.0)) == 0.0
        and "production_streaming_load_qdrant_10m_results.json"
        in str(qdrant_streaming_plan_row.get("command", ""))
        and str(qdrant_streaming_plan_row.get("claim_boundary", "")).startswith("preflight only")
    )
    qdrant_streaming_1m = _size_results(artifacts["qdrant_streaming_1m"]).get(
        "Qdrant service streaming",
        {},
    )
    qdrant_streaming_1m_tuned = _size_results(artifacts["qdrant_streaming_1m_tuned"]).get(
        "Qdrant service streaming",
        {},
    )
    qdrant_streaming_1m_tuned_pass = (
        bool(qdrant_streaming_1m_tuned)
        and int(qdrant_streaming_1m_tuned.get("vectors", 0)) >= 1_000_000
        and int(qdrant_streaming_1m_tuned.get("queries", 0)) >= 100
        and float(qdrant_streaming_1m_tuned.get("recall_at_k", 0.0)) >= 0.95
        and float(qdrant_streaming_1m_tuned.get("p99_latency_ms", float("inf"))) <= 100.0
        and qdrant_streaming_1m_tuned.get("cost_status") == "valid_slo"
        and int(qdrant_streaming_1m_tuned.get("warmup_queries", 0)) >= 100
        and float(qdrant_streaming_1m_tuned.get("wait_after_build_seconds", 0.0)) >= 30.0
        and int(qdrant_streaming_1m_tuned.get("upsert_batch_size", 0)) <= 5000
    )
    pgvector_streaming_smoke = _size_results(artifacts["pgvector_streaming_smoke"]).get(
        "WaveMind pgvector streaming",
        {},
    )
    pgvector_streaming_plan = artifacts["pgvector_streaming_10m_plan"]
    pgvector_streaming_plan_rows = [
        row
        for row in pgvector_streaming_plan.get("plans", [])
        if isinstance(row, dict)
    ]
    pgvector_streaming_plan_row = (
        pgvector_streaming_plan_rows[0] if pgvector_streaming_plan_rows else {}
    )
    pgvector_streaming_pass = (
        bool(pgvector_streaming_smoke)
        and int(pgvector_streaming_smoke.get("vectors", 0)) >= 1000
        and int(pgvector_streaming_smoke.get("queries", 0)) >= 20
        and float(pgvector_streaming_smoke.get("recall_at_k", 0.0)) >= 0.95
        and float(pgvector_streaming_smoke.get("p99_latency_ms", float("inf"))) <= 100.0
        and pgvector_streaming_smoke.get("cost_status") == "valid_slo"
        and pgvector_streaming_plan.get("schema") == "wavemind.production_streaming_load_plan.v1"
        and pgvector_streaming_plan.get("scenario", {}).get("plan_only") is True
        and int(pgvector_streaming_plan.get("scenario", {}).get("sizes", [0])[0]) >= 10_000_000
        and pgvector_streaming_plan_row.get("engine") == "WaveMind pgvector streaming"
        and int(pgvector_streaming_plan_row.get("vectors", 0)) >= 10_000_000
        and float(pgvector_streaming_plan_row.get("estimated_index_gb", 1.0)) == 0.0
        and "production_streaming_load_pgvector_10m_results.json"
        in str(pgvector_streaming_plan_row.get("command", ""))
        and str(pgvector_streaming_plan_row.get("claim_boundary", "")).startswith("preflight only")
    )
    load_1m_candidates = [row for row in (load_1m_faiss, load_1m_qdrant) if row]
    load_1m = max(
        load_1m_candidates,
        key=lambda row: (
            float(row.get("recall_at_k", 0.0)) >= 0.95,
            float(row.get("p99_latency_ms", float("inf"))) <= 100.0,
            row.get("cost_status") == "valid_slo",
            float(row.get("recall_at_k", 0.0)),
            -float(row.get("p99_latency_ms", float("inf"))),
        ),
        default={},
    )
    load_1m_queries = max(
        int(artifacts["load_1m"].get("scenario", {}).get("queries_per_size", 0)),
        int(artifacts["load_1m_faiss"].get("scenario", {}).get("queries_per_size", 0)),
    )
    scale = _engine_results(artifacts["scale"])
    competitors = _engine_results(artifacts["competitors"])
    vectordbbench_dataset = artifacts["vectordbbench_dataset"]
    vectordbbench_files = set((vectordbbench_dataset.get("files") or {}).keys())
    vectordbbench_ready = (
        vectordbbench_dataset.get("status") == "ready"
        and int(vectordbbench_dataset.get("dataset", {}).get("vectors", 0)) >= 10_000
        and int(vectordbbench_dataset.get("dataset", {}).get("queries", 0)) >= 100
        and int(vectordbbench_dataset.get("dataset", {}).get("dim", 0)) >= 128
        and int(vectordbbench_dataset.get("dataset", {}).get("top_k", 0)) >= 10
        and {"train", "test", "neighbors", "scalar_labels"}.issubset(vectordbbench_files)
    )

    cluster = scale.get("WaveMind cluster planner", {})
    cluster_autoscaler = scale.get("WaveMind cluster autoscaler", {})
    control_plane = scale.get("WaveMind control-plane consensus", {})
    capacity_100m = scale.get("WaveMind 100M capacity envelope", {})
    operator = scale.get("WaveMind Kubernetes operator", {})
    serverless = scale.get("WaveMind serverless plan", {})
    serverless_ops = scale.get("WaveMind serverless operational profile", {})
    hot_cache = scale.get("WaveMind hot cache", {})
    query_vector_cache = scale.get("WaveMind query vector cache", {})
    api_batch_query = scale.get("WaveMind API batch query", {})
    shared_rate_limiter = scale.get("WaveMind shared rate limiter", {})
    redis_cache = scale.get("WaveMind Redis hot cache", {})
    api_cache_mutations = scale.get("WaveMind API cache mutation safety", {})
    batch_feedback = scale.get("WaveMind batch feedback", {})
    memory_os = scale.get("WaveMind Memory OS", {})
    redis_memory_os_advice_ids = set(
        redis_cache.get("memory_os_architecture_recommendations", [])
    )
    memory_os_advice_ids = set(memory_os.get("architecture_advice_recommendation_ids", []))
    memory_os_architecture_pass = (
        memory_os.get("architecture_advice_status") == "architecture_required"
        and {"service-index", "namespace-sharding", "production-controls"}.issubset(
            memory_os_advice_ids
        )
        and "advise_architecture" in set(memory_os.get("actions", []))
        and int(memory_os.get("architecture_next_commands", 0)) >= 1
    )
    memory_os_suggestion_ids = set(memory_os.get("suggestion_ids", []))
    memory_os_suggestion_severities = set(memory_os.get("suggestion_severities", []))
    memory_os_suggestions_pass = (
        int(memory_os.get("suggestion_count", 0)) >= 5
        and {
            "predictive-prefetch-active",
            "priority-learning-active",
            "adaptive-forgetting-active",
            "architecture:namespace-sharding",
        }.issubset(memory_os_suggestion_ids)
        and "architecture_required" in memory_os_suggestion_severities
        and int(memory_os.get("suggestions_with_evidence", 0)) >= 5
    )
    def has_budget_risk_transition(edges: object) -> bool:
        if not isinstance(edges, list):
            return False
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            if (
                edge.get("from_query") == "budget recall"
                and edge.get("to_query") == "risk limits"
                and float(edge.get("probability", 0.0)) >= 1.0
                and int(edge.get("count", 0)) >= 1
            ):
                return True
        return False

    redis_transition_edge_pass = has_budget_risk_transition(
        redis_cache.get("memory_os_transition_prefetch_edges")
    )
    memory_os_transition_edge_pass = has_budget_risk_transition(
        memory_os.get("transition_prefetch_edges")
    )
    sharding = scale.get("WaveMind distributed sharding", {})
    http_sharding = scale.get("WaveMind distributed HTTP sharding", {})
    sustained_http_cluster = scale.get("WaveMind sustained HTTP cluster load", {})
    runtime = scale.get("WaveMind replicated runtime", {})
    active_active = scale.get("WaveMind active-active delta sync", {})
    sustained_active_active = scale.get("WaveMind sustained active-active sync", {})
    http_active_active = scale.get("WaveMind HTTP active-active service-region sync", {})
    field_crdt = scale.get("WaveMind field-state CRDT", {})
    snapshot = scale.get("WaveMind replicated snapshot", {})
    recovery_journal = scale.get("WaveMind recovery journal", {})
    postgres_pitr = artifacts["postgres_pitr"]
    postgres_pitr_profile = postgres_pitr.get("profile", {})
    postgres_pitr_checks = postgres_pitr_profile.get("validation", {}).get("checks", {})
    postgres_pitr_pass = (
        postgres_pitr.get("status") == "ready"
        and postgres_pitr_profile.get("schema") == "wavemind.postgres_pitr_plan.v1"
        and int(postgres_pitr.get("summary", {}).get("command_count", 0)) >= 7
        and postgres_pitr_checks.get("has_wal_archiving_command")
        and postgres_pitr_checks.get("has_base_backup_command")
        and postgres_pitr_checks.get("has_restore_command")
        and postgres_pitr_checks.get("has_recovery_signal")
        and postgres_pitr_checks.get("has_restore_target_time")
        and postgres_pitr_checks.get("has_replay_verification")
        and postgres_pitr_checks.get("has_promotion_command")
        and postgres_pitr_checks.get("secret_values_not_embedded")
    )
    payloads = scale.get("WaveMind structured payloads", {})
    advisor = advise_memory_architecture(
        {
            "active_memories": 1_000_000,
            "total_memories": 1_000_000,
            "expired_memories": 0,
            "audit_events": 128,
            "index": "faiss-persisted",
            "index_healthy": True,
            "vector_dim": 384,
        },
        target_memories=10_000_000,
        namespace_count=4096,
        node_count=4,
        replication_factor=3,
        deployment="production",
        observed_p99_ms=float(load_10m.get("p99_latency_ms", 60.13) or 60.13),
        target_p99_ms=100.0,
        target_qps=100.0,
        multimodal=True,
    )
    advisor_ids = {recommendation.id for recommendation in advisor.recommendations}
    advisor_pass = (
        advisor.status == "architecture_required"
        and "service-index" in advisor_ids
        and "namespace-sharding" in advisor_ids
        and "capacity-envelope" in advisor_ids
        and "production-controls" in advisor_ids
        and "load-test" in advisor_ids
        and "multimodal-payloads" in advisor_ids
        and any("http_cluster_load_benchmark.py" in command for command in advisor.next_commands)
    )

    skipped_competitors = [
        name
        for name in ("Mem0", "Zep", "LangGraph persistent memory")
        if competitors.get(name, {}).get("skipped")
    ]
    external_cluster_evidence = validate_external_cluster_payload(
        artifacts["external_http_cluster"]
    )
    external_active_active_evidence = validate_external_active_active_payload(
        artifacts["external_http_active_active"]
    )
    external_evidence = [
        {
            "id": "memory_competitor_adapters",
            "title": "Mem0, Zep, and LangGraph adapter evidence",
            "status": "pass" if not skipped_competitors else "action_required",
            "evidence": (
                "all configured"
                if not skipped_competitors
                else "skipped: " + ", ".join(skipped_competitors)
            ),
            "next_step": "Configure ZEP_API_URL or ZEP_API_KEY for a real Zep service and check in the live Zep adapter result.",
        },
        {
            "id": "external_http_cluster_load",
            "title": "External HTTP service-node load evidence",
            "status": external_cluster_evidence["status"],
            "evidence": external_cluster_evidence["evidence"],
            "next_step": external_cluster_evidence["next_step"],
        },
        {
            "id": "external_http_active_active",
            "title": "External HTTP active-active region evidence",
            "status": external_active_active_evidence["status"],
            "evidence": external_active_active_evidence["evidence"],
            "next_step": external_active_active_evidence["next_step"],
        }
    ]

    criteria = [
        _criterion(
            criterion_id="benchmark_artifact_freshness",
            title="Checked-in benchmark artifacts are synchronized",
            status="pass" if audit.get("status") == "pass" else "fail",
            requirement="Benchmark matrix, report, and leaderboard must render from the same checked-in JSON.",
            evidence=f"audit status {audit.get('status')}, generated_at {audit.get('generated_at')}",
            next_step="Keep the benchmark refresh workflow green and block stale artifacts before release.",
        ),
        _criterion(
            criterion_id="agent_coherence_quality",
            title="Agent coherence benchmark proves behavioral lift",
            status="pass" if agent_quality_pass else "fail",
            requirement=(
                "Dynamic memory must improve agent task success, avoid stale "
                "facts, preserve coherent task runs, and save prompt context "
                "against static vector and Chroma-static baselines."
            ),
            evidence=(
                f"WaveMind success {agent_success:.3f}, "
                f"Chroma static {chroma_success:.3f}, "
                f"Static vector {static_success:.3f}, "
                f"stale error {agent_stale_error:.3f}, "
                f"context saved {agent_context_saved:.3f}, "
                f"coherent turn rate {agent_coherent_turn_rate:.3f}, "
                f"avg latency {agent_latency:.3f} ms"
            ),
            next_step=(
                "Keep agent-behavior quality gated in CI and extend it with "
                "LLM answer-quality runs on LoCoMo/LongMemEval."
            ),
        ),
        _criterion(
            criterion_id="longmemeval_answer_quality",
            title="LongMemEval answer generation beats static RAG baselines",
            status="pass" if answer_quality_pass else "fail",
            requirement=(
                "A real local LLM answer-generation run must show WaveMind "
                "improves final answers, not only retrieval: 50+ LongMemEval "
                "questions, stronger answer accuracy/F1 than Chroma and Qdrant "
                "static RAG, high evidence recall, and bounded retrieval latency."
            ),
            evidence=(
                f"{answer_wavemind.get('provider')} {answer_wavemind.get('model')}, "
                f"queries {answer_queries}, "
                f"exact {answer_exact:.3f}, "
                f"contains {answer_contains:.3f}, "
                f"token F1 {answer_token_f1:.3f}, "
                f"answered {answer_answered:.3f}, "
                f"grounded {answer_grounded:.3f}, "
                f"supported {answer_supported:.3f}, "
                f"unsupported {answer_unsupported:.3f}, "
                f"faithful {answer_faithfulness:.3f}, "
                f"abstain {answer_abstention:.3f}, "
                f"evidence recall {answer_evidence_recall:.3f}, "
                f"retrieval {answer_retrieval_ms:.3f} ms, "
                f"Chroma F1 {chroma_token_f1:.3f}, "
                f"Qdrant F1 {qdrant_token_f1:.3f}"
            ),
            next_step=(
                "Scale this from the checked 50-query local run to full "
                "LongMemEval-S with stronger local/API models and faithfulness scoring."
            ),
        ),
        _criterion(
            criterion_id="production_100k_slo_cost",
            title="100k service-backed load profile passes SLO and cost gate",
            status=(
                "pass"
                if load_100k.get("slo_status") == "pass"
                and load_100k.get("cost_status") == "valid_slo"
                else "fail"
            ),
            requirement="recall@10 >= 0.95, p99 <= 100 ms, target QPS capacity available, and cost estimate present.",
            evidence=(
                f"recall {load_100k.get('recall_at_k')}, "
                f"p99 {load_100k.get('p99_latency_ms')} ms, "
                f"cost ${load_100k.get('compute_cost_per_1m_queries_usd'):.2f}/1M queries"
            ),
            next_step="Keep the 100k profile green while adding persisted FAISS and pgvector service runs.",
        ),
        _criterion(
            criterion_id="production_1m_slo",
            title="1M service-backed load profile meets recall and p99 SLO",
            status=(
                "pass"
                if float(load_1m.get("recall_at_k", 0.0)) >= 0.95
                and float(load_1m.get("p99_latency_ms", float("inf"))) <= 100.0
                and load_1m.get("cost_status") == "valid_slo"
                else "action_required"
                if float(load_1m.get("recall_at_k", 0.0)) >= 0.95
                else "fail"
            ),
            requirement="recall@10 >= 0.95 and p99 <= 100 ms at 1M vectors.",
            evidence=(
                f"{load_1m.get('engine')}: recall {load_1m.get('recall_at_k')}, "
                f"p99 {load_1m.get('p99_latency_ms')} ms, "
                f"SLO {load_1m.get('slo_status')}"
            ),
            next_step="Keep FAISS 1M green in CI-capable benchmark environments and continue tuning Qdrant/pgvector service paths.",
        ),
        _criterion(
            criterion_id="production_1m_query_depth",
            title="1M load result has enough query depth for a production claim",
            status="pass" if load_1m_queries >= 100 else "action_required",
            requirement="Use at least 100 queries for checked-in 1M production claims.",
            evidence=f"current tuned 1M profile uses {load_1m_queries} queries",
            next_step="Keep 100+ query depth for all checked-in 1M production profiles.",
        ),
        _criterion(
            criterion_id="persisted_ann_integrity",
            title="Persisted FAISS snapshots validate source-of-truth vectors",
            status="pass" if persisted_ann_integrity_pass else "fail",
            requirement=(
                "Persisted FAISS must treat SQLite/Postgres as the source of "
                "truth, verify id map, vector dimension, vector count, and "
                "normalized-vector checksum, then rebuild stale snapshots."
            ),
            evidence=(
                "source contract _vector_snapshot_checksum + vector_checksum, "
                "regression test rebuilds matching-id stale vectors"
            ),
            next_step=(
                "Keep checksum validation in the FAISS persisted path and add "
                "the same content-integrity contract to future persisted ANN backends."
            ),
        ),
        _criterion(
            criterion_id="pgvector_tuning_path",
            title="pgvector exact and iterative service profile passes 50k tuning gate",
            status="pass" if pgvector_tuning_pass else "action_required",
            requirement=(
                "A real PostgreSQL/pgvector service profile must show exact recall "
                "as the correctness floor and iterative HNSW recall@10 >= 0.95 "
                "with p99 <= 100 ms at 50000 vectors over 100 queries."
            ),
            evidence=(
                f"size {pgvector_latest_size}, "
                f"exact recall {pgvector_exact.get('recall_at_k')}, "
                f"exact p99 {pgvector_exact.get('p99_latency_ms')} ms, "
                f"iterative recall {pgvector_iterative.get('recall_at_k')}, "
                f"iterative p99 {pgvector_iterative.get('p99_latency_ms')} ms, "
                f"Qdrant reference recall {pgvector_reference.get('recall_at_k')}"
            ),
            next_step=(
                "Promote pgvector-iterative into the 100k and 1M production "
                "load SLO profiles after allocating enough disk/build time."
            ),
        ),
        _criterion(
            criterion_id="qdrant_streaming_path",
            title="Qdrant streaming runner has service smoke and 10M preflight",
            status="pass" if qdrant_streaming_pass else "action_required",
            requirement=(
                "Qdrant must have a memory-bounded streaming runner that inserts "
                "vectors in batches, passes a real service smoke, and has a "
                "committed 10M plan-only contract with exact reproduction command."
            ),
            evidence=(
                f"smoke vectors {qdrant_streaming_smoke.get('vectors')}, "
                f"smoke recall {qdrant_streaming_smoke.get('recall_at_k')}, "
                f"smoke p99 {qdrant_streaming_smoke.get('p99_latency_ms')} ms, "
                f"plan status {qdrant_streaming_plan_row.get('status')}, "
                f"plan required local free {qdrant_streaming_plan_row.get('required_local_free_gb')} GB, "
                f"blockers {', '.join(qdrant_streaming_plan_row.get('blockers', [])) or '-'}"
            ),
            next_step=(
                "Run the embedded 10M Qdrant command against a sized Qdrant "
                "service and commit production_streaming_load_qdrant_10m_results.json."
            ),
        ),
        _criterion(
            criterion_id="qdrant_streaming_1m_slo",
            title="Qdrant streaming 1M tuned profile passes recall, p99, and cost gate",
            status="pass" if qdrant_streaming_1m_tuned_pass else "action_required",
            requirement=(
                "A real Qdrant service streaming profile at 1M vectors must use "
                "safe upsert chunks, warm the service, and meet recall@10 >= 0.95, "
                "p99 <= 100 ms, and valid cost SLO over at least 100 queries."
            ),
            evidence=(
                f"cold recall {qdrant_streaming_1m.get('recall_at_k')}, "
                f"cold p99 {qdrant_streaming_1m.get('p99_latency_ms')} ms, "
                f"tuned recall {qdrant_streaming_1m_tuned.get('recall_at_k')}, "
                f"tuned p99 {qdrant_streaming_1m_tuned.get('p99_latency_ms')} ms, "
                f"warmup {qdrant_streaming_1m_tuned.get('warmup_queries')}, "
                f"wait {qdrant_streaming_1m_tuned.get('wait_after_build_seconds')} s, "
                f"upsert chunk {qdrant_streaming_1m_tuned.get('upsert_batch_size')}, "
                f"SLO {qdrant_streaming_1m_tuned.get('slo_status')}"
            ),
            next_step=(
                "Promote the same warmup/chunking profile into the checked 10M "
                "Qdrant service run on storage sized for the index."
            ),
        ),
        _criterion(
            criterion_id="pgvector_streaming_path",
            title="pgvector streaming runner has service smoke and 10M preflight",
            status="pass" if pgvector_streaming_pass else "action_required",
            requirement=(
                "PostgreSQL/pgvector must have a memory-bounded streaming runner "
                "that inserts vectors in batches, passes a real service smoke, "
                "and has a committed 10M plan-only contract with exact reproduction command."
            ),
            evidence=(
                f"smoke vectors {pgvector_streaming_smoke.get('vectors')}, "
                f"smoke recall {pgvector_streaming_smoke.get('recall_at_k')}, "
                f"smoke p99 {pgvector_streaming_smoke.get('p99_latency_ms')} ms, "
                f"plan status {pgvector_streaming_plan_row.get('status')}, "
                f"plan required local free {pgvector_streaming_plan_row.get('required_local_free_gb')} GB, "
                f"blockers {', '.join(pgvector_streaming_plan_row.get('blockers', [])) or '-'}"
            ),
            next_step=(
                "Run the embedded 10M pgvector command against a sized PostgreSQL "
                "service and commit production_streaming_load_pgvector_10m_results.json."
            ),
        ),
        _criterion(
            criterion_id="vectordbbench_custom_dataset",
            title="VectorDBBench custom dataset export is reproducible",
            status="pass" if vectordbbench_ready else "action_required",
            requirement=(
                "A public vector-database comparison path must expose "
                "train/test/neighbors/scalar-label parquet files for an official "
                "VectorDBBench custom dataset run."
            ),
            evidence=(
                f"status {vectordbbench_dataset.get('status')}, "
                f"vectors {vectordbbench_dataset.get('dataset', {}).get('vectors')}, "
                f"queries {vectordbbench_dataset.get('dataset', {}).get('queries')}, "
                f"files {sorted(vectordbbench_files)}"
            ),
            next_step=(
                "Run this custom dataset through official VectorDBBench targets "
                "for Qdrant, Milvus, pgvector, and WaveMind-backed FAISS/Qdrant profiles."
            ),
        ),
        _criterion(
            criterion_id="cluster_ha_placement",
            title="Namespace placement survives node and zone loss",
            status=(
                "pass"
                if cluster.get("node_loss_min_availability") == 1.0
                and cluster.get("zone_loss_min_availability") == 1.0
                else "fail"
            ),
            requirement="Replicated namespace placement must keep availability at 1.0 under node and zone loss simulation.",
            evidence=(
                f"node loss {cluster.get('node_loss_min_availability')}, "
                f"zone loss {cluster.get('zone_loss_min_availability')}, "
                f"namespaces {cluster.get('namespaces')}"
            ),
            next_step="Validate the same placement under live multi-node service load.",
        ),
        _criterion(
            criterion_id="cluster_autoscale_planner",
            title="Cluster autoscaler plans node additions within headroom",
            status=(
                "pass"
                if cluster_autoscaler.get("status") == "scale_required"
                and int(cluster_autoscaler.get("required_nodes", 0))
                > int(cluster_autoscaler.get("current_nodes", 0))
                and cluster_autoscaler.get("target_within_headroom")
                and cluster_autoscaler.get("has_scale_action")
                and cluster_autoscaler.get("rebalance_status") == "ready"
                and cluster_autoscaler.get("rebalance_full_plan")
                and int(cluster_autoscaler.get("rebalance_write_quorum", 0)) >= 2
                and int(cluster_autoscaler.get("rebalance_batches", 0)) >= 1
                and cluster_autoscaler.get("rebalance_all_batches_checkpointed")
                and cluster_autoscaler.get("rebalance_all_batches_repaired")
                and cluster_autoscaler.get("rebalance_all_batches_validated")
                else "fail"
            ),
            requirement=(
                "Autoscale planning must convert target memories, RF, and "
                "per-node capacity into required node count, bounded target "
                "load, and a complete rolling namespace movement plan with "
                "quorum, checkpoint, repair, and validation safeguards."
            ),
            evidence=(
                f"current {cluster_autoscaler.get('current_nodes')}, "
                f"required {cluster_autoscaler.get('required_nodes')}, "
                f"target max {cluster_autoscaler.get('target_max_node_memories')}, "
                f"moves {cluster_autoscaler.get('move_sample')}+{cluster_autoscaler.get('omitted_moves')}, "
                f"rebalance {cluster_autoscaler.get('rebalance_status')}, "
                f"batches {cluster_autoscaler.get('rebalance_batches')}, "
                f"write quorum {cluster_autoscaler.get('rebalance_write_quorum')}"
            ),
            next_step="Connect rolling rebalance execution to operator reconciliation status and real HPA/load metrics.",
        ),
        _criterion(
            criterion_id="control_plane_consensus",
            title="Control-plane consensus blocks split-brain config changes",
            status=(
                "pass"
                if control_plane.get("ok")
                and control_plane.get("stale_leader_blocked")
                and control_plane.get("stale_revision_blocked")
                and control_plane.get("minority_commit_blocked")
                and control_plane.get("membership_committed")
                and control_plane.get("monotonic_terms")
                and control_plane.get("monotonic_revisions")
                and int(control_plane.get("final_revision", 0)) >= 2
                else "fail"
            ),
            requirement=(
                "Cluster membership and operator config changes must require "
                "a majority leadership lease, reject stale leaders, reject stale "
                "config revisions, and block minority partitions."
            ),
            evidence=(
                f"voters {control_plane.get('voters_initial')} -> "
                f"{control_plane.get('voters_after_membership')}, "
                f"term {control_plane.get('lease_term')} -> "
                f"{control_plane.get('new_leader_term')}, "
                f"revision {control_plane.get('final_revision')}, "
                f"minority blocked {control_plane.get('minority_commit_blocked')}"
            ),
            next_step=(
                "Wrap the same majority lease/revision contract around remote "
                "operator membership changes."
            ),
        ),
        _criterion(
            criterion_id="hundred_million_capacity_envelope",
            title="100M-memory capacity envelope is planned across a large cluster",
            status=(
                "pass"
                if capacity_100m.get("valid_capacity_plan")
                and capacity_100m.get("target_memories") == 100_000_000
                and int(capacity_100m.get("node_count", 0)) >= 100
                and capacity_100m.get("node_loss_min_availability") == 1.0
                and capacity_100m.get("zone_loss_min_availability") == 1.0
                and float(capacity_100m.get("replica_load_skew", 99.0)) <= 1.25
                else "action_required"
            ),
            requirement=(
                "The production plan must include a deterministic 100M-memory "
                "capacity envelope with 100+ nodes, RF=3, node/zone-loss "
                "availability, balanced placement, and bounded per-node storage."
            ),
            evidence=(
                f"{capacity_100m.get('target_memories')} memories, "
                f"{capacity_100m.get('node_count')} nodes, "
                f"RF {capacity_100m.get('replication_factor')}, "
                f"replica skew {capacity_100m.get('replica_load_skew')}, "
                f"max storage/node {capacity_100m.get('max_storage_per_node_gb')} GB"
            ),
            next_step=(
                "Promote this envelope from deterministic planning to a real "
                "100M service-backed Qdrant/pgvector/FAISS load run on sized hardware."
            ),
        ),
        _criterion(
            criterion_id="operator_autoscaling_repair",
            title="Kubernetes operator bundle includes HPA and repair job",
            status=(
                "pass"
                if operator.get("bundle_has_crd")
                and operator.get("has_hpa")
                and operator.get("has_rebalance_configmap")
                and operator.get("has_repair_cronjob")
                and operator.get("has_memory_os_cronjob")
                and int(operator.get("statefulset_replicas", 0))
                == int(operator.get("capacity_required_replicas", -1))
                and int(operator.get("capacity_target_max_node_memories", 0)) <= 700_000
                and operator.get("rebalance_status") in {"ready", "ok"}
                and operator.get("rebalance_full_plan")
                and int(operator.get("rebalance_move_count", 0)) >= 1
                and int(operator.get("rebalance_batches", 0)) >= 1
                and int(operator.get("rebalance_write_quorum", 0)) >= 2
                and operator.get("rebalance_checkpoint_required")
                and operator.get("rebalance_repair_required")
                and operator.get("rebalance_validation_required")
                and operator.get("status_ready")
                and operator.get("status_phase") == "Ready"
                and int(operator.get("status_ready_replicas", 0))
                == int(operator.get("statefulset_replicas", -1))
                and int(operator.get("status_required_replicas", 0))
                == int(operator.get("statefulset_replicas", -1))
                and operator.get("status_capacity_within_headroom")
                and operator.get("status_rebalance_ready")
                and operator.get("status_rebalance_full_plan")
                and operator.get("status_memory_os_ready")
                and operator.get("status_memory_os_redis_required")
                and operator.get("status_memory_os_redis_configured")
                and operator.get("memory_os_calls_plan")
                and operator.get("memory_os_calls_run")
                and operator.get("memory_os_applies_plan_lock")
                and operator.get("memory_os_blocks_missing_redis")
                and int(operator.get("status_rebalance_move_count", 0))
                == int(operator.get("rebalance_move_count", -1))
                and int(operator.get("status_rebalance_batches", 0))
                == int(operator.get("rebalance_batches", -1))
                and operator.get("control_plane_ready")
                and int(operator.get("control_plane_voters", 0)) >= 3
                and operator.get("control_plane_minority_blocked")
                and set(operator.get("status_conditions_true", []))
                == {
                    "AutoscalingReady",
                    "CapacityPlanned",
                    "ControlPlaneReady",
                    "MemoryOSReady",
                    "RebalancePlanned",
                    "RepairScheduled",
                    "ResourcesReady",
                }
                else "fail"
            ),
            requirement=(
                "Operator output must include CRD, StatefulSet, Service, HPA, "
                "scheduled repair, capacity-aware replica reconciliation, a bounded "
                "rebalance ConfigMap with full rolling namespace-move plan metadata, "
                "Memory OS CronJob plan/run scheduling with Redis/shared-lock safety, "
                "and status conditions for readiness/autoscaling/capacity/rebalance/"
                "repair/Memory OS plus control-plane consensus safety."
            ),
            evidence=(
                f"CRD {operator.get('bundle_has_crd')}, "
                f"HPA {operator.get('has_hpa')}, repair {operator.get('has_repair_cronjob')}, "
                f"memory OS {operator.get('has_memory_os_cronjob')}, "
                f"rebalance config {operator.get('has_rebalance_configmap')}, "
                f"rebalance {operator.get('rebalance_status')} "
                f"{operator.get('rebalance_move_count')} moves/"
                f"{operator.get('rebalance_batches')} batches, "
                f"replicas {operator.get('statefulset_replicas')}, "
                f"required {operator.get('capacity_required_replicas')}, "
                f"target max {operator.get('capacity_target_max_node_memories')}, "
                f"status {operator.get('status_phase')}, "
                f"memory OS ready {operator.get('status_memory_os_ready')}, "
                f"control-plane {operator.get('control_plane_ready')}"
            ),
            next_step="Run a real Kubernetes smoke deploy and patch the same status from live HPA, pod, and leader lease metrics.",
        ),
        _criterion(
            criterion_id="serverless_externalized_state",
            title="Serverless plan externalizes state and validates KEDA target",
            status=(
                "pass"
                if serverless.get("valid_keda_scale_target")
                and serverless.get("uses_postgres")
                and serverless.get("uses_external_qdrant")
                and serverless.get("uses_shared_cache")
                and serverless_ops.get("slo_pass")
                and serverless_ops.get("external_state_ok")
                and serverless_ops.get("scale_out_possible")
                and serverless_ops.get("scale_to_zero_safe")
                and serverless_ops.get("cold_start_budget_ok")
                and serverless_ops.get("cost_ok")
                and serverless_ops.get("observed_telemetry_present")
                and serverless_ops.get("observed_slo_pass")
                else "fail"
            ),
            requirement=(
                "Serverless mode must use external durable state, external vector "
                "index, shared cache, valid KEDA scale target, scale-to-zero-safe "
                "workers, an operational SLO/cold-start/cost profile, and an "
                "observed-telemetry contract for real cluster load tests."
            ),
            evidence=(
                f"Postgres {serverless.get('uses_postgres')}, "
                f"Qdrant {serverless.get('uses_external_qdrant')}, "
                f"Redis {serverless.get('uses_shared_cache')}, "
                f"required replicas {serverless_ops.get('required_replicas')}, "
                f"burst rps {float(serverless_ops.get('burst_capacity_rps') or 0.0):.0f}, "
                f"cold start {float(serverless_ops.get('cold_start_total_ms') or 0.0):.1f} ms, "
                f"cost ${float(serverless_ops.get('monthly_compute_cost_usd') or 0.0):.2f}, "
                f"observed source {serverless_ops.get('observed_telemetry_source')}, "
                f"observed replicas {serverless_ops.get('observed_measured_replicas')}, "
                f"observed pool rps {serverless_ops.get('observed_measured_pool_requests_per_second')}, "
                f"observed p99 {serverless_ops.get('observed_p99_request_ms')} ms, "
                f"observed errors {serverless_ops.get('observed_error_rate')}"
            ),
            next_step="Run the same profile against a real Knative/KEDA cluster and replace loopback telemetry with remote p95/p99/cold-start/error-rate/scale-out metrics.",
        ),
        _criterion(
            criterion_id="hot_cache_prewarm",
            title="Hot cache and query-audit prewarm work",
            status=(
                "pass"
                if float(hot_cache.get("hit_rate", 0.0)) >= 0.8
                and hot_cache.get("prewarm_hit")
                else "fail"
            ),
            requirement="Frequently recalled memory paths must be cacheable and prewarmable.",
            evidence=(
                f"hit rate {hot_cache.get('hit_rate')}, "
                f"prewarm hit {hot_cache.get('prewarm_hit')}, "
                f"p99 {hot_cache.get('p99_lookup_ms')} ms"
            ),
            next_step="Keep local cache prewarm green while Redis carries multi-worker production cache evidence.",
        ),
        _criterion(
            criterion_id="query_vector_cache",
            title="Query-vector cache avoids repeated encoder work",
            status=(
                "pass"
                if int(query_vector_cache.get("local_encode_calls", 999999)) == 1
                and float(query_vector_cache.get("local_hit_rate", 0.0)) >= 0.95
                and query_vector_cache.get("redis_shared_across_workers")
                and int(query_vector_cache.get("redis_encode_calls", 999999)) == 1
                and query_vector_cache.get("service_results_ok")
                and query_vector_cache.get("service_metrics_exposed")
                and int(query_vector_cache.get("service_encoder_calls", 999999)) == 1
                and float(query_vector_cache.get("service_hit_rate", 0.0)) >= 0.95
                and float(query_vector_cache.get("p99_service_query_ms", 999999.0)) < 100.0
                else "fail"
            ),
            requirement=(
                "Repeated hot queries must reuse encoded query vectors locally "
                "across Redis-backed workers, and through the FastAPI service "
                "before hitting the vector index."
            ),
            evidence=(
                f"local encode calls {query_vector_cache.get('local_encode_calls')}, "
                f"local hit rate {query_vector_cache.get('local_hit_rate')}, "
                f"Redis shared {query_vector_cache.get('redis_shared_across_workers')}, "
                f"Redis encode calls {query_vector_cache.get('redis_encode_calls')}, "
                f"service encode calls {query_vector_cache.get('service_encoder_calls')}, "
                f"service hit rate {query_vector_cache.get('service_hit_rate')}, "
                f"service p99 {query_vector_cache.get('p99_service_query_ms')} ms, "
                f"service metrics {query_vector_cache.get('service_metrics_exposed')}"
            ),
            next_step="Run the same service-mode vector-cache profile with a real sentence-transformer encoder on a larger API load test.",
        ),
        _criterion(
            criterion_id="api_batch_query",
            title="Batch query API amortizes service recall overhead",
            status=(
                "pass"
                if api_batch_query.get("batch_success")
                and api_batch_query.get("individual_success")
                and int(api_batch_query.get("batch_http_requests", 999999)) == 1
                and int(api_batch_query.get("individual_http_requests", 0)) >= 100
                and float(api_batch_query.get("request_reduction_ratio", 0.0)) >= 0.99
                and int(api_batch_query.get("batch_encoder_calls", 999999)) == 1
                and float(api_batch_query.get("batch_hit_rate", 0.0)) >= 0.99
                and api_batch_query.get("batch_metrics_exposed")
                else "fail"
            ),
            requirement=(
                "FastAPI must support production batch recall so agents can issue "
                "many memory lookups with one HTTP request while preserving vector-cache reuse."
            ),
            evidence=(
                f"queries {api_batch_query.get('queries')}, "
                f"HTTP requests {api_batch_query.get('individual_http_requests')} -> "
                f"{api_batch_query.get('batch_http_requests')}, "
                f"batch encode calls {api_batch_query.get('batch_encoder_calls')}, "
                f"batch hit rate {api_batch_query.get('batch_hit_rate')}, "
                f"speedup {api_batch_query.get('batch_total_speedup')}, "
                f"metrics {api_batch_query.get('batch_metrics_exposed')}"
            ),
            next_step=(
                "Keep the real Redis multi-process batch recall profile green, "
                "then repeat it with larger batches on remote Kubernetes/serverless nodes."
            ),
        ),
        _criterion(
            criterion_id="shared_rate_limiter",
            title="Redis-compatible shared rate limiter works across workers",
            status=(
                "pass"
                if shared_rate_limiter.get("shared_across_workers")
                and int(shared_rate_limiter.get("workers", 0)) >= 2
                and int(shared_rate_limiter.get("allowed", 0)) == 4
                and int(shared_rate_limiter.get("limited", 0)) == 1
                and int(shared_rate_limiter.get("expire_seconds", 0)) == 120
                else "fail"
            ),
            requirement=(
                "Production API workers must enforce one shared request budget "
                "through Redis instead of separate per-process in-memory buckets."
            ),
            evidence=(
                f"workers {shared_rate_limiter.get('workers')}, "
                f"allowed {shared_rate_limiter.get('allowed')}, "
                f"limited {shared_rate_limiter.get('limited')}, "
                f"shared {shared_rate_limiter.get('shared_across_workers')}"
            ),
            next_step="Run the same shared limiter profile against a live Redis service in multi-worker API load tests.",
        ),
        _criterion(
            criterion_id="redis_shared_cache_memory_os",
            title="Redis-compatible shared cache and Memory OS prewarm work",
            status=(
                "pass"
                if redis_cache.get("shared_cache_visible_across_clients")
                and redis_cache.get("cache_prewarm_cross_worker_hit")
                and redis_cache.get("memory_os_ok")
                and int(redis_cache.get("memory_os_prewarm_warmed", 0)) >= 2
                and int(redis_cache.get("memory_os_predictive_generated", 0)) >= 1
                and int(redis_cache.get("memory_os_predictive_warmed", 0)) >= 1
                and "risk limits"
                in set(redis_cache.get("memory_os_transition_prefetch_queries") or [])
                and redis_cache.get("memory_os_transition_prefetch_hit")
                and redis_transition_edge_pass
                and int(redis_cache.get("memory_os_user_feedback_events", 0)) >= 2
                and float(
                    redis_cache.get("memory_os_positive_feedback_priority_delta", 0.0)
                )
                > 0.0
                and float(
                    redis_cache.get("memory_os_negative_feedback_priority_delta", 0.0)
                )
                < 0.0
                and redis_cache.get("memory_os_lock_required")
                and redis_cache.get("memory_os_lock_acquired")
                and redis_cache.get("memory_os_lock_released")
                and redis_cache.get("memory_os_busy_lock_skipped")
                and redis_cache.get("memory_os_cross_worker_hit")
                and redis_cache.get("namespace_invalidation_removed")
                and redis_cache.get("memory_os_architecture_advice_status")
                == "architecture_required"
                and {"namespace-sharding", "production-controls"}.issubset(
                    redis_memory_os_advice_ids
                )
                else "fail"
            ),
            requirement=(
                "Production cache must be shareable across workers, support "
                "query-audit prewarm, support Memory OS prewarm, guard "
                "adaptive Memory OS mutation cycles with a Redis-compatible "
                "single-flight lock, learn observed follow-up query transitions, apply explicit useful/not-useful recall "
                "feedback, invalidate a namespace after memory changes, and preserve architecture advice for production-scale "
                "deployments."
            ),
            evidence=(
                f"shared {redis_cache.get('shared_cache_visible_across_clients')}, "
                f"prewarm hit {redis_cache.get('cache_prewarm_cross_worker_hit')}, "
                f"Memory OS warmed {redis_cache.get('memory_os_prewarm_warmed')}, "
                f"predictive warmed {redis_cache.get('memory_os_predictive_warmed')}, "
                f"transition hit {redis_cache.get('memory_os_transition_prefetch_hit')}, "
                f"transition queries {redis_cache.get('memory_os_transition_prefetch_queries')}, "
                f"transition edge {redis_transition_edge_pass}, "
                f"feedback events {redis_cache.get('memory_os_user_feedback_events')}, "
                f"lock acquired {redis_cache.get('memory_os_lock_acquired')}, "
                f"busy skipped {redis_cache.get('memory_os_busy_lock_skipped')}, "
                f"Memory OS hit {redis_cache.get('memory_os_cross_worker_hit')}, "
                f"invalidation {redis_cache.get('namespace_invalidation_removed')}, "
                f"architecture {redis_cache.get('memory_os_architecture_advice_status')}"
            ),
            next_step="Keep the real Redis multi-process API load workflow green.",
        ),
        _criterion(
            criterion_id="api_cache_mutation_safety",
            title="API cache does not serve stale memory after mutations",
            status=(
                "pass"
                if api_cache_mutations.get("first_query_cached")
                and api_cache_mutations.get("cache_invalidated_on_remember")
                and api_cache_mutations.get("stale_prevented_after_remember")
                and api_cache_mutations.get("cache_invalidated_on_feedback")
                and api_cache_mutations.get("feedback_demoted_rejected_memory")
                and api_cache_mutations.get("cache_invalidated_on_forget")
                and api_cache_mutations.get("stale_prevented_after_forget")
                else "fail"
            ),
            requirement=(
                "FastAPI workers must invalidate shared query cache on remember, "
                "feedback, and forget so mutations cannot leave stale cached recall."
            ),
            evidence=(
                f"cached {api_cache_mutations.get('first_query_cached')}, "
                f"remember invalidation {api_cache_mutations.get('cache_invalidated_on_remember')}, "
                f"remember stale prevented {api_cache_mutations.get('stale_prevented_after_remember')}, "
                f"feedback invalidation {api_cache_mutations.get('cache_invalidated_on_feedback')}, "
                f"feedback demoted {api_cache_mutations.get('feedback_demoted_rejected_memory')}, "
                f"forget invalidation {api_cache_mutations.get('cache_invalidated_on_forget')}, "
                f"forget stale prevented {api_cache_mutations.get('stale_prevented_after_forget')}"
            ),
            next_step="Keep the real Redis multi-process API load workflow green.",
        ),
        _criterion(
            criterion_id="batch_recall_feedback",
            title="Batch recall feedback updates priority, audit, and cache",
            status=(
                "pass"
                if batch_feedback.get("ok")
                and int(batch_feedback.get("accepted", 0)) >= 2
                and int(batch_feedback.get("rejected", 0)) >= 1
                and batch_feedback.get("cache_was_warmed")
                and batch_feedback.get("cache_invalidated")
                and int(batch_feedback.get("audit_events", 0)) >= 2
                and float(batch_feedback.get("positive_feedback_priority_delta", 0.0)) > 0.0
                and float(batch_feedback.get("negative_feedback_priority_delta", 0.0)) < 0.0
                and float(batch_feedback.get("p99_api_ms", float("inf"))) <= 100.0
                else "fail"
            ),
            requirement=(
                "Production agents must record recall feedback in batches, reject "
                "bad namespace items, update positive and negative memory priority, "
                "write audit events, and invalidate shared cache once per affected namespace."
            ),
            evidence=(
                f"accepted {batch_feedback.get('accepted')}, "
                f"rejected {batch_feedback.get('rejected')}, "
                f"cache warmed {batch_feedback.get('cache_was_warmed')}, "
                f"cache invalidated {batch_feedback.get('cache_invalidated')}, "
                f"audit {batch_feedback.get('audit_events')}, "
                f"positive delta {batch_feedback.get('positive_feedback_priority_delta')}, "
                f"negative delta {batch_feedback.get('negative_feedback_priority_delta')}, "
                f"p99 {batch_feedback.get('p99_api_ms')} ms"
            ),
            next_step="Exercise the same batch feedback endpoint under multi-worker Redis API load.",
        ),
        _criterion(
            criterion_id="real_redis_api_load_ci",
            title="Real Redis multi-process API load passes SLO",
            status="pass" if redis_api_load_pass else "fail",
            requirement=(
                "CI must start a real Redis service, launch multiple uvicorn "
                "workers, verify cross-process cache visibility, and fail on "
                "stale-cache, batch feedback, batch recall, shared query-vector "
                "cache, or p99 SLO regression."
            ),
            evidence=(
                f"workflow {redis_api_load_ci_configured}, "
                f"workers {redis_api_load.get('workers')}, "
                f"success_rate {redis_api_load.get('success_rate')}, "
                f"p99 {redis_api_load.get('p99_latency_ms')} ms, "
                f"batch accepted {redis_api_load.get('batch_feedback_accepted')}, "
                f"batch rejected {redis_api_load.get('batch_feedback_rejected')}, "
                f"batch cache invalidated {redis_api_load.get('batch_feedback_cache_invalidated')}, "
                f"batch query {redis_api_load.get('batch_query_success')}, "
                f"batch HTTP {redis_api_load.get('batch_query_individual_http_requests')} -> "
                f"{redis_api_load.get('batch_query_batch_http_requests')}, "
                f"batch vector hits {redis_api_load.get('batch_query_batch_vector_hits')}, "
                f"batch p99 {redis_api_load.get('batch_query_batch_p99_ms')} ms, "
                f"stale prevented {redis_api_load.get('stale_prevented_after_forget')}"
            ),
            next_step=(
                "Scale this Redis-backed batch recall profile to more workers, larger "
                "batch sizes, and remote Kubernetes/serverless API nodes."
            ),
        ),
        _criterion(
            criterion_id="real_local_http_cluster_ci",
            title="Real local HTTP cluster smoke passes SLO",
            status="pass" if local_http_cluster_pass else "fail",
            requirement=(
                "CI must start multiple real localhost WaveMind API processes "
                "with isolated SQLite stores and run the sustained HTTP cluster "
                "workload through the same service-mode client used for remote nodes."
            ),
            evidence=(
                f"workflow {local_http_cluster_ci_configured}, "
                f"nodes {local_http_cluster.get('nodes')}, "
                f"read_fanout {local_http_cluster.get('read_fanout')}, "
                f"success {local_http_cluster.get('success_rate')}, "
                f"failover {local_http_cluster.get('failover_hit_rate')}, "
                f"repair {local_http_cluster.get('repair_repaired_total')}, "
                f"health {local_http_cluster.get('cluster_health_ok')}, "
                f"degraded {local_http_cluster.get('degraded_nodes')}, "
                f"p99 {local_http_cluster.get('p99_operation_ms')} ms, "
                f"slo {local_http_cluster.get('slo_pass')}"
            ),
            next_step="Refresh local_http_cluster_smoke_results.json from CI on every release candidate.",
        ),
        _criterion(
            criterion_id="real_http_active_active_ci",
            title="Real HTTP active-active service-region smoke passes SLO",
            status="pass" if local_http_active_active_pass else "fail",
            requirement=(
                "CI must start real WaveMind API region processes backed by replicated "
                "local runtimes, exchange namespace deltas over HTTP export/import "
                "endpoints, converge without duplicate replay, and propagate deletes."
            ),
            evidence=(
                f"workflow {local_http_active_active_ci_configured}, "
                f"regions {local_http_active_active.get('region_count')}, "
                f"namespaces {local_http_active_active.get('namespaces')}, "
                f"pair_syncs {local_http_active_active.get('pair_syncs')}, "
                f"convergence {local_http_active_active.get('convergence_rate')}, "
                f"delete suppression {local_http_active_active.get('delete_suppression_rate')}, "
                f"success {local_http_active_active.get('success_rate')}, "
                f"final noop {local_http_active_active.get('final_noop_records_imported')}, "
                f"p99 {local_http_active_active.get('p99_operation_ms')} ms, "
                f"slo {local_http_active_active.get('slo_pass')}"
            ),
            next_step="Refresh local_http_active_active_smoke_results.json from CI on every release candidate.",
        ),
        _criterion(
            criterion_id="memory_os_worker",
            title="Memory OS worker prewarms, consolidates, and cleans up",
            status=(
                "pass"
                if memory_os.get("ok")
                and int(memory_os.get("hot_queries", 0)) >= 2
                and int(memory_os.get("prewarm_warmed", 0)) >= 2
                and memory_os.get("prewarm_hit")
                and int(memory_os.get("predictive_prefetch_generated", 0)) >= 1
                and int(memory_os.get("predictive_prefetch_warmed", 0)) >= 1
                and "risk limits" in set(memory_os.get("transition_prefetch_queries") or [])
                and memory_os.get("transition_prefetch_hit")
                and memory_os_transition_edge_pass
                and int(memory_os.get("expired_purged", 0)) >= 1
                and int(memory_os.get("concepts_created", 0)) >= 1
                and int(memory_os.get("user_feedback_events", 0)) >= 2
                and float(memory_os.get("positive_feedback_priority_delta", 0.0)) > 0.0
                and float(memory_os.get("negative_feedback_priority_delta", 0.0)) < 0.0
                and int(memory_os.get("priority_predictions", 0)) >= 1
                and float(memory_os.get("priority_boost_total", 0.0)) > 0.0
                and int(memory_os.get("forgetting_demotions", 0)) >= 1
                and float(memory_os.get("forgetting_decay_total", 0.0)) > 0.0
                and memory_os.get("concept_recall")
                and memory_os_architecture_pass
                and memory_os_suggestions_pass
                else "fail"
            ),
            requirement="Background intelligence must turn audited hot queries, observed query transitions, and explicit user recall feedback into exact and predictive prewarm actions, usage-pattern priority boosts, adaptive forgetting, cleanup, durable concept memories, production architecture advice, and typed self-improvement suggestions with evidence.",
            evidence=(
                f"hot queries {memory_os.get('hot_queries')}, "
                f"prewarm {memory_os.get('prewarm_warmed')}, "
                f"predictive warmed {memory_os.get('predictive_prefetch_warmed')}, "
                f"transition hit {memory_os.get('transition_prefetch_hit')}, "
                f"transition queries {memory_os.get('transition_prefetch_queries')}, "
                f"transition edge {memory_os_transition_edge_pass}, "
                f"expired {memory_os.get('expired_purged')}, "
                f"concepts {memory_os.get('concepts_created')}, "
                f"feedback events {memory_os.get('user_feedback_events')}, "
                f"priority predictions {memory_os.get('priority_predictions')}, "
                f"forgetting demotions {memory_os.get('forgetting_demotions')}, "
                f"architecture {memory_os.get('architecture_advice_status')}, "
                f"suggestions {memory_os.get('suggestion_count')} "
                f"{memory_os.get('suggestion_ids')}"
            ),
            next_step="Surface typed suggestions in Studio/operator dashboards and keep usage-pattern priority prediction and adaptive forgetting green under Redis-backed service deployments.",
        ),
        _criterion(
            criterion_id="distributed_repair_tombstones",
            title="Distributed sharding repairs replicas and tombstones stale deletes",
            status=(
                "pass"
                if sharding.get("recalled_after_primary_loss")
                and sharding.get("repair_ok")
                and sharding.get("tombstone_suppressed_after_repair")
                and sharding.get("anti_entropy_worker_ok")
                else "fail"
            ),
            requirement="Replicated writes, missing-record repair, tombstone repair, and anti-entropy must all pass.",
            evidence=(
                f"repair {sharding.get('repair_repaired_total')}, "
                f"tombstone deleted {sharding.get('tombstone_repair_deleted_records')}, "
                f"anti-entropy repaired {sharding.get('anti_entropy_worker_repaired_total')}"
            ),
            next_step="Keep the algorithm profile and real HTTP shard profile in sync.",
        ),
        _criterion(
            criterion_id="distributed_http_shard_transport",
            title="HTTP shard transport handles failover, repair, and tombstones",
            status=(
                "pass"
                if http_sharding.get("proxy_bypass_default")
                and http_sharding.get("recalled_after_primary_loss")
                and http_sharding.get("repair_ok")
                and http_sharding.get("recalled_after_repair")
                and http_sharding.get("tombstone_suppressed_after_repair")
                and http_sharding.get("concurrent_write_ok")
                and float(http_sharding.get("concurrent_query_hit_rate", 0.0)) >= 1.0
                and int(http_sharding.get("tombstone_repair_deleted_records", 0)) >= 1
                else "fail"
            ),
            requirement="Real localhost API shard nodes must pass quorum write, failover query, missing-replica repair, proxy-safe HTTP transport, tombstone cleanup, and concurrent namespace traffic.",
            evidence=(
                f"proxy bypass {http_sharding.get('proxy_bypass_default')}, "
                f"failover {http_sharding.get('recalled_after_primary_loss')}, "
                f"repair {http_sharding.get('repair_repaired_total')}, "
                f"tombstone deleted {http_sharding.get('tombstone_repair_deleted_records')}, "
                f"concurrent hit rate {http_sharding.get('concurrent_query_hit_rate')}"
            ),
            next_step="Extend the same HTTP shard profile to remote service nodes and sustained load.",
        ),
        _criterion(
            criterion_id="sustained_http_cluster_load",
            title="Sustained HTTP cluster load survives failover and repair",
            status=(
                "pass"
                if int(sustained_http_cluster.get("nodes", 0)) >= 4
                and int(sustained_http_cluster.get("replication_factor", 0)) >= 3
                and float(sustained_http_cluster.get("write_success_rate", 0.0)) >= 1.0
                and float(sustained_http_cluster.get("query_hit_rate", 0.0)) >= 1.0
                and float(sustained_http_cluster.get("failover_hit_rate", 0.0)) >= 1.0
                and float(sustained_http_cluster.get("forget_success_rate", 0.0)) >= 1.0
                and float(sustained_http_cluster.get("delete_suppression_rate", 0.0)) >= 1.0
                and sustained_http_cluster.get("repair_ok")
                and int(sustained_http_cluster.get("repair_repaired_total", 0)) >= 1
                and sustained_http_cluster.get("repaired_replica")
                and float(sustained_http_cluster.get("success_rate", 0.0)) >= 1.0
                and float(sustained_http_cluster.get("p99_operation_ms", float("inf"))) <= 1000.0
                else "fail"
            ),
            requirement=(
                "The HTTP cluster path must survive a mixed write/query/failover/"
                "repair/forget workload across multiple namespaces and real API nodes."
            ),
            evidence=(
                f"nodes {sustained_http_cluster.get('nodes')}, "
                f"writes {sustained_http_cluster.get('writes')}, "
                f"queries {sustained_http_cluster.get('queries')}, "
                f"failover hit {sustained_http_cluster.get('failover_hit_rate')}, "
                f"success {sustained_http_cluster.get('success_rate')}, "
                f"p99 {float(sustained_http_cluster.get('p99_operation_ms', float('inf'))):.2f} ms"
            ),
            next_step=(
                "Repeat this profile against remote service nodes and larger "
                "namespace counts before claiming full distributed production scale."
            ),
        ),
        _criterion(
            criterion_id="replicated_runtime_loss",
            title="Runtime replica quorum survives node loss",
            status=(
                "pass"
                if runtime.get("recalled_after_node_loss")
                and runtime.get("repair_copied_records", 0) >= 1
                and runtime.get("tombstone_suppressed_after_repair")
                and runtime.get("concurrent_write_ok")
                and float(runtime.get("concurrent_query_hit_rate", 0.0)) >= 1.0
                else "fail"
            ),
            requirement="Quorum runtime must recall after node loss, repair missing records and tombstones, and survive concurrent read/write traffic.",
            evidence=(
                f"recall after loss {runtime.get('recalled_after_node_loss')}, "
                f"repair copied {runtime.get('repair_copied_records')}, "
                f"p99 {runtime.get('p99_query_after_loss_ms')} ms, "
                f"concurrent hit rate {runtime.get('concurrent_query_hit_rate')}"
            ),
            next_step="Extend the same replicated runtime profile to remote service nodes and sustained load.",
        ),
        _criterion(
            criterion_id="active_active_field_crdt",
            title="Active-active sync and field-state CRDT converge",
            status=(
                "pass"
                if active_active.get("converged_after_bidirectional_sync")
                and active_active.get("incremental_records_exported") == 1
                and active_active.get("incremental_records_imported") >= 1
                and active_active.get("incremental_converged")
                and active_active.get("field_only_records_exported") == 0
                and active_active.get("field_only_keys_exported", 0) >= 1
                and active_active.get("tombstone_converged")
                and int(sustained_active_active.get("regions", 0)) >= 3
                and int(sustained_active_active.get("namespaces", 0)) >= 3
                and float(sustained_active_active.get("convergence_rate", 0.0)) >= 1.0
                and float(sustained_active_active.get("delete_suppression_rate", 0.0)) >= 1.0
                and float(sustained_active_active.get("success_rate", 0.0)) >= 1.0
                and int(sustained_active_active.get("failed_pairs", 1)) == 0
                and int(sustained_active_active.get("final_noop_records_imported", 1)) == 0
                and int(http_active_active.get("regions", 0)) >= 3
                and http_active_active.get("api_export_endpoint") == "/namespace-delta/export"
                and http_active_active.get("api_import_endpoint") == "/namespace-delta/import"
                and float(http_active_active.get("convergence_rate", 0.0)) >= 1.0
                and float(http_active_active.get("delete_suppression_rate", 0.0)) >= 1.0
                and float(http_active_active.get("success_rate", 0.0)) >= 1.0
                and int(http_active_active.get("failed_pairs", 1)) == 0
                and int(http_active_active.get("final_noop_records_imported", 1)) == 0
                and field_crdt.get("commutative_convergence")
                and field_crdt.get("idempotent_remerge")
                and field_crdt.get("tombstone_wins")
                and field_crdt.get("watermark_convergence")
                and int(field_crdt.get("watermark_actors", 0)) >= 3
                and field_crdt.get("watermark_health_ok")
                and field_crdt.get("watermark_missing_detected")
                and field_crdt.get("watermark_lag_detected")
                else "fail"
            ),
            requirement=(
                "Multi-region memory deltas and field state must converge "
                "without duplicate amplification or full-namespace replay on "
                "incremental sync, and CRDT deltas must carry actor watermarks "
                "so regions can audit sync progress, missing actors, and "
                "replication lag."
            ),
            evidence=(
                f"delta sync {active_active.get('converged_after_bidirectional_sync')}, "
                f"incremental records {active_active.get('incremental_records_exported')}, "
                f"field-only keys {active_active.get('field_only_keys_exported')}, "
                f"sustained regions {sustained_active_active.get('regions')}, "
                f"sustained convergence {sustained_active_active.get('convergence_rate')}, "
                f"sustained delete suppression {sustained_active_active.get('delete_suppression_rate')}, "
                f"sustained success {sustained_active_active.get('success_rate')}, "
                f"HTTP service-region convergence {http_active_active.get('convergence_rate')}, "
                f"HTTP final no-op imports {http_active_active.get('final_noop_records_imported')}, "
                f"CRDT idempotent {field_crdt.get('idempotent_remerge')}, "
                f"watermarks {field_crdt.get('watermark_actors')}, "
                f"watermark health {field_crdt.get('watermark_health_status')}, "
                f"missing detected {field_crdt.get('watermark_missing_detected')}, "
                f"lag detected {field_crdt.get('watermark_lag_detected')}"
            ),
            next_step="Replace the FastAPI TestClient service-region profile with remote Kubernetes or serverless API-node evidence.",
        ),
        _criterion(
            criterion_id="backup_restore_dr",
            title="Snapshots, archives, offsite mirror, and object-store DR verify",
            status=(
                "pass"
                if snapshot.get("manifest_healthy")
                and snapshot.get("offsite_verified")
                and snapshot.get("archive_verified")
                and snapshot.get("object_store_drill_ok")
                and snapshot.get("recalled_after_restore_node_loss")
                and recovery_journal.get("full_restore_ok")
                and recovery_journal.get("point_in_time_restore_ok")
                and int(recovery_journal.get("full_deleted_records", 0)) >= 2
                and int(recovery_journal.get("full_restored_records", 0)) >= 1
                and int(recovery_journal.get("point_restored_records", 0)) >= 1
                and postgres_pitr_pass
                else "fail"
            ),
            requirement=(
                "Backups must be checksummed, restorable, offsite-capable, "
                "recover recall after restore, and support SQLite point-in-time "
                "recovery from an append-only mutation journal plus database-native "
                "Postgres PITR runbook/preflight coverage."
            ),
            evidence=(
                f"archive {snapshot.get('archive_verified')}, "
                f"object-store DR {snapshot.get('object_store_drill_ok')}, "
                f"restored files {snapshot.get('restored_files')}, "
                f"PITR full {recovery_journal.get('full_restore_ok')}, "
                f"PITR point {recovery_journal.get('point_in_time_restore_ok')}, "
                f"journal entries {recovery_journal.get('journal_entries')}, "
                f"deleted {recovery_journal.get('full_deleted_records')}, "
                f"Postgres PITR {postgres_pitr.get('status')}, "
                f"commands {postgres_pitr.get('summary', {}).get('command_count')}, "
                f"env {postgres_pitr.get('environment_status')}"
            ),
            next_step=(
                "Repeat the drill with real S3-compatible storage, larger SQLite "
                "journals, then execute the Postgres PITR runbook against a "
                "staging or managed Postgres service and commit the drill report."
            ),
        ),
        _criterion(
            criterion_id="structured_multimodal_payloads",
            title="Structured and multimodal payload retrieval works",
            status=(
                "pass"
                if payloads.get("precision_at_1") == 1.0
                and payloads.get("cross_modal_precision_at_1") == 1.0
                and payloads.get("cross_modal_provenance_rate") == 1.0
                and payloads.get("cross_modal_vectors_persisted_rate") == 1.0
                and payloads.get("precomputed_vector_precision_at_1") == 1.0
                and payloads.get("precomputed_vector_persisted_rate") == 1.0
                and payloads.get("encoder_contract_ok") is True
                and payloads.get("encoder_contract_target_precision_at_1") == 1.0
                and payloads.get("encoder_contract_global_precision_at_1") == 1.0
                and payloads.get("encoder_contract_target_modality_routing_rate") == 1.0
                and payloads.get("encoder_contract_persisted_vector_rate") == 1.0
                and payloads.get("encoder_contract_normalized_vector_rate") == 1.0
                and payloads.get("encoder_contract_finite_vector_rate") == 1.0
                and payloads.get("encoder_contract_provenance_rate") == 1.0
                and payloads.get("encoder_contract_min_global_margin", 0.0)
                >= payloads.get("encoder_contract_min_required_margin", 1.0)
                and payloads.get("encoder_health_ok") is True
                and payloads.get("encoder_health_global_precision_at_1") == 1.0
                and payloads.get("encoder_health_target_modality_routing_rate") == 1.0
                and payloads.get("encoder_health_finite_payload_vector_rate") == 1.0
                and payloads.get("encoder_health_normalized_payload_vector_rate") == 1.0
                and payloads.get("encoder_health_finite_query_vector_rate") == 1.0
                and payloads.get("encoder_health_normalized_query_vector_rate") == 1.0
                and payloads.get("encoder_health_dimension_match_rate") == 1.0
                and payloads.get("encoder_health_payload_encode_p95_ms", 999999.0) <= 50.0
                and payloads.get("encoder_health_query_encode_p95_ms", 999999.0) <= 50.0
                and payloads.get("encoder_health_min_global_margin", 0.0)
                >= payloads.get("encoder_health_min_required_margin", 1.0)
                and payloads.get("temporal_event_precision_at_1") == 1.0
                and payloads.get("temporal_event_around_precision_at_1") == 1
                and payloads.get("temporal_event_window_precision_at_1") == 1
                and payloads.get("temporal_event_recency_precision_at_1") == 1
                and payloads.get("temporal_event_interval_precision_at_1") == 1
                and payloads.get("temporal_event_persistence_rate") == 1.0
                and payloads.get("temporal_event_provenance_rate") == 1.0
                and payloads.get("knowledge_graph_precision_at_1") == 1.0
                and payloads.get("knowledge_graph_path_precision_at_1") == 1.0
                and payloads.get("knowledge_graph_direct_precision_at_1") == 1
                and payloads.get("knowledge_graph_two_hop_precision_at_1") == 1
                and payloads.get("knowledge_graph_three_hop_precision_at_1") == 1
                and payloads.get("knowledge_graph_predicate_precision_at_1") == 1
                and payloads.get("knowledge_graph_persistence_rate") == 1.0
                and payloads.get("knowledge_graph_provenance_rate") == 1.0
                and payloads.get("asset_manifest_verified")
                and payloads.get("asset_manifest_sha256_present")
                and payloads.get("asset_manifest_provenance_rate") == 1
                and int(payloads.get("cross_modal_embedding_dim", 0)) >= 64
                and int(payloads.get("precomputed_vector_embedding_dim", 0)) >= 4
                and {
                    "image",
                    "audio",
                    "table",
                    "event",
                    "video",
                    "3d",
                    "graph",
                }.issubset(set(payloads.get("modalities", [])))
                else "fail"
            ),
            requirement=(
                "Images, audio, video, 3D assets, tables, temporal events, "
                "and graph facts must be storable, retrievable through the same "
                "memory API, queryable through a shared cross-modal embedding "
                "space, returned with provenance, and compatible with externally "
                "computed multimodal vectors. Temporal events must support "
                "actor filters, interval overlap, around-time reranking, "
                "recency reranking, persistence, and provenance. Large media "
                "assets must be backed by verified content-addressed object-store "
                "manifests. Knowledge graphs must support entity/predicate filters, "
                "multi-hop path traversal, persistence, and provenance. External "
                "multimodal encoders must pass a precomputed-vector contract that "
                "checks global retrieval, target-modality routing, persisted finite "
                "normalized vectors, provenance, and vector separation margin. Active "
                "cross-modal encoders must also pass health monitoring for finite "
                "normalized payload/query vectors, target routing, p95 encode latency, "
                "dimension compatibility, and separation margin."
            ),
            evidence=(
                f"modalities {', '.join(payloads.get('modalities', []))}, "
                f"precision@1 {payloads.get('precision_at_1')}, "
                f"cross-modal precision@1 {payloads.get('cross_modal_precision_at_1')}, "
                f"vectors persisted {payloads.get('cross_modal_vectors_persisted_rate')}, "
                f"precomputed precision@1 {payloads.get('precomputed_vector_precision_at_1')}, "
                f"encoder contract {payloads.get('encoder_contract_ok')}, "
                f"encoder global@1 {payloads.get('encoder_contract_global_precision_at_1')}, "
                f"encoder target@1 {payloads.get('encoder_contract_target_precision_at_1')}, "
                f"encoder margin {payloads.get('encoder_contract_min_global_margin')}, "
                f"encoder health {payloads.get('encoder_health_ok')}, "
                f"encoder health global@1 {payloads.get('encoder_health_global_precision_at_1')}, "
                f"encoder health query p95 {payloads.get('encoder_health_query_encode_p95_ms')} ms, "
                f"provenance {payloads.get('cross_modal_provenance_rate')}, "
                f"temporal precision@1 {payloads.get('temporal_event_precision_at_1')}, "
                f"temporal around/window/recency/interval "
                f"{payloads.get('temporal_event_around_precision_at_1')}/"
                f"{payloads.get('temporal_event_window_precision_at_1')}/"
                f"{payloads.get('temporal_event_recency_precision_at_1')}/"
                f"{payloads.get('temporal_event_interval_precision_at_1')}, "
                f"temporal persisted {payloads.get('temporal_event_persistence_rate')}, "
                f"temporal provenance {payloads.get('temporal_event_provenance_rate')}, "
                f"knowledge graph precision@1 {payloads.get('knowledge_graph_precision_at_1')}, "
                f"knowledge graph direct/two-hop/three-hop/predicate "
                f"{payloads.get('knowledge_graph_direct_precision_at_1')}/"
                f"{payloads.get('knowledge_graph_two_hop_precision_at_1')}/"
                f"{payloads.get('knowledge_graph_three_hop_precision_at_1')}/"
                f"{payloads.get('knowledge_graph_predicate_precision_at_1')}, "
                f"knowledge graph paths {payloads.get('knowledge_graph_path_precision_at_1')}, "
                f"knowledge graph persisted {payloads.get('knowledge_graph_persistence_rate')}, "
                f"knowledge graph provenance {payloads.get('knowledge_graph_provenance_rate')}, "
                f"asset manifest verified {payloads.get('asset_manifest_verified')}, "
                f"asset provenance {payloads.get('asset_manifest_provenance_rate')}"
            ),
            next_step="Run the same encoder contract and encoder-health check with real CLIP/audio/video/3D vectors from production encoders, then expand the multimodal, temporal-event, and knowledge-graph retrieval profiles against larger object-store-backed corpora.",
        ),
        _criterion(
            criterion_id="ten_million_load_profile",
            title="10M-vector production load profile passes recall, p99, and cost gate",
            status="pass" if load_10m_pass else "action_required",
            requirement="A real non-skipped 10M-vector service-backed benchmark must meet recall@10 >= 0.95, p99 <= 100 ms, and valid cost SLO before claiming 10M readiness.",
            evidence=(
                f"{load_10m.get('engine')}: recall {load_10m.get('recall_at_k')}, "
                f"p99 {load_10m.get('p99_latency_ms')} ms, "
                f"cost {load_10m.get('cost_status')}"
                if load_10m
                else "no production_load_10m or production_streaming_load_ivfpq_10m non-skipped SLO row"
            ),
            next_step="Keep the 10M compressed FAISS IVF-PQ profile green and repeat with Qdrant/pgvector service profiles when larger service hardware is available.",
        ),
        _criterion(
            criterion_id="fifty_million_streaming_preflight",
            title="50M streaming load run has a checked preflight contract",
            status="pass" if load_50m_plan_pass else "action_required",
            requirement=(
                "The next 50M streaming run must have a committed plan-only "
                "artifact with exact reproduction command, local index/transient "
                "storage estimates, application-storage estimate, required env, "
                "and an explicit boundary that it is not a completed benchmark."
            ),
            evidence=(
                f"{load_50m_plan_row.get('engine')}: "
                f"status {load_50m_plan_row.get('status')}, "
                f"index {load_50m_plan_row.get('estimated_index_gb')} GB, "
                f"app storage {load_50m_plan_row.get('estimated_application_storage_gb')} GB, "
                f"required local free {load_50m_plan_row.get('required_local_free_gb')} GB, "
                f"blockers {', '.join(load_50m_plan_row.get('blockers', [])) or '-'}"
                if load_50m_plan_row
                else "no 50M plan artifact"
            ),
            next_step=(
                "Set WAVEMIND_FAISS_IVFPQ_PATH on sized storage and run the "
                "embedded 50M command to produce "
                "production_streaming_load_ivfpq_50m_results.json."
            ),
        ),
        _criterion(
            criterion_id="architecture_advisor_preflight",
            title="Architecture advisor blocks unsafe large production growth",
            status="pass" if advisor_pass else "fail",
            requirement="Advisor must convert live stats plus 10M production targets into service-index, namespace-sharding, load-test, production-controls, and multimodal readiness actions.",
            evidence=(
                f"status {advisor.status}, "
                f"recommendations {', '.join(sorted(advisor_ids))}, "
                f"commands {len(advisor.next_commands)}"
            ),
            next_step="Keep `wavemind advise --fail-on action_required` in release and deployment preflight checks.",
        ),
    ]

    pass_count = sum(1 for row in criteria if row["status"] == "pass")
    action_required_count = sum(
        1 for row in criteria if row["status"] == "action_required"
    )
    fail_count = sum(1 for row in criteria if row["status"] == "fail")
    total = len(criteria)
    readiness_score = pass_count / total
    overall_status = (
        "fail"
        if fail_count
        else "action_required"
        if action_required_count
        else "pass"
    )

    return {
        "schema": "wavemind.production_readiness.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "overall_status": overall_status,
        "readiness_score": readiness_score,
        "summary": {
            "overall_status": overall_status,
            "readiness_score": readiness_score,
            "pass_count": pass_count,
            "action_required_count": action_required_count,
            "fail_count": fail_count,
            "total_criteria": total,
        },
        "criteria": criteria,
        "external_evidence": external_evidence,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Readiness Gate",
        "",
        "This gate is generated from checked-in benchmark artifacts. It is a readiness",
        "verdict, not a marketing claim.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{summary['overall_status']}` |",
        f"| readiness score | `{summary['readiness_score']:.3f}` |",
        f"| passed criteria | `{summary['pass_count']}` |",
        f"| action required | `{summary['action_required_count']}` |",
        f"| failed criteria | `{summary['fail_count']}` |",
        f"| total criteria | `{summary['total_criteria']}` |",
        "",
        "| criterion | status | evidence | next step |",
        "|---|---|---|---|",
    ]
    for row in payload["criteria"]:
        lines.append(
            f"| {row['title']} | `{row['status']}` | {row['evidence']} | {row['next_step']} |"
        )
    external = payload.get("external_evidence", [])
    if external:
        lines.extend(
            [
                "",
                "## Non-Gating External Evidence",
                "",
                "External competitors and deployment-specific service evidence are tracked separately from WaveMind core readiness.",
                "Missing commercial API credentials or remote cluster URLs should not turn a core WaveMind readiness gate red.",
                "",
                "| evidence | status | result | next step |",
                "|---|---|---|---|",
            ]
        )
        for row in external:
            lines.append(
                f"| {row['title']} | `{row['status']}` | {row['evidence']} | {row['next_step']} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_readiness_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_READINESS.md"),
    )
    args = parser.parse_args()

    payload = evaluate_production_readiness(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"{payload['overall_status']} "
        f"({payload['summary']['pass_count']}/{payload['summary']['total_criteria']} pass)"
    )
    return 0 if payload["overall_status"] in {"pass", "action_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
