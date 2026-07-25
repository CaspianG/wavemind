# Causal Temporal State Benchmark

Raw snapshots, explicit lagged state, and a multi-timescale WaveField reservoir are compared under the same causal protocol.

- horizon: 7d;
- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- admitted at 70%: none.

## Results

| engine | all signals | all accuracy | selected signals | selected accuracy | Wilson low | worst fold | worst asset | 2026-H1 selected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lagged causal state ExtraTrees | 983 | 48.6% | 842 | 47.5% | 44.2% | 42.5% | 41.1% | 42.5% |
| Lagged causal state LightGBM | 983 | 49.7% | 711 | 51.9% | 48.2% | 48.0% | 43.3% | 48.0% |
| Lagged causal state Logistic | 983 | 49.3% | 839 | 52.0% | 48.6% | 46.8% | 48.1% | 53.6% |
| Raw ExtraTrees | 983 | 47.1% | 877 | 46.9% | 43.6% | 41.0% | 42.3% | 41.0% |
| Raw LightGBM | 983 | 48.4% | 850 | 48.7% | 45.4% | 43.4% | 41.3% | 43.4% |
| Raw Logistic | 983 | 48.7% | 630 | 49.8% | 45.9% | 46.1% | 40.3% | 52.2% |
| Temporal WaveField ExtraTrees | 983 | 46.9% | 878 | 48.3% | 45.0% | 43.3% | 39.8% | 43.3% |
| Temporal WaveField LightGBM | 983 | 49.3% | 856 | 49.6% | 46.3% | 46.9% | 45.9% | 51.8% |
| Temporal WaveField Logistic | 983 | 49.4% | 595 | 47.1% | 43.1% | 43.4% | 37.3% | 46.1% |

## Admission Rule

A 70% claim requires at least 40 independent selected signals, Wilson low >=65%, and every fold and asset slice >=65%. Thresholds are chosen only from pre-test policy data.
