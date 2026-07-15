# WaveMind Memory OS Quality Gate

Only the direct WaveMind baseline versus WaveMind plus Memory OS A/B controls this gate. LoCoMo and LongMemEval are supplemental because their current runners do not execute Memory OS policies.

Status: `pass`

| check | result | evidence | source |
|---|---|---|---|
| Baseline and Memory OS execute the same sequential adaptive protocol | `pass` | protocol_hash=b0236119a09e2b4b538bbdb4073371dfd8a399b9668421de0cf14654bc3ea39f, workload=sequential_adaptive_recall | `benchmarks/memory_os_ab_results.json` |
| Memory OS improves task success over WaveMind baseline | `pass` | memory_os=1.0000, baseline=0.8750, uplift=0.1250 | `benchmarks/memory_os_ab_results.json` |
| Memory OS reduces stale recalls over WaveMind baseline | `pass` | memory_os=0.0000, baseline=0.1250, uplift=0.1250 | `benchmarks/memory_os_ab_results.json` |
| Priority learning and adaptive forgetting both changed state | `pass` | priority_predictions=8, forgetting_demotions=8 | `benchmarks/memory_os_ab_results.json` |
| Both variants return the same context shape | `pass` | memory_os=1, baseline=1 | `benchmarks/memory_os_ab_results.json` |
| Memory OS p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=0.0287ms, baseline=11.8395ms, delta=-11.8108ms, ratio=-0.9976 | `benchmarks/memory_os_ab_results.json` |
| Cold p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=6.9555ms, baseline=8.4252ms, delta=-1.4697ms, ratio=-0.1744 | `benchmarks/memory_os_ab_results.json` |

## Supplemental public benchmarks

- `benchmarks/locomo_sentence_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json`: WaveMind answer context without Memory OS worker execution; not eligible for Memory OS uplift.
