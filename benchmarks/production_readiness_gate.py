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
        "load_100k": _load_json(benchmark_dir / "production_load_qdrant_100k_tuned_results.json"),
        "load_1m": _load_json(benchmark_dir / "production_load_qdrant_1m_tuned_results.json"),
        "load_1m_faiss": _load_json(benchmark_dir / "production_load_faiss_1m_results.json"),
        "load_1m_ef": _load_json(benchmark_dir / "production_load_qdrant_1m_ef_sweep_results.json"),
        "load_10m": _load_optional_json(benchmark_dir / "production_load_10m_results.json"),
        "load_10m_streaming": _load_optional_json(benchmark_dir / "production_streaming_load_ivfpq_10m_results.json"),
        "scale": _load_json(benchmark_dir / "scale_readiness_results.json"),
        "redis_api_load": _load_optional_json(benchmark_dir / "redis_api_load_results.json"),
        "competitors": _load_json(benchmark_dir / "memory_competitor_results.json"),
    }


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def evaluate_production_readiness(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    artifacts = _load_artifacts(root)
    full_check_workflow = _read_optional_text(root / ".github" / "workflows" / "full-check.yml")
    redis_api_load_script_exists = (root / "benchmarks" / "redis_api_load_benchmark.py").exists()
    redis_api_load_ci_configured = (
        redis_api_load_script_exists
        and "redis-api-load:" in full_check_workflow
        and "image: redis:7-alpine" in full_check_workflow
        and "benchmarks/redis_api_load_benchmark.py" in full_check_workflow
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
        and redis_api_load.get("cache_invalidated_on_forget")
        and redis_api_load.get("stale_prevented_after_forget")
        and float(redis_api_load.get("success_rate", 0.0)) >= 1.0
        and float(redis_api_load.get("p99_latency_ms", float("inf"))) <= 1000.0
        and int(redis_api_load.get("workers", 0)) >= 2
    )
    audit = artifacts["audit"]
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

    cluster = scale.get("WaveMind cluster planner", {})
    cluster_autoscaler = scale.get("WaveMind cluster autoscaler", {})
    capacity_100m = scale.get("WaveMind 100M capacity envelope", {})
    operator = scale.get("WaveMind Kubernetes operator", {})
    serverless = scale.get("WaveMind serverless plan", {})
    hot_cache = scale.get("WaveMind hot cache", {})
    query_vector_cache = scale.get("WaveMind query vector cache", {})
    shared_rate_limiter = scale.get("WaveMind shared rate limiter", {})
    redis_cache = scale.get("WaveMind Redis hot cache", {})
    api_cache_mutations = scale.get("WaveMind API cache mutation safety", {})
    memory_os = scale.get("WaveMind Memory OS", {})
    sharding = scale.get("WaveMind distributed sharding", {})
    http_sharding = scale.get("WaveMind distributed HTTP sharding", {})
    sustained_http_cluster = scale.get("WaveMind sustained HTTP cluster load", {})
    runtime = scale.get("WaveMind replicated runtime", {})
    active_active = scale.get("WaveMind active-active delta sync", {})
    field_crdt = scale.get("WaveMind field-state CRDT", {})
    snapshot = scale.get("WaveMind replicated snapshot", {})
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
                else "fail"
            ),
            requirement=(
                "Autoscale planning must convert target memories, RF, and "
                "per-node capacity into required node count, bounded target "
                "load, and namespace movement actions."
            ),
            evidence=(
                f"current {cluster_autoscaler.get('current_nodes')}, "
                f"required {cluster_autoscaler.get('required_nodes')}, "
                f"target max {cluster_autoscaler.get('target_max_node_memories')}, "
                f"moves {cluster_autoscaler.get('move_sample')}+{cluster_autoscaler.get('omitted_moves')}"
            ),
            next_step="Connect this planner to operator reconciliation status and real HPA/load metrics.",
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
                and operator.get("has_repair_cronjob")
                and int(operator.get("statefulset_replicas", 0))
                == int(operator.get("capacity_required_replicas", -1))
                and int(operator.get("capacity_target_max_node_memories", 0)) <= 700_000
                else "fail"
            ),
            requirement=(
                "Operator output must include CRD, StatefulSet, Service, HPA, "
                "scheduled repair, and capacity-aware replica reconciliation."
            ),
            evidence=(
                f"CRD {operator.get('bundle_has_crd')}, "
                f"HPA {operator.get('has_hpa')}, repair {operator.get('has_repair_cronjob')}, "
                f"replicas {operator.get('statefulset_replicas')}, "
                f"required {operator.get('capacity_required_replicas')}, "
                f"target max {operator.get('capacity_target_max_node_memories')}"
            ),
            next_step="Run a real Kubernetes smoke deploy and collect HPA behavior under load.",
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
                else "fail"
            ),
            requirement="Serverless mode must use external durable state, external vector index, and shared cache.",
            evidence=(
                f"Postgres {serverless.get('uses_postgres')}, "
                f"Qdrant {serverless.get('uses_external_qdrant')}, "
                f"Redis {serverless.get('uses_shared_cache')}"
            ),
            next_step="Run service-backed KEDA/Knative load tests instead of manifest-only checks.",
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
                else "fail"
            ),
            requirement=(
                "Repeated hot queries must reuse encoded query vectors locally "
                "and across Redis-backed workers before hitting the vector index."
            ),
            evidence=(
                f"local encode calls {query_vector_cache.get('local_encode_calls')}, "
                f"local hit rate {query_vector_cache.get('local_hit_rate')}, "
                f"Redis shared {query_vector_cache.get('redis_shared_across_workers')}, "
                f"Redis encode calls {query_vector_cache.get('redis_encode_calls')}"
            ),
            next_step="Add service-mode vector-cache load evidence with a sentence-transformer encoder.",
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
                and redis_cache.get("memory_os_cross_worker_hit")
                and redis_cache.get("namespace_invalidation_removed")
                else "fail"
            ),
            requirement=(
                "Production cache must be shareable across workers, support "
                "query-audit prewarm, support Memory OS prewarm, and invalidate "
                "a namespace after memory changes."
            ),
            evidence=(
                f"shared {redis_cache.get('shared_cache_visible_across_clients')}, "
                f"prewarm hit {redis_cache.get('cache_prewarm_cross_worker_hit')}, "
                f"Memory OS warmed {redis_cache.get('memory_os_prewarm_warmed')}, "
                f"predictive warmed {redis_cache.get('memory_os_predictive_warmed')}, "
                f"Memory OS hit {redis_cache.get('memory_os_cross_worker_hit')}, "
                f"invalidation {redis_cache.get('namespace_invalidation_removed')}"
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
                and api_cache_mutations.get("cache_invalidated_on_forget")
                and api_cache_mutations.get("stale_prevented_after_forget")
                else "fail"
            ),
            requirement=(
                "FastAPI workers must invalidate shared query cache on remember "
                "and forget so mutations cannot leave stale cached recall."
            ),
            evidence=(
                f"cached {api_cache_mutations.get('first_query_cached')}, "
                f"remember invalidation {api_cache_mutations.get('cache_invalidated_on_remember')}, "
                f"remember stale prevented {api_cache_mutations.get('stale_prevented_after_remember')}, "
                f"forget invalidation {api_cache_mutations.get('cache_invalidated_on_forget')}, "
                f"forget stale prevented {api_cache_mutations.get('stale_prevented_after_forget')}"
            ),
            next_step="Keep the real Redis multi-process API load workflow green.",
        ),
        _criterion(
            criterion_id="real_redis_api_load_ci",
            title="Real Redis multi-process API load passes SLO",
            status="pass" if redis_api_load_pass else "fail",
            requirement=(
                "CI must start a real Redis service, launch multiple uvicorn "
                "workers, verify cross-process cache visibility, and fail on "
                "stale-cache or p99 SLO regression."
            ),
            evidence=(
                f"workflow {redis_api_load_ci_configured}, "
                f"workers {redis_api_load.get('workers')}, "
                f"success_rate {redis_api_load.get('success_rate')}, "
                f"p99 {redis_api_load.get('p99_latency_ms')} ms, "
                f"stale prevented {redis_api_load.get('stale_prevented_after_forget')}"
            ),
            next_step="Refresh redis_api_load_results.json from the CI artifact on every release candidate.",
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
                and int(memory_os.get("expired_purged", 0)) >= 1
                and int(memory_os.get("concepts_created", 0)) >= 1
                and int(memory_os.get("priority_predictions", 0)) >= 1
                and float(memory_os.get("priority_boost_total", 0.0)) > 0.0
                and int(memory_os.get("forgetting_demotions", 0)) >= 1
                and float(memory_os.get("forgetting_decay_total", 0.0)) > 0.0
                and memory_os.get("concept_recall")
                else "fail"
            ),
            requirement="Background intelligence must turn audited hot queries into exact and predictive prewarm actions, usage-pattern priority boosts, adaptive forgetting, cleanup, and durable concept memories.",
            evidence=(
                f"hot queries {memory_os.get('hot_queries')}, "
                f"prewarm {memory_os.get('prewarm_warmed')}, "
                f"predictive warmed {memory_os.get('predictive_prefetch_warmed')}, "
                f"expired {memory_os.get('expired_purged')}, "
                f"concepts {memory_os.get('concepts_created')}, "
                f"priority predictions {memory_os.get('priority_predictions')}, "
                f"forgetting demotions {memory_os.get('forgetting_demotions')}"
            ),
            next_step="Keep usage-pattern priority prediction and adaptive forgetting green under Redis-backed service deployments.",
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
                and active_active.get("tombstone_converged")
                and field_crdt.get("commutative_convergence")
                and field_crdt.get("idempotent_remerge")
                and field_crdt.get("tombstone_wins")
                else "fail"
            ),
            requirement="Multi-region memory deltas and field state must converge without duplicate amplification.",
            evidence=(
                f"delta sync {active_active.get('converged_after_bidirectional_sync')}, "
                f"CRDT idempotent {field_crdt.get('idempotent_remerge')}"
            ),
            next_step="Run active-active sync against independent persistent stores.",
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
                else "fail"
            ),
            requirement="Backups must be checksummed, restorable, offsite-capable, and recover recall after restore.",
            evidence=(
                f"archive {snapshot.get('archive_verified')}, "
                f"object-store DR {snapshot.get('object_store_drill_ok')}, "
                f"restored files {snapshot.get('restored_files')}"
            ),
            next_step="Repeat the drill with real S3-compatible storage and larger SQLite/Postgres dumps.",
        ),
        _criterion(
            criterion_id="structured_multimodal_payloads",
            title="Structured and multimodal payload retrieval works",
            status=(
                "pass"
                if payloads.get("precision_at_1") == 1.0
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
            requirement="Images, audio, video, 3D assets, tables, temporal events, and graph facts must be storable and retrievable through the same memory API.",
            evidence=(
                f"modalities {', '.join(payloads.get('modalities', []))}, "
                f"precision@1 {payloads.get('precision_at_1')}"
            ),
            next_step="Add real CLIP/audio/video/3D embedding backends and larger multimodal retrieval tests.",
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
                "External competitor services are tracked separately from WaveMind production readiness.",
                "Missing commercial API credentials should not turn a core WaveMind readiness gate red.",
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
