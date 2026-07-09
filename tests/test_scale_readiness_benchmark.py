import json

from benchmarks import scale_readiness_benchmark


run_benchmark = scale_readiness_benchmark.run_benchmark


def test_scale_readiness_benchmark_covers_cluster_cache_and_payloads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        scale_readiness_benchmark,
        "SERVERLESS_REMOTE_OBSERVED_TELEMETRY_PATH",
        tmp_path / "missing-remote-telemetry.json",
    )
    payload = run_benchmark(
        simulated_memories=100_000,
        namespace_count=64,
        node_count=3,
        replication_factor=2,
        cache_queries=100,
        cache_capacity=32,
    )
    results = {result["engine"]: result for result in payload["results"]}

    assert payload["schema"] == "wavemind.scale_readiness_benchmark.v1"
    assert payload["generated_at"].endswith("Z")
    assert results["WaveMind cluster planner"]["node_loss_min_availability"] == 1.0
    assert results["WaveMind cluster planner"]["zone_loss_min_availability"] == 1.0
    assert results["WaveMind cluster planner"]["write_quorum"] == 2
    assert results["WaveMind cluster autoscaler"]["status"] == "scale_required"
    assert results["WaveMind cluster autoscaler"]["required_nodes"] > 3
    assert results["WaveMind cluster autoscaler"]["target_within_headroom"] is True
    assert results["WaveMind cluster autoscaler"]["has_scale_action"] is True
    assert results["WaveMind cluster autoscaler"]["rebalance_status"] == "ready"
    assert results["WaveMind cluster autoscaler"]["rebalance_full_plan"] is True
    assert results["WaveMind cluster autoscaler"]["rebalance_batches"] >= 1
    assert results["WaveMind cluster autoscaler"]["rebalance_move_count"] == results["WaveMind cluster autoscaler"]["move_sample"]
    assert results["WaveMind cluster autoscaler"]["rebalance_write_quorum"] == 2
    assert results["WaveMind cluster autoscaler"]["rebalance_all_batches_checkpointed"] is True
    assert results["WaveMind cluster autoscaler"]["rebalance_all_batches_repaired"] is True
    assert results["WaveMind cluster autoscaler"]["rebalance_all_batches_validated"] is True
    assert results["WaveMind control-plane consensus"]["ok"] is True
    assert results["WaveMind control-plane consensus"]["stale_leader_blocked"] is True
    assert results["WaveMind control-plane consensus"]["stale_revision_blocked"] is True
    assert results["WaveMind control-plane consensus"]["minority_commit_blocked"] is True
    assert results["WaveMind control-plane consensus"]["membership_committed"] is True
    assert results["WaveMind control-plane consensus"]["monotonic_terms"] is True
    assert results["WaveMind control-plane consensus"]["monotonic_revisions"] is True
    assert results["WaveMind control-plane consensus"]["final_revision"] == 2
    assert results["WaveMind Kubernetes operator"]["bundle_has_crd"] is True
    assert results["WaveMind Kubernetes operator"]["bundle_has_operator_deployment"] is True
    assert results["WaveMind Kubernetes operator"]["operator_replicas"] >= 2
    assert results["WaveMind Kubernetes operator"]["operator_rolling_update"] is True
    assert results["WaveMind Kubernetes operator"]["operator_leader_election"] is True
    assert results["WaveMind Kubernetes operator"]["operator_lease_backend"] == "coordination.k8s.io/v1"
    assert results["WaveMind Kubernetes operator"]["operator_lease_rbac"] is True
    assert results["WaveMind Kubernetes operator"]["operator_cross_node_anti_affinity"] is True
    assert results["WaveMind Kubernetes operator"]["operator_pdb_rbac"] is True
    assert results["WaveMind Kubernetes operator"]["has_service"] is True
    assert results["WaveMind Kubernetes operator"]["has_statefulset"] is True
    assert results["WaveMind Kubernetes operator"]["has_pod_disruption_budget"] is True
    assert results["WaveMind Kubernetes operator"]["pod_disruption_budget_min_available"] == (
        results["WaveMind Kubernetes operator"]["statefulset_replicas"] - 1
    )
    assert results["WaveMind Kubernetes operator"]["statefulset_rolling_update"] is True
    assert results["WaveMind Kubernetes operator"]["statefulset_min_ready_seconds"] == 5
    assert results["WaveMind Kubernetes operator"]["statefulset_topology_spread_keys"] == [
        "kubernetes.io/hostname",
        "topology.kubernetes.io/zone",
    ]
    assert results["WaveMind Kubernetes operator"]["statefulset_cross_node_anti_affinity"] is True
    assert results["WaveMind Kubernetes operator"]["has_hpa"] is True
    assert results["WaveMind Kubernetes operator"]["has_rebalance_configmap"] is True
    assert results["WaveMind Kubernetes operator"]["has_memory_os_cronjob"] is True
    assert results["WaveMind Kubernetes operator"]["statefulset_replicas"] >= 29
    assert results["WaveMind Kubernetes operator"]["capacity_required_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["capacity_target_max_node_memories"] <= 700_000
    assert results["WaveMind Kubernetes operator"]["autoscaling_max_replicas"] >= results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["autoscaling_metrics"] == ["cpu", "memory"]
    assert results["WaveMind Kubernetes operator"]["rebalance_status"] == "ready"
    assert results["WaveMind Kubernetes operator"]["rebalance_full_plan"] is True
    assert results["WaveMind Kubernetes operator"]["rebalance_move_count"] >= 1
    assert results["WaveMind Kubernetes operator"]["rebalance_batches"] >= 1
    assert results["WaveMind Kubernetes operator"]["rebalance_preview_batches"] == results["WaveMind Kubernetes operator"]["rebalance_preview_batch_count"]
    assert results["WaveMind Kubernetes operator"]["rebalance_write_quorum"] == 2
    assert results["WaveMind Kubernetes operator"]["rebalance_checkpoint_required"] is True
    assert results["WaveMind Kubernetes operator"]["rebalance_repair_required"] is True
    assert results["WaveMind Kubernetes operator"]["rebalance_validation_required"] is True
    assert results["WaveMind Kubernetes operator"]["status_ready"] is True
    assert results["WaveMind Kubernetes operator"]["status_phase"] == "Ready"
    assert results["WaveMind Kubernetes operator"]["status_ready_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["status_required_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["status_capacity_within_headroom"] is True
    assert results["WaveMind Kubernetes operator"]["status_rebalance_ready"] is True
    assert results["WaveMind Kubernetes operator"]["status_rebalance_full_plan"] is True
    assert results["WaveMind Kubernetes operator"]["status_rebalance_move_count"] == results["WaveMind Kubernetes operator"]["rebalance_move_count"]
    assert results["WaveMind Kubernetes operator"]["status_rebalance_batches"] == results["WaveMind Kubernetes operator"]["rebalance_batches"]
    assert results["WaveMind Kubernetes operator"]["status_rebalance_configmap"] == results["WaveMind Kubernetes operator"]["rebalance_configmap_name"]
    assert results["WaveMind Kubernetes operator"]["status_memory_os_ready"] is True
    assert results["WaveMind Kubernetes operator"]["status_memory_os_redis_required"] is True
    assert results["WaveMind Kubernetes operator"]["status_memory_os_redis_configured"] is True
    assert results["WaveMind Kubernetes operator"]["status_memory_os_cronjob"] == "wavemind-memory-os"
    assert results["WaveMind Kubernetes operator"]["production_admission_env_enabled"] is True
    assert results["WaveMind Kubernetes operator"]["production_admission_env_target_memories"] == 10_000_000
    assert results["WaveMind Kubernetes operator"]["production_admission_env_root"] == "/evidence"
    assert results["WaveMind Kubernetes operator"]["status_production_admission_enabled"] is True
    assert results["WaveMind Kubernetes operator"]["status_production_admission_required"] is True
    assert results["WaveMind Kubernetes operator"]["status_production_admission_ready"] is True
    assert results["WaveMind Kubernetes operator"]["status_production_admission_target_memories"] == 10_000_000
    assert results["WaveMind Kubernetes operator"]["status_degraded_nodes"] == 0
    assert results["WaveMind Kubernetes operator"]["control_plane_ready"] is True
    assert results["WaveMind Kubernetes operator"]["control_plane_voters"] >= 3
    assert results["WaveMind Kubernetes operator"]["control_plane_final_revision"] == 2
    assert results["WaveMind Kubernetes operator"]["control_plane_minority_blocked"] is True
    assert set(results["WaveMind Kubernetes operator"]["status_conditions_true"]) == {
        "AutoscalingReady",
        "CapacityPlanned",
        "ControlPlaneReady",
        "MemoryOSReady",
        "ProductionAdmissionReady",
        "RebalancePlanned",
        "RepairScheduled",
        "ResourcesReady",
    }
    assert results["WaveMind Kubernetes operator"]["has_repair_cronjob"] is True
    assert results["WaveMind Kubernetes operator"]["repair_namespaces"] == 64
    assert results["WaveMind Kubernetes operator"]["memory_os_calls_plan"] is True
    assert results["WaveMind Kubernetes operator"]["memory_os_calls_run"] is True
    assert results["WaveMind Kubernetes operator"]["memory_os_applies_plan_lock"] is True
    assert results["WaveMind Kubernetes operator"]["memory_os_blocks_missing_redis"] is True
    assert results["WaveMind Kubernetes operator"]["memory_os_run_on_all_replicas"] is False
    assert results["WaveMind serverless plan"]["has_knative_service"] is True
    assert results["WaveMind serverless plan"]["has_keda_scaled_object"] is True
    assert results["WaveMind serverless plan"]["scale_to_zero"] is True
    assert results["WaveMind serverless plan"]["max_scale"] == 256
    assert results["WaveMind serverless plan"]["target_concurrency"] == 80
    assert results["WaveMind serverless plan"]["uses_postgres"] is True
    assert results["WaveMind serverless plan"]["uses_external_qdrant"] is True
    assert results["WaveMind serverless plan"]["uses_shared_cache"] is True
    assert results["WaveMind serverless plan"]["safe_for_pod_eviction"] is True
    assert results["WaveMind serverless plan"]["keda_scale_target_kind"] == "Deployment"
    assert results["WaveMind serverless plan"]["valid_keda_scale_target"] is True
    assert results["WaveMind serverless plan"]["env_has_postgres_dsn"] is True
    assert results["WaveMind serverless plan"]["env_has_qdrant_url"] is True
    assert results["WaveMind serverless operational profile"]["slo_pass"] is True
    assert results["WaveMind serverless operational profile"]["external_state_ok"] is True
    assert results["WaveMind serverless operational profile"]["scale_out_possible"] is True
    assert results["WaveMind serverless operational profile"]["scale_to_zero_safe"] is True
    assert results["WaveMind serverless operational profile"]["cold_start_budget_ok"] is True
    assert results["WaveMind serverless operational profile"]["cost_ok"] is True
    assert results["WaveMind serverless operational profile"]["required_replicas"] == 4
    assert results["WaveMind serverless operational profile"]["burst_capacity_rps"] == 256000.0
    assert results["WaveMind serverless operational profile"]["observed_telemetry_source"] == "loopback-api-capacity-estimate"
    assert results["WaveMind serverless operational profile"]["observed_telemetry_path"].endswith("observed-telemetry.loopback.json")
    assert results["WaveMind serverless operational profile"]["observed_node_mode"] == "loopback"
    assert results["WaveMind serverless operational profile"]["observed_external_node_count"] == 0
    assert results["WaveMind serverless operational profile"]["observed_seed_mode"] == "all"
    assert results["WaveMind serverless operational profile"]["observed_cold_start_measured"] is True
    assert results["WaveMind serverless operational profile"]["observed_slo_pass"] is True
    assert results["WaveMind serverless operational profile"]["observed_requests_per_second"] >= 3040.0
    assert results["WaveMind serverless operational profile"]["observed_p99_request_ms"] <= 500.0
    assert results["WaveMind serverless operational profile"]["observed_max_replicas"] <= 256
    assert results["WaveMind serverless operational profile"]["observed_measured_replicas"] >= 4
    assert results["WaveMind serverless operational profile"]["observed_measured_pool_requests_per_second"] > 0.0
    assert results["WaveMind serverless operational profile"]["observed_per_replica_requests_per_second"] > 0.0
    assert "balanced pool" in results["WaveMind serverless operational profile"]["observed_telemetry_methodology"]
    assert results["WaveMind hot cache"]["hit_rate"] > 0.0
    assert results["WaveMind hot cache"]["prewarm_warmed"] == 1
    assert results["WaveMind hot cache"]["prewarm_hit"] is True
    assert results["WaveMind query vector cache"]["local_encode_calls"] == 1
    assert results["WaveMind query vector cache"]["local_cache_hits"] >= 199
    assert results["WaveMind query vector cache"]["local_hit_rate"] >= 0.99
    assert results["WaveMind query vector cache"]["redis_shared_across_workers"] is True
    assert results["WaveMind query vector cache"]["redis_encode_calls"] == 1
    assert results["WaveMind query vector cache"]["redis_reader_hits"] == 1
    assert results["WaveMind query vector cache"]["service_boundary"] == "FastAPI TestClient"
    assert results["WaveMind query vector cache"]["service_queries"] == 200
    assert results["WaveMind query vector cache"]["service_results_ok"] is True
    assert results["WaveMind query vector cache"]["service_encoder_calls"] == 1
    assert results["WaveMind query vector cache"]["service_saved_encode_calls"] == 199
    assert results["WaveMind query vector cache"]["service_cache_hits"] >= 199
    assert results["WaveMind query vector cache"]["service_cache_misses"] == 1
    assert results["WaveMind query vector cache"]["service_hit_rate"] >= 0.99
    assert results["WaveMind query vector cache"]["service_metrics_exposed"] is True
    assert results["WaveMind query vector cache"]["p99_service_query_ms"] < 100.0
    assert results["WaveMind API batch query"]["queries"] == 100
    assert results["WaveMind API batch query"]["batch_size"] == 100
    assert results["WaveMind API batch query"]["individual_http_requests"] == 100
    assert results["WaveMind API batch query"]["batch_http_requests"] == 1
    assert results["WaveMind API batch query"]["request_reduction_ratio"] == 0.99
    assert results["WaveMind API batch query"]["individual_success"] is True
    assert results["WaveMind API batch query"]["batch_success"] is True
    assert results["WaveMind API batch query"]["individual_encoder_calls"] == 1
    assert results["WaveMind API batch query"]["batch_encoder_calls"] == 1
    assert results["WaveMind API batch query"]["batch_cache_hits"] == 99
    assert results["WaveMind API batch query"]["batch_cache_misses"] == 1
    assert results["WaveMind API batch query"]["batch_hit_rate"] == 0.99
    assert results["WaveMind API batch query"]["batch_metrics_exposed"] is True
    assert results["WaveMind shared rate limiter"]["shared_across_workers"] is True
    assert results["WaveMind shared rate limiter"]["workers"] == 2
    assert results["WaveMind shared rate limiter"]["allowed"] == 4
    assert results["WaveMind shared rate limiter"]["limited"] == 1
    assert results["WaveMind shared rate limiter"]["expire_seconds"] == 120
    assert results["WaveMind Redis hot cache"]["shared_cache_visible_across_clients"] is True
    assert results["WaveMind Redis hot cache"]["cache_prewarm_warmed"] == 1
    assert results["WaveMind Redis hot cache"]["cache_prewarm_cross_worker_hit"] is True
    assert results["WaveMind Redis hot cache"]["memory_os_ok"] is True
    assert results["WaveMind Redis hot cache"]["memory_os_prewarm_warmed"] >= 2
    assert results["WaveMind Redis hot cache"]["memory_os_predictive_generated"] >= 1
    assert results["WaveMind Redis hot cache"]["memory_os_predictive_warmed"] >= 1
    assert results["WaveMind Redis hot cache"]["memory_os_transition_prefetch_queries"] == ["risk limits"]
    redis_transition = results["WaveMind Redis hot cache"]["memory_os_transition_prefetch_edges"][0]
    assert redis_transition["from_query"] == "budget recall"
    assert redis_transition["to_query"] == "risk limits"
    assert redis_transition["probability"] == 1.0
    assert results["WaveMind Redis hot cache"]["memory_os_transition_prefetch_hit"] is True
    assert results["WaveMind Redis hot cache"]["memory_os_user_feedback_events"] >= 2
    assert results["WaveMind Redis hot cache"]["memory_os_positive_feedback_priority_delta"] > 0.0
    assert results["WaveMind Redis hot cache"]["memory_os_negative_feedback_priority_delta"] < 0.0
    assert results["WaveMind Redis hot cache"]["memory_os_priority_predictions"] >= 1
    assert results["WaveMind Redis hot cache"]["memory_os_priority_boost_total"] > 0.0
    assert results["WaveMind Redis hot cache"]["memory_os_forgetting_demotions"] >= 1
    assert results["WaveMind Redis hot cache"]["memory_os_forgetting_decay_total"] > 0.0
    assert results["WaveMind Redis hot cache"]["memory_os_architecture_advice_status"] == "architecture_required"
    assert "namespace-sharding" in results["WaveMind Redis hot cache"]["memory_os_architecture_recommendations"]
    assert results["WaveMind Redis hot cache"]["memory_os_cross_worker_hit"] is True
    assert results["WaveMind Redis hot cache"]["namespace_invalidation_removed"] is True
    assert results["WaveMind API cache mutation safety"]["first_query_cached"] is True
    assert results["WaveMind API cache mutation safety"]["cache_invalidated_on_remember"] is True
    assert results["WaveMind API cache mutation safety"]["stale_prevented_after_remember"] is True
    assert results["WaveMind API cache mutation safety"]["cache_invalidated_on_feedback"] is True
    assert results["WaveMind API cache mutation safety"]["feedback_demoted_rejected_memory"] is True
    assert results["WaveMind API cache mutation safety"]["cache_invalidated_on_forget"] is True
    assert results["WaveMind API cache mutation safety"]["stale_prevented_after_forget"] is True
    assert results["WaveMind batch feedback"]["ok"] is True
    assert results["WaveMind batch feedback"]["accepted"] == 2
    assert results["WaveMind batch feedback"]["rejected"] == 1
    assert results["WaveMind batch feedback"]["cache_was_warmed"] is True
    assert results["WaveMind batch feedback"]["cache_invalidated"] is True
    assert results["WaveMind batch feedback"]["audit_events"] == 2
    assert results["WaveMind batch feedback"]["positive_feedback_priority_delta"] > 0.0
    assert results["WaveMind batch feedback"]["negative_feedback_priority_delta"] < 0.0
    assert results["WaveMind batch feedback"]["p99_api_ms"] <= 100.0
    assert results["WaveMind Memory OS"]["ok"] is True
    assert results["WaveMind Memory OS"]["hot_queries"] == 2
    assert results["WaveMind Memory OS"]["prewarm_warmed"] == 2
    assert results["WaveMind Memory OS"]["prewarm_hit"] is True
    assert results["WaveMind Memory OS"]["predictive_prefetch_generated"] >= 1
    assert results["WaveMind Memory OS"]["predictive_prefetch_warmed"] >= 1
    assert results["WaveMind Memory OS"]["predictive_prefetch_queries"]
    assert results["WaveMind Memory OS"]["transition_prefetch_queries"] == ["risk limits"]
    transition = results["WaveMind Memory OS"]["transition_prefetch_edges"][0]
    assert transition["from_query"] == "budget recall"
    assert transition["to_query"] == "risk limits"
    assert transition["probability"] == 1.0
    assert results["WaveMind Memory OS"]["transition_prefetch_hit"] is True
    assert results["WaveMind Memory OS"]["expired_purged"] == 1
    assert results["WaveMind Memory OS"]["concepts_created"] == 1
    assert results["WaveMind Memory OS"]["user_feedback_events"] >= 2
    assert results["WaveMind Memory OS"]["positive_feedback_priority_delta"] > 0.0
    assert results["WaveMind Memory OS"]["negative_feedback_priority_delta"] < 0.0
    assert results["WaveMind Memory OS"]["priority_predictions"] >= 1
    assert results["WaveMind Memory OS"]["priority_boost_total"] > 0.0
    assert results["WaveMind Memory OS"]["forgetting_demotions"] >= 1
    assert results["WaveMind Memory OS"]["forgetting_decay_total"] > 0.0
    assert results["WaveMind Memory OS"]["architecture_advice_status"] == "architecture_required"
    assert "namespace-sharding" in results["WaveMind Memory OS"]["architecture_advice_recommendation_ids"]
    assert "production-controls" in results["WaveMind Memory OS"]["architecture_advice_recommendation_ids"]
    assert results["WaveMind Memory OS"]["architecture_next_commands"] >= 1
    assert results["WaveMind Memory OS"]["suggestion_count"] >= 5
    assert "predictive-prefetch-active" in results["WaveMind Memory OS"]["suggestion_ids"]
    assert "priority-learning-active" in results["WaveMind Memory OS"]["suggestion_ids"]
    assert "adaptive-forgetting-active" in results["WaveMind Memory OS"]["suggestion_ids"]
    assert "architecture:namespace-sharding" in results["WaveMind Memory OS"]["suggestion_ids"]
    assert "architecture_required" in results["WaveMind Memory OS"]["suggestion_severities"]
    assert results["WaveMind Memory OS"]["suggestions_with_evidence"] >= 5
    assert results["WaveMind Memory OS"]["policy_status"] == "architecture_required"
    assert results["WaveMind Memory OS"]["policy_decision_count"] >= 6
    assert "prefetch-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "priority-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "forgetting-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "consolidation-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "scale-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "coordination-policy" in results["WaveMind Memory OS"]["policy_decision_ids"]
    assert "architecture_required" in results["WaveMind Memory OS"]["policy_decision_statuses"]
    assert results["WaveMind Memory OS"]["policy_decision_strategies"][
        "prefetch-policy"
    ] == "hot-query-and-transition-prefetch"
    assert results["WaveMind Memory OS"]["policy_decision_strategies"][
        "scale-policy"
    ] == "external-index-sharding-and-production-controls"
    assert results["WaveMind Memory OS"]["policy_history_trend"] == "first_run"
    assert results["WaveMind Memory OS"]["policy_history_previous_runs"] == 0
    assert results["WaveMind Memory OS"]["policy_repeated_required_ids"] == []
    assert results["WaveMind Memory OS"]["policy_history_escalations"] == 0
    assert results["WaveMind Memory OS"]["scheduler_status"] == "architecture_required"
    assert results["WaveMind Memory OS"]["scheduler_effective_cache_mode"] == "redis"
    assert results["WaveMind Memory OS"]["execution_safe_to_run"] is True
    assert results["WaveMind Memory OS"]["execution_requires_shared_cache"] is True
    assert results["WaveMind Memory OS"]["execution_requires_distributed_lock"] is True
    assert results["WaveMind Memory OS"]["execution_max_parallel_workers"] >= 4
    assert results["WaveMind Memory OS"]["execution_step_count"] >= 7
    assert "cache-prewarm" in results["WaveMind Memory OS"]["execution_worker_pool_tasks"]
    assert "memory-os" in results["WaveMind Memory OS"]["execution_singleton_tasks"]
    assert "memory-os" in results["WaveMind Memory OS"]["execution_state_mutating_tasks"]
    assert results["WaveMind Memory OS"]["execution_blocked_tasks"] == []
    assert "distributed-lock-required" in results["WaveMind Memory OS"]["execution_warnings"]
    assert "WAVEMIND_REDIS_URL" in results["WaveMind Memory OS"]["execution_required_environment"]
    assert (
        "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL"
        in results["WaveMind Memory OS"]["execution_required_environment"]
    )
    assert results["WaveMind Memory OS"]["execution_run_scopes"]["memory-os"] == "cluster-singleton"
    assert results["WaveMind Memory OS"]["execution_run_scopes"]["cache-prewarm"] == "worker-pool"
    assert results["WaveMind Memory OS"]["concept_recall"] is True
    assert "prewarm_cache" in results["WaveMind Memory OS"]["actions"]
    assert "predictive_prefetch" in results["WaveMind Memory OS"]["actions"]
    assert "predict_priority" in results["WaveMind Memory OS"]["actions"]
    assert "adaptive_forgetting" in results["WaveMind Memory OS"]["actions"]
    assert "consolidate_concepts" in results["WaveMind Memory OS"]["actions"]
    assert "advise_architecture" in results["WaveMind Memory OS"]["actions"]
    assert results["WaveMind distributed sharding"]["writes"] == 2
    assert results["WaveMind distributed sharding"]["recalled_after_primary_loss"] is True
    assert results["WaveMind distributed sharding"]["repair_missing_before"] is True
    assert results["WaveMind distributed sharding"]["repair_repaired_total"] == 1
    assert results["WaveMind distributed sharding"]["repair_ok"] is True
    assert results["WaveMind distributed sharding"]["recalled_after_repair"] is True
    assert results["WaveMind distributed sharding"]["forget_replicated_deletes"] == 2
    assert results["WaveMind distributed sharding"]["tombstone_replication_factor"] == 3
    assert results["WaveMind distributed sharding"]["tombstone_write_quorum"] == 2
    assert results["WaveMind distributed sharding"]["tombstone_missed_delete_replica_records"] == 1
    assert results["WaveMind distributed sharding"]["tombstone_suppressed_before_repair"] is True
    assert results["WaveMind distributed sharding"]["tombstone_repair_canonical_records"] == 0
    assert results["WaveMind distributed sharding"]["tombstone_repair_deleted_records"] == 1
    assert results["WaveMind distributed sharding"]["tombstone_stale_records_after_repair"] == 0
    assert results["WaveMind distributed sharding"]["tombstone_suppressed_after_repair"] is True
    assert results["WaveMind distributed sharding"]["anti_entropy_worker_ok"] is True
    assert results["WaveMind distributed sharding"]["anti_entropy_worker_repaired_total"] == 1
    assert results["WaveMind distributed sharding"]["anti_entropy_worker_tombstone_deleted"] == 1
    assert results["WaveMind distributed HTTP sharding"]["proxy_bypass_default"] is True
    assert results["WaveMind distributed HTTP sharding"]["writes"] == 2
    assert results["WaveMind distributed HTTP sharding"]["recalled_after_primary_loss"] is True
    assert results["WaveMind distributed HTTP sharding"]["repair_missing_before"] is True
    assert results["WaveMind distributed HTTP sharding"]["repair_ok"] is True
    assert results["WaveMind distributed HTTP sharding"]["repair_repaired_total"] == 1
    assert results["WaveMind distributed HTTP sharding"]["recalled_after_repair"] is True
    assert results["WaveMind distributed HTTP sharding"]["tombstone_missed_delete_replica_records"] == 1
    assert results["WaveMind distributed HTTP sharding"]["tombstone_suppressed_before_repair"] is True
    assert results["WaveMind distributed HTTP sharding"]["tombstone_repair_canonical_records"] == 0
    assert results["WaveMind distributed HTTP sharding"]["tombstone_repair_deleted_records"] == 1
    assert results["WaveMind distributed HTTP sharding"]["tombstone_stale_records_after_repair"] == 0
    assert results["WaveMind distributed HTTP sharding"]["tombstone_suppressed_after_repair"] is True
    assert results["WaveMind distributed HTTP sharding"]["concurrent_writes"] == 12
    assert results["WaveMind distributed HTTP sharding"]["concurrent_write_ok"] is True
    assert results["WaveMind distributed HTTP sharding"]["concurrent_query_hit_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["nodes"] == 4
    assert results["WaveMind sustained HTTP cluster load"]["replication_factor"] == 3
    assert results["WaveMind sustained HTTP cluster load"]["read_fanout"] == 1
    assert results["WaveMind sustained HTTP cluster load"]["write_success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["query_hit_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["failover_hit_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["forget_success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["delete_suppression_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["write_batches"] == 1
    assert results["WaveMind sustained HTTP cluster load"]["forget_batches"] == 1
    assert (
        results["WaveMind sustained HTTP cluster load"]["write_batch_http_requests"]
        < results["WaveMind sustained HTTP cluster load"][
            "write_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"][
            "write_batch_request_reduction_ratio"
        ]
        > 0.0
    )
    assert (
        results["WaveMind sustained HTTP cluster load"]["forget_batch_http_requests"]
        < results["WaveMind sustained HTTP cluster load"][
            "forget_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"]["tombstone_batch_http_requests"]
        < results["WaveMind sustained HTTP cluster load"][
            "tombstone_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"][
            "forget_tombstone_batch_http_requests"
        ]
        < results["WaveMind sustained HTTP cluster load"][
            "forget_tombstone_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"][
            "forget_tombstone_batch_request_reduction_ratio"
        ]
        > 0.0
    )
    assert results["WaveMind sustained HTTP cluster load"]["query_batches"] == 1
    assert results["WaveMind sustained HTTP cluster load"]["failover_query_batches"] == 1
    assert results["WaveMind sustained HTTP cluster load"]["delete_suppression_query_batches"] == 1
    assert (
        results["WaveMind sustained HTTP cluster load"]["query_batch_http_requests"]
        < results["WaveMind sustained HTTP cluster load"][
            "query_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"]["failover_batch_http_requests"]
        < results["WaveMind sustained HTTP cluster load"][
            "failover_batch_individual_http_requests"
        ]
    )
    assert (
        results["WaveMind sustained HTTP cluster load"][
            "query_batch_request_reduction_ratio"
        ]
        > 0.0
    )
    assert results["WaveMind sustained HTTP cluster load"]["repair_missing_before"] is True
    assert results["WaveMind sustained HTTP cluster load"]["repair_ok"] is True
    assert results["WaveMind sustained HTTP cluster load"]["repair_repaired_total"] >= 1
    assert results["WaveMind sustained HTTP cluster load"]["repaired_replica"] is True
    assert results["WaveMind sustained HTTP cluster load"]["success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["p99_operation_ms"] <= 2000.0
    assert results["WaveMind sustained HTTP cluster load"]["query_batch_p99_ms"] <= 1000.0
    assert results["WaveMind sustained HTTP cluster load"]["failover_batch_p99_ms"] <= 1000.0
    assert results["WaveMind replicated runtime"]["recalled_after_node_loss"] is True
    assert results["WaveMind replicated runtime"]["repair_copied_records"] == 1
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_before_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_after_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_repair_deleted_records"] == 1
    assert results["WaveMind replicated runtime"]["concurrent_writes"] == 12
    assert results["WaveMind replicated runtime"]["concurrent_write_ok"] is True
    assert results["WaveMind replicated runtime"]["concurrent_query_hit_rate"] == 1.0
    assert results["WaveMind active-active delta sync"]["converged_after_bidirectional_sync"] is True
    assert results["WaveMind active-active delta sync"]["incremental_records_exported"] == 1
    assert results["WaveMind active-active delta sync"]["incremental_records_imported"] == 3
    assert results["WaveMind active-active delta sync"]["incremental_skipped_records"] == 0
    assert results["WaveMind active-active delta sync"]["incremental_converged"] is True
    assert results["WaveMind active-active delta sync"]["field_only_records_exported"] == 0
    assert results["WaveMind active-active delta sync"]["field_only_keys_exported"] >= 1
    assert results["WaveMind active-active delta sync"]["field_only_imported_records"] == 0
    assert results["WaveMind active-active delta sync"]["suppressed_stale_import_after_delete"] is True
    assert results["WaveMind active-active delta sync"]["tombstone_converged"] is True
    assert results["WaveMind active-active delta sync"]["tombstone_deleted_records"] == 3
    assert results["WaveMind sustained active-active sync"]["regions"] == 3
    assert results["WaveMind sustained active-active sync"]["namespaces"] == 3
    assert results["WaveMind sustained active-active sync"]["writes"] == 18
    assert results["WaveMind sustained active-active sync"]["pair_syncs"] == 90
    assert results["WaveMind sustained active-active sync"]["cursor_count"] == 18
    assert results["WaveMind sustained active-active sync"]["records_imported"] >= 54
    assert results["WaveMind sustained active-active sync"]["tombstones_imported"] >= 1
    assert results["WaveMind sustained active-active sync"]["deleted_records"] >= 3
    assert results["WaveMind sustained active-active sync"]["field_keys_exported"] >= 1
    assert results["WaveMind sustained active-active sync"]["final_noop_records_imported"] == 0
    assert results["WaveMind sustained active-active sync"]["final_noop_failed_pairs"] == 0
    assert results["WaveMind sustained active-active sync"]["convergence_rate"] == 1.0
    assert results["WaveMind sustained active-active sync"]["delete_suppression_rate"] == 1.0
    assert results["WaveMind sustained active-active sync"]["success_rate"] == 1.0
    assert results["WaveMind sustained active-active sync"]["failed_pairs"] == 0
    assert results["WaveMind sustained active-active sync"]["has_more_pairs"] == 0
    assert results["WaveMind HTTP active-active service-region sync"]["service_boundary"] == "FastAPI TestClient"
    assert results["WaveMind HTTP active-active service-region sync"]["regions"] == 3
    assert results["WaveMind HTTP active-active service-region sync"]["namespaces"] == 2
    assert results["WaveMind HTTP active-active service-region sync"]["writes"] == 6
    assert results["WaveMind HTTP active-active service-region sync"]["pair_syncs"] == 48
    assert results["WaveMind HTTP active-active service-region sync"]["cursor_count"] == 12
    assert results["WaveMind HTTP active-active service-region sync"]["export_calls"] == 48
    assert results["WaveMind HTTP active-active service-region sync"]["import_calls"] == 48
    assert results["WaveMind HTTP active-active service-region sync"]["records_imported"] >= 18
    assert results["WaveMind HTTP active-active service-region sync"]["tombstones_imported"] >= 1
    assert results["WaveMind HTTP active-active service-region sync"]["deleted_records"] >= 3
    assert results["WaveMind HTTP active-active service-region sync"]["convergence_rate"] == 1.0
    assert results["WaveMind HTTP active-active service-region sync"]["delete_suppression_rate"] == 1.0
    assert results["WaveMind HTTP active-active service-region sync"]["success_rate"] == 1.0
    assert results["WaveMind HTTP active-active service-region sync"]["failed_pairs"] == 0
    assert results["WaveMind HTTP active-active service-region sync"]["final_noop_records_imported"] == 0
    assert results["WaveMind field-state CRDT"]["commutative_convergence"] is True
    assert results["WaveMind field-state CRDT"]["idempotent_remerge"] is True
    assert results["WaveMind field-state CRDT"]["tombstone_wins"] is True
    assert results["WaveMind field-state CRDT"]["top_key_converged"] is True
    assert results["WaveMind field-state CRDT"]["watermark_convergence"] is True
    assert results["WaveMind field-state CRDT"]["watermark_actors"] == 3
    assert results["WaveMind field-state CRDT"]["max_watermark"] == 100.0
    assert results["WaveMind field-state CRDT"]["partial_delta_watermark_actors"] == [
        "region-a",
        "region-b",
    ]
    assert results["WaveMind field-state CRDT"]["watermark_health_ok"] is True
    assert results["WaveMind field-state CRDT"]["watermark_health_status"] == "pass"
    assert results["WaveMind field-state CRDT"]["watermark_health_regions"] == 2
    assert results["WaveMind field-state CRDT"]["watermark_health_max_observed_lag"] == 0.0
    assert results["WaveMind field-state CRDT"]["watermark_missing_detected"] is True
    assert results["WaveMind field-state CRDT"]["watermark_lag_detected"] is True
    assert results["WaveMind field-state CRDT"]["budget_activation"] == 5.0
    assert results["WaveMind replicated snapshot"]["manifest_healthy"] is True
    assert results["WaveMind replicated snapshot"]["offsite_verified"] is True
    assert results["WaveMind replicated snapshot"]["archive_verified"] is True
    assert results["WaveMind replicated snapshot"]["object_store_verified"] is True
    assert results["WaveMind replicated snapshot"]["object_store_latest_verified"] is True
    assert results["WaveMind replicated snapshot"]["object_store_pruned"] == 2
    assert results["WaveMind replicated snapshot"]["object_store_download_verified"] is True
    assert results["WaveMind replicated snapshot"]["object_store_drill_ok"] is True
    assert results["WaveMind replicated snapshot"]["restored_files"] == 3
    assert results["WaveMind replicated snapshot"]["recalled_after_restore_node_loss"] is True
    assert results["WaveMind recovery journal"]["journal_entries"] == 5
    assert results["WaveMind recovery journal"]["actions"] == [
        "remember",
        "remember",
        "remember",
        "forget",
        "purge_expired",
    ]
    assert results["WaveMind recovery journal"]["full_restore_ok"] is True
    assert results["WaveMind recovery journal"]["point_in_time_restore_ok"] is True
    assert results["WaveMind recovery journal"]["full_deleted_records"] == 2
    assert results["WaveMind recovery journal"]["full_restored_records"] == 1
    assert results["WaveMind recovery journal"]["point_applied_entries"] == 1
    assert results["WaveMind recovery journal"]["point_restored_records"] == 1
    assert results["WaveMind recovery journal"]["vector_dim_preserved"] == 64
    assert results["WaveMind recovery journal"]["pattern_shape_preserved"] == [16, 16]
    assert results["WaveMind structured payloads"]["precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["modalities"] == [
        "image",
        "audio",
        "table",
        "event",
        "video",
        "3d",
        "graph",
    ]
    assert results["WaveMind structured payloads"]["queries"] == 7
    assert results["WaveMind structured payloads"]["cross_modal_queries"] == 7
    assert results["WaveMind structured payloads"]["cross_modal_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["cross_modal_embedding_dim"] == 64
    assert results["WaveMind structured payloads"]["cross_modal_vectors_persisted_rate"] == 1.0
    assert results["WaveMind structured payloads"]["cross_modal_provenance_rate"] == 1.0
    assert results["WaveMind structured payloads"]["asset_manifest_verified"] is True
    assert results["WaveMind structured payloads"]["asset_manifest_sha256_present"] is True
    assert results["WaveMind structured payloads"]["asset_manifest_media_type"] == "video/mp4"
    assert results["WaveMind structured payloads"]["asset_manifest_provenance_rate"] == 1
    assert results["WaveMind structured payloads"]["cross_modal_target_modalities"] == [
        "image",
        "audio",
        "table",
        "event",
        "video",
        "3d",
        "graph",
    ]
    assert results["WaveMind structured payloads"]["precomputed_vector_queries"] == 4
    assert results["WaveMind structured payloads"]["precomputed_vector_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["precomputed_vector_embedding_dim"] == 4
    assert results["WaveMind structured payloads"]["precomputed_vector_persisted_rate"] == 1.0
    assert results["WaveMind structured payloads"]["precomputed_vector_target_modalities"] == [
        "image",
        "audio",
        "video",
        "3d",
    ]
    assert results["WaveMind structured payloads"]["encoder_contract_ok"] is True
    assert results["WaveMind structured payloads"]["encoder_contract_encoder"] == "scale-readiness-precomputed-contract"
    assert results["WaveMind structured payloads"]["encoder_contract_modalities"] == [
        "image",
        "audio",
        "table",
        "event",
        "video",
        "3d",
        "graph",
    ]
    assert results["WaveMind structured payloads"]["encoder_contract_payloads"] == 7
    assert results["WaveMind structured payloads"]["encoder_contract_target_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_global_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_target_modality_routing_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_persisted_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_normalized_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_finite_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_contract_provenance_rate"] == 1.0
    assert (
        results["WaveMind structured payloads"]["encoder_contract_min_global_margin"]
        >= results["WaveMind structured payloads"]["encoder_contract_min_required_margin"]
    )
    assert results["WaveMind structured payloads"]["encoder_contract_failures"] == []
    assert results["WaveMind structured payloads"]["encoder_health_ok"] is True
    assert results["WaveMind structured payloads"]["encoder_health_encoder"] == "descriptor"
    assert results["WaveMind structured payloads"]["encoder_health_payloads"] == 7
    assert results["WaveMind structured payloads"]["encoder_health_queries"] == 7
    assert results["WaveMind structured payloads"]["encoder_health_global_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_target_modality_routing_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_finite_payload_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_normalized_payload_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_finite_query_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_normalized_query_vector_rate"] == 1.0
    assert results["WaveMind structured payloads"]["encoder_health_dimension_match_rate"] == 1.0
    assert (
        results["WaveMind structured payloads"]["encoder_health_min_global_margin"]
        >= results["WaveMind structured payloads"]["encoder_health_min_required_margin"]
    )
    assert results["WaveMind structured payloads"]["encoder_health_failures"] == []
    assert results["WaveMind structured payloads"]["temporal_event_queries"] == 4
    assert results["WaveMind structured payloads"]["temporal_event_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["temporal_event_around_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["temporal_event_window_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["temporal_event_recency_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["temporal_event_interval_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["temporal_event_persistence_rate"] == 1.0
    assert results["WaveMind structured payloads"]["temporal_event_provenance_rate"] == 1.0
    assert results["WaveMind structured payloads"]["knowledge_graph_queries"] == 4
    assert results["WaveMind structured payloads"]["knowledge_graph_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["knowledge_graph_path_precision_at_1"] == 1.0
    assert results["WaveMind structured payloads"]["knowledge_graph_direct_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["knowledge_graph_two_hop_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["knowledge_graph_three_hop_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["knowledge_graph_predicate_precision_at_1"] == 1
    assert results["WaveMind structured payloads"]["knowledge_graph_persistence_rate"] == 1.0
    assert results["WaveMind structured payloads"]["knowledge_graph_provenance_rate"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["target_memories"] == 100_000_000
    assert results["WaveMind 100M capacity envelope"]["placement_algorithm"] == "weighted-rendezvous-zone-aware"
    assert results["WaveMind 100M capacity envelope"]["node_count"] == 128
    assert results["WaveMind 100M capacity envelope"]["replication_factor"] == 3
    assert results["WaveMind 100M capacity envelope"]["node_loss_min_availability"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["zone_loss_min_availability"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["distinct_replica_rate"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["zone_spread_rate"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["replica_load_skew"] <= 1.25
    assert results["WaveMind 100M capacity envelope"]["scale_out_target_node_count"] == 160
    assert results["WaveMind 100M capacity envelope"]["scale_out_new_node_count"] == 32
    assert 0.0 < results["WaveMind 100M capacity envelope"]["scale_out_replica_set_movement_ratio"] < 0.75
    assert results["WaveMind 100M capacity envelope"]["scale_out_moved_to_new_node"] > 0
    assert results["WaveMind 100M capacity envelope"]["scale_out_target_zone_spread_rate"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["scale_out_target_replica_load_skew"] <= 1.25
    assert results["WaveMind 100M capacity envelope"]["valid_capacity_plan"] is True
    assert payload["scenario"]["simulated_memories"] == 100_000


def test_serverless_operational_profile_prefers_remote_observed_telemetry(
    monkeypatch,
    tmp_path,
):
    remote_path = tmp_path / "observed-telemetry.remote.json"
    remote_path.write_text(
        json.dumps(
            {
                "source": "github-actions-serverless-observed-telemetry",
                "methodology": "Measured a balanced pool of user-supplied WaveMind API node URLs.",
                "node_mode": "external",
                "requests_per_second": 5000.0,
                "measured_pool_requests_per_second": 1000.0,
                "per_replica_requests_per_second": 500.0,
                "avg_request_ms": 20.0,
                "p95_request_ms": 40.0,
                "p99_request_ms": 60.0,
                "cold_start_ms": 900.0,
                "error_rate": 0.0,
                "max_replicas": 7,
                "configured_max_scale": 256,
                "scale_out_seconds": 18.0,
                "measured_replicas": 2,
                "external_node_count": 2,
                "seed_mode": "first",
                "cold_start_measured": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scale_readiness_benchmark,
        "SERVERLESS_REMOTE_OBSERVED_TELEMETRY_PATH",
        remote_path,
    )

    profile = scale_readiness_benchmark.run_serverless_operational_profile()

    assert profile["observed_telemetry_path"].endswith("observed-telemetry.remote.json")
    assert profile["observed_telemetry_source"] == "github-actions-serverless-observed-telemetry"
    assert profile["observed_node_mode"] == "external"
    assert profile["observed_external_node_count"] == 2
    assert profile["observed_seed_mode"] == "first"
    assert profile["observed_cold_start_measured"] is False
    assert profile["observed_slo_pass"] is True
