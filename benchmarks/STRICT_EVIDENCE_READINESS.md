# WaveMind Strict Evidence Readiness

This report joins the strict evidence gate, environment preflight, GitHub
Actions dispatch plan, large-N scale plan, scale-gap report, release
claim contract, and leaderboard freshness gate. It is a runbook, not
production evidence by itself.

| metric | value |
|---|---:|
| report status | `pass` |
| readiness status | `action_required` |
| claim status | `claims_limited` |
| total requirements | `8` |
| action required | `3` |
| ready for safe dispatch | `0` |
| can auto-run now | `0` |
| planned target memories | `180000000` |

## Integrity Checks

| check | status | detail |
|---|---|---|
| all_strict_requirements_represented | `pass` | 8/8 strict requirements represented |
| every_action_required_has_safe_dispatch | `pass` | all action-required rows have workflow dispatch commands |
| every_action_required_has_promotion | `pass` | all action-required rows have download and ingest commands |
| every_action_required_has_validation | `pass` | all action-required rows have strict validation and refresh commands |
| plan_only_rows_do_not_unlock_claims | `pass` | claim_status=claims_limited; plan_only_boundaries_ok=True |
| scale_plan_target_memories_covered | `pass` | target_memories_total=180000000 |
| source_freshness_gate_passes | `pass` | leaderboard freshness status=pass |
| secret_values_not_serialized | `pass` | payload contains placeholders and secret names only |

## Requirement Runbook

| requirement | blocker | dispatch | target | artifact | missing env | locked claim |
|---|---|---|---:|---|---|---|
| Non-loopback Kubernetes or external HTTP service-node load | `complete` | `complete` |  | `benchmarks/http_cluster_load_results.json` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | Non-loopback Kubernetes service-node cluster load SLO. |
| External HTTP active-active regions with physical failure recovery | `missing_env` | `blocked_by_preflight` |  | `benchmarks/external_http_active_active_results.json` | `WAVEMIND_REMOTE_LAB_INVENTORY_JSON, WAVEMIND_REMOTE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_API_KEY, WAVEMIND_REMOTE_POSTGRES_PASSWORD` | Remote multi-region active-active convergence |
| Managed/serverless remote telemetry | `missing_env` | `blocked_by_preflight` |  | `deploy/serverless/observed-telemetry.remote.json` | `WAVEMIND_CLOUD_RUN_PROJECT_ID, WAVEMIND_CLOUD_RUN_REGION, WAVEMIND_CLOUD_RUN_SERVICE, WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER, WAVEMIND_GCP_SERVICE_ACCOUNT, WAVEMIND_API_KEY` | Hosted/serverless p99, cold-start, error-rate, and scale-out SLO. |
| 10M Qdrant service load | `complete` | `complete` | 10000000 | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` | 10M-100M service-backed production scale |
| 10M sharded Qdrant service load | `complete` | `complete` | 10000000 | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` | 10M-100M service-backed production scale |
| 10M pgvector service load | `complete` | `complete` | 10000000 | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `` | 10M-100M service-backed production scale |
| 50M FAISS IVF-PQ streaming load | `complete` | `complete` | 50000000 | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` | 10M-100M service-backed production scale |
| 100M remote load result with eight-host attestation | `missing_env` | `blocked_by_preflight` | 100000000 | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON, WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY` | 10M-100M service-backed production scale |

## Safe Dispatch Commands

- `external_http_cluster`: `gh workflow run external-http-cluster-load.yml -f nodes="$WAVEMIND_CLUSTER_NODES" -f nodes_manifest_json="$WAVEMIND_CLUSTER_NODES_MANIFEST_JSON" -f namespace_count="32" -f memories_per_namespace="8" -f workers="8" -f batch_query_size="24" -f replication_factor="3" -f read_quorum="1" -f read_fanout="1" -f p99_slo_ms="1000" -f commit_results="false"`
- `external_http_active_active`: `gh workflow run remote-production-lab.yml -f action="evidence" -f namespace_count="16"`
- `serverless_remote_telemetry`: `gh workflow run managed-serverless-cloud-run.yml -f project_id="$WAVEMIND_CLOUD_RUN_PROJECT_ID" -f region="$WAVEMIND_CLOUD_RUN_REGION" -f service_name="$WAVEMIND_CLOUD_RUN_SERVICE" -f idle_wait_seconds="900" -f requests="2000" -f workers="64" -f target_rps="3200" -f target_p99_ms="500"`
- `qdrant_10m_service`: `gh workflow run production-streaming-load.yml -f engine="qdrant-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f qdrant_url="$WAVEMIND_QDRANT_URL"`
- `qdrant_sharded_10m_service`: `gh workflow run production-streaming-load.yml -f engine="qdrant-sharded-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="250.0" -f replicas="4" -f autoscaling_max_replicas="48" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f qdrant_urls="$WAVEMIND_QDRANT_URLS"`
- `pgvector_10m_service`: `gh workflow run production-streaming-load.yml -f engine="pgvector-service" -f size="10000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="5000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="ubuntu-latest" -f runner_storage_root="state/production-runs" -f commit_results="false" -f provision_pgvector_shards="true" -f pgvector_shard_count="4" -f pgvector_profile="ivfflat-fine-production"`
- `faiss_ivfpq_50m`: `gh workflow run production-streaming-load.yml -f engine="faiss-ivfpq-persisted" -f size="50000000" -f dim="128" -f queries="2000" -f top_k="10" -f batch_size="1000000" -f target_recall="0.95" -f target_p99_ms="100.0" -f target_qps="100.0" -f replicas="3" -f autoscaling_max_replicas="24" -f capacity_headroom="0.7" -f runner_label="self-hosted-large" -f runner_storage_root="state/production-runs" -f commit_results="false" -f faiss_ivfpq_path="$WAVEMIND_FAISS_IVFPQ_PATH"`
- `hundred_million_remote_load`: `gh workflow run remote-qdrant-100m-lab.yml -f action="evidence" -f runner_label="self-hosted-large" -f resume_run_id=""`

## Promote And Validate

- Download: `gh run download <run-id> --repo CaspianG/wavemind --dir state/production-evidence-downloads`
- Ingest: `wavemind ingest-production-evidence --artifact-dir state/production-evidence-downloads --refresh`
- Strict validation: `python benchmarks/production_evidence_gate.py --output benchmarks/production_evidence_results.json --markdown-output benchmarks/PRODUCTION_EVIDENCE.md --strict`
- Refresh readiness: `python benchmarks/strict_evidence_readiness_report.py --output benchmarks/strict_evidence_readiness_results.json --markdown-output benchmarks/STRICT_EVIDENCE_READINESS.md`

Boundary: Readiness report only. It does not itself unlock any production claim; only a matching strict evidence artifact that passes validation does.
