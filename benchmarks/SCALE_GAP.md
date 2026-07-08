# WaveMind Scale Gap Matrix

This report joins the large-N production run contracts with the strict
production evidence gate. It shows which 10M, 50M, and 100M scale claims
are proven, which are plan-only, and what must run next.

| metric | value |
|---|---:|
| overall status | `action_required` |
| complete profiles | `0/5` |
| ready to run | `0` |
| blocked by env | `5` |
| planned target memories | `180000000` |
| proven target memories | `0` |
| nearest baseline max memories | `10000000` |
| claim status | `claims_limited` |

| profile | status | target | nearest baseline | gap | artifact | missing env |
|---|---|---:|---:|---:|---|---|
| qdrant-10m | `blocked_by_env` | 10000000 | 1000000 | 10.0 | `benchmarks/production_streaming_load_qdrant_10m_results.json` | `WAVEMIND_QDRANT_URL` |
| qdrant-sharded-10m | `blocked_by_env` | 10000000 | 1000000 | 10.0 | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` | `WAVEMIND_QDRANT_URLS` |
| pgvector-10m | `blocked_by_env` | 10000000 | 50000 | 200.0 | `benchmarks/production_streaming_load_pgvector_10m_results.json` | `WAVEMIND_PGVECTOR_DSN` |
| faiss-ivfpq-50m | `blocked_by_env` | 50000000 | 10000000 | 5.0 | `benchmarks/production_streaming_load_ivfpq_50m_results.json` | `WAVEMIND_FAISS_IVFPQ_PATH` |
| qdrant-sharded-100m | `blocked_by_env` | 100000000 | 1000000 | 100.0 | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | `WAVEMIND_QDRANT_URLS` |

## Commands

- `qdrant-10m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 100 --top-k 10 --seed 42 --noise 0.08 --batch-size 100000 --engines qdrant-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_qdrant_10m_results.json --checkpoint-path state/qdrant-service-10000000.checkpoint.json`
- `qdrant-sharded-10m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 100 --top-k 10 --seed 42 --noise 0.08 --batch-size 100000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_qdrant_sharded_10m_results.json --checkpoint-path state/qdrant-sharded-service-10000000.checkpoint.json`
- `pgvector-10m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --dim 128 --queries 100 --top-k 10 --seed 42 --noise 0.08 --batch-size 100000 --engines pgvector-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_pgvector_10m_results.json --checkpoint-path state/pgvector-service-10000000.checkpoint.json`
- `faiss-ivfpq-50m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 50000000 --dim 128 --queries 100 --top-k 10 --seed 42 --noise 0.08 --batch-size 100000 --engines faiss-ivfpq-persisted --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_ivfpq_50m_results.json --checkpoint-path state/faiss-ivfpq-persisted-50000000.checkpoint.json`
- `qdrant-sharded-100m`: `python benchmarks/production_streaming_load_benchmark.py --sizes 100000000 --dim 128 --queries 100 --top-k 10 --seed 42 --noise 0.08 --batch-size 100000 --engines qdrant-sharded-service --target-recall 0.95 --target-p99-ms 100.0 --target-qps 100.0 --replicas 3 --autoscaling-max-replicas 24 --capacity-headroom 0.7 --output benchmarks\production_streaming_load_qdrant_sharded_100m_results.json --checkpoint-path state/qdrant-sharded-service-100000000.checkpoint.json`
