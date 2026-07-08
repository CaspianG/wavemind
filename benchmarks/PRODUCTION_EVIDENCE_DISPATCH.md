# WaveMind Production Evidence Dispatch Plan

This report turns strict production-evidence gaps into concrete GitHub
Actions dispatch payloads. It does not unlock production claims by itself;
claims unlock only after the resulting artifacts pass the ingest gate and
strict production-evidence validation.

| metric | value |
|---|---:|
| overall status | `action_required` |
| ready to dispatch | `0` |
| blocked by preflight | `8` |
| complete | `0` |
| total jobs | `8` |
| runner label | `self-hosted-large` |
| commit results default | `False` |

## Jobs

| job | status | wave | workflow | artifact | missing env |
|---|---|---|---|---|---|
| External HTTP service-node load | `blocked_by_preflight` | `remote-service` | `external-http-cluster-load.yml` | `benchmarks/http_cluster_load_results.json` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` |
| External HTTP active-active regions | `blocked_by_preflight` | `remote-service` | `external-http-active-active.yml` | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_ACTIVE_ACTIVE_REGIONS, WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` |
| Managed/serverless remote telemetry | `blocked_by_preflight` | `remote-service` | `serverless-observed-telemetry.yml` | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_SERVERLESS_NODES` |
| 10M Qdrant service load | `blocked_by_preflight` | `service-scale-10m` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` |
| 10M sharded Qdrant service load | `blocked_by_preflight` | `service-scale-10m` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` |
| 10M pgvector service load | `blocked_by_preflight` | `service-scale-10m` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSN` |
| 50M FAISS IVF-PQ streaming load | `blocked_by_preflight` | `large-local-index` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` |
| 100M remote load result | `blocked_by_preflight` | `hundred-million-service` | `production-streaming-load.yml` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS` |

## Safe Launch Commands

- `external_http_cluster`: `gh workflow run external-http-cluster-load.yml -f nodes="$WAVEMIND_CLUSTER_NODES" -f nodes_manifest_json="$WAVEMIND_CLUSTER_NODES_MANIFEST_JSON" -f namespace_count="32" -f memories_per_namespace="8" -f workers="8" -f batch_query_size="24" -f replication_factor="3" -f read_quorum="1" -f read_fanout="1" -f p99_slo_ms="1000" -f commit_results="false"`
- `external_http_active_active`: `gh workflow run external-http-active-active.yml -f regions="$WAVEMIND_ACTIVE_ACTIVE_REGIONS" -f regions_manifest_json="$WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON" -f namespace_count="16" -f p99_slo_ms="1500" -f commit_results="false"`
- `serverless_remote_telemetry`: `gh workflow run serverless-observed-telemetry.yml -f nodes="$WAVEMIND_SERVERLESS_NODES" -f requests="240" -f workers="4" -f seed_memories="24" -f seed_mode="first" -f max_scale="256" -f target_rps="3200" -f target_p99_ms="500" -f external_cold_start_ms="900" -f estimated_scale_out_seconds="18" -f commit_results="false"`
- `qdrant_10m_service`: `gh workflow run production-streaming-load.yml -f engine="qdrant-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f qdrant_url="$WAVEMIND_QDRANT_URL"`
- `qdrant_sharded_10m_service`: `gh workflow run production-streaming-load.yml -f engine="qdrant-sharded-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="250.0" -f replicas="4" -f autoscaling_max_replicas="48" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f qdrant_urls="$WAVEMIND_QDRANT_URLS"`
- `pgvector_10m_service`: `gh workflow run production-streaming-load.yml -f engine="pgvector-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f pgvector_dsn="$WAVEMIND_PGVECTOR_DSN"`
- `faiss_ivfpq_50m`: `gh workflow run production-streaming-load.yml -f engine="faiss-ivfpq-persisted" -f size="50000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f faiss_ivfpq_path="$WAVEMIND_FAISS_IVFPQ_PATH"`
- `hundred_million_remote_load`: `gh workflow run production-streaming-load.yml -f engine="qdrant-sharded-service" -f size="100000000" -f dim="128" -f queries="5000" -f top_k="10" -f batch_size="10000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="500.0" -f replicas="8" -f autoscaling_max_replicas="128" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f qdrant_urls="$WAVEMIND_QDRANT_URLS"`

## Promotion

- Download: `gh run download <run-id> --repo CaspianG/wavemind --dir state/production-evidence-downloads`
- Ingest: `wavemind ingest-production-evidence --artifact-dir state/production-evidence-downloads --refresh`
- Boundary: Only artifacts that pass ingest-production-evidence and the strict production-evidence gate may unlock remote, 50M, or 100M claims.
