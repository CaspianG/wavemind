from __future__ import annotations

import pytest

from benchmarks.experienced_work_agent_benchmark import (
    DATASET_REVISION,
    LATENCY_REPETITIONS,
    _median_latency_row,
    _paired_latency_regression,
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
    checks = {check["id"]: check for check in payload["checks"]}
    assert all(
        check["passed"]
        for check_id, check in checks.items()
        if check_id != "p95-latency"
    )
    assert checks["p95-latency"]["target"] == (
        "<= 0.20 relative, or <= 5 ms absolute delta when baseline is < 5 ms; "
        "experience runtime overhead <= 75 ms"
    )
    assert checks["p95-latency"]["evidence"][
        "relative_regression"
    ] == pytest.approx(payload["uplift"]["p95_latency_regression"])
    by_engine = {row["engine"]: row for row in payload["results"]}
    assert payload["uplift"]["p95_latency_regression"] == pytest.approx(
        by_engine["WaveMind Experience"]["p95_runtime_overhead_ms"]
        / by_engine["WaveMind Core"]["p95_runtime_overhead_ms"]
        - 1.0
    )
    assert payload["uplift"][
        "p95_runtime_overhead_absolute_delta_ms"
    ] == pytest.approx(
        by_engine["WaveMind Experience"]["p95_runtime_overhead_ms"]
        - by_engine["WaveMind Core"]["p95_runtime_overhead_ms"]
    )
    assert payload["protocol"]["paired_latency_samples"] is True
    assert payload["protocol"]["core_retrieval_mode"] == "raw_non_production"
    assert payload["protocol"]["production_abstention_admission_eligible"] is False
    assert payload["protocol"]["paired_latency_regression_estimator"] == (
        "relative regression between engine p95 runtime overheads from "
        "per-case paired medians, excluding tool and environment-verification "
        "latency"
    )
    assert (
        payload["protocol"]["latency_repetitions_per_case"]
        == LATENCY_REPETITIONS
    )
    assert all(
        len(row["latency_samples_ms"]) == LATENCY_REPETITIONS
        for engine in ("core", "experience")
        for row in payload["held_out_results"][engine]
    )
    assert all(
        len(row["paired_latency_regression_samples"]) == LATENCY_REPETITIONS
        for row in payload["held_out_results"]["experience"]
    )
    assert all(
        len(row["runtime_overhead_samples_ms"]) == LATENCY_REPETITIONS
        for engine in ("core", "experience")
        for row in payload["held_out_results"][engine]
    )
    assert all(
        0.0 <= row["runtime_overhead_ms"] <= row["latency_ms"]
        for engine in ("core", "experience")
        for row in payload["held_out_results"][engine]
    )
    assert payload["training"]["active_strategies"] == 6
    assert payload["dataset"]["metadata_leakage"] is False


def test_latency_row_uses_median_to_reject_single_runner_outlier() -> None:
    row = _median_latency_row(
        [
            {
                "request_id": "case",
                "latency_ms": 10.0,
                "runtime_overhead_ms": 4.0,
            },
            {
                "request_id": "case",
                "latency_ms": 1000.0,
                "runtime_overhead_ms": 400.0,
            },
            {
                "request_id": "case",
                "latency_ms": 11.0,
                "runtime_overhead_ms": 5.0,
            },
        ]
    )

    assert row["latency_ms"] == 11.0
    assert row["latency_samples_ms"] == [10.0, 1000.0, 11.0]
    assert row["runtime_overhead_ms"] == 5.0
    assert row["runtime_overhead_samples_ms"] == [4.0, 400.0, 5.0]


def test_paired_latency_regression_rejects_unpaired_runner_drift() -> None:
    regression, samples = _paired_latency_regression(
        [
            {"runtime_overhead_ms": 10.0},
            {"runtime_overhead_ms": 20.0},
            {"runtime_overhead_ms": 40.0},
        ],
        [
            {"runtime_overhead_ms": 11.0},
            {"runtime_overhead_ms": 22.0},
            {"runtime_overhead_ms": 44.0},
        ],
    )

    assert regression == pytest.approx(0.10)
    assert samples == pytest.approx([0.10, 0.10, 0.10])
