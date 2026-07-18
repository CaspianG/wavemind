# Multi-Year Binance Event Benchmark

Strict nested walk-forward evaluation on verified Binance USD-M archives.

- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- horizon: 24h;
- field: Actual wavemind.core.WaveField correct-vs-wrong regime memory;
- admitted at 70%: none;
- admitted at 75%: none;
- admitted at 80%: none.

## Test Results

| gate | signals | coverage | accuracy | Wilson low | worst fold | worst asset | 2026-H1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 24h mean-reversion direction | 2747 | 40.4% | 53.1% | 51.2% | 50.6% | 48.0% | 50.6% |
| 24h momentum direction | 3813 | 56.1% | 47.4% | 45.8% | 44.7% | 44.3% | 47.0% |
| 6d mean-reversion direction | 3048 | 44.8% | 53.4% | 51.6% | 51.7% | 51.3% | 52.9% |
| 6d momentum direction | 5619 | 82.7% | 47.9% | 46.6% | 47.2% | 46.1% | 47.5% |
| Calibrated WaveField meta gate | 5907 | 86.9% | 53.1% | 51.8% | 50.4% | 50.4% | 52.6% |
| Direct WaveField regime gate | 5988 | 88.1% | 52.9% | 51.6% | 49.2% | 49.7% | 51.5% |
| Direction-margin gate | 3666 | 53.9% | 52.8% | 51.2% | 49.8% | 49.9% | 51.5% |
| Event-probability gate | 3487 | 51.3% | 50.7% | 49.0% | 45.1% | 42.7% | 50.7% |
| ExtraTrees direction | 4018 | 59.1% | 54.6% | 53.0% | 51.8% | 52.9% | 52.8% |
| Histogram direction | 3430 | 50.5% | 51.6% | 49.9% | 48.3% | 46.0% | 48.3% |
| Return-regression direction | 2606 | 38.3% | 52.6% | 50.7% | 48.5% | 49.1% | 48.5% |
| Static directional baseline | 6797 | 100.0% | 52.0% | 50.8% | 48.3% | 50.2% | 51.0% |
| Tabular ensemble direction | 4059 | 59.7% | 52.5% | 51.0% | 50.7% | 49.6% | 51.2% |

## Causal Policy Audit

