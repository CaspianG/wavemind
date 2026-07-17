# Binance Futures Walk-Forward

Official Binance USD-M data. Every test target matures after all training targets used by its fold.

- horizon: 7d from completed 4h candles;
- training: rolling 720-timestamp window; target must mature before fold start;
- model scope: All named engines are statistical baselines/ensembles. WaveMind core is not credited with their accuracy.

| engine | signals | direction accuracy | avg model margin | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|
| Derivatives logistic baseline (per-symbol) | 5760 | 54.9% | 47.0% | 50.9% | 42.1% |
| OHLCV logistic baseline (per-symbol) | 5760 | 47.5% | 19.3% | 43.4% | 41.5% |
| Tabular ensemble (per-symbol) | 5760 | 55.3% | 38.6% | 47.6% | 44.0% |
| Histogram gradient baseline (per-symbol) | 5760 | 55.3% | 62.7% | 47.2% | 41.9% |
| kNN analogue baseline (per-symbol) | 5760 | 55.4% | 26.8% | 47.9% | 46.8% |
| Large-move classifier (per-symbol) | 5760 | 53.8% | 25.5% | 49.0% | 46.7% |
| Return regression ensemble (per-symbol) | 5760 | 56.0% | 46.2% | 48.4% | 44.3% |
| ExtraTrees baseline (per-symbol) | 5760 | 54.8% | 35.1% | 48.5% | 40.1% |

## Admission

75% admitted: none

80% admitted: none

## Best Selective Frontier

Best observed threshold per engine with at least 40 non-overlapping signals. This is diagnostic, not an admitted result.

| engine | threshold | independent signals | accuracy | Wilson low | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|---:|
| Derivatives logistic baseline (per-symbol) | 200 bps | 124 | 62.9% | 54.1% | 58.8% | 46.7% |
| OHLCV logistic baseline (per-symbol) | 0 bps | 160 | 45.0% | 37.5% | 35.0% | 25.0% |
| Tabular ensemble (per-symbol) | 500 bps | 50 | 60.0% | 46.2% | 33.3% | 33.3% |
| Histogram gradient baseline (per-symbol) | 500 bps | 104 | 58.7% | 49.0% | 53.6% | 30.8% |
| kNN analogue baseline (per-symbol) | 200 bps | 81 | 56.8% | 45.9% | 38.9% | 36.4% |
| Large-move classifier (per-symbol) | 300 bps | 56 | 58.9% | 45.9% | 37.5% | 30.0% |
| Return regression ensemble (per-symbol) | 500 bps | 69 | 60.9% | 49.1% | 33.3% | 36.4% |
| ExtraTrees baseline (per-symbol) | 400 bps | 64 | 59.4% | 47.1% | 42.9% | 40.0% |

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
