# Binance Causal Evidence Fusion Benchmark

Seven feature variants use identical BTC/ETH rows, calendar folds, model hyperparameters, and past-only threshold selection. All source joins are causal and 2026-H1 remains untouched until final evaluation.

- rows: 11062;
- assets: BTCUSDT, ETHUSDT;
- fusion admitted at 70%: none.

## Full Coverage

| engine | signals | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion worst final asset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 226 | 49.1% / 36.0% | 51.3% / 40.0% | 48.7% / 40.0% | 48.2% / 34.0% | 52.7% / 56.0% | 51.3% / 40.0% | 50.9% / 38.0% | 36.0% |
| Tabular ensemble direction | 226 | 48.2% / 36.0% | 50.4% / 40.0% | 49.1% / 36.0% | 49.6% / 36.0% | 51.3% / 48.0% | 50.0% / 40.0% | 49.6% / 38.0% | 36.0% |
| WaveField-gated Logistic direction | 226 | 53.5% / 44.0% | 53.5% / 44.0% | 49.6% / 36.0% | 54.9% / 42.0% | 46.5% / 34.0% | 54.9% / 44.0% | 48.2% / 36.0% | 36.0% |
| Calibrated WaveField-gated Logistic direction | 226 | 53.5% / 44.0% | 53.5% / 44.0% | 49.6% / 36.0% | 54.9% / 42.0% | 46.5% / 34.0% | 54.9% / 44.0% | 48.2% / 36.0% | 36.0% |
| WaveField outcome direction | 226 | 54.4% / 56.0% | 50.9% / 54.0% | 51.8% / 48.0% | 50.9% / 52.0% | 49.1% / 50.0% | 47.8% / 42.0% | 48.7% / 52.0% | 44.0% |
| WaveField regime memory direction | 226 | 50.0% / 44.0% | 47.3% / 40.0% | 46.9% / 48.0% | 53.5% / 48.0% | 50.9% / 50.0% | 44.7% / 40.0% | 50.4% / 44.0% | 32.0% |

## Past-Selected Policy

| engine | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion final signals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 |
| Tabular ensemble direction | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 |
| WaveField-gated Logistic direction | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 |
| Calibrated WaveField-gated Logistic direction | 52.7% / 38.9% | 61.8% / 46.2% | 52.8% / 40.9% | 56.3% / 26.3% | 48.4% / 27.8% | 52.1% / 33.3% | 48.4% / 33.3% | 3 |
| WaveField outcome direction | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 |
| WaveField regime memory direction | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 |

Fusion is admitted only if the combined causal evidence transfers across the final period and every asset slice; development-only uplift is rejected.
