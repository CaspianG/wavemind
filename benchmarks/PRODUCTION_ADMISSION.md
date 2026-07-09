# WaveMind Production Admission

This is the deployment-facing admission gate. It answers whether a
requested production scale is backed by passing strict evidence, or still
limited to a plan-only run contract.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| engine | `qdrant-sharded-service` |
| target memories | `100000000` |
| required profiles | `qdrant-sharded-100m` |
| blocking issues | `1` |
| strict evidence | `action_required` |
| scale gap | `action_required` |

## Required Evidence

| profile | strict | scale gap | artifact | nearest baseline | missing env |
|---|---|---|---|---:|---|
| qdrant-sharded-100m | `action_required` | `blocked_by_env` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | 1000000 | `WAVEMIND_QDRANT_URLS` |

## Issues

- qdrant-sharded-100m is not admitted: strict_status=action_required, scale_gap_status=blocked_by_env

## Next Actions

- Do not admit production traffic yet; run the listed strict-evidence job first.
- `python benchmarks/production_streaming_load_benchmark.py --sizes 100000000 --dim 128 --queries 5000 --top-k 10 --seed 42 --noise 0.08 --batch-size 10000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 500.0 --replicas 8 --autoscaling-max-replicas 128 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_qdrant_sharded_100m_results.json --checkpoint-path state/production-runs/qdrant-sharded-service-100000000.checkpoint.json`
