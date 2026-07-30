# LongMemEval-V2 Frozen Split Analysis

Status: `failed_experiment`

This report separates the 32-question development split from the untouched remaining 419 questions. The full result was evaluated only after the architecture and thresholds were frozen.

## Results

| Split | Core success | Memory OS success | Uplift | Improved categories |
|---|---:|---:|---:|---:|
| Full 451 | 0.1863 | 0.1818 | -0.0044 | 3 |
| Untouched 419 | 0.1885 | 0.1766 | -0.0119 | 3 |

Full-context saving: `41.00%`. Full p95 delta: `+1.591 ms`.

## Gates

| Gate | Status | Actual | Requirement |
|---|---|---|---|
| `full_protocol_complete` | `pass` | `{"full_questions":451,"rows":902,"development_questions":32,"untouched_questions":419}` | 451 full questions, 902 rows, official haystacks, isolated A/B stores, all images, dev32 and untouched419 |
| `zero_execution_errors` | `pass` | `{"row_errors":0,"aggregate_errors":0,"worker_errors":0}` | zero row, aggregate, and worker errors |
| `full_memory_os_quality` | `pass` | `0.18181818181818182` | >= 0.18 |
| `full_memory_os_uplift` | `fail` | `-0.00443458980044345` | >= Core + 0.01 absolute |
| `full_improved_categories` | `fail` | `3` | >= 4 |
| `full_context_saving` | `pass` | `0.4099552226942337` | >= 0.35 versus Core |
| `full_p95_latency_delta` | `pass` | `1.5909000067040324` | <= 5 ms |
| `full_p95_latency_ratio` | `pass` | `0.014834977375592178` | <= 20% |
| `untouched419_memory_os_uplift` | `fail` | `-0.011933174224343673` | >= Core + 0.01 absolute |

## Verdict

This is a failed frozen experiment, not admission evidence. It passes execution, context, and latency controls but does not prove Memory OS quality uplift. The held-out result must not be used to tune this architecture.
