# WaveMind Scale Gap Matrix

This report joins the large-N production run contracts with the strict
production evidence gate. It shows which 10M, 50M, and 100M scale claims
are proven, which are plan-only, and what must run next.

| metric | value |
|---|---:|
| overall status | `action_required` |
| complete profiles | `4/5` |
| ready to run | `0` |
| blocked by env | `1` |
| planned target memories | `180000000` |
| proven target memories | `80000000` |
| nearest baseline max memories | `10000000` |
| claim status | `claims_limited` |

| profile | status | target | nearest baseline | gap | artifact | missing env |
|---|---|---:|---:|---:|---|---|
| qdrant-10m | `complete` | 10000000 | 1000000 | 10.0 | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` |
| qdrant-sharded-10m | `complete` | 10000000 | 1000000 | 10.0 | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` |
| pgvector-10m | `complete` | 10000000 | 50000 | 200.0 | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSNS` |
| faiss-ivfpq-50m | `complete` | 50000000 | 10000000 | 5.0 | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` |
| qdrant-sharded-100m | `blocked_by_env` | 100000000 | 1000000 | 100.0 | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON, WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY` |

## Commands

- `qdrant-10m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines qdrant-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_qdrant_10m_results.json --checkpoint-path state/production-runs/qdrant-service-10000000.checkpoint.json`
- `qdrant-sharded-10m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 5000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 250.0 --replicas 4 --autoscaling-max-replicas 48 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_qdrant_sharded_10m_results.json --checkpoint-path state/production-runs/qdrant-sharded-service-10000000.checkpoint.json`
- `pgvector-10m`: `gh workflow run production-streaming-load.yml --ref main -f engine=pgvector-service -f size=10000000 -f dim=128 -f queries=2000 -f top_k=10 -f batch_size=5000 -f target_recall=0.95 -f target_p99_ms=100 -f target_qps=100 -f replicas=3 -f autoscaling_max_replicas=24 -f capacity_headroom=0.7 -f runner_label=ubuntu-latest -f provision_pgvector_shards=true -f pgvector_shard_count=4 -f pgvector_profile=ivfflat-fine-production -f runner_storage_root=state -f commit_results=true`
- `faiss-ivfpq-50m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 50000000 --dim 128 --queries 2000 --top-k 10 --seed 42 --noise 0.08 --batch-size 1000000 --engines faiss-ivfpq-persisted --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_ivfpq_50m_results.json --checkpoint-path state/production-runs/faiss-ivfpq-persisted-50000000.checkpoint.json`
- `qdrant-sharded-100m`: `gh workflow run remote-qdrant-100m-lab.yml --ref main -f action=evidence -f runner_label=self-hosted-large`
