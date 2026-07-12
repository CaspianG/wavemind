# WaveMind Production Evidence Environment Contract

This is the operator-facing environment contract for strict production
evidence runs. It maps every required variable to the claims, workflows,
artifacts, and GitHub secrets it unlocks. It is secret-safe: values are not serialized.

Environment contract only. It stores placeholders and secret names, never credential values, and does not unlock production claims until strict evidence artifacts pass ingestion and validation.

| metric | value |
|---|---:|
| overall status | `action_required` |
| required env | `21` |
| configured required env | `0` |
| missing required env | `21` |
| recommended missing env | `2` |
| workflows | `5` |
| dispatch jobs | `8` |
| strict requirements | `8` |

## Variables

| variable | status | kind | used by | workflows | artifacts |
|---|---|---|---|---|---|
| `WAVEMIND_ACTIVE_ACTIVE_REGIONS` | `optional` | `api-region-list` |  |  |  |
| `WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` | `optional` | `api-region-manifest-json` |  |  |  |
| `WAVEMIND_API_KEY` | `missing` | `api-secret` | `external_http_cluster`, `serverless_remote_telemetry` | `external-http-cluster-load.yml`, `managed-serverless-cloud-run.yml` | `benchmarks/http_cluster_load_results.json`, `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_CLOUD_RUN_PROJECT_ID` | `missing` | `gcp-project-id` | `serverless_remote_telemetry` | `managed-serverless-cloud-run.yml` | `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_CLOUD_RUN_REGION` | `missing` | `gcp-region` | `serverless_remote_telemetry` | `managed-serverless-cloud-run.yml` | `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_CLOUD_RUN_SERVICE` | `missing` | `cloud-run-service` | `serverless_remote_telemetry` | `managed-serverless-cloud-run.yml` | `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_CLUSTER_NODES` | `missing` | `api-node-list` | `external_http_cluster` | `external-http-cluster-load.yml` | `benchmarks/http_cluster_load_results.json` |
| `WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | `missing` | `api-node-manifest-json` | `external_http_cluster` | `external-http-cluster-load.yml` | `benchmarks/http_cluster_load_results.json` |
| `WAVEMIND_FAISS_IVFPQ_FREE_GB` | `optional` | `disk-free-override-gb` |  |  |  |
| `WAVEMIND_FAISS_IVFPQ_PATH` | `missing` | `filesystem-path` | `faiss_ivfpq_50m` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_ivfpq_50m_results.json` |
| `WAVEMIND_GCP_SERVICE_ACCOUNT` | `missing` | `gcp-service-account` | `serverless_remote_telemetry` | `managed-serverless-cloud-run.yml` | `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER` | `missing` | `gcp-workload-identity-provider` | `serverless_remote_telemetry` | `managed-serverless-cloud-run.yml` | `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_PGVECTOR_DSNS` | `missing` | `postgres-dsn-list` | `pgvector_10m_service` |  | `benchmarks/production_streaming_load_pgvector_10m_results.json` |
| `WAVEMIND_QDRANT_API_KEY` | `recommended` | `qdrant-api-secret` | `qdrant_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_10m_results.json` |
| `WAVEMIND_QDRANT_API_KEYS` | `recommended` | `qdrant-api-secret-list` | `qdrant_sharded_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` |
| `WAVEMIND_QDRANT_URL` | `missing` | `qdrant-url` | `qdrant_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_10m_results.json` |
| `WAVEMIND_QDRANT_URLS` | `missing` | `qdrant-url-list` | `qdrant_sharded_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` |
| `WAVEMIND_REMOTE_API_KEY` | `missing` | `api-secret` | `external_http_active_active` | `remote-production-lab.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_REMOTE_LAB_INVENTORY_JSON` | `missing` | `remote-lab-inventory-json` | `external_http_active_active` | `remote-production-lab.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_REMOTE_POSTGRES_PASSWORD` | `missing` | `postgres-password` | `external_http_active_active` | `remote-production-lab.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON` | `missing` | `remote-qdrant-scale-inventory-json` | `hundred_million_remote_load` | `remote-qdrant-100m-lab.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` |
| `WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY` | `missing` | `qdrant-api-secret` | `hundred_million_remote_load` | `remote-qdrant-100m-lab.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` |
| `WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS` | `missing` | `ssh-known-hosts` | `hundred_million_remote_load` | `remote-qdrant-100m-lab.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` |
| `WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY` | `missing` | `ssh-private-key` | `hundred_million_remote_load` | `remote-qdrant-100m-lab.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` |
| `WAVEMIND_REMOTE_SSH_KNOWN_HOSTS` | `missing` | `ssh-known-hosts` | `external_http_active_active` | `remote-production-lab.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_REMOTE_SSH_PRIVATE_KEY` | `missing` | `ssh-private-key` | `external_http_active_active` | `remote-production-lab.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_SERVERLESS_NODES` | `optional` | `serverless-api-node-list` |  |  |  |

