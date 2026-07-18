# Multi-Year Binance Event Benchmark

Strict nested walk-forward evaluation on verified Binance USD-M archives.

- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- horizon: 7d;
- field: Actual wavemind.core.WaveField correct-vs-wrong regime memory;
- admitted at 70%: none;
- admitted at 75%: none;
- admitted at 80%: none.

## Test Results

| gate | signals | coverage | accuracy | Wilson low | worst fold | worst asset | 2026-H1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 24h mean-reversion direction | 730 | 74.3% | 51.2% | 47.6% | 43.4% | 44.3% | 52.1% |
| 24h momentum direction | 901 | 91.7% | 49.2% | 45.9% | 46.3% | 38.8% | 55.2% |
| 6d mean-reversion direction | 851 | 86.6% | 51.7% | 48.3% | 46.5% | 46.2% | 46.5% |
| 6d momentum direction | 837 | 85.1% | 45.4% | 42.1% | 34.4% | 39.6% | 51.2% |
| Calibrated WaveField meta gate | 888 | 90.3% | 48.5% | 45.3% | 43.5% | 45.0% | 43.5% |
| Direct WaveField regime gate | 723 | 73.6% | 50.6% | 47.0% | 43.9% | 45.6% | 48.9% |
| Direction-margin gate | 798 | 81.2% | 53.3% | 49.8% | 48.0% | 45.9% | 53.5% |
| Event-probability gate | 910 | 92.6% | 47.6% | 44.4% | 43.8% | 40.9% | 47.7% |
| ExtraTrees direction | 904 | 92.0% | 47.8% | 44.5% | 36.5% | 41.2% | 36.5% |
| Histogram direction | 915 | 93.1% | 48.0% | 44.8% | 42.5% | 44.5% | 42.5% |
| Return-regression direction | 913 | 92.9% | 45.6% | 42.4% | 37.2% | 38.8% | 37.2% |
| Static directional baseline | 983 | 100.0% | 48.7% | 45.6% | 43.5% | 43.9% | 43.5% |
| Tabular ensemble direction | 851 | 86.6% | 50.9% | 47.5% | 44.9% | 47.7% | 44.9% |

## Causal Policy Audit

