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
    assert results["WaveMind hot cache"]["hit_rate"] > 0.0
    assert results["WaveMind structured payloads"]["precision_at_1"] == 1.0
    assert payload["scenario"]["simulated_memories"] == 100_000
