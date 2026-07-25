# Causal Temporal State Benchmark

Raw snapshots, explicit lagged state, and a multi-timescale WaveField reservoir are compared under the same causal protocol.

- horizon: 24h;
- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- admitted at 70%: none.

## Results

| engine | all signals | all accuracy | selected signals | selected accuracy | Wilson low | worst fold | worst asset | 2026-H1 selected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lagged causal state ExtraTrees | 6797 | 50.2% | 4071 | 50.9% | 49.3% | 48.7% | 48.1% | 48.7% |
| Lagged causal state LightGBM | 6797 | 50.4% | 2260 | 53.8% | 51.8% | 51.7% | 51.1% | 51.7% |
| Lagged causal state Logistic | 6797 | 50.9% | 3671 | 49.4% | 47.7% | 44.2% | 48.5% | 55.3% |
| Raw ExtraTrees | 6797 | 50.7% | 3985 | 52.3% | 50.8% | 51.0% | 49.8% | 51.0% |
| Raw LightGBM | 6797 | 50.0% | 3291 | 51.2% | 49.5% | 49.4% | 48.1% | 50.6% |
| Raw Logistic | 6797 | 52.1% | 5501 | 52.3% | 51.0% | 50.4% | 49.5% | 50.9% |
| Temporal WaveField ExtraTrees | 6797 | 50.7% | 3867 | 51.7% | 50.1% | 50.8% | 46.8% | 52.1% |
| Temporal WaveField LightGBM | 6797 | 50.7% | 3592 | 52.1% | 50.5% | 49.6% | 49.9% | 51.2% |
| Temporal WaveField Logistic | 6797 | 52.0% | 4652 | 51.3% | 49.9% | 46.8% | 49.3% | 49.8% |

## Admission Rule

A 70% claim requires at least 40 independent selected signals, Wilson low >=65%, and every fold and asset slice >=65%. Thresholds are chosen only from pre-test policy data.
