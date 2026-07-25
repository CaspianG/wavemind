# Deribit Options Evidence Transfer Benchmark

Control and Deribit options treatment use identical BTC/ETH rows and calendar folds. Three deterministic trade samples per UTC day are fingerprinted and become visible only at the next UTC midnight.

- rows: 11980;
- assets: BTCUSDT, ETHUSDT;
- admitted at 70%: none.

## Full Coverage

| engine | signals | control all/final | options all/final | delta all/final | options worst final asset |
|---|---:|---:|---:|---:|---:|
| LightGBM direction | 246 | 47.2% / 42.0% | 45.5% / 44.0% | -1.6% / +2.0% | 40.0% |
| Tabular ensemble direction | 246 | 46.7% / 40.0% | 45.5% / 42.0% | -1.2% / +2.0% | 36.0% |
| WaveField-gated Logistic direction | 246 | 49.6% / 44.0% | 48.4% / 44.0% | -1.2% / +0.0% | 32.0% |
| Calibrated WaveField-gated Logistic direction | 246 | 49.6% / 44.0% | 48.4% / 44.0% | -1.2% / +0.0% | 32.0% |
| WaveField outcome direction | 246 | 42.7% / 30.0% | 49.2% / 42.0% | +6.5% / +12.0% | 32.0% |
| WaveField regime memory direction | 246 | 52.8% / 50.0% | 50.0% / 52.0% | -2.8% / +2.0% | 48.0% |

## Past-Selected Policy

| engine | control all/final | options all/final | options final signals |
|---|---:|---:|---:|
| LightGBM direction | n/a / n/a | n/a / n/a | 0 |
| Tabular ensemble direction | n/a / n/a | n/a / n/a | 0 |
| WaveField-gated Logistic direction | n/a / n/a | n/a / n/a | 0 |
| Calibrated WaveField-gated Logistic direction | 73.7% / n/a | 47.6% / n/a | 0 |
| WaveField outcome direction | n/a / n/a | n/a / n/a | 0 |
| WaveField regime memory direction | n/a / n/a | n/a / n/a | 0 |

The options sample is admitted only if it transfers to the untouched period and every asset slice. It is a deterministic sample of the historical tape, not a claim of complete exchange volume.
