# WaveMind Memory OS Policy Bundle

This bundle turns checked canary and policy-evolution evidence into a
runtime policy manifest for operators. It is safe for staging promotion
when the canary and evolution checks pass. Production automation remains
blocked until `memory-os-admission` is admitted with external evidence.

| metric | value |
|---|---:|
| status | `production_ready` |
| staging promotable | `True` |
| production promotable | `True` |
| production locked | `False` |
| worker count | `1` |
| cache mode | `redis` |
| passed checks | `7/7` |

## Runtime Policy

| field | value |
|---|---|
| target deployment | `staging` |
| production auto-enable | `False` |
| required env | `WAVEMIND_REDIS_URL, WAVEMIND_MEMORY_OS_LOCK_REDIS_URL` |
| enabled tasks | `memory-os, cache-prewarm, predictive-prefetch, adaptive-forgetting, consolidation, maintenance, architecture-advice` |
| policy escalations | `scale-policy` |
| rollout mode | `shadow_then_canary` |
| automatic promotion | `False` |
| rollback action | `suspend_memory_os_cronjob` |
| manual override | `memoryOs.emergencyStop=true` |

## Checks

| check | status | evidence | action |
|---|---|---|---|
| Memory OS staging canary passed | `pass` | status=pass, ok=True | Run wavemind memory-os-canary with representative staging traffic. |
| Memory OS policy evolution passed | `pass` | status=pass, ok=True | Run wavemind memory-os-evolution and fix repeated-policy checks. |
| Runtime env contract declares Redis and lock wiring | `pass` | WAVEMIND_REDIS_URL, WAVEMIND_MEMORY_OS_LOCK_REDIS_URL | Declare WAVEMIND_REDIS_URL and WAVEMIND_MEMORY_OS_LOCK_REDIS_URL in the runtime bundle. |
| Bundle can be promoted to staging | `pass` | canary=True, evolution=True, env=True | Do not deploy the Memory OS policy bundle until canary, evolution, and runtime env contract pass. |
| Production promotion remains behind strict admission | `pass` | admission_status=admitted, admitted=True, blockers=[] | Resolve memory-os-admission blockers with real Redis, distributed lock, runtime env, and large-scale evidence. |
| Bundle does not enable unattended production automation | `pass` | production_auto_enable=False, production_locked=False | Keep production_auto_enable=false unless memory-os-admission returns admitted. |
| Shadow, canary, rollback, and manual stop policy is explicit | `pass` | mode=shadow_then_canary, automatic_promotion=False, automatic_pause=True | Keep staged promotion, automatic pause, atomic lease, job receipts, and emergency stop enabled. |

## Kubernetes Runtime Patch

```json
{
  "apiVersion": "wavemind.dev/v1",
  "kind": "MemoryOSPolicyBundle",
  "metadata": {
    "name": "wavemind-memory-os-staging"
  },
  "spec": {
    "targetDeployment": "staging",
    "productionAutoEnable": false,
    "env": [
      {
        "name": "WAVEMIND_MEMORY_OS_ENABLED",
        "value": "1"
      },
      {
        "name": "WAVEMIND_MEMORY_OS_POLICY_BUNDLE",
        "value": "memory_os_policy_bundle_results.json"
      },
      {
        "name": "WAVEMIND_MEMORY_OS_CANARY_REQUIRED",
        "value": "1"
      },
      {
        "name": "WAVEMIND_MEMORY_OS_PRODUCTION_ADMISSION_REQUIRED",
        "value": "1"
      },
      {
        "name": "WAVEMIND_MEMORY_OS_EMERGENCY_STOP",
        "value": "0"
      },
      {
        "name": "WAVEMIND_MEMORY_OS_DEPLOYMENT",
        "value": "staging"
      },
      {
        "name": "WAVEMIND_REDIS_URL",
        "valueFrom": {
          "secretKeyRef": {
            "name": "wavemind-memory-os-runtime",
            "key": "redis-url"
          }
        }
      },
      {
        "name": "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL",
        "valueFrom": {
          "secretKeyRef": {
            "name": "wavemind-memory-os-runtime",
            "key": "lock-redis-url"
          }
        }
      }
    ],
    "cronJobs": [
      {
        "name": "wavemind-memory-os",
        "task_id": "memory-os",
        "schedule": "*/5 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-cache-prewarm",
        "task_id": "cache-prewarm",
        "schedule": "*/2 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-predictive-prefetch",
        "task_id": "predictive-prefetch",
        "schedule": "*/5 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-adaptive-forgetting",
        "task_id": "adaptive-forgetting",
        "schedule": "17 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-consolidation",
        "task_id": "consolidation",
        "schedule": "37 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-maintenance",
        "task_id": "maintenance",
        "schedule": "47 * * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      },
      {
        "name": "wavemind-architecture-advice",
        "task_id": "architecture-advice",
        "schedule": "11 */6 * * *",
        "concurrencyPolicy": "Forbid",
        "restartPolicy": "OnFailure"
      }
    ],
    "requiredRuntimeEnv": [
      "WAVEMIND_REDIS_URL",
      "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL"
    ],
    "observability": {
      "required_metrics": [
        "wavemind_memory_os_cycle_duration_ms",
        "wavemind_memory_os_worker_errors_total",
        "wavemind_memory_os_hot_queries",
        "wavemind_memory_os_prewarm_warmed",
        "wavemind_memory_os_predictive_warmed",
        "wavemind_memory_os_priority_predictions",
        "wavemind_memory_os_forgetting_demotions",
        "wavemind_memory_os_concepts_created"
      ],
      "trace_attributes": [
        "wavemind.namespace",
        "wavemind.memory_os.task_id",
        "wavemind.memory_os.policy_bundle_id",
        "wavemind.memory_os.idempotency_key"
      ]
    },
    "safety": {
      "state_mutating_tasks": [
        "maintenance",
        "adaptive-forgetting",
        "consolidation",
        "memory-os"
      ],
      "singleton_task_ids": [
        "architecture-advice",
        "maintenance",
        "adaptive-forgetting",
        "consolidation",
        "memory-os",
        "cache-prewarm",
        "predictive-prefetch"
      ],
      "idempotency_required": true,
      "production_admission_required": true,
      "large_scale_evidence_required": true,
      "atomic_lease_required": true,
      "lease_heartbeat_required": true,
      "job_receipt_required": true,
      "manual_emergency_stop_required": true
    }
  }
}
```

## Next Actions

- Apply the production bundle through the controlled shadow and canary rollout.
- Keep the same policy bundle id in deployment annotations for auditability.
- Rerun admission for every release commit or production topology change.
