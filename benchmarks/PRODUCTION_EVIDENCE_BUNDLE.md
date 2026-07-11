# WaveMind Production Evidence Bundle

This bundle is the operator-facing status page for large-scale production claims.
It combines strict evidence, environment preflight, readiness, benchmark audit,
claim boundaries, and the exact next actions required to unlock blocked claims.

| metric | value |
|---|---:|
| claim status | `claims_limited` |
| strict evidence | `4/8` |
| preflight ready | `0/8` |
| production readiness | `pass` |
| readiness score | `1.0` |
| artifact audit | `pass` |
| implemented benchmarks | `37` |
| production scale run contract | `available` |
| production scale profiles | `5` |
| production scale target memories | `180000000` |
| next actions | `4` |

## Claim Boundaries

| claim | status | evidence |
|---|---|---|
| Core library/API readiness | `unlocked` | `production_readiness_results.json and benchmark_artifact_audit.json` |
| Non-loopback Kubernetes service-node cluster SLO | `unlocked` | `benchmarks/http_cluster_load_results.json` |
| Remote multi-region active-active convergence | `locked` | `benchmarks/external_http_active_active_results.json` |
| Large-N production run contracts | `available` | `benchmarks/production_scale_run_plan.json` |
| 10M-100M service-backed production scale | `locked` | `large-N production_streaming_load result artifacts` |

## Production Scale Run Contract

| profile | status | engine | target memories | output artifact | missing env |
|---|---|---|---:|---|---|
| qdrant-10m | `action_required` | `qdrant-service` | 10000000 | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` |
| qdrant-sharded-10m | `action_required` | `qdrant-sharded-service` | 10000000 | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` |
| pgvector-10m | `action_required` | `pgvector-service` | 10000000 | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSN` |
| faiss-ivfpq-50m | `action_required` | `faiss-ivfpq-persisted` | 50000000 | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` |
| qdrant-sharded-100m | `action_required` | `qdrant-sharded-service` | 100000000 | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS` |

## Next Actions

| item | strict | preflight | artifact | missing env | command |
|---|---|---|---|---|---|
| External HTTP active-active regions | `action_required` | `action_required` | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_ACTIVE_ACTIVE_REGIONS, WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON; issues: missing artifact` | `gh workflow run external-http-active-active.yml -f regions="$WAVEMIND_ACTIVE_ACTIVE_REGIONS" -f commit_results=true` |
| Managed/serverless remote telemetry | `action_required` | `action_required` | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_SERVERLESS_NODES; issues: missing artifact` | `gh workflow run serverless-observed-telemetry.yml -f nodes="$WAVEMIND_SERVERLESS_NODES" -f seed_mode=first -f commit_results=true` |
| 10M pgvector service load | `action_required` | `action_required` | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSN; issues: missing artifact` | `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines pgvector-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_pgvector_10m_results.json --checkpoint-path state/production-runs/pgvector-service-10000000.checkpoint.json` |
| 100M remote load result | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS; issues: missing artifact` | `python benchmarks/production_streaming_load_benchmark.py --sizes 100000000 --dim 128 --queries 5000 --top-k 10 --seed 42 --noise 0.08 --batch-size 10000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 500.0 --replicas 8 --autoscaling-max-replicas 128 --capacity-headroom 0.7 --output benchmarks/production_streaming_load_qdrant_sharded_100m_results.json --checkpoint-path state/production-runs/qdrant-sharded-service-100000000.checkpoint.json` |
