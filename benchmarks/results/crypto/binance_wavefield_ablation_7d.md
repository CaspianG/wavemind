# Binance Futures Walk-Forward

Official Binance USD-M data. Every test target matures after all training targets used by its fold.

- horizon: 7d from completed 4h candles;
- training: rolling 720-timestamp window; target must mature before fold start;
- model scope: Direct wavemind.core.WaveField ablation. Unsigned uses separate up/down fields; signed uses one outcome-weighted field.

| engine | signals | direction accuracy | avg model margin | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|
| WaveMind signed outcome field ablation | 5760 | 51.6% | 86.9% | 43.9% | 38.6% |
| WaveMind unsigned outcome field ablation | 5760 | 50.7% | 72.7% | 45.8% | 42.5% |

## Admission

75% admitted: none

80% admitted: none

## Best Selective Frontier

Best observed threshold per engine with at least 40 non-overlapping signals. This is diagnostic, not an admitted result.

| engine | threshold | independent signals | accuracy | Wilson low | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind signed outcome field ablation | 25 bps | 158 | 51.3% | 43.5% | 42.5% | 35.0% |
| WaveMind unsigned outcome field ablation | 50 bps | 149 | 58.4% | 50.4% | 50.0% | 42.1% |

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
