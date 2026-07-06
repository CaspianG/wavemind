# WaveMind Benchmark Leaderboard

Generated from `benchmarks/benchmark_matrix_results.json`.
Last refresh: `2026-07-06T22:53:40Z` from `d0e1970d2e22`.

This is a compact reader-facing view of checked-in benchmark results. It is not a universal vector-database leaderboard: each row uses the primary quality metric for that benchmark, and latency is shown separately so quality wins are not confused with speed wins.

| benchmark | category | primary metric | best WaveMind result | best baseline result | readout |
|---|---|---|---|---|---|
| Agent user-memory retrieval | agent-memory | precision@1 | WaveMind: 0.82 / 2.249 ms | Chroma: 0.82 / 0.933 ms | Quality tie; WaveMind slower |
| Agent coherence and token savings | agent-memory | task success | WaveMind: 0.917 / 2.984 ms | Chroma static: 0.417 / 3.637 ms | WaveMind leads on quality |
| Dynamic memory policy | agent-memory | precision@1 | WaveMind: 1 / 3.918 ms | Chroma static: 0.571 / 1.662 ms | WaveMind leads on quality |
| Field memory graph dynamics | agent-memory | precision@1 | WaveMind graph: 1 / 0.332 ms | - | WaveMind-only check |
| WaveMind capacity curve | capacity | precision@1 | WaveMind dynamic capacity: 1 / 48.4 ms | - | WaveMind-only check |
| Long-term memory evidence | long-term-agent-memory | evidence recall@k | WaveMind: 1 / 6.103 ms | Static vector: 1 / 0.648 ms | Quality tie; WaveMind slower |
| BEIR-style open retrieval runner | retrieval | precision@1 | WaveMind: 0.24 / 117.0 ms | Chroma: 0.243 / 1.794 ms | Baseline leads on quality |
| [NoMIRACL Russian retrieval](https://huggingface.co/datasets/miracl/nomiracl) | multilingual-retrieval | precision@1 | WaveMind: 0.41 / 10.2 ms | Chroma: 0.41 / 2.603 ms | Quality tie; WaveMind slower |
| [LoCoMo evidence retrieval runner](https://github.com/snap-research/locomo) | long-term-conversation-memory | evidence recall@k | WaveMind sentence: 0.547 / 3.438 ms | Qdrant sentence: 0.409 / 124.3 ms | WaveMind leads on quality |
| [LongMemEval evidence retrieval](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | evidence recall@k | WaveMind: 0.782 / 7.274 ms | Static vector: 0.52 / 0.083 ms | WaveMind leads on quality |
| [LongMemEval evidence 50-query smoke](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | evidence recall@k | WaveMind: 0.92 / 15.3 ms | Static vector: 0.6 / 0.337 ms | WaveMind leads on quality |
| [ANN index latency curve](https://github.com/erikbern/ann-benchmarks) | index-latency | Recall@k | WaveMind numpy: 1 / 6.485 ms | Qdrant local: 1 / 43.5 ms | Quality tie; WaveMind faster |
| Production index profile | index-latency | Recall@k | WaveMind faiss-persisted: 1 / 3.524 ms | Qdrant service: 1 / 4.414 ms | Quality tie; WaveMind faster |
| Production load profile 100k | production-scale | Recall@k | WaveMind pgvector: 0.736 / 17.8 ms | Qdrant service: 1 / 10.3 ms | Baseline leads on quality; production SLO pass: Qdrant service; cost: Qdrant service $1.39/1M queries |
| Production load profile 1M | production-scale | Recall@k | WaveMind faiss-persisted: 1 / 39.1 ms | Qdrant service: 0.984 / 82.6 ms | WaveMind leads on quality; production SLO needs scale: WaveMind faiss-persisted; cost: WaveMind faiss-persisted $4.17/1M queries |
| Qdrant 1M HNSW ef sweep | production-scale | Recall@k | - | hnsw_ef=2048: 0.977 / 64.8 ms | No WaveMind result; production SLO miss; cost if SLO fixed: hnsw_ef=512 $4.86/1M queries |
| Production streaming load runner | production-scale | Recall@k | 10k smoke / WaveMind numpy-streaming: 1 / 0.098 ms | - | WaveMind-only check; production SLO pass: 10k smoke / WaveMind numpy-streaming; cost: 10k smoke / WaveMind numpy-streaming $0.69/1M queries |
| Scale readiness profile | production-scale | precision@1 | WaveMind structured payloads: 1 / 1.21 ms | - | WaveMind-only check |
| Production readiness gate | production-scale | readiness score | WaveMind production readiness: 1 / - | - | WaveMind-only check |
| Memory competitor adapter profile | agent-memory | precision@1 | WaveMind: 0.8 / 3.088 ms | GraphRAG static graph: 1 / 0.013 ms | Baseline leads on quality |
| [LongMemEval answer generation](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | token F1 | WaveMind + qwen2.5:1.5b: 0.333 / - | Chroma static + qwen2.5:1.5b: 0.17 / - | WaveMind leads on quality |

## Reading Rules

- `WaveMind leads on quality` means the best checked-in WaveMind row beats the best checked-in non-WaveMind baseline on that benchmark's primary quality metric.
- `Quality tie; WaveMind slower` is still a real limitation. It means retrieval quality matched the baseline, but the current memory layer adds latency.
- `production SLO pass/miss` uses the checked-in SLO gate: recall target, p99 target, requested QPS, current replicas, autoscaling max replicas, and capacity headroom.
- `cost` uses the checked-in benchmark cost model: required replicas, target QPS, replica hourly cost, vector size, and estimated payload storage.
- `WaveMind-only check` is a regression or capacity check, not a competitor claim.
- Planned public benchmarks stay in `benchmarks/BENCHMARK_REPORT.md` until a real result JSON is checked in.
