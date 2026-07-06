from benchmarks.scale_readiness_benchmark import run_benchmark


def test_scale_readiness_benchmark_covers_cluster_cache_and_payloads():
    payload = run_benchmark(
        simulated_memories=100_000,
        namespace_count=64,
        node_count=3,
        replication_factor=2,
        cache_queries=100,
        cache_capacity=32,
    )
    results = {result["engine"]: result for result in payload["results"]}

    assert results["WaveMind cluster planner"]["node_loss_min_availability"] == 1.0
    assert results["WaveMind cluster planner"]["zone_loss_min_availability"] == 1.0
    assert results["WaveMind cluster planner"]["write_quorum"] == 2
    assert results["WaveMind cluster autoscaler"]["status"] == "scale_required"
    assert results["WaveMind cluster autoscaler"]["required_nodes"] > 3
    assert results["WaveMind cluster autoscaler"]["target_within_headroom"] is True
    assert results["WaveMind cluster autoscaler"]["has_scale_action"] is True
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
    assert results["WaveMind Kubernetes operator"]["has_service"] is True
    assert results["WaveMind Kubernetes operator"]["has_statefulset"] is True
    assert results["WaveMind Kubernetes operator"]["has_hpa"] is True
    assert results["WaveMind Kubernetes operator"]["statefulset_replicas"] >= 29
    assert results["WaveMind Kubernetes operator"]["capacity_required_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["capacity_target_max_node_memories"] <= 700_000
    assert results["WaveMind Kubernetes operator"]["autoscaling_max_replicas"] >= results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["autoscaling_metrics"] == ["cpu", "memory"]
    assert results["WaveMind Kubernetes operator"]["status_ready"] is True
    assert results["WaveMind Kubernetes operator"]["status_phase"] == "Ready"
    assert results["WaveMind Kubernetes operator"]["status_ready_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["status_required_replicas"] == results["WaveMind Kubernetes operator"]["statefulset_replicas"]
    assert results["WaveMind Kubernetes operator"]["status_capacity_within_headroom"] is True
    assert results["WaveMind Kubernetes operator"]["status_degraded_nodes"] == 0
    assert results["WaveMind Kubernetes operator"]["control_plane_ready"] is True
    assert results["WaveMind Kubernetes operator"]["control_plane_voters"] >= 3
    assert results["WaveMind Kubernetes operator"]["control_plane_final_revision"] == 2
    assert results["WaveMind Kubernetes operator"]["control_plane_minority_blocked"] is True
    assert set(results["WaveMind Kubernetes operator"]["status_conditions_true"]) == {
        "AutoscalingReady",
        "CapacityPlanned",
        "ControlPlaneReady",
        "RepairScheduled",
        "ResourcesReady",
    }
    assert results["WaveMind Kubernetes operator"]["has_repair_cronjob"] is True
    assert results["WaveMind Kubernetes operator"]["repair_namespaces"] == 64
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
    assert results["WaveMind API cache mutation safety"]["cache_invalidated_on_forget"] is True
    assert results["WaveMind API cache mutation safety"]["stale_prevented_after_forget"] is True
    assert results["WaveMind Memory OS"]["ok"] is True
    assert results["WaveMind Memory OS"]["hot_queries"] == 2
    assert results["WaveMind Memory OS"]["prewarm_warmed"] == 2
    assert results["WaveMind Memory OS"]["prewarm_hit"] is True
    assert results["WaveMind Memory OS"]["predictive_prefetch_generated"] >= 1
    assert results["WaveMind Memory OS"]["predictive_prefetch_warmed"] >= 1
    assert results["WaveMind Memory OS"]["predictive_prefetch_queries"]
    assert results["WaveMind Memory OS"]["expired_purged"] == 1
    assert results["WaveMind Memory OS"]["concepts_created"] == 1
    assert results["WaveMind Memory OS"]["priority_predictions"] >= 1
    assert results["WaveMind Memory OS"]["priority_boost_total"] > 0.0
    assert results["WaveMind Memory OS"]["forgetting_demotions"] >= 1
    assert results["WaveMind Memory OS"]["forgetting_decay_total"] > 0.0
    assert results["WaveMind Memory OS"]["architecture_advice_status"] == "architecture_required"
    assert "namespace-sharding" in results["WaveMind Memory OS"]["architecture_advice_recommendation_ids"]
    assert "production-controls" in results["WaveMind Memory OS"]["architecture_advice_recommendation_ids"]
    assert results["WaveMind Memory OS"]["architecture_next_commands"] >= 1
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
    assert results["WaveMind sustained HTTP cluster load"]["write_success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["query_hit_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["failover_hit_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["forget_success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["delete_suppression_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["repair_missing_before"] is True
    assert results["WaveMind sustained HTTP cluster load"]["repair_ok"] is True
    assert results["WaveMind sustained HTTP cluster load"]["repair_repaired_total"] >= 1
    assert results["WaveMind sustained HTTP cluster load"]["repaired_replica"] is True
    assert results["WaveMind sustained HTTP cluster load"]["success_rate"] == 1.0
    assert results["WaveMind sustained HTTP cluster load"]["p99_operation_ms"] < 1000.0
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
    assert results["WaveMind field-state CRDT"]["commutative_convergence"] is True
    assert results["WaveMind field-state CRDT"]["idempotent_remerge"] is True
    assert results["WaveMind field-state CRDT"]["tombstone_wins"] is True
    assert results["WaveMind field-state CRDT"]["top_key_converged"] is True
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
    assert results["WaveMind 100M capacity envelope"]["target_memories"] == 100_000_000
    assert results["WaveMind 100M capacity envelope"]["node_count"] == 128
    assert results["WaveMind 100M capacity envelope"]["replication_factor"] == 3
    assert results["WaveMind 100M capacity envelope"]["node_loss_min_availability"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["zone_loss_min_availability"] == 1.0
    assert results["WaveMind 100M capacity envelope"]["replica_load_skew"] <= 1.25
    assert results["WaveMind 100M capacity envelope"]["valid_capacity_plan"] is True
    assert payload["scenario"]["simulated_memories"] == 100_000
