# WaveMind Memory OS Admission

This gate decides whether the adaptive Memory OS worker set is safe to
schedule as production automation, or whether it is still only a runbook.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| target memories | `10000000` |
| worker count | `12` |
| effective cache | `redis` |
| hot query count | `0` |
| passed requirements | `5/11` |
| blockers | `5` |
| warnings | `1` |

## Requirements

| requirement | status | evidence | action |
|---|---|---|---|
| Execution plan has no blocked worker tasks | `pass` | safe_to_run=True, blocked=[] | Resolve execution_plan.blocked_task_ids before scheduling Memory OS. |
| All Memory OS worker lanes are planned | `pass` | adaptive-forgetting, architecture-advice, cache-prewarm, consolidation, maintenance, memory-os, predictive-prefetch | Planner must include memory-os, cache-prewarm, predictive-prefetch, forgetting, consolidation, maintenance, and architecture-advice. |
| Query audit traffic enables prewarm and predictive workers | `action_required` | hot_query_count=0, enabled=['adaptive-forgetting', 'architecture-advice', 'maintenance', 'memory-os'] | Enable audited query traffic in staging, replay representative traffic, then rerun memory-os-admission. |
| Consolidation worker is active when clusters exist | `action_required` | enabled=['adaptive-forgetting', 'architecture-advice', 'maintenance', 'memory-os'] | Seed enough representative memories/query traffic for stable concept clusters before production rollout. |
| Shared Redis cache is configured when the plan requires it | `action_required` | requires_shared_cache=True, effective_cache_mode=redis, redis_configured=False | Set WAVEMIND_REDIS_URL or pass --redis-url before enabling multi-worker Memory OS. |
| Distributed single-flight lock is configured for state mutation | `action_required` | requires_distributed_lock=True, lock_configured=False | Set WAVEMIND_MEMORY_OS_LOCK_REDIS_URL or pass --lock-redis-url before running production Memory OS workers. |
| State-mutating tasks are singleton/idempotent | `pass` | state_mutating=['adaptive-forgetting', 'maintenance', 'memory-os'], singleton=['adaptive-forgetting', 'architecture-advice', 'maintenance', 'memory-os'] | Keep mutation tasks as cluster singletons with idempotency keys. |
| Policy manifest covers prefetch, priority, forgetting, consolidation, scale, and coordination | `pass` | consolidation-policy, coordination-policy, forgetting-policy, prefetch-policy, priority-policy, scale-policy | Memory OS admission requires a full policy manifest before rollout. |
| Production infrastructure contract is explicit | `pass` | OpenTelemetry metrics for worker duration, errors, and warmed queries, Redis-compatible shared hot-query cache, distributed worker lock or single-flight scheduler, durable queue or Kubernetes CronJobs | Production plans must list Redis, lock/scheduler, queue/CronJob, and OpenTelemetry requirements. |
| Large target stays behind strict architecture evidence | `action_required` | architecture_status=architecture_required, strict_target=True | Do not admit Memory OS production rollout for million-plus targets until architecture-required evidence is resolved. |
| Required runtime environment is present | `action_required` | missing=['WAVEMIND_MEMORY_OS_LOCK_REDIS_URL', 'WAVEMIND_REDIS_URL'] | Provide every required environment variable before scheduling the worker set. |

## Next Actions

- Keep this as a runbook until the action_required requirements pass.
- Enable audited query traffic in staging, replay representative traffic, then rerun memory-os-admission.
- Seed enough representative memories/query traffic for stable concept clusters before production rollout.
- Set WAVEMIND_REDIS_URL or pass --redis-url before enabling multi-worker Memory OS.
- Set WAVEMIND_MEMORY_OS_LOCK_REDIS_URL or pass --lock-redis-url before running production Memory OS workers.
- Do not admit Memory OS production rollout for million-plus targets until architecture-required evidence is resolved.
- Provide every required environment variable before scheduling the worker set.

## Enabled Tasks

- `adaptive-forgetting`
- `architecture-advice`
- `maintenance`
- `memory-os`