| gate | fold | test starts | past-only threshold | policy signals | policy accuracy |
|---|---:|---|---:|---:|---:|
| Static directional baseline | 0 | 2024-01-01 | 0.10 | 338 | 53.3% |
| Event-probability gate | 0 | 2024-01-01 | 0.65 | 71 | 66.2% |
| Direction-margin gate | 0 | 2024-01-01 | 0.52 | 332 | 58.7% |
| Direct WaveField regime gate | 0 | 2024-01-01 | 0.90 | 112 | 65.2% |
| Calibrated WaveField meta gate | 0 | 2024-01-01 | 0.50 | 337 | 55.2% |
| Histogram direction | 0 | 2024-01-01 | 0.95 | 42 | 71.4% |
| ExtraTrees direction | 0 | 2024-01-01 | 0.30 | 267 | 61.4% |
| Tabular ensemble direction | 0 | 2024-01-01 | 0.65 | 206 | 61.2% |
| Return-regression direction | 0 | 2024-01-01 | 0.80 | 46 | 93.5% |
| 24h momentum direction | 0 | 2024-01-01 | 0.12 | 287 | 47.7% |
| 6d momentum direction | 0 | 2024-01-01 | 0.20 | 212 | 45.8% |
| 24h mean-reversion direction | 0 | 2024-01-01 | 0.30 | 173 | 61.8% |
| 6d mean-reversion direction | 0 | 2024-01-01 | 0.30 | 147 | 61.9% |
| Static directional baseline | 1 | 2024-07-01 | 0.10 | 360 | 50.0% |
| Event-probability gate | 1 | 2024-07-01 | 0.45 | 261 | 55.9% |
| Direction-margin gate | 1 | 2024-07-01 | 0.45 | 195 | 65.6% |
| Direct WaveField regime gate | 1 | 2024-07-01 | 0.27 | 336 | 58.0% |
| Calibrated WaveField meta gate | 1 | 2024-07-01 | 0.57 | 142 | 55.6% |
| Histogram direction | 1 | 2024-07-01 | 0.47 | 146 | 65.8% |
| ExtraTrees direction | 1 | 2024-07-01 | 0.17 | 230 | 60.9% |
| Tabular ensemble direction | 1 | 2024-07-01 | 0.37 | 86 | 73.3% |
| Return-regression direction | 1 | 2024-07-01 | 0.20 | 157 | 61.1% |
| 24h momentum direction | 1 | 2024-07-01 | 0.15 | 266 | 45.5% |
| 6d momentum direction | 1 | 2024-07-01 | 0.10 | 316 | 51.9% |
| 24h mean-reversion direction | 1 | 2024-07-01 | 0.50 | 67 | 70.1% |
| 6d mean-reversion direction | 1 | 2024-07-01 | 0.42 | 89 | 58.4% |
| Static directional baseline | 2 | 2025-01-01 | 0.10 | 360 | 50.8% |
| Event-probability gate | 2 | 2025-01-01 | 0.65 | 212 | 58.5% |
| Direction-margin gate | 2 | 2025-01-01 | 0.70 | 59 | 66.1% |
| Direct WaveField regime gate | 2 | 2025-01-01 | 0.40 | 283 | 55.5% |
| Calibrated WaveField meta gate | 2 | 2025-01-01 | 0.10 | 360 | 50.8% |
| Histogram direction | 2 | 2025-01-01 | 0.12 | 334 | 58.1% |
| ExtraTrees direction | 2 | 2025-01-01 | 0.40 | 86 | 65.1% |
| Tabular ensemble direction | 2 | 2025-01-01 | 0.15 | 316 | 55.4% |
| Return-regression direction | 2 | 2025-01-01 | 0.60 | 46 | 65.2% |
| 24h momentum direction | 2 | 2025-01-01 | 0.40 | 188 | 48.9% |
| 6d momentum direction | 2 | 2025-01-01 | 0.15 | 315 | 48.9% |
| 24h mean-reversion direction | 2 | 2025-01-01 | 0.82 | 44 | 72.7% |
| 6d mean-reversion direction | 2 | 2025-01-01 | 0.85 | 46 | 63.0% |
| Static directional baseline | 3 | 2025-07-01 | 0.10 | 360 | 46.9% |
| Event-probability gate | 3 | 2025-07-01 | 0.62 | 64 | 57.8% |
| Direction-margin gate | 3 | 2025-07-01 | 0.37 | 251 | 49.8% |
| Direct WaveField regime gate | 3 | 2025-07-01 | 0.10 | 360 | 46.9% |
| Calibrated WaveField meta gate | 3 | 2025-07-01 | 0.45 | 307 | 51.8% |
| Histogram direction | 3 | 2025-07-01 | 0.22 | 221 | 47.5% |
| ExtraTrees direction | 3 | 2025-07-01 | 0.10 | 202 | 37.1% |
| Tabular ensemble direction | 3 | 2025-07-01 | 0.22 | 168 | 47.0% |
| Return-regression direction | 3 | 2025-07-01 | 0.12 | 312 | 49.4% |
| 24h momentum direction | 3 | 2025-07-01 | 0.22 | 218 | 57.8% |
| 6d momentum direction | 3 | 2025-07-01 | 0.12 | 282 | 49.6% |
| 24h mean-reversion direction | 3 | 2025-07-01 | 0.42 | 113 | 52.2% |
| 6d mean-reversion direction | 3 | 2025-07-01 | 0.32 | 130 | 62.3% |
| Static directional baseline | 4 | 2026-01-01 | 0.10 | 360 | 56.9% |
| Event-probability gate | 4 | 2026-01-01 | 0.22 | 353 | 58.1% |
| Direction-margin gate | 4 | 2026-01-01 | 0.27 | 214 | 64.0% |
| Direct WaveField regime gate | 4 | 2026-01-01 | 0.50 | 343 | 61.5% |
| Calibrated WaveField meta gate | 4 | 2026-01-01 | 0.10 | 360 | 56.9% |
| Histogram direction | 4 | 2026-01-01 | 0.37 | 114 | 60.5% |
| ExtraTrees direction | 4 | 2026-01-01 | 0.10 | 245 | 56.7% |
| Tabular ensemble direction | 4 | 2026-01-01 | 0.12 | 247 | 65.6% |
| Return-regression direction | 4 | 2026-01-01 | 0.15 | 80 | 66.2% |
| 24h momentum direction | 4 | 2026-01-01 | 0.60 | 44 | 59.1% |
| 6d momentum direction | 4 | 2026-01-01 | 0.10 | 313 | 45.4% |
| 24h mean-reversion direction | 4 | 2026-01-01 | 0.10 | 315 | 58.7% |
| 6d mean-reversion direction | 4 | 2026-01-01 | 0.12 | 290 | 58.6% |

A threshold is chosen only from the preceding policy block. Test outcomes never tune it.
