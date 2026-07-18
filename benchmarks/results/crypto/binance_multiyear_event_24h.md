# Multi-Year Binance Event Benchmark

Strict nested walk-forward evaluation on verified Binance USD-M archives.

- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- horizon: 24h;
- field: Actual wavemind.core.WaveField correct-vs-wrong regime memory;
- admitted at 75%: none;
- admitted at 80%: none.

## Test Results

| gate | signals | coverage | accuracy | Wilson low | worst fold | worst asset | 2026-H1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Calibrated WaveField meta gate | 5742 | 84.5% | 53.3% | 52.0% | 50.6% | 51.5% | 51.7% |
| Direct WaveField regime gate | 5439 | 80.0% | 52.5% | 51.1% | 48.5% | 51.2% | 51.4% |
| Direction-margin gate | 3289 | 48.4% | 52.4% | 50.6% | 47.5% | 50.1% | 51.5% |
| Event-probability gate | 4557 | 67.0% | 52.2% | 50.8% | 48.3% | 50.8% | 52.2% |
| Static directional baseline | 6797 | 100.0% | 52.3% | 51.1% | 48.5% | 50.8% | 51.2% |

## Causal Policy Audit

| gate | fold | test starts | past-only threshold | policy signals | policy accuracy |
|---|---:|---|---:|---:|---:|
| Static directional baseline | 0 | 2024-01-01 | 0.10 | 338 | 52.7% |
| Event-probability gate | 0 | 2024-01-01 | 0.50 | 237 | 62.0% |
| Direction-margin gate | 0 | 2024-01-01 | 0.37 | 336 | 59.5% |
| Direct WaveField regime gate | 0 | 2024-01-01 | 0.50 | 164 | 57.3% |
| Calibrated WaveField meta gate | 0 | 2024-01-01 | 0.52 | 338 | 54.7% |
| Static directional baseline | 1 | 2024-07-01 | 0.10 | 360 | 51.4% |
| Event-probability gate | 1 | 2024-07-01 | 0.50 | 220 | 55.0% |
| Direction-margin gate | 1 | 2024-07-01 | 0.65 | 74 | 70.3% |
| Direct WaveField regime gate | 1 | 2024-07-01 | 0.10 | 360 | 51.4% |
| Calibrated WaveField meta gate | 1 | 2024-07-01 | 0.57 | 155 | 58.7% |
| Static directional baseline | 2 | 2025-01-01 | 0.10 | 360 | 50.6% |
| Event-probability gate | 2 | 2025-01-01 | 0.65 | 212 | 57.1% |
| Direction-margin gate | 2 | 2025-01-01 | 0.70 | 56 | 69.6% |
| Direct WaveField regime gate | 2 | 2025-01-01 | 0.32 | 221 | 54.3% |
| Calibrated WaveField meta gate | 2 | 2025-01-01 | 0.10 | 360 | 50.6% |
| Static directional baseline | 3 | 2025-07-01 | 0.10 | 360 | 47.2% |
| Event-probability gate | 3 | 2025-07-01 | 0.32 | 324 | 48.8% |
| Direction-margin gate | 3 | 2025-07-01 | 0.35 | 262 | 49.6% |
| Direct WaveField regime gate | 3 | 2025-07-01 | 0.32 | 354 | 50.0% |
| Calibrated WaveField meta gate | 3 | 2025-07-01 | 0.25 | 352 | 52.0% |
| Static directional baseline | 4 | 2026-01-01 | 0.10 | 360 | 56.7% |
| Event-probability gate | 4 | 2026-01-01 | 0.40 | 312 | 60.3% |
| Direction-margin gate | 4 | 2026-01-01 | 0.27 | 200 | 66.0% |
| Direct WaveField regime gate | 4 | 2026-01-01 | 0.95 | 139 | 64.7% |
| Calibrated WaveField meta gate | 4 | 2026-01-01 | 0.60 | 292 | 58.6% |

A threshold is chosen only from the preceding policy block. Test outcomes never tune it.
