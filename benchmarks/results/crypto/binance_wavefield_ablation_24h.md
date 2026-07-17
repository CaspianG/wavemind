# Binance Futures Walk-Forward

Official Binance USD-M data. Every test target matures after all training targets used by its fold.

- horizon: 24h from completed 4h candles;
- training: rolling 720-timestamp window; target must mature before fold start;
- model scope: Direct wavemind.core.WaveField ablation. Unsigned uses separate up/down fields; signed uses one outcome-weighted field.

| engine | signals | direction accuracy | avg model margin | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|
| WaveMind signed outcome field ablation | 5760 | 50.8% | 87.3% | 48.0% | 48.9% |
| WaveMind unsigned outcome field ablation | 5760 | 52.0% | 70.2% | 49.3% | 49.3% |

## Admission

75% admitted: none

80% admitted: none

## Best Selective Frontier

Best observed threshold per engine with at least 40 non-overlapping signals. This is diagnostic, not an admitted result.

| engine | threshold | independent signals | accuracy | Wilson low | worst fold | worst symbol |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind signed outcome field ablation | 100 bps | 946 | 49.8% | 46.6% | 45.8% | 45.4% |
| WaveMind unsigned outcome field ablation | 200 bps | 782 | 55.9% | 52.4% | 51.4% | 48.5% |

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
