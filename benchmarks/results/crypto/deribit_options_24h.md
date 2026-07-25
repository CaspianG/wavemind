# Deribit Options Evidence Transfer Benchmark

Control and Deribit options treatment use identical BTC/ETH rows and calendar folds. Three deterministic trade samples per UTC day are fingerprinted and become visible only at the next UTC midnight.

- rows: 12040;
- assets: BTCUSDT, ETHUSDT;
- admitted at 70%: none.

## Full Coverage

| engine | signals | control all/final | options all/final | delta all/final | options worst final asset |
|---|---:|---:|---:|---:|---:|
| LightGBM direction | 1702 | 53.5% / 48.6% | 52.2% / 48.0% | -1.3% / -0.6% | 46.9% |
| Tabular ensemble direction | 1702 | 52.5% / 48.3% | 53.2% / 48.3% | +0.6% / +0.0% | 45.8% |
| WaveField-gated Logistic direction | 1702 | 54.2% / 50.6% | 53.0% / 51.4% | -1.2% / +0.8% | 48.6% |
| Calibrated WaveField-gated Logistic direction | 1702 | 54.2% / 50.6% | 53.0% / 51.4% | -1.2% / +0.8% | 48.6% |
| WaveField outcome direction | 1702 | 52.0% / 49.4% | 51.8% / 50.6% | -0.2% / +1.1% | 49.7% |
| WaveField regime memory direction | 1702 | 51.9% / 52.0% | 49.7% / 48.9% | -2.2% / -3.1% | 48.0% |

## Past-Selected Policy

| engine | control all/final | options all/final | options final signals |
|---|---:|---:|---:|
| LightGBM direction | 52.7% / n/a | 51.3% / n/a | 0 |
| Tabular ensemble direction | 53.9% / n/a | 54.4% / n/a | 0 |
| WaveField-gated Logistic direction | 51.6% / n/a | 49.7% / n/a | 0 |
| Calibrated WaveField-gated Logistic direction | 54.0% / 50.8% | 53.0% / 51.4% | 358 |
| WaveField outcome direction | 49.6% / n/a | n/a / n/a | 0 |
| WaveField regime memory direction | 49.0% / n/a | 49.0% / n/a | 0 |

The options sample is admitted only if it transfers to the untouched period and every asset slice. It is a deterministic sample of the historical tape, not a claim of complete exchange volume.
