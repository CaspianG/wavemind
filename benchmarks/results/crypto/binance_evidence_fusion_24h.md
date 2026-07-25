# Binance Causal Evidence Fusion Benchmark

Seven feature variants use identical BTC/ETH rows, calendar folds, model hyperparameters, and past-only threshold selection. All source joins are causal and 2026-H1 remains untouched until final evaluation.

- rows: 11122;
- assets: BTCUSDT, ETHUSDT;
- fusion admitted at 70%: none.

## Full Coverage

| engine | signals | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion worst final asset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 1534 | 52.2% / 50.6% | 51.8% / 48.3% | 52.8% / 51.4% | 51.8% / 50.9% | 50.5% / 49.4% | 52.3% / 51.7% | 51.5% / 50.6% | 50.0% |
| Tabular ensemble direction | 1534 | 51.6% / 49.1% | 52.1% / 48.0% | 52.2% / 50.9% | 52.3% / 50.0% | 50.8% / 50.0% | 52.3% / 53.2% | 51.9% / 50.3% | 48.8% |
| WaveField-gated Logistic direction | 1534 | 54.1% / 52.3% | 54.0% / 54.0% | 54.2% / 53.8% | 54.0% / 52.9% | 53.5% / 53.5% | 54.6% / 54.0% | 52.5% / 52.3% | 51.7% |
| Calibrated WaveField-gated Logistic direction | 1534 | 54.1% / 52.3% | 54.0% / 54.0% | 54.2% / 53.8% | 54.0% / 52.9% | 53.5% / 53.5% | 54.6% / 54.0% | 52.5% / 52.3% | 51.7% |
| WaveField outcome direction | 1534 | 50.0% / 48.3% | 52.7% / 49.4% | 51.0% / 48.8% | 52.4% / 50.3% | 52.2% / 50.6% | 52.0% / 50.0% | 53.1% / 50.9% | 46.6% |
| WaveField regime memory direction | 1534 | 47.1% / 46.8% | 50.2% / 46.2% | 49.0% / 50.6% | 47.9% / 43.6% | 48.4% / 45.7% | 49.2% / 46.5% | 49.9% / 50.0% | 48.8% |

## Past-Selected Policy

| engine | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion final signals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 47.8% / n/a | 49.0% / n/a | 51.1% / n/a | 48.1% / n/a | 51.2% / n/a | 49.5% / n/a | 50.0% / n/a | 0 |
| Tabular ensemble direction | 50.5% / n/a | 48.3% / n/a | 50.0% / n/a | 52.8% / n/a | n/a / n/a | 47.8% / n/a | n/a / n/a | 0 |
| WaveField-gated Logistic direction | 52.2% / 53.6% | 52.9% / 52.8% | 55.9% / n/a | 52.7% / 52.5% | 53.4% / n/a | 52.0% / n/a | 53.9% / n/a | 0 |
| Calibrated WaveField-gated Logistic direction | 53.2% / 50.3% | 53.8% / 55.1% | 53.4% / 52.9% | 52.9% / 53.2% | 53.5% / 53.5% | 53.4% / 54.0% | 52.5% / 52.3% | 346 |
| WaveField outcome direction | 49.2% / 48.6% | 49.9% / 48.3% | 52.4% / n/a | 51.7% / 50.0% | n/a / n/a | 52.1% / 54.5% | 48.1% / 48.1% | 337 |
| WaveField regime memory direction | 47.1% / n/a | 47.1% / n/a | 47.1% / n/a | 49.4% / n/a | n/a / n/a | 47.1% / n/a | 44.5% / n/a | 0 |

Fusion is admitted only if the combined causal evidence transfers across the final period and every asset slice; development-only uplift is rejected.
