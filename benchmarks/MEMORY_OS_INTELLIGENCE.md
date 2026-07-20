# WaveMind Memory OS Intelligence Report

Generated: `2026-07-09T22:45:10Z`.

Memory OS intelligence rows come from checked-in deterministic scale, agent-coherence, direct adaptive A/B, staging canary, admission, and policy-bundle artifacts. They prove worker behavior, policy generation, cache prewarm, predictive prefetch, priority learning, adaptive forgetting, consolidation, and rollout safety. Production admission is backed by the checked six-hour multi-worker shared Redis and distributed lock artifact for the exact tested release and topology; automatic promotion remains disabled.

## Summary

- Status: `pass`.
- Checks: `39/39`.
- Hot queries: `2`.
- Cache prewarm warmed: `2`.
- Predictive prefetch warmed: `6`.
- Transition-prefetch hit: `True`.
- Priority predictions: `2`.
- Forgetting demotions: `4`.
- Concepts created: `1`.
- Policy decisions: `6`.
- Execution safe to run: `True`.
- Admission status: `admitted`.
- Policy bundle status: `production_ready`.
- Quality gate: `pass` (7/7).

## Gate Checks

| check | status | value | target |
|---|---|---:|---:|
| worker_ok | `pass` | `1` | `is True` |
| hot_queries | `pass` | `2` | `>= 2` |
| prewarm_warmed | `pass` | `2` | `>= 2` |
| predictive_prefetch_warmed | `pass` | `6` | `>= 6` |
| transition_prefetch_hit | `pass` | `1` | `is True` |
| concepts_created | `pass` | `1` | `>= 1` |
| concept_recall | `pass` | `1` | `is True` |
| feedback_events | `pass` | `8` | `>= 8` |
| positive_priority_delta | `pass` | `0.4` | `> 0.0` |
| negative_priority_delta | `pass` | `-0.3` | `< 0.0` |
| priority_predictions | `pass` | `2` | `>= 2` |
| forgetting_demotions | `pass` | `4` | `>= 1` |
| policy_decisions_present | `pass` | `1` | `is True` |
| execution_safe_to_run | `pass` | `1` | `is True` |
| execution_requires_shared_cache | `pass` | `1` | `is True` |
| execution_requires_distributed_lock | `pass` | `1` | `is True` |
| redis_cross_worker_hit | `pass` | `1` | `is True` |
| redis_busy_lock_skipped | `pass` | `1` | `is True` |
| redis_lock_required | `pass` | `1` | `is True` |
| redis_lock_acquired | `pass` | `1` | `is True` |
| redis_lock_released | `pass` | `1` | `is True` |
| agent_task_success | `pass` | `0.917` | `>= 0.9` |
| agent_stale_error | `pass` | `0` | `<= 0.05` |
| agent_context_saved | `pass` | `0.931` | `>= 0.9` |
| agent_memory_os_cache_hit_rate | `pass` | `0.24` | `>= 0.2` |
| agent_priority_predictions | `pass` | `5` | `>= 1` |
| canary_pass | `pass` | `pass` | `== pass` |
| canary_admitted | `pass` | `1` | `is True` |
| canary_predictive_warmed | `pass` | `15` | `>= 10` |
| quality_gate_pass | `pass` | `pass` | `== pass` |
| quality_task_uplift | `pass` | `0.125` | `>= 0.05` |
| quality_p95_delta | `pass` | `-0.428` | `<= 5.0` |
| quality_p95_ratio | `pass` | `-0.088` | `<= 0.2` |
| admission_is_admitted | `pass` | `1` | `is True` |
| admission_has_no_blockers | `pass` | `0` | `== 0` |
| policy_bundle_production_ready | `pass` | `production_ready` | `== production_ready` |
| policy_bundle_staging_promotable | `pass` | `1` | `is True` |
| policy_bundle_production_unlocked | `pass` | `0` | `is False` |
| policy_bundle_production_promotable | `pass` | `1` | `is True` |

## Intelligence Coverage

| area | evidence |
|---|---|
| Hot-query prewarm | `2` hot queries, `2` warmed. |
| Predictive prefetch | `6` warmed, transition hit `True`. |
| Priority learning | `2` predictions, positive delta `0.4`, negative delta `-0.3`. |
| Adaptive forgetting | `4` demotions, decay total `0.4`. |
| Consolidation | `1` concepts created, recall `True`. |
| Rollout safety | shared cache `True`, distributed lock `True`, required env `WAVEMIND_MEMORY_OS_LOCK_REDIS_URL, WAVEMIND_REDIS_URL`. |
| Policy bundle | status `production_ready`, staging `True`, production locked `False`. |
| Agent effect | task success `0.917`, stale error `0`, context saved `0.931`. |
| Direct Memory OS A/B | task-success uplift `0.125`, stale-suppression uplift `0.125`, p95 delta `-0.428` ms. |

## Production Boundary

Production admission is `admitted` for the exact checked release and tested multi-worker topology. Rollout remains operator-controlled, with automatic promotion disabled and fresh admission required after release or topology changes.
