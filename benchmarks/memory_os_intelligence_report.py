from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCALE_SOURCE = "benchmarks/scale_readiness_results.json"
AGENT_SOURCE = "benchmarks/agent_coherence_results.json"
CANARY_SOURCE = "benchmarks/memory_os_canary_results.json"
ADMISSION_SOURCE = "benchmarks/memory_os_admission_results.json"

REQUIRED_POLICY_IDS = {
    "prefetch-policy",
    "priority-policy",
    "forgetting-policy",
    "consolidation-policy",
    "scale-policy",
    "coordination-policy",
}


def build_memory_os_intelligence_report(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    scale = _load_json(root / SCALE_SOURCE)
    agent = _load_json(root / AGENT_SOURCE)
    canary = _load_json(root / CANARY_SOURCE)
    admission = _load_json(root / ADMISSION_SOURCE)

    memory_os = _engine_row(scale, "WaveMind Memory OS")
    redis_os = _engine_row(scale, "WaveMind Redis hot cache")
    agent_os = _engine_row(agent, "WaveMind + Memory OS")
    agent_os_metrics = (
        dict(agent_os.get("memory_os") or {})
        if isinstance(agent_os.get("memory_os"), dict)
        else {}
    )

    checks = _checks(memory_os, redis_os, agent_os, agent_os_metrics, canary, admission)
    passed = sum(1 for check in checks if check["pass"])
    summary = {
        "status": "pass" if passed == len(checks) else "watch",
        "check_count": len(checks),
        "passed_check_count": passed,
        "worker_ok": memory_os.get("ok"),
        "hot_queries": memory_os.get("hot_queries"),
        "prewarm_warmed": memory_os.get("prewarm_warmed"),
        "predictive_prefetch_warmed": memory_os.get("predictive_prefetch_warmed"),
        "transition_prefetch_hit": memory_os.get("transition_prefetch_hit"),
        "concepts_created": memory_os.get("concepts_created"),
        "concept_recall": memory_os.get("concept_recall"),
        "user_feedback_events": memory_os.get("user_feedback_events"),
        "positive_feedback_priority_delta": memory_os.get("positive_feedback_priority_delta"),
        "negative_feedback_priority_delta": memory_os.get("negative_feedback_priority_delta"),
        "priority_predictions": memory_os.get("priority_predictions"),
        "priority_boost_total": memory_os.get("priority_boost_total"),
        "forgetting_demotions": memory_os.get("forgetting_demotions"),
        "forgetting_decay_total": memory_os.get("forgetting_decay_total"),
        "policy_status": memory_os.get("policy_status"),
        "policy_decision_count": memory_os.get("policy_decision_count"),
        "policy_decision_ids": memory_os.get("policy_decision_ids", []),
        "execution_safe_to_run": memory_os.get("execution_safe_to_run"),
        "execution_requires_shared_cache": memory_os.get("execution_requires_shared_cache"),
        "execution_requires_distributed_lock": memory_os.get("execution_requires_distributed_lock"),
        "execution_step_count": memory_os.get("execution_step_count"),
        "execution_worker_pool_tasks": memory_os.get("execution_worker_pool_tasks", []),
        "execution_singleton_tasks": memory_os.get("execution_singleton_tasks", []),
        "execution_required_environment": memory_os.get("execution_required_environment", []),
        "redis_memory_os_cross_worker_hit": redis_os.get("memory_os_cross_worker_hit"),
        "redis_memory_os_busy_lock_skipped": redis_os.get("memory_os_busy_lock_skipped"),
        "redis_memory_os_lock_required": redis_os.get("memory_os_lock_required"),
        "redis_memory_os_lock_acquired": redis_os.get("memory_os_lock_acquired"),
        "redis_memory_os_lock_released": redis_os.get("memory_os_lock_released"),
        "agent_task_success_rate": agent_os.get("task_success_rate"),
        "agent_stale_error_rate": agent_os.get("stale_error_rate"),
        "agent_context_budget_saved": agent_os.get("context_budget_saved"),
        "agent_memory_os_cache_hit_rate": agent_os_metrics.get("cache_hit_rate"),
        "agent_memory_os_priority_predictions": agent_os_metrics.get("priority_predictions"),
        "canary_status": canary.get("status"),
        "canary_admitted": (canary.get("summary") or {}).get("admitted"),
        "canary_prewarm_warmed": (canary.get("summary") or {}).get("prewarm_warmed"),
        "canary_predictive_warmed": (canary.get("summary") or {}).get("predictive_warmed"),
        "admission_status": admission.get("status"),
        "admission_passed_count": (admission.get("summary") or {}).get("passed_count"),
        "admission_blocker_count": (admission.get("summary") or {}).get("blocker_count"),
        "admission_blocker_ids": (admission.get("summary") or {}).get("blocker_ids", []),
    }

    return {
        "schema": "wavemind.memory_os_intelligence_report.v1",
        "generated_at": _generated_at(root),
        "source_ref": _source_ref(root),
        "source_files": [SCALE_SOURCE, AGENT_SOURCE, CANARY_SOURCE, ADMISSION_SOURCE],
        "claim_boundary": (
            "Memory OS intelligence rows come from checked-in deterministic scale, "
            "agent-coherence, staging canary, and admission artifacts. They prove "
            "worker behavior, policy generation, cache prewarm, predictive prefetch, "
            "priority learning, adaptive forgetting, consolidation, and rollout "
            "safety on these fixtures. They do not unlock unattended production "
            "Memory OS automation until the admission gate is admitted with real "
            "shared Redis, distributed lock, runtime env, and large-scale evidence."
        ),
        "summary": summary,
        "checks": checks,
        "raw_metrics": {
            "scale_memory_os": memory_os,
            "redis_memory_os": redis_os,
            "agent_memory_os": agent_os_metrics,
            "canary_summary": canary.get("summary", {}),
            "admission_summary": admission.get("summary", {}),
        },
    }


def render_memory_os_intelligence_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    checks = payload.get("checks", [])
    return "\n".join(
        [
            "# WaveMind Memory OS Intelligence Report",
            "",
            f"Generated: `{payload.get('generated_at', 'unknown')}`.",
            "",
            str(payload.get("claim_boundary", "")),
            "",
            "## Summary",
            "",
            f"- Status: `{summary.get('status', 'missing')}`.",
            f"- Checks: `{summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)}`.",
            f"- Hot queries: `{summary.get('hot_queries', 0)}`.",
            f"- Cache prewarm warmed: `{summary.get('prewarm_warmed', 0)}`.",
            f"- Predictive prefetch warmed: `{summary.get('predictive_prefetch_warmed', 0)}`.",
            f"- Transition-prefetch hit: `{summary.get('transition_prefetch_hit')}`.",
            f"- Priority predictions: `{summary.get('priority_predictions', 0)}`.",
            f"- Forgetting demotions: `{summary.get('forgetting_demotions', 0)}`.",
            f"- Concepts created: `{summary.get('concepts_created', 0)}`.",
            f"- Policy decisions: `{summary.get('policy_decision_count', 0)}`.",
            f"- Execution safe to run: `{summary.get('execution_safe_to_run')}`.",
            f"- Admission status: `{summary.get('admission_status', 'missing')}`.",
            "",
            "## Gate Checks",
            "",
            "| check | status | value | target |",
            "|---|---|---:|---:|",
            *[_check_row(check) for check in checks],
            "",
            "## Intelligence Coverage",
            "",
            "| area | evidence |",
            "|---|---|",
            (
                "| Hot-query prewarm | "
                f"`{summary.get('hot_queries', 0)}` hot queries, "
                f"`{summary.get('prewarm_warmed', 0)}` warmed. |"
            ),
            (
                "| Predictive prefetch | "
                f"`{summary.get('predictive_prefetch_warmed', 0)}` warmed, "
                f"transition hit `{summary.get('transition_prefetch_hit')}`. |"
            ),
            (
                "| Priority learning | "
                f"`{summary.get('priority_predictions', 0)}` predictions, "
                f"positive delta `{_fmt(summary.get('positive_feedback_priority_delta'))}`, "
                f"negative delta `{_fmt(summary.get('negative_feedback_priority_delta'))}`. |"
            ),
            (
                "| Adaptive forgetting | "
                f"`{summary.get('forgetting_demotions', 0)}` demotions, "
                f"decay total `{_fmt(summary.get('forgetting_decay_total'))}`. |"
            ),
            (
                "| Consolidation | "
                f"`{summary.get('concepts_created', 0)}` concepts created, "
                f"recall `{summary.get('concept_recall')}`. |"
            ),
            (
                "| Rollout safety | "
                f"shared cache `{summary.get('execution_requires_shared_cache')}`, "
                f"distributed lock `{summary.get('execution_requires_distributed_lock')}`, "
                f"required env `{', '.join(summary.get('execution_required_environment', []))}`. |"
            ),
            (
                "| Agent effect | "
                f"task success `{_fmt(summary.get('agent_task_success_rate'))}`, "
                f"stale error `{_fmt(summary.get('agent_stale_error_rate'))}`, "
                f"context saved `{_fmt(summary.get('agent_context_budget_saved'))}`. |"
            ),
            "",
            "## Production Boundary",
            "",
            "The checked-in Memory OS canary passes, but production admission remains plan-only until shared Redis, distributed lock, runtime environment, and strict large-scale evidence are present.",
            "",
        ]
    )


def _checks(
    memory_os: dict[str, Any],
    redis_os: dict[str, Any],
    agent_os: dict[str, Any],
    agent_os_metrics: dict[str, Any],
    canary: dict[str, Any],
    admission: dict[str, Any],
) -> list[dict[str, Any]]:
    policy_ids = set(memory_os.get("policy_decision_ids", []) or [])
    admission_summary = admission.get("summary") if isinstance(admission.get("summary"), dict) else {}
    canary_summary = canary.get("summary") if isinstance(canary.get("summary"), dict) else {}
    return [
        _check("worker_ok", memory_os.get("ok"), True, "is"),
        _check("hot_queries", memory_os.get("hot_queries"), 2, ">="),
        _check("prewarm_warmed", memory_os.get("prewarm_warmed"), 2, ">="),
        _check("predictive_prefetch_warmed", memory_os.get("predictive_prefetch_warmed"), 6, ">="),
        _check("transition_prefetch_hit", memory_os.get("transition_prefetch_hit"), True, "is"),
        _check("concepts_created", memory_os.get("concepts_created"), 1, ">="),
        _check("concept_recall", memory_os.get("concept_recall"), True, "is"),
        _check("feedback_events", memory_os.get("user_feedback_events"), 8, ">="),
        _check("positive_priority_delta", memory_os.get("positive_feedback_priority_delta"), 0.0, ">"),
        _check("negative_priority_delta", memory_os.get("negative_feedback_priority_delta"), 0.0, "<"),
        _check("priority_predictions", memory_os.get("priority_predictions"), 2, ">="),
        _check("forgetting_demotions", memory_os.get("forgetting_demotions"), 1, ">="),
        _check("policy_decisions_present", REQUIRED_POLICY_IDS.issubset(policy_ids), True, "is"),
        _check("execution_safe_to_run", memory_os.get("execution_safe_to_run"), True, "is"),
        _check("execution_requires_shared_cache", memory_os.get("execution_requires_shared_cache"), True, "is"),
        _check("execution_requires_distributed_lock", memory_os.get("execution_requires_distributed_lock"), True, "is"),
        _check("redis_cross_worker_hit", redis_os.get("memory_os_cross_worker_hit"), True, "is"),
        _check("redis_busy_lock_skipped", redis_os.get("memory_os_busy_lock_skipped"), True, "is"),
        _check("redis_lock_required", redis_os.get("memory_os_lock_required"), True, "is"),
        _check("redis_lock_acquired", redis_os.get("memory_os_lock_acquired"), True, "is"),
        _check("redis_lock_released", redis_os.get("memory_os_lock_released"), True, "is"),
        _check("agent_task_success", agent_os.get("task_success_rate"), 0.9, ">="),
        _check("agent_stale_error", agent_os.get("stale_error_rate"), 0.05, "<="),
        _check("agent_context_saved", agent_os.get("context_budget_saved"), 0.9, ">="),
        _check("agent_memory_os_cache_hit_rate", agent_os_metrics.get("cache_hit_rate"), 0.2, ">="),
        _check("agent_priority_predictions", agent_os_metrics.get("priority_predictions"), 1, ">="),
        _check("canary_pass", canary.get("status"), "pass", "=="),
        _check("canary_admitted", canary_summary.get("admitted"), True, "is"),
        _check("canary_predictive_warmed", canary_summary.get("predictive_warmed"), 10, ">="),
        _check("admission_is_strictly_limited", admission.get("status"), "plan_only", "=="),
        _check("admission_has_blockers", admission_summary.get("blocker_count"), 1, ">="),
    ]


def _check(name: str, value: Any, target: Any, op: str) -> dict[str, Any]:
    passed = False
    if op in {">=", ">", "<=", "<"}:
        try:
            left = float(value)
            right = float(target)
            if op == ">=":
                passed = left >= right
            elif op == ">":
                passed = left > right
            elif op == "<=":
                passed = left <= right
            elif op == "<":
                passed = left < right
        except (TypeError, ValueError):
            passed = False
    elif op == "is":
        passed = value is target
    elif op == "==":
        passed = value == target
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": op,
        "pass": passed,
    }


def _check_row(check: dict[str, Any]) -> str:
    status = "pass" if check.get("pass") else "watch"
    target = f"{check.get('op')} {check.get('target')}"
    return (
        f"| {check.get('name')} | `{status}` | "
        f"`{_fmt(check.get('value'))}` | `{target}` |"
    )


def _engine_row(payload: dict[str, Any], engine: str) -> dict[str, Any]:
    for row in payload.get("results", []):
        if isinstance(row, dict) and row.get("engine") == engine:
            return row
    return {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _generated_at(root: Path) -> str:
    value = os.getenv("WAVEMIND_BENCHMARK_GENERATED_AT")
    if value:
        return value
    source = _load_json(root / SCALE_SOURCE)
    if source.get("generated_at"):
        return str(source["generated_at"])
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str:
    value = os.getenv("GITHUB_SHA") or os.getenv("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value[:12]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_intelligence_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/MEMORY_OS_INTELLIGENCE.md"),
    )
    args = parser.parse_args()
    payload = build_memory_os_intelligence_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_memory_os_intelligence_markdown(payload),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
