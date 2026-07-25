# Causal Fear & Greed Transfer Benchmark

Control and sentiment treatment use identical rows and calendar folds. Each daily Fear & Greed observation becomes visible only after the configured publication lag.

- rows: 53436;
- assets: ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, SOLUSDT, XRPUSDT;
- admitted at 70%: none.

## Full-Coverage Control vs Sentiment

| engine | signals | control | sentiment | delta | final signals | control final | sentiment final | delta | sentiment worst final asset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 6797 | 51.0% | 51.1% | +0.1% | 1432 | 50.8% | 49.7% | -1.2% | 45.8% |
| Tabular ensemble direction | 6797 | 51.5% | 51.5% | +0.0% | 1432 | 49.1% | 48.6% | -0.5% | 43.6% |
| WaveField-gated Logistic direction | 6797 | 53.8% | 53.2% | -0.6% | 1432 | 52.5% | 51.4% | -1.1% | 47.5% |
| Calibrated WaveField-gated Logistic direction | 6797 | 53.8% | 53.2% | -0.6% | 1432 | 52.5% | 51.4% | -1.1% | 47.5% |
| WaveField outcome direction | 6797 | 51.5% | 50.6% | -0.9% | 1432 | 52.0% | 49.7% | -2.3% | 46.9% |
| WaveField regime memory direction | 6797 | 51.2% | 49.6% | -1.6% | 1432 | 54.6% | 47.0% | -7.6% | 42.5% |

## Past-Selected Policy

| engine | control | sentiment | delta | control final | sentiment final | delta |
|---|---:|---:|---:|---:|---:|---:|
| LightGBM direction | 52.7% | 51.1% | -1.5% | 51.2% | 47.4% | -3.8% |
| Tabular ensemble direction | 53.4% | 52.9% | -0.5% | 50.8% | 52.8% | +2.0% |
| WaveField-gated Logistic direction | 52.2% | 51.0% | -1.2% | 49.9% | 49.3% | -0.6% |
| Calibrated WaveField-gated Logistic direction | 52.8% | 52.6% | -0.2% | 52.5% | 50.8% | -1.8% |
| WaveField outcome direction | 52.4% | 50.7% | -1.7% | 50.0% | 51.0% | +1.0% |
| WaveField regime memory direction | 50.8% | 52.3% | +1.5% | 50.0% | 51.9% | +1.9% |

Sentiment is retained as predictive evidence only if gains transfer to the untouched final period.
