# Multi-Year Binance Event Benchmark

Strict nested walk-forward evaluation on verified Binance USD-M archives.

- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- horizon: 7d;
- field: Actual wavemind.core.WaveField correct-vs-wrong regime memory;
- admitted at 75%: none;
- admitted at 80%: none.

## Test Results

| gate | signals | coverage | accuracy | Wilson low | worst fold | worst asset | 2026-H1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Calibrated WaveField meta gate | 915 | 93.1% | 49.6% | 46.4% | 42.5% | 47.4% | 42.5% |
| Direct WaveField regime gate | 949 | 96.5% | 49.5% | 46.4% | 44.8% | 45.4% | 47.5% |
| Direction-margin gate | 833 | 84.7% | 50.8% | 47.4% | 48.3% | 43.3% | 48.3% |
| Event-probability gate | 831 | 84.5% | 49.5% | 46.1% | 44.8% | 45.6% | 50.9% |
| Static directional baseline | 983 | 100.0% | 48.5% | 45.4% | 42.5% | 45.5% | 42.5% |

## Causal Policy Audit

| gate | fold | test starts | past-only threshold | policy signals | policy accuracy |
|---|---:|---|---:|---:|---:|
| Static directional baseline | 0 | 2024-01-01 | 0.10 | 54 | 51.9% |
| Event-probability gate | 0 | 2024-01-01 | 0.45 | 40 | 60.0% |
| Direction-margin gate | 0 | 2024-01-01 | 0.95 | 50 | 66.0% |
| Direct WaveField regime gate | 0 | 2024-01-01 | 0.12 | 43 | 60.5% |
| Calibrated WaveField meta gate | 0 | 2024-01-01 | 0.10 | 54 | 51.9% |
| Static directional baseline | 1 | 2024-07-01 | 0.10 | 56 | 50.0% |
| Event-probability gate | 1 | 2024-07-01 | 0.35 | 49 | 61.2% |
| Direction-margin gate | 1 | 2024-07-01 | 0.60 | 49 | 65.3% |
| Direct WaveField regime gate | 1 | 2024-07-01 | 0.10 | 56 | 50.0% |
| Calibrated WaveField meta gate | 1 | 2024-07-01 | 0.60 | 56 | 51.8% |
| Static directional baseline | 2 | 2025-01-01 | 0.10 | 56 | 46.4% |
| Event-probability gate | 2 | 2025-01-01 | 0.32 | 53 | 47.2% |
| Direction-margin gate | 2 | 2025-01-01 | 0.40 | 54 | 53.7% |
| Direct WaveField regime gate | 2 | 2025-01-01 | 0.30 | 46 | 50.0% |
| Calibrated WaveField meta gate | 2 | 2025-01-01 | 0.40 | 45 | 60.0% |
| Static directional baseline | 3 | 2025-07-01 | 0.10 | 56 | 42.9% |
| Event-probability gate | 3 | 2025-07-01 | 0.12 | 56 | 44.6% |
| Direction-margin gate | 3 | 2025-07-01 | 0.57 | 43 | 51.2% |
| Direct WaveField regime gate | 3 | 2025-07-01 | 0.75 | 53 | 45.3% |
| Calibrated WaveField meta gate | 3 | 2025-07-01 | 0.10 | 56 | 42.9% |
| Static directional baseline | 4 | 2026-01-01 | 0.10 | 56 | 66.1% |
| Event-probability gate | 4 | 2026-01-01 | 0.47 | 42 | 76.2% |
| Direction-margin gate | 4 | 2026-01-01 | 0.42 | 48 | 75.0% |
| Direct WaveField regime gate | 4 | 2026-01-01 | 0.17 | 56 | 75.0% |
| Calibrated WaveField meta gate | 4 | 2026-01-01 | 0.10 | 56 | 66.1% |

A threshold is chosen only from the preceding policy block. Test outcomes never tune it.
