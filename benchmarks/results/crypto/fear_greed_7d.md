# Causal Fear & Greed Transfer Benchmark

Control and sentiment treatment use identical rows and calendar folds. Each daily Fear & Greed observation becomes visible only after the configured publication lag.

- rows: 53196;
- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- admitted at 70%: none.

## Full-Coverage Control vs Sentiment

| engine | signals | control | sentiment | delta | final signals | control final | sentiment final | delta | sentiment worst final asset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 983 | 53.2% | 54.0% | +0.8% | 200 | 52.5% | 43.0% | -9.5% | 36.0% |
| Tabular ensemble direction | 983 | 54.0% | 52.8% | -1.2% | 200 | 49.5% | 41.5% | -8.0% | 36.0% |
| WaveField-gated Logistic direction | 983 | 49.1% | 48.7% | -0.4% | 200 | 43.0% | 34.5% | -8.5% | 28.0% |
| Calibrated WaveField-gated Logistic direction | 983 | 49.1% | 48.7% | -0.4% | 200 | 43.0% | 34.5% | -8.5% | 28.0% |
| WaveField outcome direction | 983 | 49.1% | 46.2% | -3.0% | 200 | 35.0% | 36.5% | +1.5% | 24.0% |
| WaveField regime memory direction | 983 | 48.5% | 48.0% | -0.5% | 200 | 46.0% | 40.5% | -5.5% | 28.0% |

## Past-Selected Policy

| engine | control | sentiment | delta | control final | sentiment final | delta |
|---|---:|---:|---:|---:|---:|---:|
| LightGBM direction | n/a | n/a | n/a | n/a | n/a | n/a |
| Tabular ensemble direction | n/a | n/a | n/a | n/a | n/a | n/a |
| WaveField-gated Logistic direction | n/a | n/a | n/a | n/a | n/a | n/a |
| Calibrated WaveField-gated Logistic direction | 38.1% | 52.8% | +14.7% | 28.6% | 0.0% | -28.6% |
| WaveField outcome direction | n/a | n/a | n/a | n/a | n/a | n/a |
| WaveField regime memory direction | n/a | n/a | n/a | n/a | n/a | n/a |

Sentiment is retained as predictive evidence only if gains transfer to the untouched final period.