## GitHub Secrets

Run these from a shell where each variable is already exported. The
commands pipe values from the environment; values are not echoed into
the repository.

- `printf '%s' "$WAVEMIND_ACTIVE_ACTIVE_REGIONS" | gh secret set WAVEMIND_ACTIVE_ACTIVE_REGIONS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON" | gh secret set WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_API_KEY" | gh secret set WAVEMIND_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLOUD_RUN_PROJECT_ID" | gh secret set WAVEMIND_CLOUD_RUN_PROJECT_ID --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLOUD_RUN_REGION" | gh secret set WAVEMIND_CLOUD_RUN_REGION --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLOUD_RUN_SERVICE" | gh secret set WAVEMIND_CLOUD_RUN_SERVICE --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLUSTER_NODES" | gh secret set WAVEMIND_CLUSTER_NODES --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLUSTER_NODES_MANIFEST_JSON" | gh secret set WAVEMIND_CLUSTER_NODES_MANIFEST_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_FAISS_IVFPQ_FREE_GB" | gh secret set WAVEMIND_FAISS_IVFPQ_FREE_GB --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_FAISS_IVFPQ_PATH" | gh secret set WAVEMIND_FAISS_IVFPQ_PATH --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_GCP_SERVICE_ACCOUNT" | gh secret set WAVEMIND_GCP_SERVICE_ACCOUNT --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER" | gh secret set WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_PGVECTOR_DSNS" | gh secret set WAVEMIND_PGVECTOR_DSNS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_API_KEY" | gh secret set WAVEMIND_QDRANT_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_API_KEYS" | gh secret set WAVEMIND_QDRANT_API_KEYS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_URL" | gh secret set WAVEMIND_QDRANT_URL --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_URLS" | gh secret set WAVEMIND_QDRANT_URLS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_API_KEY" | gh secret set WAVEMIND_REMOTE_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_LAB_INVENTORY_JSON" | gh secret set WAVEMIND_REMOTE_LAB_INVENTORY_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_POSTGRES_PASSWORD" | gh secret set WAVEMIND_REMOTE_POSTGRES_PASSWORD --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SCALE_INVENTORY_JSON" | gh secret set WAVEMIND_REMOTE_SCALE_INVENTORY_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY" | gh secret set WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS" | gh secret set WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY" | gh secret set WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SSH_KNOWN_HOSTS" | gh secret set WAVEMIND_REMOTE_SSH_KNOWN_HOSTS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_REMOTE_SSH_PRIVATE_KEY" | gh secret set WAVEMIND_REMOTE_SSH_PRIVATE_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_SERVERLESS_NODES" | gh secret set WAVEMIND_SERVERLESS_NODES --repo CaspianG/wavemind --body-file -`

## Checks

| check | status | detail |
|---|---|---|
| all_preflight_env_represented | `pass` | 20/20 preflight env vars represented |
| all_dispatch_env_represented | `pass` | 22/22 dispatch env vars represented |
| all_scale_gap_env_represented | `pass` | 8/8 scale-gap env vars represented |
| no_missing_contract_rows | `pass` | none |
| strict_requirements_joined | `pass` | 8 strict requirements |
| secret_values_not_serialized | `pass` | contract uses placeholders and secret names only |
