# Verified Agent Experience Benchmark

Status: **pass**

Source SHA: `7a457e18082c3eda2e9fbafba2a2ac32fbd2abae`

| Mode | Task success | Repeated error | Context tokens | p95 runtime |
|---|---:|---:|---:|---:|
| No memory | 0.200 | 1.000 | 0 | 0.000 ms |
| Static always-on | 1.000 | 0.000 | 20250 | 0.006 ms |
| Selective verified | 1.000 | 0.000 | 12320 | 6.123 ms |

## Frozen gates

- PASS `task_success_uplift`
- PASS `positive_uplift_all_domains`
- PASS `repeated_error_reduction`
- PASS `context_token_reduction`
- PASS `unnecessary_intervention`
- PASS `runtime_latency`
- PASS `capture_rate`
- PASS `unverified_promotion`
- PASS `namespace_isolation`
- PASS `rollback_provenance`
