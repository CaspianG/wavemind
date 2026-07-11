# WaveMind Production Evidence Environment Contract

This is the operator-facing environment contract for strict production
evidence runs. It maps every required variable to the claims, workflows,
artifacts, and GitHub secrets it unlocks. It is secret-safe: values are not serialized.

Environment contract only. It stores placeholders and secret names, never credential values, and does not unlock production claims until strict evidence artifacts pass ingestion and validation.

| metric | value |
|---|---:|
| overall status | `action_required` |
| required env | `9` |
| configured required env | `0` |
| missing required env | `9` |
| recommended missing env | `3` |
| workflows | `4` |
| dispatch jobs | `8` |
| strict requirements | `8` |

## Variables

| variable | status | kind | used by | workflows | artifacts |
|---|---|---|---|---|---|
| `WAVEMIND_ACTIVE_ACTIVE_REGIONS` | `missing` | `api-region-list` | `external_http_active_active` | `external-http-active-active.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` | `missing` | `api-region-manifest-json` | `external_http_active_active` | `external-http-active-active.yml` | `benchmarks/external_http_active_active_results.json` |
| `WAVEMIND_API_KEY` | `recommended` | `api-secret` | `external_http_active_active`, `external_http_cluster`, `serverless_remote_telemetry` | `external-http-active-active.yml`, `external-http-cluster-load.yml`, `serverless-observed-telemetry.yml` | `benchmarks/external_http_active_active_results.json`, `benchmarks/http_cluster_load_results.json`, `deploy/serverless/observed-telemetry.remote.json` |
| `WAVEMIND_CLUSTER_NODES` | `missing` | `api-node-list` | `external_http_cluster` | `external-http-cluster-load.yml` | `benchmarks/http_cluster_load_results.json` |
| `WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | `missing` | `api-node-manifest-json` | `external_http_cluster` | `external-http-cluster-load.yml` | `benchmarks/http_cluster_load_results.json` |
| `WAVEMIND_FAISS_IVFPQ_FREE_GB` | `optional` | `disk-free-override-gb` |  |  |  |
| `WAVEMIND_FAISS_IVFPQ_PATH` | `missing` | `filesystem-path` | `faiss_ivfpq_50m` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_ivfpq_50m_results.json` |
| `WAVEMIND_PGVECTOR_DSNS` | `missing` | `postgres-dsn-list` | `pgvector_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_pgvector_10m_results.json` |
| `WAVEMIND_QDRANT_API_KEY` | `recommended` | `qdrant-api-secret` | `qdrant_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_10m_results.json` |
| `WAVEMIND_QDRANT_API_KEYS` | `recommended` | `qdrant-api-secret-list` | `hundred_million_remote_load`, `qdrant_sharded_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json`, `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` |
| `WAVEMIND_QDRANT_URL` | `missing` | `qdrant-url` | `qdrant_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_10m_results.json` |
| `WAVEMIND_QDRANT_URLS` | `missing` | `qdrant-url-list` | `hundred_million_remote_load`, `qdrant_sharded_10m_service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json`, `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` |
| `WAVEMIND_SERVERLESS_NODES` | `missing` | `serverless-api-node-list` | `serverless_remote_telemetry` | `serverless-observed-telemetry.yml` | `deploy/serverless/observed-telemetry.remote.json` |

## GitHub Secrets

Run these from a shell where each variable is already exported. The
commands pipe values from the environment; values are not echoed into
the repository.

- `printf '%s' "$WAVEMIND_ACTIVE_ACTIVE_REGIONS" | gh secret set WAVEMIND_ACTIVE_ACTIVE_REGIONS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON" | gh secret set WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_API_KEY" | gh secret set WAVEMIND_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLUSTER_NODES" | gh secret set WAVEMIND_CLUSTER_NODES --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_CLUSTER_NODES_MANIFEST_JSON" | gh secret set WAVEMIND_CLUSTER_NODES_MANIFEST_JSON --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_FAISS_IVFPQ_FREE_GB" | gh secret set WAVEMIND_FAISS_IVFPQ_FREE_GB --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_FAISS_IVFPQ_PATH" | gh secret set WAVEMIND_FAISS_IVFPQ_PATH --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_PGVECTOR_DSNS" | gh secret set WAVEMIND_PGVECTOR_DSNS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_API_KEY" | gh secret set WAVEMIND_QDRANT_API_KEY --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_API_KEYS" | gh secret set WAVEMIND_QDRANT_API_KEYS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_URL" | gh secret set WAVEMIND_QDRANT_URL --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_QDRANT_URLS" | gh secret set WAVEMIND_QDRANT_URLS --repo CaspianG/wavemind --body-file -`
- `printf '%s' "$WAVEMIND_SERVERLESS_NODES" | gh secret set WAVEMIND_SERVERLESS_NODES --repo CaspianG/wavemind --body-file -`

## Checks

| check | status | detail |
|---|---|---|
| all_preflight_env_represented | `pass` | 9/9 preflight env vars represented |
| all_dispatch_env_represented | `pass` | 12/12 dispatch env vars represented |
| all_scale_gap_env_represented | `pass` | 4/4 scale-gap env vars represented |
| no_missing_contract_rows | `pass` | none |
| strict_requirements_joined | `pass` | 8 strict requirements |
| secret_values_not_serialized | `pass` | contract uses placeholders and secret names only |
