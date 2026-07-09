# WaveMind Cost Efficiency Leaderboard

Generated: `2026-07-09T13:44:41Z`.

Measured rows come from checked-in load artifacts. Planned rows are capacity and cost contracts only; they do not unlock production latency or recall claims until the matching benchmark result exists.

## Summary

- Measured rows: `20`.
- Measured SLO pass rows: `9`.
- Measured valid cost rows: `11`.
- Planned cost rows: `5`.
- Measured frontier: `sub_100k-wavemind-numpy-streaming-production_streaming_load_smoke_results, 100k-qdrant-service-production_load_qdrant_100k_tuned_results, 1m-qdrant-service-streaming-production_streaming_load_qdrant_1m_tuned_results, 1m-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_1m_results, 100k-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_100k_results, 10m-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_10m_results`.
- Planned frontier: `qdrant-sharded-100m, faiss-ivfpq-50m`.

## Measured Cost Frontier

| rank | profile | target class | engine | memories | recall | p99 ms | SLO | cost / 1M queries | monthly cost | source |
|---:|---|---|---|---:|---:|---:|---|---:|---:|---|
| 1 | sub_100k-wavemind-numpy-streaming-production_streaming_load_smoke_results | sub_100k | WaveMind numpy-streaming | 10,000 | 1 | 0.459 | pass | $0.694 | $182.5 | `benchmarks/production_streaming_load_smoke_results.json` |
| 2 | sub_100k-wavemind-pgvector-streaming-production_streaming_load_pgvector_smoke_results | sub_100k | WaveMind pgvector streaming | 1,000 | 1 | 7.624 | pass | $0.694 | $182.5 | `benchmarks/production_streaming_load_pgvector_smoke_results.json` |
| 3 | sub_100k-qdrant-sharded-service-streaming-production_streaming_load_qdrant_sharded_smoke_results | sub_100k | Qdrant sharded service streaming | 5,000 | 1 | 16.02 | pass | $1.389 | $365 | `benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json` |
| 4 | sub_100k-qdrant-service-streaming-production_streaming_load_qdrant_smoke_results | sub_100k | Qdrant service streaming | 1,000 | 1 | 17.9 | pass | $1.389 | $365 | `benchmarks/production_streaming_load_qdrant_smoke_results.json` |
| 5 | 100k-qdrant-service-production_load_qdrant_100k_tuned_results | 100k | Qdrant service | 100,000 | 1 | 21.26 | pass | $1.389 | $365.02 | `benchmarks/production_load_qdrant_100k_tuned_results.json` |
| 6 | 1m-qdrant-service-streaming-production_streaming_load_qdrant_1m_tuned_results | 1m | Qdrant service streaming | 1,000,000 | 1 | 26.37 | pass | $2.083 | $547.74 | `benchmarks/production_streaming_load_qdrant_1m_tuned_results.json` |
| 7 | 100k-qdrant-service-production_load_results | 100k | Qdrant service | 100,000 | 1 | - | pass | $1.389 | $365.02 | `benchmarks/production_load_results.json` |
| 8 | 1m-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_1m_results | 1m | WaveMind faiss-ivfpq-persisted streaming | 1,000,000 | 0.99 | 4.992 | pass | $0.694 | $182.74 | `benchmarks/production_streaming_load_ivfpq_1m_results.json` |
| 9 | 100k-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_100k_results | 100k | WaveMind faiss-ivfpq-persisted streaming | 100,000 | 0.96 | 1.104 | pass | $0.694 | $182.52 | `benchmarks/production_streaming_load_ivfpq_100k_results.json` |
| 10 | 1m-wavemind-faiss-persisted-production_load_faiss_1m_results | 1m | WaveMind faiss-persisted | 1,000,000 | 1 | 57.71 | scale_required | $4.167 | $1,095.24 | `benchmarks/production_load_faiss_1m_results.json` |
| 11 | 10m-wavemind-faiss-ivfpq-persisted-streaming-production_streaming_load_ivfpq_10m_results | 10m | WaveMind faiss-ivfpq-persisted streaming | 10,000,000 | 0.99 | 60.13 | scale_required | $4.861 | $1,279.88 | `benchmarks/production_streaming_load_ivfpq_10m_results.json` |
| 12 | 1m-qdrant-service-streaming-production_streaming_load_qdrant_1m_results | 1m | Qdrant service streaming | 1,000,000 | 0.99 | 3,013.98 | fail | $16.67 | $4,380.24 | `benchmarks/production_streaming_load_qdrant_1m_results.json` |

## Planned Cost Frontier

| rank | profile | target class | engine | memories | recall | p99 ms | SLO | cost / 1M queries | monthly cost | source |
|---:|---|---|---|---:|---:|---:|---|---:|---:|---|
| 1 | qdrant-sharded-100m | 100m_plus | qdrant-sharded-service | 100,000,000 | 0.95 | 100 | scale_required | $5 | $6,593.84 | `benchmarks/production_scale_run_plan.json` |
| 2 | qdrant-sharded-10m | 10m | qdrant-sharded-service | 10,000,000 | 0.95 | 100 | scale_required | $5 | $3,287.38 | `benchmarks/production_scale_run_plan.json` |
| 3 | faiss-ivfpq-50m | 50m | faiss-ivfpq-persisted | 50,000,000 | 0.95 | 100 | scale_required | $5.556 | $1,471.92 | `benchmarks/production_scale_run_plan.json` |
| 4 | pgvector-10m | 10m | pgvector-service | 10,000,000 | 0.95 | 100 | scale_required | $5.556 | $1,462.38 | `benchmarks/production_scale_run_plan.json` |
| 5 | qdrant-10m | 10m | qdrant-service | 10,000,000 | 0.95 | 100 | scale_required | $5.556 | $1,462.38 | `benchmarks/production_scale_run_plan.json` |

## Reading Rules

- `measured` rows are allowed to support benchmark claims if their source artifact is current.
- planned rows are capacity/cost contracts only.
- `scale_required` means recall and p99 can be inside target, but more replicas are needed for the requested QPS.
- Cost estimates use checked-in benchmark assumptions for required replicas, hourly replica cost, target QPS, vector size, and payload size.
