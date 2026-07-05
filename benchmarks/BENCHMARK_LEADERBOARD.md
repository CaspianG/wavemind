# WaveMind Benchmark Leaderboard

Generated from `benchmarks/benchmark_matrix_results.json`.

This is a compact reader-facing view of checked-in benchmark results. It is not a universal vector-database leaderboard: each row uses the primary quality metric for that benchmark, and latency is shown separately so quality wins are not confused with speed wins.

| benchmark | category | primary metric | best WaveMind result | best baseline result | readout |
|---|---|---|---|---|---|
| Agent user-memory retrieval | agent-memory | precision@1 | WaveMind: 0.82 / 2.249 ms | Chroma: 0.82 / 0.933 ms | Quality tie; WaveMind slower |
| Dynamic memory policy | agent-memory | precision@1 | WaveMind: 1 / 25.3 ms | Chroma static: 0.571 / 1.752 ms | WaveMind leads on quality |
| Field memory graph dynamics | agent-memory | precision@1 | WaveMind graph: 1 / 1.807 ms | - | WaveMind-only check |
| WaveMind capacity curve | capacity | precision@1 | WaveMind dynamic capacity: 1 / 48.4 ms | - | WaveMind-only check |
| Long-term memory evidence | long-term-agent-memory | evidence recall@k | WaveMind: 1 / 6.103 ms | Static vector: 1 / 0.648 ms | Quality tie; WaveMind slower |
| BEIR-style open retrieval runner | retrieval | precision@1 | WaveMind: 0.24 / 117.0 ms | Chroma: 0.243 / 1.794 ms | Baseline leads on quality |
| [NoMIRACL Russian retrieval](https://huggingface.co/datasets/miracl/nomiracl) | multilingual-retrieval | precision@1 | WaveMind: 0.41 / 10.2 ms | Chroma: 0.41 / 2.603 ms | Quality tie; WaveMind slower |
| [LoCoMo evidence retrieval runner](https://github.com/snap-research/locomo) | long-term-conversation-memory | evidence recall@k | WaveMind sentence: 0.547 / 3.438 ms | Qdrant sentence: 0.409 / 124.3 ms | WaveMind leads on quality |
| [LongMemEval evidence retrieval](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | evidence recall@k | WaveMind: 0.782 / 7.274 ms | Static vector: 0.52 / 0.083 ms | WaveMind leads on quality |
| [LongMemEval evidence 50-query smoke](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | evidence recall@k | WaveMind: 0.92 / 15.3 ms | Static vector: 0.6 / 0.337 ms | WaveMind leads on quality |
| [ANN index latency curve](https://github.com/erikbern/ann-benchmarks) | index-latency | Recall@k | WaveMind numpy: 1 / 6.485 ms | Qdrant local: 1 / 43.5 ms | Quality tie; WaveMind faster |
| Production index profile | index-latency | Recall@k | WaveMind faiss-persisted: 1 / 3.524 ms | Qdrant service: 1 / 4.414 ms | Quality tie; WaveMind faster |
| Scale readiness profile | production-scale | precision@1 | WaveMind structured payloads: 1 / 0.791 ms | - | WaveMind-only check |
| [LongMemEval answer generation](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | token F1 | WaveMind + qwen2.5:1.5b: 0.333 / - | Chroma static + qwen2.5:1.5b: 0.17 / - | WaveMind leads on quality |

## Reading Rules

- `WaveMind leads on quality` means the best checked-in WaveMind row beats the best checked-in non-WaveMind baseline on that benchmark's primary quality metric.
- `Quality tie; WaveMind slower` is still a real limitation. It means retrieval quality matched the baseline, but the current memory layer adds latency.
- `WaveMind-only check` is a regression or capacity check, not a competitor claim.
- Planned public benchmarks stay in `benchmarks/BENCHMARK_REPORT.md` until a real result JSON is checked in.
