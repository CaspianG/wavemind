# Causal Temporal Analogue Benchmark

Fold 1 selects one fixed temporal analogue configuration; folds [2, 3, 4] are untouched.

- selected: `dtw`, sequence 3d, 31 neighbours;
- final market accuracy: 48.0%;
- final market Wilson low: 43.7%;
- final asset accuracy: 47.7%;
- worst final fold: 45.7%;
- worst final asset: 46.6%;
- admitted at 70%: no.

## Validation Selection

| engine | sequence | neighbours | market accuracy | asset accuracy |
|---|---:|---:|---:|---:|
| knn | 3d | 15 | 52.2% | 49.5% |
| dtw | 3d | 15 | 51.6% | 48.9% |
| wavefield | 3d | 15 | 51.1% | 48.6% |
| hybrid | 3d | 15 | 51.1% | 49.6% |
| knn | 3d | 31 | 51.6% | 48.8% |
| dtw | 3d | 31 | 52.7% | 50.0% |
| wavefield | 3d | 31 | 51.1% | 48.6% |
| hybrid | 3d | 31 | 50.5% | 48.1% |
| knn | 7d | 15 | 48.9% | 47.0% |
| dtw | 7d | 15 | 39.7% | 40.9% |
| wavefield | 7d | 15 | 48.4% | 47.0% |
| hybrid | 7d | 15 | 48.9% | 46.6% |
| knn | 7d | 31 | 52.2% | 50.8% |
| dtw | 7d | 31 | 51.6% | 50.0% |
| wavefield | 7d | 31 | 48.4% | 47.0% |
| hybrid | 7d | 31 | 48.4% | 46.9% |
| knn | 14d | 15 | 51.1% | 49.6% |
| dtw | 14d | 15 | 50.5% | 48.9% |
| wavefield | 14d | 15 | 47.8% | 46.3% |
| hybrid | 14d | 15 | 50.0% | 48.8% |
| knn | 14d | 31 | 48.4% | 47.3% |
| dtw | 14d | 31 | 45.7% | 44.7% |
| wavefield | 14d | 31 | 47.8% | 46.3% |
| hybrid | 14d | 31 | 47.3% | 45.4% |

## Final Folds

| fold | asset signals | accuracy |
|---:|---:|---:|
| 2 | 1448 | 49.4% |
| 3 | 1240 | 47.9% |
| 4 | 1432 | 45.7% |

Configuration selection sees validation only. DTW, k-NN, and WaveField share the same causal sequences and mature labels.
