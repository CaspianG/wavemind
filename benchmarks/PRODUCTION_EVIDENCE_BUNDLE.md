# WaveMind Production Evidence Bundle

This bundle is the operator-facing status page for large-scale production claims.
It combines strict evidence, environment preflight, readiness, benchmark audit,
claim boundaries, and the exact next actions required to unlock blocked claims.

| metric | value |
|---|---:|
| claim status | `claims_limited` |
| strict evidence | `5/8` |
| preflight ready | `1/8` |
| production readiness | `pass` |
| readiness score | `1.0` |
| artifact audit | `pass` |
| implemented benchmarks | `37` |
| production scale run contract | `available` |
| production scale profiles | `5` |
| production scale target memories | `180000000` |
| next actions | `3` |

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
| pgvector-10m | `action_required` | `pgvector-service` | 10000000 | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSNS` |
| faiss-ivfpq-50m | `action_required` | `faiss-ivfpq-persisted` | 50000000 | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` |
| qdrant-sharded-100m | `action_required` | `qdrant-sharded-service` | 100000000 | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS` |

## Next Actions

| item | strict | preflight | artifact | missing env | command |
|---|---|---|---|---|---|
| External HTTP active-active regions with physical failure recovery | `action_required` | `action_required` | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_REMOTE_LAB_INVENTORY_JSON, WAVEMIND_REMOTE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_API_KEY, WAVEMIND_REMOTE_POSTGRES_PASSWORD; issues: missing artifact, failure drill: missing remote region failure drill artifact` | `gh workflow run remote-production-lab.yml --ref main -f action=evidence -f namespace_count=16` |
| Managed/serverless remote telemetry | `action_required` | `action_required` | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_CLOUD_RUN_PROJECT_ID, WAVEMIND_CLOUD_RUN_REGION, WAVEMIND_CLOUD_RUN_SERVICE, WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER, WAVEMIND_GCP_SERVICE_ACCOUNT, WAVEMIND_API_KEY; issues: missing artifact` | `gh workflow run managed-serverless-cloud-run.yml --ref main -f project_id="$WAVEMIND_CLOUD_RUN_PROJECT_ID" -f region="$WAVEMIND_CLOUD_RUN_REGION" -f service_name="$WAVEMIND_CLOUD_RUN_SERVICE"` |
| 100M remote load result with eight-host attestation | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON, WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY; issues: missing artifact, remote topology: missing remote Qdrant 100M attestation artifact` | `gh workflow run remote-qdrant-100m-lab.yml --ref main -f action=evidence -f runner_label=self-hosted-large` |
