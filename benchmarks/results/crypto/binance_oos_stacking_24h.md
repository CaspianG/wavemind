# Out-of-Sample Crypto Stacking Benchmark

Meta-model training folds [0, 1, 2]; model and confidence threshold selection on fold 3; one final evaluation on fold 4.

## Final Test

| engine | signals | coverage | accuracy | Wilson low | worst symbol |
|---|---:|---:|---:|---:|---:|
| logistic_stacker full coverage | 1432 | 100.0% | 50.9% | 48.3% | 46.4% |
| logistic_stacker selective | 1432 | 100.0% | 50.9% | 48.3% | 46.4% |
| Single expert (6d mean-reversion direction) | 1432 | 100.0% | 51.5% | 48.9% | 48.6% |
| Majority vote | 1432 | 100.0% | 49.4% | 46.8% | 45.3% |

- selected confidence threshold: `0.000`;
- strict 70% admission: **rejected**;
- model and threshold were selected before the final test.

## Validation Candidates

| model | full accuracy | full Wilson low | best selective accuracy | selective signals |
|---|---:|---:|---:|---:|
| logistic_stacker | 51.8% | 49.0% | 51.8% | 1240 |
| histogram_stacker | 48.1% | 45.3% | 48.1% | 1240 |
| extra_trees_stacker | 47.6% | 44.8% | 47.6% | 1240 |
| lightgbm_stacker | 48.3% | 45.5% | 48.3% | 1240 |
