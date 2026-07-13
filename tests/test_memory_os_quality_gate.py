import copy
import json
from pathlib import Path

from benchmarks.memory_os_quality_gate import build_quality_gate, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name).read_text(encoding="utf-8"))


def _payload() -> dict:
    return build_quality_gate(
        agent_payload=_load("memory_os_agent_quality_results.json"),
        locomo_payload=_load("locomo_sentence_evidence_results.json"),
        longmemeval_payload=_load("longmemeval_evidence_results.json"),
        answer_payload=_load("longmemeval_answer_qwen25_1_5b_50_results.json"),
    )


def test_memory_os_quality_gate_passes_checked_evidence():
    payload = _payload()

    assert payload["schema"] == "wavemind.memory_os_quality_gate.v1"
    assert payload["status"] == "pass"
    assert payload["summary"]["passed_count"] == payload["summary"]["check_count"]
    assert payload["metrics"]["memory_os_stale_error_rate"] == 0
    assert payload["metrics"]["locomo_recall_lift"] > 0.1
    assert payload["metrics"]["longmemeval_recall_lift"] > 0.2


def test_memory_os_quality_gate_fails_agent_regression():
    agent = copy.deepcopy(_load("memory_os_agent_quality_results.json"))
    memory_os = next(item for item in agent["results"] if item["engine"] == "WaveMind + Memory OS")
    memory_os["task_success_rate"] = 0.1
    payload = build_quality_gate(
        agent_payload=agent,
        locomo_payload=_load("locomo_sentence_evidence_results.json"),
        longmemeval_payload=_load("longmemeval_evidence_results.json"),
        answer_payload=_load("longmemeval_answer_qwen25_1_5b_50_results.json"),
    )

    assert payload["status"] == "fail"
    assert "memory-os-agent-non-regression" in payload["summary"]["failed_check_ids"]


def test_memory_os_quality_markdown_keeps_claim_boundary_visible():
    markdown = render_markdown(_payload())

    assert "# WaveMind Memory OS Quality Gate" in markdown
    assert "do not claim that unattended Memory OS workers ran" in markdown
    assert "LoCoMo" in markdown
    assert "LongMemEval" in markdown
