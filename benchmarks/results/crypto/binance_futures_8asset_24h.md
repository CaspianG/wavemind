# Binance Futures Walk-Forward

Official Binance USD-M data. Every test target matures after all training targets used by its fold.

- horizon: 24h from completed 4h candles;
- training: rolling 720-timestamp window; target must mature before fold start;
- model scope: All named engines are statistical baselines/ensembles. WaveMind core is not credited with their accuracy.

| engine | signals | direction accuracy | avg model margin | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|
| Derivatives logistic baseline (per-symbol) | 5760 | 50.8% | 32.0% | 48.8% | 48.1% |
| OHLCV logistic baseline (per-symbol) | 5760 | 51.4% | 17.8% | 47.9% | 46.7% |
| Tabular ensemble (per-symbol) | 5760 | 52.2% | 23.9% | 51.5% | 49.7% |
| Histogram gradient baseline (per-symbol) | 5760 | 51.9% | 42.7% | 51.4% | 47.6% |
| kNN analogue baseline (per-symbol) | 5760 | 52.4% | 17.3% | 51.5% | 48.6% |
| Large-move classifier (per-symbol) | 5760 | 52.4% | 18.1% | 50.2% | 48.8% |
| Return regression ensemble (per-symbol) | 5760 | 51.8% | 31.2% | 49.7% | 48.9% |
| ExtraTrees baseline (per-symbol) | 5760 | 53.1% | 20.2% | 50.8% | 50.1% |

## Admission

75% admitted: none

80% admitted: none

## Best Selective Frontier

Best observed threshold per engine with at least 40 non-overlapping signals. This is diagnostic, not an admitted result.

| engine | threshold | independent signals | accuracy | Wilson low | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|---:|
| Derivatives logistic baseline (per-symbol) | 500 bps | 226 | 58.0% | 51.4% | 52.2% | 45.0% |
| OHLCV logistic baseline (per-symbol) | 200 bps | 349 | 54.2% | 48.9% | 48.5% | 46.4% |
| Tabular ensemble (per-symbol) | 200 bps | 537 | 54.9% | 50.7% | 51.8% | 46.8% |
| Histogram gradient baseline (per-symbol) | 200 bps | 735 | 54.3% | 50.7% | 51.4% | 46.4% |
| kNN analogue baseline (per-symbol) | 200 bps | 348 | 55.2% | 49.9% | 51.8% | 47.6% |
| Large-move classifier (per-symbol) | 300 bps | 176 | 56.2% | 48.9% | 44.4% | 25.0% |
| Return regression ensemble (per-symbol) | 300 bps | 489 | 56.6% | 52.2% | 51.2% | 50.0% |
| ExtraTrees baseline (per-symbol) | 400 bps | 98 | 56.1% | 46.3% | 46.7% | 27.3% |

## Source Audit

| symbol | bars | metrics | depth snapshots | missing optional archives |
|---|---:|---:|---:|---:|
| ADAUSDT | 2190 | 105116 | 105096 | 0 |
| BNBUSDT | 2190 | 105116 | 105096 | 0 |
| BTCUSDT | 2190 | 105116 | 105096 | 0 |
| DOGEUSDT | 2190 | 105116 | 105063 | 0 |
| ETHUSDT | 2190 | 105116 | 105096 | 0 |
| LINKUSDT | 2190 | 105116 | 105096 | 0 |
| SOLUSDT | 2190 | 105116 | 104808 | 1 |
| XRPUSDT | 2190 | 105117 | 104808 | 1 |
