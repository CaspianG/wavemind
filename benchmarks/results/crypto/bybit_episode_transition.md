# Market-Episode Transition Benchmark

This benchmark predicts bounce versus continuation after a cross-asset capitulation event. Evidence is counted at the globally aligned market-episode level.

- train: before 2024-01-01;
- model selection: 2024 only;
- final split: 2025-01-01 through 2026-07-27;
- event thresholds: frozen from the training period;

| horizon | train | validation | final | selected model | final accuracy | Wilson low | majority | uplift | admitted |
|---|---:|---:|---:|---|---:|---:|---:|---:|:---:|
| 24h | 127 | 59 | 84 | majority | 58.3% | 47.7% | 58.3% | 0.0% | no |
| 48h | 63 | 31 | 36 | extra_trees | 66.7% | 50.3% | 52.8% | 13.9% | no |

## 24h Model Audit

| model | validation accuracy | final accuracy | final Wilson | Brier |
|---|---:|---:|---:|---:|
| majority | 52.5% | 58.3% | 47.7% | 0.417 |
| logistic | 47.5% | 54.8% | 44.1% | 0.252 |
| extra_trees | 49.2% | 57.1% | 46.5% | 0.244 |
| knn | 45.8% | 64.3% | 53.6% | 0.230 |
| wavefield | 42.4% | 52.4% | 41.8% | 0.270 |
| field_tree_hybrid | 44.1% | 54.8% | 44.1% | 0.248 |

A 70% claim is admitted only when final support, Wilson, calendar-year stability, and uplift over the train-frozen majority baseline all pass.
