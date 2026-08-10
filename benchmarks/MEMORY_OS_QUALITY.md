# WaveMind Memory OS Quality Gate

Only the direct WaveMind baseline versus WaveMind plus Memory OS A/B controls this gate. LoCoMo and LongMemEval are supplemental because their current runners do not execute Memory OS policies.

Status: `pass`

| check | result | evidence | source |
|---|---|---|---|
| Baseline and Memory OS execute the same sequential adaptive protocol | `pass` | protocol_hash=e9604ec394c706aa734f1699740b5351a0ffd0ee5ab7782c2fda6f4768835572, workload=sequential_adaptive_recall | `benchmarks/memory_os_ab_results.json` |
| Memory OS improves task success over WaveMind baseline | `pass` | memory_os=1.0000, baseline=0.3889, uplift=0.6111 | `benchmarks/memory_os_ab_results.json` |
| Memory OS reduces stale recalls over WaveMind baseline | `pass` | memory_os=0.0000, baseline=0.6111, uplift=0.6111 | `benchmarks/memory_os_ab_results.json` |
| Priority learning and adaptive forgetting both changed state | `pass` | priority_predictions=90, forgetting_demotions=90 | `benchmarks/memory_os_ab_results.json` |
| Both variants return the same context shape | `pass` | memory_os=1, baseline=1 | `benchmarks/memory_os_ab_results.json` |
| Memory OS p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=4.7283ms, baseline=5.2480ms, delta=-0.5197ms, ratio=-0.0990 | `benchmarks/memory_os_ab_results.json` |
| Cold p95 stays within both the 20 percent and 5 ms regression limits | `pass` | memory_os=4.9421ms, baseline=5.2668ms, delta=-0.3247ms, ratio=-0.0617 | `benchmarks/memory_os_ab_results.json` |

## Supplemental public benchmarks

- `benchmarks/locomo_sentence_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_evidence_results.json`: WaveMind retrieval without Memory OS worker execution; not eligible for Memory OS uplift.
- `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json`: WaveMind answer context without Memory OS worker execution; not eligible for Memory OS uplift.
