from benchmarks.memory_os_ab_benchmark import run_benchmark


def test_memory_os_ab_uses_identical_protocol_and_proves_uplift():
    payload = run_benchmark(
        observed_repetitions=8,
        evaluation_repetitions=12,
        cold_repetitions=10,
        measurement_trials=5,
    )
    results = {item["engine"]: item for item in payload["results"]}
    baseline = results["WaveMind baseline"]
    memory_os = results["WaveMind + Memory OS"]

    assert payload["schema"] == "wavemind.memory_os_ab_benchmark.v1"
    assert payload["protocol"]["same_memories"] is True
    assert payload["protocol"]["same_observed_queries"] is True
    assert payload["protocol"]["same_evaluation_queries"] is True
    assert payload["protocol"]["cold_repetitions"] == 10
    assert payload["protocol"]["measurement_trials"] == 5
    assert payload["protocol"]["latency_aggregation"] == "median_of_trial_p95"
    assert payload["protocol"]["execution_order"] == "alternating_baseline_memory_os"
    assert baseline["measurement_trials"] == 5
    assert memory_os["measurement_trials"] == 5
    assert baseline["query_count"] == baseline["queries_per_trial"] * 5
    assert len(memory_os["latency_trials_ms"]["cold_p95_latency_ms"]) == 5
    assert memory_os["task_success_rate"] > baseline["task_success_rate"]
    assert memory_os["stale_error_rate"] < baseline["stale_error_rate"]
    assert memory_os["priority_predictions"] >= payload["protocol"]["case_count"]
    assert memory_os["forgetting_demotions"] >= payload["protocol"]["case_count"]
