# WaveMind Memory OS Admission

This gate decides whether the adaptive Memory OS worker set is safe to
schedule as production automation, or whether it is still only a runbook.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| target memories | `50000` |
| worker count | `1` |
| effective cache | `redis` |
| hot query count | `16` |
| passed requirements | `12/13` |
| blockers | `1` |
| warnings | `0` |

## Requirements

| requirement | status | evidence | action |
|---|---|---|---|
| Execution plan has no blocked worker tasks | `pass` | safe_to_run=True, blocked=[] | Resolve execution_plan.blocked_task_ids before scheduling Memory OS. |
| All Memory OS worker lanes are planned | `pass` | adaptive-forgetting, architecture-advice, cache-prewarm, consolidation, maintenance, memory-os, predictive-prefetch | Planner must include memory-os, cache-prewarm, predictive-prefetch, forgetting, consolidation, maintenance, and architecture-advice. |
| Query audit traffic enables prewarm and predictive workers | `pass` | hot_query_count=16, enabled=['adaptive-forgetting', 'architecture-advice', 'cache-prewarm', 'consolidation', 'maintenance', 'memory-os', 'predictive-prefetch'] | Enable audited query traffic in staging, replay representative traffic, then rerun memory-os-admission. |
| Consolidation worker is active when clusters exist | `pass` | enabled=['adaptive-forgetting', 'architecture-advice', 'cache-prewarm', 'consolidation', 'maintenance', 'memory-os', 'predictive-prefetch'] | Seed enough representative memories/query traffic for stable concept clusters before production rollout. |
| Shared Redis cache is configured when the plan requires it | `pass` | requires_shared_cache=True, effective_cache_mode=redis, redis_configured=True | Set WAVEMIND_REDIS_URL or pass --redis-url before enabling multi-worker Memory OS. |
| Distributed single-flight lock is configured for state mutation | `pass` | requires_distributed_lock=True, lock_configured=True | Set WAVEMIND_MEMORY_OS_LOCK_REDIS_URL or pass --lock-redis-url before running production Memory OS workers. |
| State-mutating tasks are singleton/idempotent | `pass` | state_mutating=['adaptive-forgetting', 'consolidation', 'maintenance', 'memory-os'], singleton=['adaptive-forgetting', 'architecture-advice', 'cache-prewarm', 'consolidation', 'maintenance', 'memory-os', 'predictive-prefetch'] | Keep mutation tasks as cluster singletons with idempotency keys. |
| Policy manifest covers prefetch, priority, forgetting, consolidation, scale, and coordination | `pass` | consolidation-policy, coordination-policy, forgetting-policy, prefetch-policy, priority-policy, scale-policy | Memory OS admission requires a full policy manifest before rollout. |
| Production infrastructure contract is explicit | `pass` | OpenTelemetry metrics for worker duration, errors, and warmed queries, Redis-compatible shared hot-query cache, distributed worker lock or single-flight scheduler, durable queue or Kubernetes CronJobs | Production plans must list Redis, lock/scheduler, queue/CronJob, and OpenTelemetry requirements. |
| Large target stays behind strict architecture evidence | `pass` | architecture_status=action_required, strict_target=False | Do not admit Memory OS production rollout for million-plus targets until architecture-required evidence is resolved. |
| Required runtime environment is present | `pass` | missing=[] | Provide every required environment variable before scheduling the worker set. |
| Direct adaptive A/B proves Memory OS quality uplift within latency limits | `pass` | schema=wavemind.memory_os_quality_gate.v2, status=pass, task_uplift=0.125, p95_delta_ms=-11.810799944214523, p95_ratio=-0.9975759074334425 | Run memory_os_ab_benchmark.py and memory_os_quality_gate.py on this release; non-regression and static-retrieval comparisons do not satisfy this requirement. |
| Fresh six-hour remote soak proves 500-cycle lease, retry, and state safety | `action_required` | schema=wavemind.memory_os_runtime_soak.v1, status=pass, environment=local_redis, duration=3.309, cycles=None, fresh=False, commit_matches=False, checks_pass=True | Run the six-hour remote soak against two or more HTTPS workers and their TLS Redis, then attach the fresh artifact from the exact release commit. |

## Next Actions

- Keep this as a runbook until the action_required requirements pass.
- Run the six-hour remote soak against two or more HTTPS workers and their TLS Redis, then attach the fresh artifact from the exact release commit.

## Enabled Tasks

- `adaptive-forgetting`
- `architecture-advice`
- `cache-prewarm`
- `consolidation`
- `maintenance`
- `memory-os`
- `predictive-prefetch`
