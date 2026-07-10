# WaveMind Release Claims

This is the compact release-facing claim contract. It separates what a
release may safely claim from production-scale claims that remain locked
until strict external evidence artifacts pass.

| metric | value |
|---|---:|
| release status | `core_release_ready` |
| claim status | `claims_limited` |
| strict evidence | `action_required` |
| production readiness | `pass` |
| artifact audit | `pass` |
| allowed claims | `2` |
| locked claims | `3` |
| next actions | `7` |

## Allowed Claims

| claim | status | evidence |
|---|---|---|
| Core library/API readiness | `unlocked` | `production_readiness_results.json and benchmark_artifact_audit.json` |
| Large-N production run contracts | `available` | `benchmarks/production_scale_run_plan.json` |

## Locked Claims

| claim | status | evidence |
|---|---|---|
| Remote service-node cluster SLO | `locked` | `benchmarks/http_cluster_load_results.json` |
| Remote multi-region active-active convergence | `locked` | `benchmarks/external_http_active_active_results.json` |
| 10M-100M service-backed production scale | `locked` | `large-N production_streaming_load result artifacts` |

## Next Actions

| item | strict | preflight | artifact | missing env | command |
|---|---|---|---|---|---|
| External HTTP service-node load | `action_required` | `action_required` | `benchmarks/http_cluster_load_results.json` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | `gh workflow run external-http-cluster-load.yml -f nodes="$WAVEMIND_CLUSTER_NODES" -f batch_query_size=24 -f commit_results=true` |
| External HTTP active-active regions | `action_required` | `action_required` | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_ACTIVE_ACTIVE_REGIONS, WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` | `gh workflow run external-http-active-active.yml -f regions="$WAVEMIND_ACTIVE_ACTIVE_REGIONS" -f commit_results=true` |
| Managed/serverless remote telemetry | `action_required` | `action_required` | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_SERVERLESS_NODES` | `gh workflow run serverless-observed-telemetry.yml -f nodes="$WAVEMIND_SERVERLESS_NODES" -f seed_mode=first -f commit_results=true` |
| 10M Qdrant service load | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` | `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines qdrant-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_qdrant_10m_results.json --checkpoint-path state/production-runs/qdrant-service-10000000.checkpoint.json` |
| 10M sharded Qdrant service load | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` | `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 250.0 --replicas 4 --autoscaling-max-replicas 48 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_qdrant_sharded_10m_results.json --checkpoint-path state/production-runs/qdrant-sharded-service-10000000.checkpoint.json` |
| 10M pgvector service load | `action_required` | `action_required` | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSN` | `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines pgvector-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_pgvector_10m_results.json --checkpoint-path state/production-runs/pgvector-service-10000000.checkpoint.json` |
| 100M remote load result | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS` | `python benchmarks/production_streaming_load_benchmark.py --sizes 100000000 --dim 128 --queries 5000 --top-k 10 --seed 42 --noise 0.08 --batch-size 10000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 500.0 --replicas 8 --autoscaling-max-replicas 128 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_qdrant_sharded_100m_results.json --checkpoint-path state/production-runs/qdrant-sharded-service-100000000.checkpoint.json` |
