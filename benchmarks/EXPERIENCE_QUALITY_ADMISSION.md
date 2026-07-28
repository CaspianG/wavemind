# Experienced Work Agent Admission

Status: **admitted**

Source SHA: `d011eb848e031e1383a8437da3ca8d8f86dcb74e`

Checks: **12/12**

| check | status | evidence | target |
|---|---|---|---|
| artifact-schema | pass | `{"schema":"wavemind.experienced_work_agent_benchmark.v1","status":"pass"}` | passing experienced-work-agent v1 artifact |
| source-sha | pass | `"d011eb848e031e1383a8437da3ca8d8f86dcb74e"` | d011eb848e031e1383a8437da3ca8d8f86dcb74e |
| frozen-split | pass | `{"revision":"experienced-work-agent-v1-frozen-20260728","fingerprint_sha256":"0d8a6b2de3e18f6273f3b148e6fb4b1fbfb7fa0b79dd82c42efb3973caf41225","training_trajectories":60,"held_out_tasks":30,"metadata_leakage":false}` | frozen 60/30 split with exact fingerprint and no leakage |
| fair-protocol | pass | `{"same_held_out_tasks":true,"same_runtime_verifiers":true,"same_tool_implementations":true,"no_paid_api":true,"experience_promotion_gates":true,"core_top_k":3,"paired_latency_samples":true,"latency_repetitions_per_case":3}` | same tasks, runtimes, tools, gated experience promotion, and at least three paired latency samples per case |
| training-evidence | pass | `{"successful":48,"failed":12,"known_error_codes":["approval_missing","case_closed_before_merge","config_keys_lost","duplicate_ledger_entry","execution_missing","identity_lookup_missing","identity_not_verified","merge_not_completed","schema_field_lost","update_missing"],"active_strategies":6}` | 48 verified successes, 12 observed failures, 6 active strategies |
| task-success-uplift | pass | `0.8333333333333334` | >= 0.15 |
| repeated-error-reduction | pass | `1.0` | >= 0.50 |
| tool-step-reduction | pass | `0.25` | >= 0.25 |
| context-token-reduction | pass | `0.4` | >= 0.35 |
| p95-latency | pass | `-0.42198785835167174` | <= 0.20 relative regression |
| held-out-parity | pass | `{"cold":30,"core":30,"experience":30}` | same 30 ordered held-out IDs for all engines |
| embedded-checks | pass | `8` | all embedded benchmark checks pass |
