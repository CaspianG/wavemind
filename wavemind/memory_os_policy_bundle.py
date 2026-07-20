from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEMORY_OS_POLICY_BUNDLE_SCHEMA = "wavemind.memory_os_policy_bundle.v1"

DEFAULT_CANARY_PATH = Path("benchmarks/memory_os_canary_results.json")
DEFAULT_EVOLUTION_PATH = Path("benchmarks/memory_os_policy_evolution_results.json")
DEFAULT_ADMISSION_PATH = Path("benchmarks/memory_os_admission_results.json")

REQUIRED_RUNTIME_ENV = (
    "WAVEMIND_REDIS_URL",
    "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL",
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    return json.loads(resolved.read_text(encoding="utf-8"))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_pass(payload: dict[str, Any]) -> bool:
    return bool(payload.get("ok")) or payload.get("status") == "pass"


def _admission_blockers(admission: dict[str, Any]) -> list[str]:
    summary = _as_dict(admission.get("summary"))
    return [str(item) for item in _as_list(summary.get("blocker_ids"))]


def _check(
    id: str,
    title: str,
    passed: bool,
    evidence: str,
    action: str,
    *,
    severity: str = "blocker",
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "status": "pass" if passed else "action_required",
        "passed": bool(passed),
        "severity": "ok" if passed else severity,
        "evidence": evidence,
        "action": action,
    }


def _runtime_policy(canary: dict[str, Any], evolution: dict[str, Any]) -> dict[str, Any]:
    canary_plan = _as_dict(canary.get("schedule_plan"))
    canary_summary = _as_dict(canary.get("summary"))
    evolution_summary = _as_dict(evolution.get("summary"))
    evolution_plan = _as_dict(evolution.get("schedule_plan"))
    execution_plan = _as_dict(canary_plan.get("execution_plan"))
    worker_report = _as_dict(canary.get("worker_report"))
    policy_manifest = _as_dict(
        canary_plan.get("policy_manifest")
        or worker_report.get("policy_manifest")
    )
    enabled_task_ids = [
        str(item)
        for item in _as_list(canary_plan.get("enabled_task_ids"))
    ]
    return {
        "target_deployment": "staging",
        "production_auto_enable": False,
        "namespace": canary.get("namespace"),
        "enabled_task_ids": enabled_task_ids,
        "worker_count": int(canary_plan.get("worker_count") or 1),
        "effective_cache_mode": canary_plan.get("effective_cache_mode"),
        "required_runtime_env": list(REQUIRED_RUNTIME_ENV),
        "required_infrastructure": _as_list(canary_plan.get("required_infrastructure")),
        "schedules": {
            "memory_os": "*/5 * * * *",
            "cache_prewarm": "*/2 * * * *",
            "predictive_prefetch": "*/5 * * * *",
            "adaptive_forgetting": "17 * * * *",
            "consolidation": "37 * * * *",
            "maintenance": "47 * * * *",
            "architecture_advice": "11 */6 * * *",
        },
        "feature_flags": {
            "audit_queries_required": True,
            "shared_cache_required": bool(execution_plan.get("requires_shared_cache")),
            "distributed_lock_required": bool(execution_plan.get("requires_distributed_lock")),
            "predictive_prefetch": "predictive-prefetch" in enabled_task_ids,
            "priority_learning": int(canary_summary.get("priority_predictions") or 0) > 0,
            "adaptive_forgetting": "adaptive-forgetting" in enabled_task_ids,
            "consolidation": "consolidation" in enabled_task_ids,
            "architecture_advice": "architecture-advice" in enabled_task_ids,
            "policy_history_escalation": int(
                evolution_summary.get("escalation_action_count") or 0
            ) > 0,
        },
        "policy_manifest": policy_manifest,
        "policy_history": _as_dict(evolution_plan.get("policy_history")),
        "policy_escalation_ids": _as_list(evolution_plan.get("policy_escalation_ids")),
        "policy_auto_adjustments": _as_list(evolution_plan.get("policy_auto_adjustments")),
        "observability": {
            "required_metrics": [
                "wavemind_memory_os_cycle_duration_ms",
                "wavemind_memory_os_worker_errors_total",
                "wavemind_memory_os_hot_queries",
                "wavemind_memory_os_prewarm_warmed",
                "wavemind_memory_os_predictive_warmed",
                "wavemind_memory_os_priority_predictions",
                "wavemind_memory_os_forgetting_demotions",
                "wavemind_memory_os_concepts_created",
            ],
            "trace_attributes": [
                "wavemind.namespace",
                "wavemind.memory_os.task_id",
                "wavemind.memory_os.policy_bundle_id",
                "wavemind.memory_os.idempotency_key",
            ],
        },
        "rollout": {
            "mode": "shadow_then_canary",
            "automatic_promotion": False,
            "phases": [
                {"name": "shadow", "mutation_enabled": False, "minimum_minutes": 60},
                {"name": "canary", "mutation_enabled": True, "traffic_percent": 5, "minimum_minutes": 60},
                {"name": "staged", "mutation_enabled": True, "traffic_percent": 25, "minimum_minutes": 240},
                {"name": "production", "mutation_enabled": True, "traffic_percent": 100},
            ],
            "promotion_gates": {
                "worker_error_rate_max": 0.01,
                "query_p99_regression_max": 0.10,
                "agent_success_regression_max": 0.0,
                "stale_error_rate_regression_max": 0.0,
                "duplicate_mutation_count_max": 0,
            },
        },
        "rollback": {
            "automatic_pause": True,
            "action": "suspend_memory_os_cronjob",
            "manual_override": "memoryOs.emergencyStop=true",
            "manual_suspend": "memoryOs.suspend=true",
            "recall_path_remains_available": True,
            "state_recovery": "restore_last_verified_snapshot_if_semantic_state_revert_is_required",
            "in_doubt_job_action": "keep_mutations_paused_and_review_the_running_receipt_before_manual_replay",
        },
        "safety": {
            "state_mutating_tasks": _as_list(execution_plan.get("state_mutating_task_ids")),
            "singleton_task_ids": _as_list(execution_plan.get("singleton_task_ids")),
            "idempotency_required": True,
            "production_admission_required": True,
            "large_scale_evidence_required": True,
            "atomic_lease_required": True,
            "lease_heartbeat_required": True,
            "job_receipt_required": True,
            "manual_emergency_stop_required": True,
        },
    }


def _kubernetes_patch(runtime_policy: dict[str, Any]) -> dict[str, Any]:
    env = [
        {"name": "WAVEMIND_MEMORY_OS_ENABLED", "value": "1"},
        {"name": "WAVEMIND_MEMORY_OS_POLICY_BUNDLE", "value": "memory_os_policy_bundle_results.json"},
        {"name": "WAVEMIND_MEMORY_OS_CANARY_REQUIRED", "value": "1"},
        {"name": "WAVEMIND_MEMORY_OS_PRODUCTION_ADMISSION_REQUIRED", "value": "1"},
        {"name": "WAVEMIND_MEMORY_OS_EMERGENCY_STOP", "value": "0"},
        {"name": "WAVEMIND_MEMORY_OS_DEPLOYMENT", "value": str(runtime_policy["target_deployment"])},
        {
            "name": "WAVEMIND_REDIS_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "wavemind-memory-os-runtime",
                    "key": "redis-url",
                }
            },
        },
        {
            "name": "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "wavemind-memory-os-runtime",
                    "key": "lock-redis-url",
                }
            },
        },
    ]
    cronjobs = [
        {
            "name": f"wavemind-{task_id}",
            "task_id": task_id,
            "schedule": runtime_policy["schedules"].get(task_id.replace("-", "_"), "*/5 * * * *"),
            "concurrencyPolicy": "Forbid",
            "restartPolicy": "OnFailure",
        }
        for task_id in runtime_policy["enabled_task_ids"]
    ]
    return {
        "apiVersion": "wavemind.dev/v1",
        "kind": "MemoryOSPolicyBundle",
        "metadata": {"name": "wavemind-memory-os-staging"},
        "spec": {
            "targetDeployment": runtime_policy["target_deployment"],
            "productionAutoEnable": False,
            "env": env,
            "cronJobs": cronjobs,
            "requiredRuntimeEnv": runtime_policy["required_runtime_env"],
            "observability": runtime_policy["observability"],
            "safety": runtime_policy["safety"],
        },
    }


