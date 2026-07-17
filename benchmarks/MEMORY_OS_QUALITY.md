# WaveMind Memory OS Quality Gate

Only the direct WaveMind baseline versus WaveMind plus Memory OS A/B controls this gate. LoCoMo and LongMemEval are supplemental because their current runners do not execute Memory OS policies.

Status: `pass`

| check | result | evidence | source |
|---|---|---|---|
| Baseline and Memory OS execute the same sequential adaptive protocol | `pass` | protocol_hash=3e0cb4781fa976ecb0d4c742ca6e32b5cdb66964a2c9c1f573236329b9d9411c, workload=sequential_adaptive_recall | `benchmarks/memory_os_ab_results.json` |
| Memory OS improves task success over WaveMind baseline | `pass` | memory_os=1.0000, baseline=0.8750, uplift=0.1250 | `benchmarks/memory_os_ab_results.json` |
| Memory OS reduces stale recalls over WaveMind baseline | `pass` | memory_os=0.0000, baseline=0.1250, uplift=0.1250 | `benchmarks/memory_os_ab_results.json` |
| Priority learning and adaptive forgetting both changed state | `pass` | priority_predictions=8, forgetting_demotions=8 | `benchmarks/memory_os_ab_results.json` |
| Both variants return the same context shape | `pass` | memory_os=1, baseline=1 | `benchmarks/memory_os_ab_results.json` |
| Memory OS p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=3.3693ms, baseline=4.7348ms, delta=-1.3655ms, ratio=-0.2884 | `benchmarks/memory_os_ab_results.json` |
| Cold p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=3.9077ms, baseline=3.9394ms, delta=-0.0317ms, ratio=-0.0080 | `benchmarks/memory_os_ab_results.json` |

## Supplemental public benchmarks

- `benchmarks/locomo_sentence_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json`: WaveMind answer context without Memory OS worker execution; not eligible for Memory OS uplift.
