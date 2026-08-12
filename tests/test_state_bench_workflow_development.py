from __future__ import annotations

import json
from pathlib import Path

from benchmarks.state_bench_workflow_development import (
    MODEL_WEIGHT_SHA256,
    SEEDS,
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