def build_memory_os_policy_bundle(
    *,
    canary: dict[str, Any],
    evolution: dict[str, Any],
    admission: dict[str, Any],
) -> dict[str, Any]:
    canary_passed = _is_pass(canary)
    evolution_passed = _is_pass(evolution)
    admission_status = str(admission.get("status") or "missing")
    production_admitted = bool(admission.get("admitted"))
    blockers = _admission_blockers(admission)
    runtime_policy = _runtime_policy(canary, evolution)
    runtime_env_declared = set(REQUIRED_RUNTIME_ENV).issubset(
        {str(item) for item in runtime_policy["required_runtime_env"]}
    )
    production_locked = not production_admitted and bool(blockers)
    staging_allowed = canary_passed and evolution_passed and runtime_env_declared
    production_allowed = staging_allowed and production_admitted and not blockers
    no_unattended_production = (
        runtime_policy["target_deployment"] == "staging"
        and runtime_policy["production_auto_enable"] is False
        and runtime_policy["safety"]["production_admission_required"] is True
    )
    rollout_safety = (
        runtime_policy["rollout"]["mode"] == "shadow_then_canary"
        and runtime_policy["rollout"]["automatic_promotion"] is False
        and runtime_policy["rollback"]["automatic_pause"] is True
        and runtime_policy["rollback"]["recall_path_remains_available"] is True
        and runtime_policy["safety"]["atomic_lease_required"] is True
        and runtime_policy["safety"]["job_receipt_required"] is True
    )
    checks = [
        _check(
            "canary-pass",
            "Memory OS staging canary passed",
            canary_passed,
            f"status={canary.get('status')}, ok={canary.get('ok')}",
            "Run wavemind memory-os-canary with representative staging traffic.",
        ),
        _check(
            "policy-evolution-pass",
            "Memory OS policy evolution passed",
            evolution_passed,
            f"status={evolution.get('status')}, ok={evolution.get('ok')}",
            "Run wavemind memory-os-evolution and fix repeated-policy checks.",
        ),
        _check(
            "runtime-env-contract",
            "Runtime env contract declares Redis and lock wiring",
            runtime_env_declared,
            ", ".join(runtime_policy["required_runtime_env"]),
            "Declare WAVEMIND_REDIS_URL and WAVEMIND_MEMORY_OS_LOCK_REDIS_URL in the runtime bundle.",
        ),
        _check(
            "staging-promotion",
            "Bundle can be promoted to staging",
            staging_allowed,
            f"canary={canary_passed}, evolution={evolution_passed}, env={runtime_env_declared}",
            "Do not deploy the Memory OS policy bundle until canary, evolution, and runtime env contract pass.",
        ),
        _check(
            "production-admission",
            "Production promotion remains behind strict admission",
            production_allowed,
            f"admission_status={admission_status}, admitted={production_admitted}, blockers={blockers}",
            "Resolve memory-os-admission blockers with real Redis, distributed lock, runtime env, and large-scale evidence.",
            severity="production_blocker",
        ),
        _check(
            "production-lock",
            "Bundle does not enable unattended production automation",
            no_unattended_production and (production_locked or production_allowed),
            f"production_auto_enable={runtime_policy['production_auto_enable']}, production_locked={production_locked}",
            "Keep production_auto_enable=false unless memory-os-admission returns admitted.",
        ),
        _check(
            "rollout-safety",
            "Shadow, canary, rollback, and manual stop policy is explicit",
            rollout_safety,
            (
                f"mode={runtime_policy['rollout']['mode']}, "
                f"automatic_promotion={runtime_policy['rollout']['automatic_promotion']}, "
                f"automatic_pause={runtime_policy['rollback']['automatic_pause']}"
            ),
            "Keep staged promotion, automatic pause, atomic lease, job receipts, and emergency stop enabled.",
        ),
    ]
    failed = [item["id"] for item in checks if not item["passed"]]
    blocking_failed = [
        item["id"]
        for item in checks
        if not item["passed"] and item.get("severity") != "production_blocker"
    ]
    if production_allowed:
        status = "production_ready"
    elif staging_allowed and not blocking_failed:
        status = "staging_ready"
    else:
        status = "action_required"
    bundle_id = f"memory-os-policy-{_utc_now().replace(':', '').replace('-', '')}"
    return {
        "schema": MEMORY_OS_POLICY_BUNDLE_SCHEMA,
        "generated_at": _utc_now(),
        "bundle_id": bundle_id,
        "status": status,
        "ok": status in {"staging_ready", "production_ready"},
        "claim_boundary": (
            "This is an operator-applied Memory OS runtime policy bundle. Production "
            "promotion is allowed only when memory-os-admission is admitted with real "
            "Redis, distributed locks, runtime environment, and strict large-scale "
            "evidence. Automatic promotion remains disabled, and the admission applies "
            "only to the exact tested release and topology."
        ),
        "source_artifacts": {
            "canary_schema": canary.get("schema"),
            "canary_status": canary.get("status"),
            "evolution_schema": evolution.get("schema"),
            "evolution_status": evolution.get("status"),
            "admission_schema": admission.get("schema"),
            "admission_status": admission_status,
        },
        "summary": {
            "status": status,
            "staging_promotable": staging_allowed,
            "production_promotable": production_allowed,
            "production_locked": not production_allowed,
            "production_blocker_ids": blockers,
            "runtime_env_declared": runtime_env_declared,
            "enabled_task_ids": runtime_policy["enabled_task_ids"],
            "worker_count": runtime_policy["worker_count"],
            "effective_cache_mode": runtime_policy["effective_cache_mode"],
            "policy_escalation_ids": runtime_policy["policy_escalation_ids"],
            "check_count": len(checks),
            "passed_checks": sum(1 for item in checks if item["passed"]),
            "failed_check_ids": failed,
        },
        "checks": checks,
        "runtime_policy": runtime_policy,
        "kubernetes_patch": _kubernetes_patch(runtime_policy),
        "next_actions": (
            [
                "Apply the bundle only to staging CronJobs/workers.",
                "Replay representative tenant traffic and rerun memory-os-canary.",
                "Keep production blocked until memory-os-admission returns admitted with external evidence.",
            ]
            if status == "staging_ready"
            else [
                "Apply the production bundle through the controlled shadow and canary rollout.",
                "Keep the same policy bundle id in deployment annotations for auditability.",
                "Rerun admission for every release commit or production topology change.",
            ]
            if status == "production_ready"
            else [
                "Do not apply the policy bundle until failed checks are fixed.",
                *[
                    item["action"]
                    for item in checks
                    if not item["passed"] and item.get("severity") != "production_blocker"
                ],
            ]
        ),
    }


