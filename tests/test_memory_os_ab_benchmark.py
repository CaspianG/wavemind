from benchmarks.memory_os_ab_benchmark import run_benchmark


def test_memory_os_ab_uses_identical_protocol_and_proves_uplift():
    payload = run_benchmark(observed_repetitions=8, evaluation_repetitions=8)
    results = {item["engine"]: item for item in payload["results"]}
    baseline = results["WaveMind baseline"]
    memory_os = results["WaveMind + Memory OS"]

    assert payload["schema"] == "wavemind.memory_os_ab_benchmark.v1"
    assert payload["protocol"]["same_memories"] is True
    assert payload["protocol"]["same_observed_queries"] is True
    assert payload["protocol"]["same_evaluation_queries"] is True
    assert memory_os["task_success_rate"] > baseline["task_success_rate"]
    assert memory_os["stale_error_rate"] < baseline["stale_error_rate"]
    assert memory_os["priority_predictions"] >= payload["protocol"]["case_count"]
    assert memory_os["forgetting_demotions"] >= payload["protocol"]["case_count"]
