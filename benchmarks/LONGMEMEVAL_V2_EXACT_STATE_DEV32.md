# LongMemEval-V2 Exact-State Development Gate

Status: `failed_experiment`

This was the final development-only hypothesis after the frozen full-451
hybrid experiment failed. It uses the original deterministic stratified
32-question development split with seed `20260728`. No question from the
untouched remaining 419 was used to select or tune this policy.

Source SHA: `81c8c2650115310f8b405442420f718696379207`

## Results

| Metric | Core | Memory OS | Gate |
|---|---:|---:|---|
| Task success | 0.1875 | 0.1875 | fail: uplift is 0.0000, required +0.0100 |
| Context tokens | 63,849 | 40,753 | pass: 36.17% saving, required 35% |
| Retrieval-path p95 | 119.09 ms | 121.20 ms | pass: +2.11 ms / +1.77% |
| Execution errors | 0 | 0 | pass |
| Worker errors | - | 0 | pass |

Only `procedure-abs` improved; `static-environment` regressed. The required
four improved categories were not reached.

## Verdict

The exact-state policy preserves the context and latency benefits but does not
prove Memory OS answer-quality uplift. It is therefore a failed development
experiment. No new full-451 run is permitted for this policy, and the frozen
419-question result remains untouched.
