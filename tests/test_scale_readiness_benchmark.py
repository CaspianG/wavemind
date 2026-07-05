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
    assert results["WaveMind hot cache"]["hit_rate"] > 0.0
    assert results["WaveMind distributed sharding"]["writes"] == 2
    assert results["WaveMind distributed sharding"]["recalled_after_primary_loss"] is True
    assert results["WaveMind distributed sharding"]["forget_replicated_deletes"] == 2
    assert results["WaveMind replicated runtime"]["recalled_after_node_loss"] is True
    assert results["WaveMind replicated runtime"]["repair_copied_records"] == 1
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_before_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_suppressed_after_repair"] is True
    assert results["WaveMind replicated runtime"]["tombstone_repair_deleted_records"] == 1
    assert results["WaveMind active-active delta sync"]["converged_after_bidirectional_sync"] is True
    assert results["WaveMind active-active delta sync"]["suppressed_stale_import_after_delete"] is True
    assert results["WaveMind active-active delta sync"]["tombstone_converged"] is True
    assert results["WaveMind active-active delta sync"]["tombstone_deleted_records"] == 3
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
