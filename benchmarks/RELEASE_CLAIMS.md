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
| allowed claims | `3` |
| locked claims | `2` |
| next actions | `3` |

## Allowed Claims

| claim | status | evidence |
|---|---|---|
| Core library/API readiness | `unlocked` | `production_readiness_results.json and benchmark_artifact_audit.json` |
| Non-loopback Kubernetes service-node cluster SLO | `unlocked` | `benchmarks/http_cluster_load_results.json` |
| Large-N production run contracts | `available` | `benchmarks/production_scale_run_plan.json` |

## Locked Claims

| claim | status | evidence |
|---|---|---|
| Remote multi-region active-active convergence | `locked` | `benchmarks/external_http_active_active_results.json` |
| 10M-100M service-backed production scale | `locked` | `large-N production_streaming_load result artifacts` |

## Next Actions

| item | strict | preflight | artifact | missing env | command |
|---|---|---|---|---|---|
| External HTTP active-active regions with physical failure recovery | `action_required` | `action_required` | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_REMOTE_LAB_INVENTORY_JSON, WAVEMIND_REMOTE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_API_KEY, WAVEMIND_REMOTE_POSTGRES_PASSWORD` | `gh workflow run remote-production-lab.yml --ref main -f action=evidence -f namespace_count=16` |
| Managed/serverless remote telemetry | `action_required` | `action_required` | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_CLOUD_RUN_PROJECT_ID, WAVEMIND_CLOUD_RUN_REGION, WAVEMIND_CLOUD_RUN_SERVICE, WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER, WAVEMIND_GCP_SERVICE_ACCOUNT, WAVEMIND_API_KEY` | `gh workflow run managed-serverless-cloud-run.yml --ref main -f project_id="$WAVEMIND_CLOUD_RUN_PROJECT_ID" -f region="$WAVEMIND_CLOUD_RUN_REGION" -f service_name="$WAVEMIND_CLOUD_RUN_SERVICE"` |
| 100M remote load result with eight-host attestation | `action_required` | `action_required` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON, WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY` | `gh workflow run remote-qdrant-100m-lab.yml --ref main -f action=evidence -f runner_label=self-hosted-large` |
