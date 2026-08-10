from __future__ import annotations


def test_dynamic_dataset_has_two_provable_memory_categories():
    from benchmarks.agent_memory_advantage_benchmark import build_dynamic_dataset

    dataset = build_dynamic_dataset()
    categories = {query.category for query in dataset.queries}

    assert len(dataset.memories) == len(dataset.queries) * 2
    assert {"knowledge_update", "workflow_gotcha"}.issubset(categories)
    assert all(query.expected_evidence_ids for query in dataset.queries)
    assert all(query.forbidden_evidence_ids for query in dataset.queries)


def test_advantage_benchmark_reports_paired_confidence_and_honest_skips():
    from benchmarks.agent_memory_advantage_benchmark import run_benchmark

    payload = run_benchmark(
        measurement_trials=5,
        include_chroma=False,
        include_qdrant=False,
        include_mem0=False,
        include_langgraph=False,
    )
    results = {row["engine"]: row for row in payload["results"]}
    memory_os = results["WaveMind + Memory OS"]
    core = results["WaveMind Core"]

    assert payload["status"] == "pass"
    assert payload["protocol"]["measurement_trials"] == 5
    assert payload["protocol"]["same_memories"] is True
    assert payload["protocol"]["same_queries"] is True
    assert payload["protocol"]["same_embeddings"] is True
    assert memory_os["task_success_rate"] > core["task_success_rate"]
    assert memory_os["stale_error_rate"] <= 0.02
    assert memory_os["context_budget_saved"] >= 0.30
    assert (
        payload["paired_lift"]["categories"]["knowledge_update"]["lower"]
        > 0.0
    )
    assert (
        payload["paired_lift"]["categories"]["knowledge_update"]["observations"]
        == 9
    )
    assert (
        payload["paired_lift"]["categories"]["workflow_gotcha"]["lower"]
        > 0.0
    )
    assert (
        payload["paired_lift"]["categories"]["workflow_gotcha"]["observations"]
        == 6
    )
    assert payload["strongest_local_baseline"]["combined_lift"] > 0.0
    skipped = {row["engine"]: row for row in payload["skipped"]}
    assert skipped["Chroma static"]["reason"] == "disabled_by_cli"
    assert skipped["Qdrant static"]["reason"] == "disabled_by_cli"
    assert skipped["Mem0 OSS"]["reason"] == "disabled_by_cli"
    assert skipped["LangGraph persistent memory"]["reason"] == "disabled_by_cli"