| gate | fold | test starts | past-only threshold | policy signals | policy accuracy |
|---|---:|---|---:|---:|---:|
| Static directional baseline | 0 | 2024-01-01 | 0.10 | 54 | 51.9% |
| Event-probability gate | 0 | 2024-01-01 | 0.42 | 42 | 59.5% |
| Direction-margin gate | 0 | 2024-01-01 | 0.90 | 50 | 64.0% |
| Direct WaveField regime gate | 0 | 2024-01-01 | 1.00 | 0 | n/a |
| Calibrated WaveField meta gate | 0 | 2024-01-01 | 0.10 | 54 | 51.9% |
| Histogram direction | 0 | 2024-01-01 | 0.87 | 41 | 68.3% |
| ExtraTrees direction | 0 | 2024-01-01 | 0.42 | 46 | 65.2% |
| Tabular ensemble direction | 0 | 2024-01-01 | 0.52 | 46 | 67.4% |
| Return-regression direction | 0 | 2024-01-01 | 0.50 | 41 | 70.7% |
| 24h momentum direction | 0 | 2024-01-01 | 0.10 | 52 | 53.8% |
| 6d momentum direction | 0 | 2024-01-01 | 0.20 | 50 | 52.0% |
| 24h mean-reversion direction | 0 | 2024-01-01 | 0.22 | 48 | 58.3% |
| 6d mean-reversion direction | 0 | 2024-01-01 | 0.30 | 42 | 59.5% |
| Static directional baseline | 1 | 2024-07-01 | 0.10 | 56 | 48.2% |
| Event-probability gate | 1 | 2024-07-01 | 0.42 | 41 | 65.9% |
| Direction-margin gate | 1 | 2024-07-01 | 0.60 | 48 | 66.7% |
| Direct WaveField regime gate | 1 | 2024-07-01 | 0.37 | 44 | 61.4% |
| Calibrated WaveField meta gate | 1 | 2024-07-01 | 0.75 | 44 | 56.8% |
| Histogram direction | 1 | 2024-07-01 | 0.42 | 49 | 53.1% |
| ExtraTrees direction | 1 | 2024-07-01 | 0.10 | 56 | 55.4% |
| Tabular ensemble direction | 1 | 2024-07-01 | 0.45 | 40 | 57.5% |
| Return-regression direction | 1 | 2024-07-01 | 0.17 | 50 | 48.0% |
| 24h momentum direction | 1 | 2024-07-01 | 0.20 | 48 | 64.6% |
| 6d momentum direction | 1 | 2024-07-01 | 0.20 | 49 | 65.3% |
| 24h mean-reversion direction | 1 | 2024-07-01 | 0.30 | 43 | 53.5% |
| 6d mean-reversion direction | 1 | 2024-07-01 | 0.27 | 40 | 45.0% |
| Static directional baseline | 2 | 2025-01-01 | 0.10 | 56 | 50.0% |
| Event-probability gate | 2 | 2025-01-01 | 0.10 | 56 | 50.0% |
| Direction-margin gate | 2 | 2025-01-01 | 0.35 | 55 | 56.4% |
| Direct WaveField regime gate | 2 | 2025-01-01 | 0.20 | 40 | 52.5% |
| Calibrated WaveField meta gate | 2 | 2025-01-01 | 0.45 | 43 | 65.1% |
| Histogram direction | 2 | 2025-01-01 | 0.30 | 55 | 41.8% |
| ExtraTrees direction | 2 | 2025-01-01 | 0.12 | 54 | 42.6% |
| Tabular ensemble direction | 2 | 2025-01-01 | 0.10 | 56 | 37.5% |
| Return-regression direction | 2 | 2025-01-01 | 0.10 | 55 | 47.3% |
| 24h momentum direction | 2 | 2025-01-01 | 0.22 | 54 | 63.0% |
| 6d momentum direction | 2 | 2025-01-01 | 0.47 | 43 | 65.1% |
| 24h mean-reversion direction | 2 | 2025-01-01 | 0.60 | 40 | 55.0% |
| 6d mean-reversion direction | 2 | 2025-01-01 | 0.22 | 55 | 47.3% |
| Static directional baseline | 3 | 2025-07-01 | 0.10 | 56 | 41.1% |
| Event-probability gate | 3 | 2025-07-01 | 0.15 | 56 | 42.9% |
| Direction-margin gate | 3 | 2025-07-01 | 0.60 | 43 | 51.2% |
| Direct WaveField regime gate | 3 | 2025-07-01 | 0.80 | 52 | 42.3% |
| Calibrated WaveField meta gate | 3 | 2025-07-01 | 0.10 | 56 | 41.1% |
| Histogram direction | 3 | 2025-07-01 | 0.37 | 48 | 52.1% |
| ExtraTrees direction | 3 | 2025-07-01 | 0.10 | 55 | 47.3% |
| Tabular ensemble direction | 3 | 2025-07-01 | 0.35 | 49 | 53.1% |
| Return-regression direction | 3 | 2025-07-01 | 0.15 | 53 | 43.4% |
| 24h momentum direction | 3 | 2025-07-01 | 0.17 | 53 | 50.9% |
| 6d momentum direction | 3 | 2025-07-01 | 0.10 | 56 | 44.6% |
| 24h mean-reversion direction | 3 | 2025-07-01 | 0.40 | 42 | 71.4% |
| 6d mean-reversion direction | 3 | 2025-07-01 | 0.30 | 41 | 68.3% |
| Static directional baseline | 4 | 2026-01-01 | 0.10 | 56 | 64.3% |
| Event-probability gate | 4 | 2026-01-01 | 0.25 | 56 | 66.1% |
| Direction-margin gate | 4 | 2026-01-01 | 0.57 | 42 | 73.8% |
| Direct WaveField regime gate | 4 | 2026-01-01 | 0.30 | 50 | 68.0% |
| Calibrated WaveField meta gate | 4 | 2026-01-01 | 0.10 | 56 | 64.3% |
| Histogram direction | 4 | 2026-01-01 | 0.12 | 56 | 57.1% |
| ExtraTrees direction | 4 | 2026-01-01 | 0.25 | 43 | 65.1% |
| Tabular ensemble direction | 4 | 2026-01-01 | 0.22 | 51 | 64.7% |
| Return-regression direction | 4 | 2026-01-01 | 0.17 | 41 | 41.5% |
| 24h momentum direction | 4 | 2026-01-01 | 0.35 | 46 | 34.8% |
| 6d momentum direction | 4 | 2026-01-01 | 0.25 | 49 | 44.9% |
| 24h mean-reversion direction | 4 | 2026-01-01 | 0.40 | 40 | 77.5% |
| 6d mean-reversion direction | 4 | 2026-01-01 | 0.10 | 56 | 62.5% |

A threshold is chosen only from the preceding policy block. Test outcomes never tune it.
