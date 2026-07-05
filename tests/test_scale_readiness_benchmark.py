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
    assert results["WaveMind Kubernetes operator"]["bundle_has_crd"] is True
    assert results["WaveMind Kubernetes operator"]["bundle_has_operator_deployment"] is True
    assert results["WaveMind Kubernetes operator"]["has_service"] is True
    assert results["WaveMind Kubernetes operator"]["has_statefulset"] is True
    assert results["WaveMind Kubernetes operator"]["has_hpa"] is True
    assert results["WaveMind Kubernetes operator"]["autoscaling_max_replicas"] == 12
    assert results["WaveMind Kubernetes operator"]["autoscaling_metrics"] == ["cpu", "memory"]
    assert results["WaveMind Kubernetes operator"]["has_repair_cronjob"] is True
    assert results["WaveMind Kubernetes operator"]["repair_namespaces"] == 64
    assert results["WaveMind serverless plan"]["has_knative_service"] is True
    assert results["WaveMind serverless plan"]["has_keda_scaled_object"] is True
    assert results["WaveMind serverless plan"]["scale_to_zero"] is True
    assert results["WaveMind serverless plan"]["max_scale"] == 64
    assert results["WaveMind serverless plan"]["target_concurrency"] == 80
    assert results["WaveMind serverless plan"]["uses_postgres"] is True
    assert results["WaveMind serverless plan"]["uses_external_qdrant"] is True
    assert results["WaveMind serverless plan"]["uses_shared_cache"] is True
    assert results["WaveMind serverless plan"]["safe_for_pod_eviction"] is True
    assert results["WaveMind serverless plan"]["keda_scale_target_kind"] == "Deployment"
    assert results["WaveMind serverless plan"]["valid_keda_scale_target"] is True
    assert results["WaveMind serverless plan"]["env_has_postgres_dsn"] is True
    assert results["WaveMind serverless plan"]["env_has_qdrant_url"] is True
    assert results["WaveMind hot cache"]["hit_rate"] > 0.0
    assert results["WaveMind hot cache"]["prewarm_warmed"] == 1
    assert results["WaveMind hot cache"]["prewarm_hit"] is True
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
    assert results["WaveMind replicated runtime"]["recalled_after_node_loss"] is True
    assert results["WaveMind replicated runtime"]["repair_copied_records"] == 1
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_before_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_after_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_repair_deleted_records"] == 1
    assert results["WaveMind active-active delta sync"]["converged_after_bidirectional_sync"] is True
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
    assert payload["scenario"]["simulated_memories"] == 100_000