def run_memory_os_policy_bundle(
    *,
    root: str | Path = ".",
    canary_path: str | Path = DEFAULT_CANARY_PATH,
    evolution_path: str | Path = DEFAULT_EVOLUTION_PATH,
    admission_path: str | Path = DEFAULT_ADMISSION_PATH,
) -> dict[str, Any]:
    root_path = Path(root)
    canary = _load_json(root_path / canary_path)
    evolution = _load_json(root_path / evolution_path)
    admission = _load_json(root_path / admission_path)
    return build_memory_os_policy_bundle(
        canary=canary,
        evolution=evolution,
        admission=admission,
    )


def render_memory_os_policy_bundle_markdown(payload: dict[str, Any]) -> str:
    summary = _as_dict(payload.get("summary"))
    runtime = _as_dict(payload.get("runtime_policy"))
    lines = [
        "# WaveMind Memory OS Policy Bundle",
        "",
        "This bundle turns checked canary and policy-evolution evidence into a",
        "runtime policy manifest for operators. It is safe for staging promotion",
        "when the canary and evolution checks pass. Production automation remains",
        "blocked until `memory-os-admission` is admitted with external evidence.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload.get('status')}` |",
        f"| staging promotable | `{summary.get('staging_promotable')}` |",
        f"| production promotable | `{summary.get('production_promotable')}` |",
        f"| production locked | `{summary.get('production_locked')}` |",
        f"| worker count | `{summary.get('worker_count')}` |",
        f"| cache mode | `{summary.get('effective_cache_mode')}` |",
        f"| passed checks | `{summary.get('passed_checks')}/{summary.get('check_count')}` |",
        "",
        "## Runtime Policy",
        "",
        "| field | value |",
        "|---|---|",
        f"| target deployment | `{runtime.get('target_deployment')}` |",
        f"| production auto-enable | `{runtime.get('production_auto_enable')}` |",
        f"| required env | `{', '.join(runtime.get('required_runtime_env') or [])}` |",
        f"| enabled tasks | `{', '.join(runtime.get('enabled_task_ids') or [])}` |",
        f"| policy escalations | `{', '.join(runtime.get('policy_escalation_ids') or [])}` |",
        f"| rollout mode | `{_as_dict(runtime.get('rollout')).get('mode')}` |",
        f"| automatic promotion | `{_as_dict(runtime.get('rollout')).get('automatic_promotion')}` |",
        f"| rollback action | `{_as_dict(runtime.get('rollback')).get('action')}` |",
        f"| manual override | `{_as_dict(runtime.get('rollback')).get('manual_override')}` |",
        "",
        "## Checks",
        "",
        "| check | status | evidence | action |",
        "|---|---|---|---|",
    ]
    for item in _as_list(payload.get("checks")):
        lines.append(
            "| {title} | `{status}` | {evidence} | {action} |".format(
                title=str(item.get("title", "")),
                status=str(item.get("status", "")),
                evidence=str(item.get("evidence", "")).replace("|", "\\|"),
                action=str(item.get("action", "")).replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Kubernetes Runtime Patch", "", "```json"])
    lines.append(json.dumps(payload.get("kubernetes_patch", {}), ensure_ascii=False, indent=2))
    lines.extend(["```", "", "## Next Actions", ""])
    for action in _as_list(payload.get("next_actions")):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"
