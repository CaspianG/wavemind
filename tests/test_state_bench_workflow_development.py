from __future__ import annotations

import json
from pathlib import Path

from benchmarks.state_bench_workflow_development import (
    MODEL_WEIGHT_SHA256,
    SEEDS,
    TREATMENTS,
    _aggregate_baseline,
    _ollama_messages,
    _ollama_tools,
    _payload_sha256,
)

PROTOCOL = Path("benchmarks/state_bench_workflow_development_protocol_v1.json")


def test_frozen_state_bench_workflow_protocol_is_development_only() -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))

    assert payload["phase"] == "bounded_development_only"
    assert payload["official_source"]["official_agent_learning_result"] is False
    assert payload["execution_profile"]["cpu_only"] is True
    assert payload["execution_profile"]["num_gpu"] == 0
    assert payload["execution_profile"]["seeds"] == list(SEEDS)
    assert payload["execution_profile"]["model_weight_sha256"] == MODEL_WEIGHT_SHA256
    assert len(payload["rows"]) == 15
    assert {row["split"] for row in payload["rows"]} == {"development"}
    assert len({row["unit_id"] for row in payload["rows"]}) == 15
    assert payload["integrity"]["payload_sha256"] == _payload_sha256(payload)


def test_frozen_protocol_does_not_claim_official_or_text_judge_results() -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    claim = payload["claim_boundary"].lower()

    assert "not an official state-bench result" in claim
    assert "does not score ux" in claim
    assert payload["execution_profile"]["ux_judge"] == "disabled_no_pinned_calibration"
    assert "task_id" in payload["access_policy"]["backend_forbidden_fields"]
    assert "state_requirements" in payload["access_policy"]["backend_forbidden_fields"]


def test_ollama_adapter_preserves_tool_names_and_results() -> None:
    tools = [
        {
            "type": "function",
            "name": "get_booking",
            "description": "Lookup",
            "parameters": {
                "type": "object",
                "properties": {"booking_id": {"type": "string"}},
                "required": ["booking_id"],
            },
        }
    ]
    assert _ollama_tools(tools)[0]["function"]["name"] == "get_booking"

    messages = _ollama_messages(
        "system",
        [
            {"role": "user", "content": "lookup"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "name": "get_booking",
                        "arguments": {"booking_id": "BK-1"},
                        "result": {"status": "confirmed"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": [
                    {
                        "name": "get_booking",
                        "arguments": {"booking_id": "BK-1"},
                        "result": {"status": "confirmed"},
                    }
                ],
            },
        ],
    )
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == {
        "booking_id": "BK-1"
    }
    assert json.loads(messages[3]["content"])["status"] == "confirmed"


def test_baseline_aggregation_is_paired_by_task_and_fail_closed(monkeypatch) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    rows = []
    for unit in protocol["rows"]:
        for seed in SEEDS:
            for treatment in TREATMENTS:
                state_pass = int(
                    treatment == "wavemind-memory-os"
                    or (treatment == "wavemind-core" and seed != SEEDS[0])
                )
                rows.append(
                    {
                        "unit_id": unit["unit_id"],
                        "treatment": treatment,
                        "seed": seed,
                        "status": "completed",
                        "state_pass": state_pass,
                        "has_state_requirements": unit["has_state_requirements"],
                        "turns": 1,
                        "tool_calls": 1,
                        "memory_tool_calls": int(treatment != "no-memory"),
                        "domain_tool_calls": int(treatment == "no-memory"),
                        "tool_errors": 0,
                        "repeated_calls": 0,
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "latency_ms": 20.0,
                        "forbidden_memory_mutations": 0,
                    }
                )
    monkeypatch.setattr(
        "benchmarks.state_bench_workflow_development._git_sha",
        lambda _root: "a" * 40,
    )

    result = _aggregate_baseline(repo_root=Path("."), protocol=protocol, rows=rows)

    assert result["strongest_baseline"] == "wavemind-core"
    assert result["treatments"]["wavemind-core"]["primary_state_task_count"] == 13
    assert result["treatments"]["wavemind-core"]["diagnostic_no_state_task_count"] == 2
    assert result["memory_os_paired_lift"]["mean"] == 0.2
    assert result["memory_os_paired_lift"]["low"] == 0.2
    assert result["admitted_for_product_candidate"] is True
    assert result["integrity"]["payload_sha256"] == _payload_sha256(result)


def test_baseline_aggregation_rejects_missing_rows(monkeypatch) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "benchmarks.state_bench_workflow_development._git_sha",
        lambda _root: "a" * 40,
    )

    try:
        _aggregate_baseline(repo_root=Path("."), protocol=protocol, rows=[])
    except ValueError as exc:
        assert "expected 225 completed rows" in str(exc)
    else:
        raise AssertionError("missing baseline rows must block aggregation")
