# WaveMind Agent Impact Leaderboard

Generated: `2026-07-10T06:49:30Z`.

Agent-impact rows come from checked-in benchmark artifacts. They show behavioral lift on the configured tasks; they do not claim general agent success outside the listed scenarios.

## Summary

- Benchmarks covered: `6`.
- WaveMind rows: `7`.
- Baseline rows: `12`.
- WaveMind primary wins: `6`.
- Average primary lift: `0.37`.
- Average context saved: `0.719`.
- Average stale-safety score: `1`.
- Best impact profile: `agent-coherence-and-token-savings-wavemind`.

## WaveMind Impact Ranking

| rank | benchmark | engine | primary metric | value | best baseline | lift | stale safety | context saved | avg latency | source |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Agent coherence and token savings | WaveMind | task success | 0.917 | 0.333 | 0.583 | 1 | 0.931 | 2.647 | `benchmarks/agent_coherence_results.json` |
| 2 | Agent coherence and token savings | WaveMind + Memory OS | task success | 0.917 | 0.333 | 0.583 | 1 | 0.931 | 3.299 | `benchmarks/agent_coherence_results.json` |
| 3 | Long-term memory evidence | WaveMind | precision@1 | 1 | 0.571 | 0.429 | 1 | 0.866 | 6.103 | `benchmarks/long_memory_evidence_results.json` |
| 4 | Dynamic memory policy | WaveMind | precision@1 | 1 | 0.571 | 0.429 | 1 | - | 3.918 | `benchmarks/dynamic_memory_results.json` |
| 5 | LongMemEval evidence retrieval | WaveMind | evidence recall@k | 0.782 | 0.52 | 0.263 | 1 | 0.869 | 7.274 | `benchmarks/longmemeval_evidence_results.json` |
| 6 | LongMemEval answer quality | WaveMind | token F1 | 0.333 | 0.17 | 0.163 | - | - | 36.59 | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |
| 7 | LoCoMo sentence evidence retrieval | WaveMind | evidence recall@k | 0.547 | 0.409 | 0.138 | 1 | 0 | 3.438 | `benchmarks/locomo_sentence_evidence_results.json` |

## Benchmark Groups

| benchmark | category | best WaveMind | best baseline | primary lift | source |
|---|---|---:|---:|---:|---|
| Agent coherence and token savings | agent_behavior | 0.917 | 0.333 | 0.583 | `benchmarks/agent_coherence_results.json` |
| Dynamic memory policy | memory_policy | 1 | 0.571 | 0.429 | `benchmarks/dynamic_memory_results.json` |
| Long-term memory evidence | memory_policy | 1 | 0.571 | 0.429 | `benchmarks/long_memory_evidence_results.json` |
| LoCoMo sentence evidence retrieval | long_memory_retrieval | 0.547 | 0.409 | 0.138 | `benchmarks/locomo_sentence_evidence_results.json` |
| LongMemEval evidence retrieval | long_memory_retrieval | 0.782 | 0.52 | 0.263 | `benchmarks/longmemeval_evidence_results.json` |
| LongMemEval answer quality | answer_quality | 0.333 | 0.17 | 0.163 | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |

## Reading Rules

- Primary lift compares the best WaveMind variant with the best non-WaveMind baseline inside the same artifact.
- Stale safety is `1 - stale_error_rate` when the benchmark reports stale errors, otherwise `stale_suppression` or `suppression_rate`.
- Context saved measures prompt/context reduction where the artifact reports `context_budget_saved`.
- Answer-quality rows use the checked-in local Ollama LongMemEval smoke artifact, not a full independent LLM benchmark.
