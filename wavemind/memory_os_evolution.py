from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .core import WaveMind
from .encoders import HashingTextEncoder
from .jobs import HotMemoryCache, MemoryOSScheduler, MemoryOSWorker


MEMORY_OS_EVOLUTION_SCHEMA = "wavemind.memory_os_policy_evolution.v1"
REQUIRED_DECISION_IDS = {
    "prefetch-policy",
    "priority-policy",
    "forgetting-policy",
    "consolidation-policy",
    "scale-policy",
    "coordination-policy",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _seed_memory(memory: WaveMind, *, namespace: str, run_id: str) -> None:
    rows = [
        (
            "The user budget is two thousand dollars.",
            ("profile", "budget"),
            2.0,
        ),
        (
            "The user risk limit is two percent per trade.",
            ("profile", "risk"),
            2.0,
        ),
        (
            "The user prefers concise operational answers.",
            ("profile", "style"),
            2.0,
        ),
        (
            "The user researches market structure and liquidity sweeps.",
            ("research", "trading"),
            1.5,
        ),
        (
            "Memory OS should learn hot budget and risk recall paths.",
            ("memory-os", "policy"),
            1.5,
        ),
        (
            "Stale note: the user wants slow verbose essays.",
            ("stale",),
            0.4,
        ),
    ]
    for text, tags, priority in rows:
        memory.remember(
            text,
            namespace=namespace,
            tags=tags,
            priority=priority,
            metadata={"policy_evolution_run_id": run_id},
        )


def _replay_cycle_queries(
    memory: WaveMind,
    *,
    namespace: str,
    top_k: int,
    repetitions: int,
) -> list[str]:
    sequence = [
        "budget recall",
        "risk limits",
        "budget recall",
        "risk limits",
        "concise answers",
        "budget recall",
        "memory os policy",
        "risk limits",
    ]
    replayed: list[str] = []
    for _ in range(max(1, int(repetitions))):
        for query in sequence:
            memory.query(query, namespace=namespace, top_k=max(1, int(top_k)))
            replayed.append(query)
    return replayed


def _decision_statuses(report: dict[str, Any]) -> dict[str, str]:
    manifest = report.get("policy_manifest") if isinstance(report.get("policy_manifest"), dict) else {}
    decisions = manifest.get("decisions") if isinstance(manifest.get("decisions"), list) else []
    return {
        str(decision.get("id")): str(decision.get("status"))
        for decision in decisions
        if isinstance(decision, dict) and decision.get("id") is not None
    }


def _policy_history(report: dict[str, Any]) -> dict[str, Any]:
    value = report.get("policy_history")
    return value if isinstance(value, dict) else {}


def _count_policy_history_suggestions(report: dict[str, Any]) -> int:
    suggestions = report.get("suggestions") if isinstance(report.get("suggestions"), list) else []
    return sum(
        1
        for suggestion in suggestions
        if isinstance(suggestion, dict)
        and str(suggestion.get("id") or "").startswith("policy-history:")
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_worker_cycles(
    memory: WaveMind,
    *,
    namespace: str,
    cycles: int,
    query_repetitions: int,
    top_k: int,
    target_memories: int,
    namespace_count: int,
    node_count: int,
    target_qps: float,
    target_p99_ms: float,
    observed_p99_ms: float | None,
    memory_pressure_threshold: int,
    deployment: str,
    multimodal: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    cache = HotMemoryCache(capacity=128, ttl_seconds=120)
    reports: list[dict[str, Any]] = []
    replayed: list[str] = []
    worker = MemoryOSWorker(memory, cache)
    for _ in range(max(1, int(cycles))):
        replayed.extend(
            _replay_cycle_queries(
                memory,
                namespace=namespace,
                top_k=top_k,
                repetitions=query_repetitions,
            )
        )
        report = worker.run_once(
            namespace=namespace,
            audit_limit=512,
            max_hot_queries=16,
            min_frequency=2,
            top_k=top_k,
            target_memories=target_memories,
            namespace_count=namespace_count,
            node_count=node_count,
            target_qps=target_qps,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            deployment=deployment,
            multimodal=multimodal,
            memory_pressure_threshold=memory_pressure_threshold,
            forgetting_min_age_seconds=0.0,
            forgetting_max_access_count=0,
            forgetting_max_memories=8,
            min_concept_energy=0.0,
            min_concept_size=2,
            max_concepts=2,
        )
        reports.append(report.as_dict())
    return reports, replayed


def run_memory_os_policy_evolution(
    *,
    namespace: str = "evolution:memory-os",
    db_path: str | Path | None = None,
    cycles: int = 3,
    query_repetitions: int = 1,
    target_memories: int = 2_000_000,
    namespace_count: int = 4096,
    node_count: int = 4,
    target_qps: float = 1000.0,
    target_p99_ms: float = 80.0,
    observed_p99_ms: float | None = 220.0,
    memory_pressure_threshold: int = 3,
    deployment: str = "production",
    top_k: int = 2,
    multimodal: bool = True,
) -> dict[str, Any]:
    """Run a multi-cycle Memory OS policy evolution benchmark.

    The canary proves that one Memory OS cycle can act on representative
    traffic. This runner proves the next requirement: policy history survives
    across cycles, repeated requirements escalate into explicit suggestions,
    and the scheduler changes its plan based on accumulated evidence.
    """

    if cycles < 2:
        raise ValueError("cycles must be at least 2")
    if target_memories <= 0:
        raise ValueError("target_memories must be positive")
    if namespace_count <= 0:
        raise ValueError("namespace_count must be positive")
    if node_count <= 0:
        raise ValueError("node_count must be positive")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="wavemind-memory-os-evolution-")
        resolved_db_path = Path(temp_dir.name) / "evolution.sqlite3"
    else:
        resolved_db_path = Path(db_path)
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    memory = WaveMind(
        db_path=resolved_db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
        score_threshold=0.0,
    )
    try:
        run_id = f"memory-os-evolution-{int(time.time() * 1000)}"
        _seed_memory(memory, namespace=namespace, run_id=run_id)
        cycle_reports, replayed_queries = _run_worker_cycles(
            memory,
            namespace=namespace,
            cycles=cycles,
            query_repetitions=query_repetitions,
            top_k=top_k,
            target_memories=target_memories,
            namespace_count=namespace_count,
            node_count=node_count,
            target_qps=target_qps,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            memory_pressure_threshold=memory_pressure_threshold,
            deployment=deployment,
            multimodal=multimodal,
        )
        schedule = MemoryOSScheduler(memory).plan(
            namespace=namespace,
            target_memories=target_memories,
            namespace_count=namespace_count,
            node_count=node_count,
            target_qps=target_qps,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            deployment=deployment,
            cache_mode="auto",
            multimodal=multimodal,
            memory_pressure_threshold=memory_pressure_threshold,
        ).as_dict()
    finally:
        memory.close()
        if temp_dir is not None:
            temp_dir.cleanup()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    decision_ids_by_cycle = [
        sorted(_decision_statuses(report))
        for report in cycle_reports
    ]
    decision_coverage_rate = (
        sum(1 for ids in decision_ids_by_cycle if REQUIRED_DECISION_IDS.issubset(ids))
        / len(decision_ids_by_cycle)
        if decision_ids_by_cycle
        else 0.0
    )
    repeated_required_cycles = [
        index + 1
        for index, report in enumerate(cycle_reports)
        if _policy_history(report).get("repeated_required_ids")
    ]
    history_suggestion_count = sum(
        _count_policy_history_suggestions(report) for report in cycle_reports
    )
    escalation_action_count = sum(
        1
        for report in cycle_reports
        if "escalate_policy_history" in set(report.get("actions") or [])
    )
    stable_ok_ids = sorted(
        {
            str(item)
            for report in cycle_reports
            for item in (_policy_history(report).get("stable_ok_ids") or [])
        }
    )
    scheduler_history = schedule.get("policy_history") if isinstance(schedule.get("policy_history"), dict) else {}
    scheduler_escalations = list(schedule.get("policy_escalation_ids") or [])
    scheduler_enabled = list(schedule.get("enabled_task_ids") or [])
    totals = {
        "prewarm_warmed": sum(
            int((report.get("prewarm") or {}).get("warmed") or 0)
            for report in cycle_reports
        ),
        "predictive_prefetch_warmed": sum(
            int((report.get("predictive_prefetch") or {}).get("warmed") or 0)
            for report in cycle_reports
        ),
        "priority_predictions": sum(
            int(report.get("priority_predictions") or 0)
            for report in cycle_reports
        ),
        "forgetting_demotions": sum(
            int(report.get("forgetting_demotions") or 0)
            for report in cycle_reports
        ),
        "concepts_created": sum(
            int(report.get("concepts_created") or 0)
            for report in cycle_reports
        ),
    }
    checks = [
        _check("cycles", len(cycle_reports), max(2, int(cycles)), ">="),
        _check("decision_coverage_rate", decision_coverage_rate, 1.0, ">="),
        _check("repeated_required_cycles", len(repeated_required_cycles), max(1, cycles - 1), ">="),
        _check("history_suggestions", history_suggestion_count, 1, ">="),
        _check("escalation_actions", escalation_action_count, 1, ">="),
        _check("scheduler_escalations", len(scheduler_escalations), 1, ">="),
        _check("scheduler_history_previous_runs", scheduler_history.get("previous_runs"), cycles, ">="),
        _check("stable_ok_ids", len(stable_ok_ids), 1, ">="),
        _check("prewarm_warmed", totals["prewarm_warmed"], 1, ">="),
        _check("predictive_prefetch_warmed", totals["predictive_prefetch_warmed"], 1, ">="),
        _check("priority_predictions", totals["priority_predictions"], 1, ">="),
        _check("required_tasks_enabled", _required_tasks_enabled(scheduler_enabled), True, "is"),
    ]
    passed = sum(1 for check in checks if check["pass"])
    status = "pass" if passed == len(checks) else "action_required"
    return {
        "schema": MEMORY_OS_EVOLUTION_SCHEMA,
        "generated_at": _utc_now(),
        "status": status,
        "ok": status == "pass",
        "namespace": namespace,
        "deployment": deployment,
        "target_memories": int(target_memories),
        "namespace_count": int(namespace_count),
        "node_count": int(node_count),
        "target_qps": float(target_qps),
        "target_p99_ms": float(target_p99_ms),
        "observed_p99_ms": observed_p99_ms,
        "cycles": len(cycle_reports),
        "query_repetitions": int(query_repetitions),
        "replayed_query_count": len(replayed_queries),
        "unique_replayed_queries": sorted(set(replayed_queries)),
        "elapsed_ms": elapsed_ms,
        "claim_boundary": (
            "Policy evolution is deterministic local/staging evidence. It proves "
            "policy-history escalation, self-adjusting scheduler behavior, and "
            "multi-cycle Memory OS learning on this workload; it does not unlock "
            "unattended production automation without remote Redis, distributed "
            "lock, runtime env, and strict large-scale evidence."
        ),
        "summary": {
            "status": status,
            "passed_checks": passed,
            "check_count": len(checks),
            "decision_coverage_rate": decision_coverage_rate,
            "repeated_required_cycle_count": len(repeated_required_cycles),
            "repeated_required_cycles": repeated_required_cycles,
            "history_suggestion_count": history_suggestion_count,
            "escalation_action_count": escalation_action_count,
            "scheduler_policy_escalation_ids": scheduler_escalations,
            "scheduler_policy_auto_adjustments": list(schedule.get("policy_auto_adjustments") or []),
            "scheduler_history_trend": scheduler_history.get("trend"),
            "scheduler_history_previous_runs": scheduler_history.get("previous_runs"),
            "stable_ok_ids": stable_ok_ids,
            **totals,
        },
        "checks": checks,
        "cycle_reports": [
            _compact_cycle_report(index + 1, report)
            for index, report in enumerate(cycle_reports)
        ],
        "schedule_plan": {
            "status": schedule.get("status"),
            "effective_cache_mode": schedule.get("effective_cache_mode"),
            "worker_count": schedule.get("worker_count"),
            "enabled_task_ids": scheduler_enabled,
            "policy_history": scheduler_history,
            "policy_escalation_ids": scheduler_escalations,
            "policy_auto_adjustments": list(schedule.get("policy_auto_adjustments") or []),
            "execution_plan": schedule.get("execution_plan"),
        },
        "next_actions": _next_actions(status, scheduler_escalations),
    }


def _required_tasks_enabled(enabled: Sequence[Any]) -> bool:
    return {
        "memory-os",
        "cache-prewarm",
        "predictive-prefetch",
        "adaptive-forgetting",
        "consolidation",
        "maintenance",
        "architecture-advice",
    }.issubset({str(item) for item in enabled})


def _compact_cycle_report(cycle: int, report: dict[str, Any]) -> dict[str, Any]:
    history = _policy_history(report)
    return {
        "cycle": cycle,
        "ok": report.get("ok"),
        "actions": list(report.get("actions") or []),
        "policy_status": (report.get("policy_manifest") or {}).get("status"),
        "decision_statuses": _decision_statuses(report),
        "policy_history": history,
        "policy_history_suggestion_count": _count_policy_history_suggestions(report),
        "prewarm_warmed": (report.get("prewarm") or {}).get("warmed"),
        "predictive_prefetch_warmed": (report.get("predictive_prefetch") or {}).get("warmed"),
        "priority_predictions": report.get("priority_predictions"),
        "forgetting_demotions": report.get("forgetting_demotions"),
        "concepts_created": report.get("concepts_created"),
    }


def _check(name: str, value: Any, target: Any, op: str) -> dict[str, Any]:
    passed = False
    if op == ">=":
        passed = _as_float(value) >= _as_float(target)
    elif op == "<=":
        passed = _as_float(value) <= _as_float(target)
    elif op == "is":
        passed = value is target
    elif op == "==":
        passed = value == target
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": op,
        "pass": bool(passed),
    }


def _next_actions(status: str, scheduler_escalations: Sequence[Any]) -> list[str]:
    if status != "pass":
        return [
            "Do not rely on Memory OS policy evolution until all checks pass.",
            "Inspect cycle_reports for missing policy history, prewarm, predictive prefetch, or scheduler escalation evidence.",
        ]
    rows = [
        "Use this artifact as the regression gate for multi-cycle Memory OS policy learning.",
        "Keep production automation locked behind memory-os-admission until Redis, distributed lock, runtime env, and large-scale evidence pass.",
    ]
    if scheduler_escalations:
        rows.append(
            "Resolve repeated scheduler policy escalations before widening Memory OS worker scope: "
            + ", ".join(str(item) for item in scheduler_escalations)
        )
    return rows


def render_memory_os_policy_evolution_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# WaveMind Memory OS Policy Evolution",
        "",
        "This benchmark runs several Memory OS cycles against the same namespace",
        "and verifies that policy history affects later plans. It is the regression",
        "artifact for self-improving memory policy behavior.",
        "",
        str(payload.get("claim_boundary", "")),
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload.get('status')}` |",
        f"| cycles | `{payload.get('cycles')}` |",
        f"| deployment | `{payload.get('deployment')}` |",
        f"| target memories | `{payload.get('target_memories')}` |",
        f"| replayed queries | `{payload.get('replayed_query_count')}` |",
        f"| decision coverage | `{summary.get('decision_coverage_rate')}` |",
        f"| repeated required cycles | `{summary.get('repeated_required_cycle_count')}` |",
        f"| history suggestions | `{summary.get('history_suggestion_count')}` |",
        f"| escalation actions | `{summary.get('escalation_action_count')}` |",
        f"| scheduler history trend | `{summary.get('scheduler_history_trend')}` |",
        f"| scheduler escalations | `{', '.join(summary.get('scheduler_policy_escalation_ids') or [])}` |",
        f"| prewarm warmed | `{summary.get('prewarm_warmed')}` |",
        f"| predictive prefetch warmed | `{summary.get('predictive_prefetch_warmed')}` |",
        f"| priority predictions | `{summary.get('priority_predictions')}` |",
        "",
        "## Checks",
        "",
        "| check | status | value | target |",
        "|---|---|---:|---:|",
    ]
    for check in payload.get("checks", []):
        lines.append(
            "| {name} | `{status}` | `{value}` | `{op} {target}` |".format(
                name=check.get("name"),
                status="pass" if check.get("pass") else "action_required",
                value=check.get("value"),
                op=check.get("op"),
                target=check.get("target"),
            )
        )
    lines.extend(["", "## Cycles", ""])
    lines.extend(["| cycle | policy | repeated required | stable ok | actions |", "|---:|---|---|---|---|"])
    for row in payload.get("cycle_reports", []):
        history = row.get("policy_history") if isinstance(row.get("policy_history"), dict) else {}
        lines.append(
            "| {cycle} | `{policy}` | `{required}` | `{stable}` | {actions} |".format(
                cycle=row.get("cycle"),
                policy=row.get("policy_status"),
                required=", ".join(history.get("repeated_required_ids") or []),
                stable=", ".join(history.get("stable_ok_ids") or []),
                actions=", ".join(row.get("actions") or []),
            )
        )
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions", []):
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_memory_os_policy_evolution_artifacts(
    payload: dict[str, Any],
    *,
    output: str | Path = "benchmarks/memory_os_policy_evolution_results.json",
    markdown_output: str | Path = "benchmarks/MEMORY_OS_POLICY_EVOLUTION.md",
) -> None:
    output_path = Path(output)
    markdown_path = Path(markdown_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_memory_os_policy_evolution_markdown(payload),
        encoding="utf-8",
    )
