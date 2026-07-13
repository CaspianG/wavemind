# WaveMind Memory OS Quality Gate

Memory OS non-regression is measured directly on the agent-coherence workload. LoCoMo and LongMemEval rows prove the underlying WaveMind dynamic retrieval and answer-context quality; they do not claim that unattended Memory OS workers ran inside those public datasets.

Status: `pass`

| check | result | evidence | source |
|---|---|---|---|
| Memory OS preserves WaveMind agent task success | `pass` | memory_os=0.9167, base=0.9167, delta=0.0000 | `benchmarks\memory_os_agent_quality_results.json` |
| Memory OS does not increase stale-memory errors | `pass` | memory_os=0.0000, base=0.0000 | `benchmarks\memory_os_agent_quality_results.json` |
| Memory OS retains at least 80 percent context savings | `pass` | context_budget_saved=0.9309 | `benchmarks\memory_os_agent_quality_results.json` |
| Dynamic memory beats static memory on agent task success | `pass` | memory_os=0.9167, static=0.3333 | `benchmarks\memory_os_agent_quality_results.json` |
| WaveMind improves LoCoMo evidence recall over static retrieval | `pass` | wave=0.5467, static=0.4087, lift=0.1380 | `benchmarks\locomo_sentence_evidence_results.json` |
| WaveMind improves LongMemEval evidence recall over static retrieval | `pass` | wave=0.7822, static=0.5197, lift=0.2625 | `benchmarks\longmemeval_evidence_results.json` |
| WaveMind context improves LongMemEval answer F1 and evidence recall | `pass` | f1_lift=0.1632, evidence_lift=0.3200 | `benchmarks\longmemeval_answer_qwen25_1_5b_50_results.json` |
