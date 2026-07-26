# Causal Cross-Asset Market Wave Benchmark

Fold 1 selects a fixed engine and memory lookback; folds [2, 3, 4] are the untouched final test.

- selected: `hybrid` with 360-panel rolling memory;
- final market accuracy: 49.7%;
- final market Wilson low: 45.4%;
- final asset accuracy: 49.8%;
- worst final fold: 48.2%;
- worst final asset: 48.0%;
- admitted at 70%: no.

## Validation Selection

| engine | lookback | market accuracy | Wilson low | asset accuracy |
|---|---:|---:|---:|---:|
| direct | 90 | 55.4% | 48.2% | 53.9% |
| wavefield | 90 | 52.7% | 45.5% | 50.1% |
| hybrid | 90 | 54.9% | 47.7% | 52.7% |
| direct | 180 | 57.1% | 49.8% | 53.9% |
| wavefield | 180 | 53.3% | 46.1% | 50.7% |
| hybrid | 180 | 54.3% | 47.1% | 52.4% |
| direct | 360 | 55.4% | 48.2% | 52.4% |
| wavefield | 360 | 54.9% | 47.7% | 52.2% |
| hybrid | 360 | 58.7% | 51.5% | 54.3% |

## Final Folds

| fold | asset signals | accuracy |
|---:|---:|---:|
| 2 | 1448 | 50.4% |
| 3 | 1240 | 48.2% |
| 4 | 1432 | 50.6% |

The future-market-factor oracle reaches 88.7% asset accuracy. It is a diagnostic ceiling, not a predictor, because it uses the future cross-asset direction.

The production claim remains rejected unless the fixed rolling policy clears every admission condition on the untouched folds.
