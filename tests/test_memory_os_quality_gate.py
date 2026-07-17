import copy
import json
from pathlib import Path

from benchmarks.memory_os_quality_gate import build_quality_gate, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name).read_text(encoding="utf-8"))


def _payload() -> dict:
    return build_quality_gate(
        agent_payload=_load("memory_os_ab_results.json"),
        locomo_payload=_load("locomo_sentence_evidence_results.json"),
        longmemeval_payload=_load("longmemeval_evidence_results.json"),
        answer_payload=_load("longmemeval_answer_qwen25_1_5b_50_results.json"),
    )


def test_memory_os_quality_gate_requires_direct_uplift_and_latency_safety():
    payload = _payload()

    assert payload["schema"] == "wavemind.memory_os_quality_gate.v2"
    assert payload["status"] == "pass"
    assert payload["summary"]["passed_count"] == payload["summary"]["check_count"]
    assert payload["metrics"]["task_success_uplift"] >= 0.05
    assert payload["metrics"]["stale_suppression_uplift"] > 0
    assert payload["metrics"]["p95_latency_delta_ms"] <= 5
    assert payload["metrics"]["p95_latency_regression_ratio"] <= 0.20
    assert payload["sources"] == ["benchmarks/memory_os_ab_results.json"]
    assert all(
        item["eligible_for_memory_os_uplift"] is False
        for item in payload["supplemental_evidence"]
    )


def test_memory_os_quality_gate_rejects_non_regression_without_improvement():
    direct_ab = copy.deepcopy(_load("memory_os_ab_results.json"))
    results = {item["engine"]: item for item in direct_ab["results"]}
    results["WaveMind + Memory OS"]["task_success_rate"] = results["WaveMind baseline"][
        "task_success_rate"
    ]
    payload = build_quality_gate(agent_payload=direct_ab)

    assert payload["status"] == "fail"
    assert "memory-os-task-success-uplift" in payload["summary"]["failed_check_ids"]


def test_memory_os_quality_gate_rejects_under_sampled_cold_latency():
    direct_ab = copy.deepcopy(_load("memory_os_ab_results.json"))
    direct_ab["protocol"]["cold_repetitions"] = 5
    payload = build_quality_gate(agent_payload=direct_ab)

    assert payload["status"] == "fail"
    assert "direct-comparable-protocol" in payload["summary"]["failed_check_ids"]


def test_memory_os_quality_gate_rejects_either_latency_limit():
    direct_ab = copy.deepcopy(_load("memory_os_ab_results.json"))
    results = {item["engine"]: item for item in direct_ab["results"]}
    baseline = results["WaveMind baseline"]
    memory_os = results["WaveMind + Memory OS"]
    memory_os["p95_latency_ms"] = float(baseline["p95_latency_ms"]) * 1.21
    payload = build_quality_gate(agent_payload=direct_ab)
    assert "memory-os-p95-latency" in payload["summary"]["failed_check_ids"]

    direct_ab = copy.deepcopy(_load("memory_os_ab_results.json"))
    results = {item["engine"]: item for item in direct_ab["results"]}
    results["WaveMind + Memory OS"]["p95_latency_ms"] = (
        float(results["WaveMind baseline"]["p95_latency_ms"]) + 5.01
    )
    payload = build_quality_gate(agent_payload=direct_ab)
    assert "memory-os-p95-latency" in payload["summary"]["failed_check_ids"]


def test_memory_os_quality_markdown_keeps_claim_boundary_visible():
    markdown = render_markdown(_payload())

    assert "# WaveMind Memory OS Quality Gate" in markdown
    assert "Only the direct WaveMind baseline" in markdown
    assert "not eligible for Memory OS uplift" in markdown
