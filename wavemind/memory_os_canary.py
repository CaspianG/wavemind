from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .core import WaveMind
from .jobs import HotMemoryCache, MemoryOSScheduler, MemoryOSWorker
from .memory_os_admission import (
    evaluate_memory_os_admission,
    render_memory_os_admission_markdown,
)


CANARY_SCHEMA = "wavemind.memory_os_canary.v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _seed_memory(memory: WaveMind, *, namespace: str, run_id: str) -> list[int]:
    rows = [
        (
            "The user budget is two thousand dollars.",
            ("profile", "budget"),
            {"topic": "budget", "canary_run_id": run_id},
            None,
            2.0,
        ),
        (
            "The user risk limit is two percent per trade.",
            ("profile", "risk"),
            {"topic": "risk", "canary_run_id": run_id},
            None,
            2.0,
        ),
        (
            "The user prefers concise operational answers.",
            ("profile", "preference"),
            {"topic": "style", "canary_run_id": run_id},
            None,
            2.0,
        ),
        (
            "Memory OS should prewarm repeated budget and risk recall paths.",
            ("memory-os", "ops"),
            {"topic": "memory-os", "canary_run_id": run_id},
            None,
            1.5,
        ),
        (
            "Memory OS can consolidate related user preference memories.",
            ("memory-os", "ops"),
            {"topic": "memory-os", "canary_run_id": run_id},
            None,
            1.5,
        ),
        (
            "Outdated note: the user wants long essays.",
            ("stale",),
            {"topic": "stale", "canary_run_id": run_id},
            -1.0,
            1.0,
        ),
    ]
    ids: list[int] = []
    for text, tags, metadata, ttl_seconds, priority in rows:
        ids.append(
            int(
                memory.remember(
                    text,
                    namespace=namespace,
                    tags=tags,
                    metadata=metadata,
                    ttl_seconds=ttl_seconds,
                    priority=priority,
                )
            )
        )
    return ids


def _replay_queries(
    memory: WaveMind,
    *,
    namespace: str,
    repetitions: int,
    top_k: int,
) -> list[str]:
    base_sequence = [
        "budget recall",
        "risk limits",
        "budget recall",
        "risk limits",
        "concise answers",
        "budget recall",
        "memory os prewarm",
        "memory os prewarm",
        "user preferences",
    ]
    queries: list[str] = []
    for _ in range(max(1, int(repetitions))):
        for query in base_sequence:
            memory.query(query, namespace=namespace, top_k=max(1, int(top_k)))
            queries.append(query)
    return queries


def _check(
    id: str,
    title: str,
    passed: bool,
    evidence: str,
    action: str,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "status": "pass" if passed else "action_required",
        "passed": bool(passed),
        "evidence": evidence,
        "action": action,
    }


