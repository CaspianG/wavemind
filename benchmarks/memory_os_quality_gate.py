from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AGENT = Path("benchmarks/memory_os_agent_quality_results.json")
DEFAULT_LOCOMO = Path("benchmarks/locomo_sentence_evidence_results.json")
DEFAULT_LONGMEMEVAL = Path("benchmarks/longmemeval_evidence_results.json")
DEFAULT_ANSWERS = Path("benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["engine"]): dict(item)
        for item in payload.get("results") or []
        if isinstance(item, dict) and item.get("engine")
    }


def _check(
    check_id: str,
    title: str,
    passed: bool,
    evidence: str,
    source: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "passed": bool(passed),
        "evidence": evidence,
        "source": source,
    }


def build_quality_gate(
    *,
    agent_payload: dict[str, Any],
    locomo_payload: dict[str, Any],
    longmemeval_payload: dict[str, Any],
    answer_payload: dict[str, Any],
) -> dict[str, Any]:
    agent = _results(agent_payload)
    locomo = _results(locomo_payload)
    longmemeval = _results(longmemeval_payload)
    answers = _results(answer_payload)
    base = agent["WaveMind"]
    memory_os = agent["WaveMind + Memory OS"]
    agent_static = agent["Static vector"]
    locomo_wave = locomo["WaveMind"]
    locomo_static = locomo["Static vector"]
    long_wave = longmemeval["WaveMind"]
    long_static = longmemeval["Static vector"]
    answer_wave = answers["WaveMind"]
    answer_static = max(
        (answers[name] for name in ("Chroma static", "Qdrant static")),
        key=lambda item: float(item["token_f1"]),
    )

    agent_delta = float(memory_os["task_success_rate"]) - float(base["task_success_rate"])
    stale_delta = float(memory_os["stale_error_rate"]) - float(base["stale_error_rate"])
    locomo_lift = float(locomo_wave["evidence_recall_at_k"]) - float(
        locomo_static["evidence_recall_at_k"]
    )
    long_lift = float(long_wave["evidence_recall_at_k"]) - float(
        long_static["evidence_recall_at_k"]
    )
    answer_f1_lift = float(answer_wave["token_f1"]) - float(answer_static["token_f1"])
    answer_evidence_lift = float(answer_wave["evidence_recall_at_k"]) - float(
        answer_static["evidence_recall_at_k"]
    )

    checks = [
        _check(
            "memory-os-agent-non-regression",
            "Memory OS preserves WaveMind agent task success",
            agent_delta >= -0.01,
            f"memory_os={memory_os['task_success_rate']:.4f}, base={base['task_success_rate']:.4f}, delta={agent_delta:.4f}",
            str(DEFAULT_AGENT),
        ),
        _check(
            "memory-os-stale-safety",
            "Memory OS does not increase stale-memory errors",
            stale_delta <= 0.0 and float(memory_os["stale_error_rate"]) == 0.0,
            f"memory_os={memory_os['stale_error_rate']:.4f}, base={base['stale_error_rate']:.4f}",
            str(DEFAULT_AGENT),
        ),
        _check(
            "memory-os-context-efficiency",
            "Memory OS retains at least 80 percent context savings",
            float(memory_os["context_budget_saved"]) >= 0.80,
            f"context_budget_saved={memory_os['context_budget_saved']:.4f}",
            str(DEFAULT_AGENT),
        ),
        _check(
            "agent-static-lift",
            "Dynamic memory beats static memory on agent task success",
            float(memory_os["task_success_rate"]) > float(agent_static["task_success_rate"]),
            f"memory_os={memory_os['task_success_rate']:.4f}, static={agent_static['task_success_rate']:.4f}",
            str(DEFAULT_AGENT),
        ),
        _check(
            "locomo-retrieval-lift",
            "WaveMind improves LoCoMo evidence recall over static retrieval",
            locomo_lift >= 0.05,
            f"wave={locomo_wave['evidence_recall_at_k']:.4f}, static={locomo_static['evidence_recall_at_k']:.4f}, lift={locomo_lift:.4f}",
            str(DEFAULT_LOCOMO),
        ),
        _check(
            "longmemeval-retrieval-lift",
            "WaveMind improves LongMemEval evidence recall over static retrieval",
            long_lift >= 0.10,
            f"wave={long_wave['evidence_recall_at_k']:.4f}, static={long_static['evidence_recall_at_k']:.4f}, lift={long_lift:.4f}",
            str(DEFAULT_LONGMEMEVAL),
        ),
        _check(
            "longmemeval-answer-lift",
            "WaveMind context improves LongMemEval answer F1 and evidence recall",
            answer_f1_lift >= 0.05 and answer_evidence_lift >= 0.10,
            f"f1_lift={answer_f1_lift:.4f}, evidence_lift={answer_evidence_lift:.4f}",
            str(DEFAULT_ANSWERS),
        ),
    ]
    passed = all(item["passed"] for item in checks)
    return {
        "schema": "wavemind.memory_os_quality_gate.v1",
        "generated_at": _utc_now(),
        "status": "pass" if passed else "fail",
        "claim_boundary": (
            "Memory OS non-regression is measured directly on the agent-coherence workload. "
            "LoCoMo and LongMemEval rows prove the underlying WaveMind dynamic retrieval and "
            "answer-context quality; they do not claim that unattended Memory OS workers ran "
            "inside those public datasets."
        ),
        "summary": {
            "passed_count": sum(item["passed"] for item in checks),
            "check_count": len(checks),
            "failed_check_ids": [item["id"] for item in checks if not item["passed"]],
        },
        "metrics": {
            "memory_os_task_success": memory_os["task_success_rate"],
            "memory_os_stale_error_rate": memory_os["stale_error_rate"],
            "memory_os_context_budget_saved": memory_os["context_budget_saved"],
            "memory_os_agent_delta": agent_delta,
            "locomo_recall_lift": locomo_lift,
            "longmemeval_recall_lift": long_lift,
            "longmemeval_answer_f1_lift": answer_f1_lift,
            "longmemeval_answer_evidence_lift": answer_evidence_lift,
        },
        "checks": checks,
        "sources": [
            str(DEFAULT_AGENT),
            str(DEFAULT_LOCOMO),
            str(DEFAULT_LONGMEMEVAL),
            str(DEFAULT_ANSWERS),
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WaveMind Memory OS Quality Gate",
        "",
        payload["claim_boundary"],
        "",
        f"Status: `{payload['status']}`",
        "",
        "| check | result | evidence | source |",
        "|---|---|---|---|",
    ]
    lines.extend(
        "| {title} | `{result}` | {evidence} | `{source}` |".format(
            title=item["title"],
            result="pass" if item["passed"] else "fail",
            evidence=item["evidence"],
            source=item["source"],
        )
        for item in payload["checks"]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    parser.add_argument("--locomo", type=Path, default=DEFAULT_LOCOMO)
    parser.add_argument("--longmemeval", type=Path, default=DEFAULT_LONGMEMEVAL)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_quality_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/MEMORY_OS_QUALITY.md"),
    )
    args = parser.parse_args()
    payload = build_quality_gate(
        agent_payload=_load(args.agent),
        locomo_payload=_load(args.locomo),
        longmemeval_payload=_load(args.longmemeval),
        answer_payload=_load(args.answers),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
