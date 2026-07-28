from __future__ import annotations

from benchmarks.experienced_work_agent_benchmark import (
    DATASET_REVISION,
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
    payload = run_benchmark(tmp_path)
    assert payload["schema"] == "wavemind.experienced_work_agent_benchmark.v1"
    assert payload["status"] == "pass"
    assert all(check["passed"] for check in payload["checks"])
    assert payload["training"]["active_strategies"] == 6
    assert payload["dataset"]["metadata_leakage"] is False
