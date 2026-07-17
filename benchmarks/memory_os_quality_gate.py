from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AB = Path("benchmarks/memory_os_ab_results.json")
DEFAULT_LOCOMO = Path("benchmarks/locomo_sentence_evidence_results.json")
DEFAULT_LONGMEMEVAL = Path("benchmarks/longmemeval_evidence_results.json")
DEFAULT_ANSWERS = Path("benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json")
MAX_P95_REGRESSION_RATIO = 0.20
MAX_P95_REGRESSION_MS = 5.0
MIN_TASK_SUCCESS_UPLIFT = 0.05


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source(path: Path) -> str:
    return path.as_posix()


def _results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["engine"]): dict(item)
        for item in payload.get("results") or []
        if isinstance(item, dict) and item.get("engine")
    }


def _check(check_id: str, title: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "passed": bool(passed),
        "evidence": evidence,
        "source": _source(DEFAULT_AB),
    }


def _latency_delta(memory_os: dict[str, Any], baseline: dict[str, Any], key: str) -> tuple[float, float]:
    baseline_value = float(baseline[key])
    delta_ms = float(memory_os[key]) - baseline_value
    ratio = delta_ms / baseline_value if baseline_value > 0.0 else float("inf")
    return delta_ms, ratio


def _supplemental_evidence(
    locomo_payload: dict[str, Any] | None,
    longmemeval_payload: dict[str, Any] | None,
    answer_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, payload, mode in (
        (DEFAULT_LOCOMO, locomo_payload, "WaveMind retrieval without Memory OS worker execution"),
        (DEFAULT_LONGMEMEVAL, longmemeval_payload, "WaveMind retrieval without Memory OS worker execution"),
        (DEFAULT_ANSWERS, answer_payload, "WaveMind answer context without Memory OS worker execution"),
    ):
        if payload is None:
            continue
        rows.append(
            {
                "source": _source(source),
                "schema": payload.get("schema"),
                "execution_mode": mode,
                "eligible_for_memory_os_uplift": False,
                "reason": "The dataset runner does not execute Memory OS background policies.",
            }
        )
    return rows


def build_quality_gate(
    *,
    agent_payload: dict[str, Any],
    locomo_payload: dict[str, Any] | None = None,
    longmemeval_payload: dict[str, Any] | None = None,
    answer_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if agent_payload.get("schema") != "wavemind.memory_os_ab_benchmark.v1":
        raise ValueError("quality gate requires wavemind.memory_os_ab_benchmark.v1 evidence")
    protocol = dict(agent_payload.get("protocol") or {})
    engines = _results(agent_payload)
    baseline = engines["WaveMind baseline"]
    memory_os = engines["WaveMind + Memory OS"]

    task_uplift = float(memory_os["task_success_rate"]) - float(baseline["task_success_rate"])
    stale_suppression_uplift = float(baseline["stale_error_rate"]) - float(memory_os["stale_error_rate"])
    p95_delta_ms, p95_regression_ratio = _latency_delta(memory_os, baseline, "p95_latency_ms")
    cold_delta_ms, cold_regression_ratio = _latency_delta(memory_os, baseline, "cold_p95_latency_ms")
    comparable_protocol = (
        bool(protocol.get("hash"))
        and protocol.get("same_memories") is True
        and protocol.get("same_observed_queries") is True
        and protocol.get("same_evaluation_queries") is True
        and int(protocol.get("cold_repetitions") or 0) >= 5
    )
    latency_ok = (
        p95_delta_ms <= MAX_P95_REGRESSION_MS
        and p95_regression_ratio <= MAX_P95_REGRESSION_RATIO
    )
    cold_latency_ok = (
        cold_delta_ms <= MAX_P95_REGRESSION_MS
        and cold_regression_ratio <= MAX_P95_REGRESSION_RATIO
    )
    checks = [
        _check(
            "direct-comparable-protocol",
            "Baseline and Memory OS execute the same sequential adaptive protocol",
            comparable_protocol,
            f"protocol_hash={protocol.get('hash')}, workload={protocol.get('workload')}",
        ),
        _check(
            "memory-os-task-success-uplift",
            "Memory OS improves task success over WaveMind baseline",
            task_uplift >= MIN_TASK_SUCCESS_UPLIFT,
            f"memory_os={memory_os['task_success_rate']:.4f}, baseline={baseline['task_success_rate']:.4f}, uplift={task_uplift:.4f}",
        ),
        _check(
            "memory-os-stale-suppression-uplift",
            "Memory OS reduces stale recalls over WaveMind baseline",
            stale_suppression_uplift > 0.0 and float(memory_os["stale_error_rate"]) == 0.0,
            f"memory_os={memory_os['stale_error_rate']:.4f}, baseline={baseline['stale_error_rate']:.4f}, uplift={stale_suppression_uplift:.4f}",
        ),
        _check(
            "memory-os-adaptation-fired",
            "Priority learning and adaptive forgetting both changed state",
            int(memory_os.get("priority_predictions") or 0) > 0
            and int(memory_os.get("forgetting_demotions") or 0) > 0,
            f"priority_predictions={memory_os.get('priority_predictions')}, forgetting_demotions={memory_os.get('forgetting_demotions')}",
        ),
        _check(
            "context-shape-equivalent",
            "Both variants return the same context shape",
            int(memory_os.get("context_items_per_query") or 0)
            == int(baseline.get("context_items_per_query") or 0),
            f"memory_os={memory_os.get('context_items_per_query')}, baseline={baseline.get('context_items_per_query')}",
        ),
        _check(
            "memory-os-p95-latency",
            "Memory OS p95 stays within both the 20 percent and 5 ms regression limits",
            latency_ok,
            f"memory_os={memory_os['p95_latency_ms']:.4f}ms, baseline={baseline['p95_latency_ms']:.4f}ms, delta={p95_delta_ms:.4f}ms, ratio={p95_regression_ratio:.4f}",
        ),
        _check(
            "memory-os-cold-p95-latency",
            "Cold p95 stays within both the 20 percent and 5 ms regression limits",
            cold_latency_ok,
            f"memory_os={memory_os['cold_p95_latency_ms']:.4f}ms, baseline={baseline['cold_p95_latency_ms']:.4f}ms, delta={cold_delta_ms:.4f}ms, ratio={cold_regression_ratio:.4f}",
        ),
    ]
    passed = all(item["passed"] for item in checks)
    return {
        "schema": "wavemind.memory_os_quality_gate.v2",
        "generated_at": _utc_now(),
        "source_ref": agent_payload.get("source_ref"),
        "status": "pass" if passed else "fail",
        "claim_boundary": (
            "Only the direct WaveMind baseline versus WaveMind plus Memory OS A/B controls this gate. "
            "LoCoMo and LongMemEval are supplemental because their current runners do not execute Memory OS policies."
        ),
        "thresholds": {
            "min_task_success_uplift": MIN_TASK_SUCCESS_UPLIFT,
            "max_p95_regression_ratio": MAX_P95_REGRESSION_RATIO,
            "max_p95_regression_ms": MAX_P95_REGRESSION_MS,
        },
        "summary": {
            "passed_count": sum(item["passed"] for item in checks),
            "check_count": len(checks),
            "failed_check_ids": [item["id"] for item in checks if not item["passed"]],
        },
        "metrics": {
            "memory_os_task_success": memory_os["task_success_rate"],
            "baseline_task_success": baseline["task_success_rate"],
            "task_success_uplift": task_uplift,
            "memory_os_stale_error_rate": memory_os["stale_error_rate"],
            "baseline_stale_error_rate": baseline["stale_error_rate"],
            "stale_suppression_uplift": stale_suppression_uplift,
            "memory_os_p95_latency_ms": memory_os["p95_latency_ms"],
            "baseline_p95_latency_ms": baseline["p95_latency_ms"],
            "p95_latency_delta_ms": p95_delta_ms,
            "p95_latency_regression_ratio": p95_regression_ratio,
            "cold_p95_latency_delta_ms": cold_delta_ms,
            "cold_p95_latency_regression_ratio": cold_regression_ratio,
        },
        "checks": checks,
        "sources": [_source(DEFAULT_AB)],
        "supplemental_evidence": _supplemental_evidence(
            locomo_payload,
            longmemeval_payload,
            answer_payload,
        ),
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
    lines.extend(["", "## Supplemental public benchmarks", ""])
    for item in payload.get("supplemental_evidence") or []:
        lines.append(
            f"- `{item['source']}`: {item['execution_mode']}; not eligible for Memory OS uplift."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=DEFAULT_AB)
    parser.add_argument("--locomo", type=Path, default=DEFAULT_LOCOMO)
    parser.add_argument("--longmemeval", type=Path, default=DEFAULT_LONGMEMEVAL)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/memory_os_quality_results.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("benchmarks/MEMORY_OS_QUALITY.md"))
    args = parser.parse_args()
    payload = build_quality_gate(
        agent_payload=_load(args.agent),
        locomo_payload=_load(args.locomo) if args.locomo.exists() else None,
        longmemeval_payload=_load(args.longmemeval) if args.longmemeval.exists() else None,
        answer_payload=_load(args.answers) if args.answers.exists() else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
