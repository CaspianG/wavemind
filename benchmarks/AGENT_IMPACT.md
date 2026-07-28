# WaveMind Agent Impact Leaderboard

Generated: `2026-07-28T17:57:37Z`.

Agent-impact rows come from checked-in benchmark artifacts. They show behavioral lift on the configured tasks; they do not claim general agent success outside the listed scenarios.

## Summary

- Benchmarks covered: `8`.
- WaveMind rows: `11`.
- Baseline rows: `18`.
- WaveMind primary wins: `8`.
- Average primary lift: `0.412`.
- Average context saved: `0.657`.
- Average stale-safety score: `0.924`.
- Best impact profile: `experienced-work-agent-wavemind-experience`.

## WaveMind Impact Ranking

| rank | benchmark | engine | primary metric | value | best baseline | lift | stale safety | context saved | avg latency | source |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Experienced Work Agent | WaveMind Experience | task success | 1 | 0 | 1 | - | - | - | `benchmarks/experienced_work_agent_results.json` |
| 2 | Adaptive agent-memory advantage | WaveMind + Memory OS | task success | 1 | 0.222 | 0.778 | 1 | 0.502 | - | `benchmarks/agent_memory_advantage_results.json` |
| 3 | Agent coherence and token savings | WaveMind | task success | 0.917 | 0.417 | 0.5 | 1 | 0.931 | 1.43 | `benchmarks/agent_coherence_results.json` |
| 4 | Agent coherence and token savings | WaveMind + Memory OS | task success | 0.917 | 0.417 | 0.5 | 1 | 0.931 | 1.637 | `benchmarks/agent_coherence_results.json` |
| 5 | Long-term memory evidence | WaveMind | precision@1 | 1 | 0.571 | 0.429 | 1 | 0.866 | 6.103 | `benchmarks/long_memory_evidence_results.json` |
| 6 | Dynamic memory policy | WaveMind | precision@1 | 1 | 0.571 | 0.429 | 1 | - | 3.918 | `benchmarks/dynamic_memory_results.json` |
| 7 | LongMemEval evidence retrieval | WaveMind | evidence recall@k | 0.782 | 0.52 | 0.263 | 1 | 0.869 | 7.274 | `benchmarks/longmemeval_evidence_results.json` |
| 8 | Adaptive agent-memory advantage | WaveMind Core | task success | 0.389 | 0.222 | 0.167 | 0.389 | 0.502 | - | `benchmarks/agent_memory_advantage_results.json` |
| 9 | Experienced Work Agent | WaveMind Core | task success | 0.167 | 0 | 0.167 | - | - | - | `benchmarks/experienced_work_agent_results.json` |
| 10 | LongMemEval answer quality | WaveMind | token F1 | 0.333 | 0.17 | 0.163 | - | - | 36.59 | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |
| 11 | LoCoMo sentence evidence retrieval | WaveMind | evidence recall@k | 0.547 | 0.409 | 0.138 | 1 | 0 | 3.438 | `benchmarks/locomo_sentence_evidence_results.json` |

## Benchmark Groups

| benchmark | category | best WaveMind | best baseline | primary lift | source |
|---|---|---:|---:|---:|---|
| Adaptive agent-memory advantage | agent_behavior | 1 | 0.222 | 0.778 | `benchmarks/agent_memory_advantage_results.json` |
| Agent coherence and token savings | agent_behavior | 0.917 | 0.417 | 0.5 | `benchmarks/agent_coherence_results.json` |
| Experienced Work Agent | agent_experience | 1 | 0 | 1 | `benchmarks/experienced_work_agent_results.json` |
| Dynamic memory policy | memory_policy | 1 | 0.571 | 0.429 | `benchmarks/dynamic_memory_results.json` |
| Long-term memory evidence | memory_policy | 1 | 0.571 | 0.429 | `benchmarks/long_memory_evidence_results.json` |
| LoCoMo sentence evidence retrieval | long_memory_retrieval | 0.547 | 0.409 | 0.138 | `benchmarks/locomo_sentence_evidence_results.json` |
| LongMemEval evidence retrieval | long_memory_retrieval | 0.782 | 0.52 | 0.263 | `benchmarks/longmemeval_evidence_results.json` |
| LongMemEval answer quality | answer_quality | 0.333 | 0.17 | 0.163 | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |

## Reading Rules

- Primary lift compares the best WaveMind variant with the best non-WaveMind baseline inside the same artifact.
- Stale safety is `1 - stale_error_rate` when the benchmark reports stale errors, otherwise `stale_suppression` or `suppression_rate`.
- Context saved measures prompt/context reduction where the artifact reports `context_budget_saved`.
- The adaptive advantage row uses seven identical-protocol trials and a 95% paired bootstrap interval; unavailable external competitors remain explicitly skipped.
- The legacy LongMemEval answer-quality row is a 50-query local Ollama smoke. Full LongMemEval-V2 Small evidence is tracked separately in the admission artifact.