def run_memory_os_canary(
    memory: WaveMind,
    *,
    namespace: str = "canary:memory-os",
    deployment: str = "staging",
    target_memories: int = 100_000,
    namespace_count: int = 64,
    node_count: int = 3,
    target_qps: float = 100.0,
    target_p99_ms: float = 100.0,
    observed_p99_ms: float | None = None,
    memory_pressure_threshold: int = 1_000_000,
    audit_limit: int = 512,
    max_hot_queries: int = 16,
    min_frequency: int = 2,
    top_k: int = 2,
    query_repetitions: int = 2,
    redis_url: str = "redis://redis.example.internal:6379/0",
    lock_redis_url: str = "redis://redis.example.internal:6379/1",
) -> dict[str, Any]:
    """Run a deterministic staging canary for Memory OS production admission.

    This is not a remote production benchmark. It creates representative query
    audit traffic, runs one Memory OS cycle, then checks whether the scheduler
    and admission gate would allow the worker set when production Redis and
    lock wiring are declared.
    """

    run_id = f"memory-os-canary-{int(time.time() * 1000)}"
    previous_audit = bool(getattr(memory, "audit_queries", False))
    memory.audit_queries = True
    cache = HotMemoryCache(capacity=64, ttl_seconds=120)

    try:
        seeded_ids = _seed_memory(memory, namespace=namespace, run_id=run_id)
        replayed_queries = _replay_queries(
            memory,
            namespace=namespace,
            repetitions=query_repetitions,
            top_k=top_k,
        )
        worker_report = MemoryOSWorker(memory, cache).run_once(
            namespace=namespace,
            audit_limit=audit_limit,
            max_hot_queries=max_hot_queries,
            min_frequency=min_frequency,
            top_k=top_k,
            consolidate_steps=3,
            min_concept_energy=0.0,
            min_concept_size=2,
            max_concepts=2,
            memory_pressure_threshold=memory_pressure_threshold,
            target_memories=target_memories,
            namespace_count=namespace_count,
            node_count=node_count,
            target_qps=target_qps,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            deployment=deployment,
        )
        plan = MemoryOSScheduler(memory).plan(
            namespace=namespace,
            audit_limit=audit_limit,
            max_hot_queries=max_hot_queries,
            min_frequency=min_frequency,
            top_k=top_k,
            target_memories=target_memories,
            namespace_count=namespace_count,
            node_count=node_count,
            target_qps=target_qps,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            deployment=deployment,
            cache_mode="auto",
            memory_pressure_threshold=memory_pressure_threshold,
        )
        admission = evaluate_memory_os_admission(
            plan,
            deployment=deployment,
            redis_url=redis_url,
            lock_redis_url=lock_redis_url,
        )
        cache_hit = cache.get(namespace, "budget recall", top_k=top_k) is not None
        worker = worker_report.as_dict()
        plan_payload = plan.as_dict()
        checks = [
            _check(
                "query-audit-signal",
                "Representative query audit created hot queries",
                int(plan_payload.get("hot_query_count") or 0) >= 1,
                f"hot_query_count={plan_payload.get('hot_query_count')}, replayed_queries={len(replayed_queries)}",
                "Replay representative staging traffic with query audit enabled before Memory OS rollout.",
            ),
            _check(
                "worker-prewarm",
                "Memory OS prewarmed hot recall paths",
                int(worker.get("prewarm", {}).get("warmed") or 0) >= 1 and cache_hit,
                f"prewarm_warmed={worker.get('prewarm', {}).get('warmed')}, cache_hit={cache_hit}",
                "Fix cache wiring or audit filters before scheduling cache-prewarm workers.",
            ),
            _check(
                "predictive-prefetch",
                "Memory OS generated predictive follow-up queries",
                int(worker.get("predictive_prefetch", {}).get("warmed") or 0) >= 1,
                "predictive_warmed="
                + str(worker.get("predictive_prefetch", {}).get("warmed")),
                "Keep transition audit enabled so predictive prefetch can learn follow-up paths.",
            ),
            _check(
                "priority-learning",
                "Memory OS applied bounded priority learning",
                int(worker.get("priority_predictions") or 0) >= 1,
                f"priority_predictions={worker.get('priority_predictions')}",
                "Investigate recall quality if hot queries do not produce priority updates.",
            ),
            _check(
                "ttl-cleanup",
                "Memory OS purged expired stale memories",
                int(worker.get("expired_purged") or 0) >= 1,
                f"expired_purged={worker.get('expired_purged')}",
                "Keep maintenance enabled before stale TTL records can compete with live memories.",
            ),
            _check(
                "admission",
                "Memory OS scheduler passes staging admission",
                bool(admission.get("admitted")),
                f"status={admission.get('status')}, blockers={admission.get('summary', {}).get('blocker_ids')}",
                "Resolve admission blockers before enabling production automation.",
            ),
        ]
        failed = [item["id"] for item in checks if not item["passed"]]
        status = "pass" if not failed else "action_required"
        return {
            "schema": CANARY_SCHEMA,
            "generated_at": _utc_now(),
            "status": status,
            "ok": status == "pass",
            "claim_boundary": "staging_canary; not remote Kubernetes, Redis, or 10M production evidence",
            "namespace": namespace,
            "deployment": deployment,
            "target_memories": int(target_memories),
            "namespace_count": int(namespace_count),
            "node_count": int(node_count),
            "seeded_memory_ids": seeded_ids,
            "replayed_query_count": len(replayed_queries),
            "unique_replayed_queries": sorted(set(replayed_queries)),
            "checks": checks,
            "failed_check_ids": failed,
            "summary": {
                "status": status,
                "ok": status == "pass",
                "passed_checks": sum(1 for item in checks if item["passed"]),
                "check_count": len(checks),
                "failed_check_ids": failed,
                "hot_query_count": plan_payload.get("hot_query_count"),
                "worker_actions": worker.get("actions", []),
                "prewarm_warmed": worker.get("prewarm", {}).get("warmed"),
                "predictive_warmed": worker.get("predictive_prefetch", {}).get("warmed"),
                "priority_predictions": worker.get("priority_predictions"),
                "expired_purged": worker.get("expired_purged"),
                "admission_status": admission.get("status"),
                "admitted": admission.get("admitted"),
            },
            "worker_report": worker,
            "schedule_plan": plan_payload,
            "admission": admission,
            "next_actions": (
                [
                    "Use this canary as a staging gate before enabling Memory OS CronJobs.",
                    "Run memory-os-admission separately for million-plus production targets; this canary does not unlock 10M/100M scale claims.",
                ]
                if status == "pass"
                else [
                    "Do not schedule Memory OS workers until failed canary checks are fixed.",
                    *[
                        item["action"]
                        for item in checks
                        if not item["passed"]
                    ],
                ]
            ),
        }
    finally:
        memory.audit_queries = previous_audit


def render_memory_os_canary_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Memory OS Canary",
        "",
        "This staging canary seeds representative memories and query-audit traffic,",
        "runs one Memory OS cycle, and verifies that the scheduler plus admission",
        "gate can safely admit the worker set when Redis/cache and lock wiring are",
        "declared. It is not remote production scale evidence.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| deployment | `{payload['deployment']}` |",
        f"| namespace | `{payload['namespace']}` |",
        f"| target memories | `{payload['target_memories']}` |",
        f"| replayed queries | `{payload['replayed_query_count']}` |",
        f"| hot queries | `{summary['hot_query_count']}` |",
        f"| admission | `{summary['admission_status']}` |",
        f"| admitted | `{summary['admitted']}` |",
        f"| passed checks | `{summary['passed_checks']}/{summary['check_count']}` |",
        "",
        "## Checks",
        "",
        "| check | status | evidence | action |",
        "|---|---|---|---|",
    ]
    for item in payload.get("checks", []):
        lines.append(
            "| {title} | `{status}` | {evidence} | {action} |".format(
                title=item["title"],
                status=item["status"],
                evidence=str(item.get("evidence") or "").replace("|", "\\|"),
                action=str(item.get("action") or "").replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Admission Detail", ""])
    lines.append(render_memory_os_admission_markdown(payload["admission"]).strip())
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"
