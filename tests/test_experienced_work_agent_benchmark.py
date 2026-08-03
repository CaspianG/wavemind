from __future__ import annotations

from benchmarks.experienced_work_agent_benchmark import (
    DATASET_REVISION,
    LATENCY_REPETITIONS,
    _median_latency_row,
    build_split,
    run_benchmark,
    split_fingerprint,
)


def test_experienced_work_agent_split_is_frozen_and_balanced() -> None:
    training, held_out = build_split()
    assert DATASET_REVISION == "experienced-work-agent-v1-frozen-20260728"
    assert len(training) == 60
    assert len(held_out) == 30
    assert len({request.id for _, request in training}) == 60
    assert len({request.id for _, request in held_out}) == 30
    assert {scenario.domain for scenario, _ in held_out} == {
        "coding_repository",
        "support_crm",
        "enterprise_workflow",
    }
    assert all(not request.demonstration_plan for _, request in held_out)
    assert (
        split_fingerprint(training, held_out)
        == "0d8a6b2de3e18f6273f3b148e6fb4b1fbfb7fa0b79dd82c42efb3973caf41225"
    )


def test_experienced_work_agent_meets_held_out_product_gates(tmp_path) -> None:
    assert LATENCY_REPETITIONS >= 7
    payload = run_benchmark(tmp_path)
    assert payload["schema"] == "wavemind.experienced_work_agent_benchmark.v1"
    assert payload["status"] == "pass"
    assert all(check["passed"] for check in payload["checks"])
    assert payload["protocol"]["paired_latency_samples"] is True
    assert (
        payload["protocol"]["latency_repetitions_per_case"]
        == LATENCY_REPETITIONS
    )
    assert all(
        len(row["latency_samples_ms"]) == LATENCY_REPETITIONS
        for engine in ("core", "experience")
        for row in payload["held_out_results"][engine]
    )
    assert payload["training"]["active_strategies"] == 6
    assert payload["dataset"]["metadata_leakage"] is False


def test_latency_row_uses_median_to_reject_single_runner_outlier() -> None:
    row = _median_latency_row(
        [
            {"request_id": "case", "latency_ms": 10.0},
            {"request_id": "case", "latency_ms": 1000.0},
            {"request_id": "case", "latency_ms": 11.0},
        ]
    )

    assert row["latency_ms"] == 11.0
    assert row["latency_samples_ms"] == [10.0, 1000.0, 11.0]
