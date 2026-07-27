# Preregistered Longitudinal Capitulation Replication

The frozen rebound rule is evaluated on 24 previously unused Bybit assets from 2021-03-15 through 2026-07-27. The protocol was committed before the dataset was downloaded.

- protocol: `benchmarks/protocols/bybit_longitudinal_capitulation_v1.json`;
- assets: 24;
- source interval: completed 4h candles and causal 4h OI;

| horizon | asset signals | signal accuracy | market episodes | episode accuracy | episode Wilson low | unconditional up | episode uplift | admitted |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| 12h | 163 | 68.1% | 45 | 53.3% | 39.1% | 49.0% | 4.3% | no |
| 24h | 148 | 67.6% | 46 | 56.5% | 42.2% | 47.1% | 9.5% | no |
| 48h | 137 | 72.3% | 45 | 62.2% | 47.6% | 48.0% | 14.2% | no |
| 7d | 133 | 63.9% | 42 | 50.0% | 35.5% | 43.1% | 6.9% | no |

## 24h Episode Folds

| fold | episodes | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 0 | 1 | 100.0% | 20.7% |
| 1 | 3 | 66.7% | 20.8% |
| 2 | 1 | 0.0% | 0.0% |
| 3 | 2 | 50.0% | 9.5% |
| 5 | 2 | 100.0% | 34.2% |
| 6 | 2 | 0.0% | 0.0% |
| 7 | 2 | 50.0% | 9.5% |
| 8 | 2 | 50.0% | 9.5% |
| 9 | 5 | 60.0% | 23.1% |
| 10 | 3 | 66.7% | 20.8% |
| 11 | 5 | 40.0% | 11.8% |
| 12 | 4 | 100.0% | 51.0% |
| 13 | 1 | 100.0% | 20.7% |
| 14 | 1 | 100.0% | 20.7% |
| 15 | 2 | 100.0% | 34.2% |
| 16 | 4 | 75.0% | 30.1% |
| 17 | 4 | 0.0% | 0.0% |
| 18 | 2 | 0.0% | 0.0% |

The asset-signal count is not treated as an independent sample. Admission is decided on globally clustered market episodes and remains false whenever support, Wilson, time, or asset stability fails.
