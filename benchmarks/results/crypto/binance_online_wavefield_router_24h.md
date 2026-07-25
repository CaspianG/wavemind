# Causal Online WaveField Router

All base predictions are out-of-sample. Router state is updated only after target_end_utc. Configuration is selected on fold 3; fold 4 is the final test.

## Final Test

| engine | signals | accuracy | Wilson low | worst symbol |
|---|---:|---:|---:|---:|
| WaveField router (statistical_slow) | 1432 | 51.5% | 48.9% | 47.5% |
| Single expert (6d mean-reversion direction) | 1432 | 51.5% | 48.9% | 48.6% |
| Majority vote | 1432 | 49.4% | 46.8% | 45.3% |

- strict 70% admission: **rejected**;
- selected only on validation: `statistical_slow`;
- test labels never choose the router configuration.

## Validation Selection

| candidate | field weight | validation signals | validation accuracy | Wilson low |
|---|---:|---:|---:|---:|
| statistical_fast | 0.00 | 1240 | 55.7% | 52.9% |
| statistical_slow | 0.00 | 1240 | 57.7% | 55.0% |
| wavefield_fast | 0.35 | 1240 | 53.8% | 51.0% |
| wavefield_slow | 0.35 | 1240 | 54.4% | 51.6% |
