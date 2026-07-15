from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_TASK_IDS = {
    "memory-os",
    "cache-prewarm",
    "predictive-prefetch",
    "adaptive-forgetting",
    "consolidation",
    "maintenance",
    "architecture-advice",
}

REQUIRED_POLICY_IDS = {
    "prefetch-policy",
    "priority-policy",
    "forgetting-policy",
    "consolidation-policy",
    "scale-policy",
    "coordination-policy",
}

STRICT_MEMORY_OS_TARGET = 1_000_000
PRODUCTION_DEPLOYMENTS = {"production", "prod", "staging"}
REMOTE_SOAK_DEPLOYMENTS = {"production", "prod"}
REMOTE_WORKER_SOAK_SCHEMA = "wavemind.memory_os_remote_worker_soak.v1"
MEMORY_OS_QUALITY_SCHEMA = "wavemind.memory_os_quality_gate.v2"
REMOTE_SOAK_MIN_DURATION_SECONDS = 6 * 60 * 60
REMOTE_SOAK_MIN_WORKER_CYCLES = 500
REMOTE_SOAK_MAX_AGE_SECONDS = 24 * 60 * 60
REMOTE_WORKER_SOAK_CHECK_IDS = {
    "remote-topology",
    "worker-health",
    "worker-version",
    "worker-commit",
    "worker-plan",
    "remote-redis-semantics",
    "soak-duration",
    "worker-cycles",
    "cross-worker-single-flight",
    "cross-worker-retry",
    "error-rate",
    "lock-safety",
    "duplicate-mutation-safety",
    "state-integrity",
    "no-in-doubt-jobs",
    "cleanup",
}
QUALITY_CHECK_IDS = {
    "direct-comparable-protocol",
    "memory-os-task-success-uplift",
    "memory-os-stale-suppression-uplift",
    "memory-os-adaptation-fired",
    "context-shape-equivalent",
    "memory-os-p95-latency",
    "memory-os-cold-p95-latency",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repository_commit() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _as_dict(plan: Any) -> dict[str, Any]:
    if hasattr(plan, "as_dict"):
        return dict(plan.as_dict())
    if isinstance(plan, dict):
        return dict(plan)
    raise TypeError("plan must be a MemoryOSSchedulePlan or plan dictionary")


def _configured(value: str | None) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    lowered = value.lower()
    return lowered not in {"0", "false", "none", "null", "disabled"}


def _requirement(
    id: str,
    title: str,
    passed: bool,
    evidence: str,
    action: str,
    *,
    severity: str = "blocker",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "status": "pass" if passed else "action_required",
        "passed": bool(passed),
        "severity": "ok" if passed else severity,
        "evidence": evidence,
        "action": action,
        "details": details or {},
    }


def _task_ids(plan: dict[str, Any]) -> set[str]:
    return {str(task.get("id")) for task in plan.get("tasks", []) if isinstance(task, dict)}


def _enabled_task_ids(plan: dict[str, Any]) -> set[str]:
    return {str(task_id) for task_id in plan.get("enabled_task_ids", [])}


def _step_by_id(execution_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(step.get("task_id")): dict(step)
        for step in execution_plan.get("steps", [])
        if isinstance(step, dict)
    }


def _missing_required_env(
    execution_plan: dict[str, Any],
    *,
    redis_configured: bool,
    lock_configured: bool,
) -> list[str]:
    missing: list[str] = []
    for step in execution_plan.get("steps", []):
        if not isinstance(step, dict) or not step.get("enabled"):
            continue
        for name in step.get("required_environment", []):
            if name == "WAVEMIND_REDIS_URL" and not redis_configured:
                missing.append(name)
            if name == "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL" and not lock_configured:
                missing.append(name)
    return list(dict.fromkeys(missing))


def evaluate_memory_os_admission(
    plan: Any,
    *,
    deployment: str | None = None,
    redis_url: str | None = None,
    lock_redis_url: str | None = None,
    allow_plan_only: bool = False,
    runtime_evidence: dict[str, Any] | None = None,
    quality_evidence: dict[str, Any] | None = None,
    expected_commit_sha: str | None = None,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Gate a Memory OS worker rollout against production safety requirements.

    `memory-os-plan` answers what should run. This admission gate answers whether
    the planned worker set is ready to run as production automation, or whether
    it is still only a runbook because audit traffic, Redis, lock wiring, or
    large-scale evidence is missing.
    """

    plan_payload = _as_dict(plan)
    env_payload = os.environ if env is None else env
    deployment_name = str(deployment or plan_payload.get("deployment") or "local").lower()
    production_like = deployment_name in PRODUCTION_DEPLOYMENTS
    remote_soak_required = deployment_name in REMOTE_SOAK_DEPLOYMENTS
    target_memories = int(plan_payload.get("target_memories") or 0)
    strict_target = production_like and target_memories >= STRICT_MEMORY_OS_TARGET
    execution_plan = dict(plan_payload.get("execution_plan") or {})
    architecture = dict(plan_payload.get("architecture_advice") or {})
    policy_manifest = dict(plan_payload.get("policy_manifest") or {})
    policy_ids = {str(item) for item in policy_manifest.get("decision_ids", [])}
    tasks = _task_ids(plan_payload)
    enabled_tasks = _enabled_task_ids(plan_payload)
    steps = _step_by_id(execution_plan)
    redis_configured = _configured(redis_url) or _configured(env_payload.get("WAVEMIND_REDIS_URL"))
    lock_configured = _configured(lock_redis_url) or _configured(
        env_payload.get("WAVEMIND_MEMORY_OS_LOCK_REDIS_URL")
    )
    required_env_missing = _missing_required_env(
        execution_plan,
        redis_configured=redis_configured,
        lock_configured=lock_configured,
    )

    safe_execution = bool(execution_plan.get("safe_to_run")) and not execution_plan.get(
        "blocked_task_ids"
    )
    shared_cache_ok = not bool(execution_plan.get("requires_shared_cache")) or (
        plan_payload.get("effective_cache_mode") == "redis" and redis_configured
    )
    distributed_lock_ok = not bool(execution_plan.get("requires_distributed_lock")) or lock_configured
    hot_query_count = int(plan_payload.get("hot_query_count") or 0)
    hot_workers_enabled = {"cache-prewarm", "predictive-prefetch"}.issubset(enabled_tasks)
    consolidation_enabled = "consolidation" in enabled_tasks
    all_tasks_planned = REQUIRED_TASK_IDS.issubset(tasks)
    all_policies_planned = REQUIRED_POLICY_IDS.issubset(policy_ids)
    state_mutating_tasks = set(execution_plan.get("state_mutating_task_ids") or [])
    singleton_tasks = set(execution_plan.get("singleton_task_ids") or [])
    state_mutations_singleton = state_mutating_tasks.issubset(singleton_tasks)
    lock_scoped_mutations = all(
        bool(steps.get(task_id, {}).get("idempotency_key"))
        for task_id in state_mutating_tasks
        if execution_plan.get("requires_distributed_lock")
    )
    architecture_status = str(architecture.get("status") or plan_payload.get("status") or "")
    architecture_boundary_ok = architecture_status != "architecture_required" or not strict_target
    runtime_env_ok = not required_env_missing
    required_infrastructure = set(plan_payload.get("required_infrastructure") or [])
    infrastructure_contract_ok = (
        not production_like
        or {
            "Redis-compatible shared hot-query cache",
            "distributed worker lock or single-flight scheduler",
            "durable queue or Kubernetes CronJobs",
            "OpenTelemetry metrics for worker duration, errors, and warmed queries",
        }.issubset(required_infrastructure)
    )
    runtime_evidence_payload = dict(runtime_evidence or {})
    runtime_checks = runtime_evidence_payload.get("checks") or []
    runtime_checks_pass = bool(runtime_checks) and all(
        isinstance(item, dict) and bool(item.get("passed")) for item in runtime_checks
    )
    runtime_check_ids = {
        str(item.get("id"))
        for item in runtime_checks
        if isinstance(item, dict) and item.get("id")
    }
    runtime_preflight = dict(runtime_evidence_payload.get("preflight") or {})
    runtime_topology = dict(runtime_preflight.get("topology") or {})
    runtime_config = dict(runtime_evidence_payload.get("config") or {})
    runtime_metrics = dict(runtime_evidence_payload.get("metrics") or {})
    required_runtime_metric_ids = {
        "duration_seconds",
        "worker_cycles",
        "completed_runs",
        "duplicate_retries",
        "job_request_attempts",
        "job_request_failures",
        "error_rate",
        "lock_breach_count",
        "duplicate_mutation_count",
        "state_corruption_count",
    }
    runtime_metrics_complete = required_runtime_metric_ids.issubset(runtime_metrics)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    finished_at = _parse_utc(runtime_evidence_payload.get("finished_at"))
    evidence_age_seconds = (
        (current_time - finished_at).total_seconds() if finished_at is not None else None
    )
    evidence_fresh = (
        evidence_age_seconds is not None
        and -300.0 <= evidence_age_seconds <= REMOTE_SOAK_MAX_AGE_SECONDS
    )
    expected_source_ref = (
        expected_commit_sha
        or env_payload.get("GITHUB_SHA")
        or env_payload.get("WAVEMIND_COMMIT_SHA")
        or _repository_commit()
    )
    runtime_source_ref = str(runtime_evidence_payload.get("source_ref") or "")
    commit_matches = (
        bool(expected_source_ref)
        and bool(re.fullmatch(r"[0-9a-f]{40}", runtime_source_ref))
        and runtime_source_ref == expected_source_ref
    )
    duration_ok = float(runtime_metrics.get("duration_seconds") or 0.0) >= REMOTE_SOAK_MIN_DURATION_SECONDS
    worker_cycles_ok = int(runtime_metrics.get("worker_cycles") or 0) >= REMOTE_SOAK_MIN_WORKER_CYCLES
    configured_duration_ok = float(runtime_config.get("min_duration_seconds") or 0.0) >= REMOTE_SOAK_MIN_DURATION_SECONDS
    configured_cycles_ok = int(runtime_config.get("min_worker_cycles") or 0) >= REMOTE_SOAK_MIN_WORKER_CYCLES
    integrity_metrics_ok = (
        float(runtime_metrics.get("error_rate") or 0.0) == 0.0
        and int(runtime_metrics.get("job_request_failures") or 0) == 0
        and int(runtime_metrics.get("lock_breach_count") or 0) == 0
        and int(runtime_metrics.get("duplicate_mutation_count") or 0) == 0
        and int(runtime_metrics.get("state_corruption_count") or 0) == 0
        and int(runtime_metrics.get("completed_runs") or 0)
        == int(runtime_metrics.get("worker_cycles") or -1)
        and int(runtime_metrics.get("duplicate_retries") or 0)
        == int(runtime_metrics.get("worker_cycles") or -1)
    )
    runtime_evidence_valid = (
        runtime_evidence_payload.get("schema") == REMOTE_WORKER_SOAK_SCHEMA
        and runtime_evidence_payload.get("status") == "pass"
        and runtime_evidence_payload.get("environment") == "remote_worker_cluster"
        and runtime_checks_pass
        and REMOTE_WORKER_SOAK_CHECK_IDS.issubset(runtime_check_ids)
        and evidence_fresh
        and commit_matches
        and duration_ok
        and worker_cycles_ok
        and configured_duration_ok
        and configured_cycles_ok
        and runtime_metrics_complete
        and integrity_metrics_ok
    )
    remote_runtime_evidence = (
        runtime_evidence_valid
        and runtime_preflight.get("status") == "pass"
        and int(runtime_topology.get("worker_count") or 0) >= 2
        and int(runtime_topology.get("distinct_worker_count") or 0) >= 2
        and runtime_topology.get("worker_https") is True
        and runtime_topology.get("redis_tls") is True
    )
    runtime_soak_ok = not remote_soak_required or remote_runtime_evidence

    quality_evidence_payload = dict(quality_evidence or {})
    quality_checks = quality_evidence_payload.get("checks") or []
    quality_check_ids = {
        str(item.get("id"))
        for item in quality_checks
        if isinstance(item, dict) and item.get("id")
    }
    quality_checks_pass = bool(quality_checks) and all(
        isinstance(item, dict) and bool(item.get("passed")) for item in quality_checks
    )
    quality_metrics = dict(quality_evidence_payload.get("metrics") or {})
    required_quality_metric_ids = {
        "task_success_uplift",
        "stale_suppression_uplift",
        "p95_latency_delta_ms",
        "p95_latency_regression_ratio",
    }
    quality_evidence_valid = (
        quality_evidence_payload.get("schema") == MEMORY_OS_QUALITY_SCHEMA
        and quality_evidence_payload.get("status") == "pass"
        and quality_checks_pass
        and QUALITY_CHECK_IDS.issubset(quality_check_ids)
        and required_quality_metric_ids.issubset(quality_metrics)
        and float(quality_metrics.get("task_success_uplift") or 0.0) > 0.0
        and float(quality_metrics.get("stale_suppression_uplift") or 0.0) > 0.0
        and float(quality_metrics.get("p95_latency_delta_ms") or 0.0) <= 5.0
        and float(quality_metrics.get("p95_latency_regression_ratio") or 0.0) <= 0.20
    )
    quality_uplift_ok = not remote_soak_required or quality_evidence_valid

    requirements = [
        _requirement(
            "execution-safe",
            "Execution plan has no blocked worker tasks",
            safe_execution,
            f"safe_to_run={execution_plan.get('safe_to_run')}, blocked={execution_plan.get('blocked_task_ids')}",
            "Resolve execution_plan.blocked_task_ids before scheduling Memory OS.",
        ),
        _requirement(
            "task-coverage",
            "All Memory OS worker lanes are planned",
            all_tasks_planned,
            ", ".join(sorted(tasks)),
            "Planner must include memory-os, cache-prewarm, predictive-prefetch, forgetting, consolidation, maintenance, and architecture-advice.",
        ),
        _requirement(
            "hot-query-signal",
            "Query audit traffic enables prewarm and predictive workers",
            hot_query_count > 0 and hot_workers_enabled,
            f"hot_query_count={hot_query_count}, enabled={sorted(enabled_tasks)}",
            "Enable audited query traffic in staging, replay representative traffic, then rerun memory-os-admission.",
        ),
        _requirement(
            "consolidation-enabled",
            "Consolidation worker is active when clusters exist",
            consolidation_enabled,
            f"enabled={sorted(enabled_tasks)}",
            "Seed enough representative memories/query traffic for stable concept clusters before production rollout.",
            severity="warning",
        ),
        _requirement(
            "shared-cache-configured",
            "Shared Redis cache is configured when the plan requires it",
            shared_cache_ok,
            f"requires_shared_cache={execution_plan.get('requires_shared_cache')}, effective_cache_mode={plan_payload.get('effective_cache_mode')}, redis_configured={redis_configured}",
            "Set WAVEMIND_REDIS_URL or pass --redis-url before enabling multi-worker Memory OS.",
        ),
        _requirement(
            "distributed-lock-configured",
            "Distributed single-flight lock is configured for state mutation",
            distributed_lock_ok,
            f"requires_distributed_lock={execution_plan.get('requires_distributed_lock')}, lock_configured={lock_configured}",
            "Set WAVEMIND_MEMORY_OS_LOCK_REDIS_URL or pass --lock-redis-url before running production Memory OS workers.",
        ),
        _requirement(
            "state-mutation-singleton",
            "State-mutating tasks are singleton/idempotent",
            state_mutations_singleton and lock_scoped_mutations,
            f"state_mutating={sorted(state_mutating_tasks)}, singleton={sorted(singleton_tasks)}",
            "Keep mutation tasks as cluster singletons with idempotency keys.",
        ),
        _requirement(
            "policy-coverage",
            "Policy manifest covers prefetch, priority, forgetting, consolidation, scale, and coordination",
            all_policies_planned,
            ", ".join(sorted(policy_ids)),
            "Memory OS admission requires a full policy manifest before rollout.",
        ),
        _requirement(
            "infrastructure-contract",
            "Production infrastructure contract is explicit",
            infrastructure_contract_ok,
            ", ".join(sorted(required_infrastructure)),
            "Production plans must list Redis, lock/scheduler, queue/CronJob, and OpenTelemetry requirements.",
        ),
        _requirement(
            "scale-boundary",
            "Large target stays behind strict architecture evidence",
            architecture_boundary_ok,
            f"architecture_status={architecture_status}, strict_target={strict_target}",
            "Do not admit Memory OS production rollout for million-plus targets until architecture-required evidence is resolved.",
        ),
        _requirement(
            "runtime-env",
            "Required runtime environment is present",
            runtime_env_ok,
            f"missing={required_env_missing}",
            "Provide every required environment variable before scheduling the worker set.",
        ),
        _requirement(
            "quality-uplift",
            "Direct adaptive A/B proves Memory OS quality uplift within latency limits",
            quality_uplift_ok,
            (
                f"schema={quality_evidence_payload.get('schema')}, "
                f"status={quality_evidence_payload.get('status')}, "
                f"task_uplift={quality_metrics.get('task_success_uplift')}, "
                f"p95_delta_ms={quality_metrics.get('p95_latency_delta_ms')}, "
                f"p95_ratio={quality_metrics.get('p95_latency_regression_ratio')}"
            ),
            "Run memory_os_ab_benchmark.py and memory_os_quality_gate.py on this release; non-regression and static-retrieval comparisons do not satisfy this requirement.",
            details={
                "quality_evidence_valid": quality_evidence_valid,
                "required_schema": MEMORY_OS_QUALITY_SCHEMA,
                "required_check_ids": sorted(QUALITY_CHECK_IDS),
                "quality_evidence": quality_evidence_payload,
            },
        ),
        _requirement(
            "runtime-soak",
            "Fresh six-hour remote soak proves 500-cycle lease, retry, and state safety",
            runtime_soak_ok,
            (
                f"schema={runtime_evidence_payload.get('schema')}, "
                f"status={runtime_evidence_payload.get('status')}, "
                f"environment={runtime_evidence_payload.get('environment')}, "
                f"duration={runtime_metrics.get('duration_seconds')}, "
                f"cycles={runtime_metrics.get('worker_cycles')}, "
                f"fresh={evidence_fresh}, commit_matches={commit_matches}, "
                f"checks_pass={runtime_checks_pass}"
            ),
            "Run the six-hour remote soak against two or more HTTPS workers and their TLS Redis, then attach the fresh artifact from the exact release commit.",
            details={
                "runtime_evidence_valid": runtime_evidence_valid,
                "remote_runtime_evidence": remote_runtime_evidence,
                "evidence_age_seconds": evidence_age_seconds,
                "evidence_fresh": evidence_fresh,
                "expected_commit_sha": expected_source_ref,
                "commit_matches": commit_matches,
                "duration_ok": duration_ok,
                "worker_cycles_ok": worker_cycles_ok,
                "integrity_metrics_ok": integrity_metrics_ok,
                "required_schema": REMOTE_WORKER_SOAK_SCHEMA,
                "required_check_ids": sorted(REMOTE_WORKER_SOAK_CHECK_IDS),
                "runtime_evidence": runtime_evidence_payload,
            },
        ),
    ]

    blocker_ids = [
        item["id"]
        for item in requirements
        if not item["passed"] and item["severity"] == "blocker"
    ]
    warning_ids = [
        item["id"]
        for item in requirements
        if not item["passed"] and item["severity"] == "warning"
    ]
    admitted = not blocker_ids
    if admitted:
        status = "admitted"
    elif allow_plan_only and safe_execution and all_tasks_planned:
        status = "plan_only"
    else:
        status = "blocked"

    next_actions: list[str] = []
    if admitted:
        next_actions.append("Schedule Memory OS workers with the emitted singleton, lock, and Redis requirements.")
    elif status == "plan_only":
        next_actions.append("Keep this as a runbook until the action_required requirements pass.")
    else:
        next_actions.append("Do not schedule production Memory OS workers until blockers are resolved.")
    for item in requirements:
        if not item["passed"] and item["action"] not in next_actions:
            next_actions.append(str(item["action"]))

    return {
        "schema": "wavemind.memory_os_admission.v1",
        "generated_at": _utc_now(),
        "status": status,
        "admitted": admitted,
        "deployment": deployment_name,
        "target_memories": target_memories,
        "namespace_count": int(plan_payload.get("namespace_count") or 0),
        "worker_count": int(plan_payload.get("worker_count") or 0),
        "effective_cache_mode": plan_payload.get("effective_cache_mode"),
        "hot_query_count": hot_query_count,
        "allow_plan_only": bool(allow_plan_only),
        "claim_boundary": (
            "strict_memory_os_evidence_required"
            if strict_target
            else "memory_os_runtime_gate"
        ),
        "summary": {
            "status": status,
            "admitted": admitted,
            "requirement_count": len(requirements),
            "passed_count": sum(1 for item in requirements if item["passed"]),
            "blocker_count": len(blocker_ids),
            "warning_count": len(warning_ids),
            "blocker_ids": blocker_ids,
            "warning_ids": warning_ids,
            "enabled_task_ids": sorted(enabled_tasks),
            "missing_runtime_env": required_env_missing,
        },
        "requirements": requirements,
        "execution_plan": execution_plan,
        "policy_manifest": policy_manifest,
        "architecture_advice": architecture,
        "runtime_evidence": runtime_evidence_payload,
        "plan": plan_payload,
        "next_actions": next_actions,
    }


def render_memory_os_admission_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Memory OS Admission",
        "",
        "This gate decides whether the adaptive Memory OS worker set is safe to",
        "schedule as production automation, or whether it is still only a runbook.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| admitted | `{payload['admitted']}` |",
        f"| deployment | `{payload['deployment']}` |",
        f"| target memories | `{payload['target_memories']}` |",
        f"| worker count | `{payload['worker_count']}` |",
        f"| effective cache | `{payload['effective_cache_mode']}` |",
        f"| hot query count | `{payload['hot_query_count']}` |",
        f"| passed requirements | `{summary['passed_count']}/{summary['requirement_count']}` |",
        f"| blockers | `{summary['blocker_count']}` |",
        f"| warnings | `{summary['warning_count']}` |",
        "",
        "## Requirements",
        "",
        "| requirement | status | evidence | action |",
        "|---|---|---|---|",
    ]
    for item in payload.get("requirements", []):
        lines.append(
            "| {title} | `{status}` | {evidence} | {action} |".format(
                title=item["title"],
                status=item["status"],
                evidence=str(item.get("evidence") or "").replace("|", "\\|"),
                action=str(item.get("action") or "").replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions", []):
        lines.append(f"- {action}")
    lines.extend(["", "## Enabled Tasks", ""])
    for task_id in summary.get("enabled_task_ids", []):
        lines.append(f"- `{task_id}`")
    return "\n".join(lines) + "\n"
