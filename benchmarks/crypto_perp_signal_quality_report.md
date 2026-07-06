# WaveMind Crypto Signal Quality Benchmark

Walk-forward benchmark for separating always-on price forecasts from trade-quality subsets. This is not financial advice.

The price forecast always exists. The signal tier is a historical evidence filter, not a calibrated probability.

## Summary

| tier | selected | coverage | direction hit | MAE return | MAPE | within 50 bps | worst slice hit | mean agreement | mean strength |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_forecasts | 2880 | 1.000 | 0.591 | 392.4 bps | 4.05% | 0.096 | 0.411 | 0.264 | 0.945 |
| broad_trade_quality | 373 | 0.130 | 0.531 | 582.5 bps | 6.59% | 0.075 | 0.000 | 0.533 | 1.056 |
| strong_trade_quality | 267 | 0.093 | 0.524 | 670.5 bps | 7.79% | 0.060 | 0.000 | 0.537 | 1.339 |
| high_conviction | 207 | 0.072 | 0.556 | 726.2 bps | 8.61% | 0.068 | 0.000 | 0.530 | 1.547 |
| large_move_directional_edge | 39 | 0.014 | 0.872 | 771.2 bps | 10.53% | 0.103 | 0.000 | 0.327 | 2.989 |
| consensus_edge | 0 | 0.000 | 0.000 | inf bps | inf% | 0.000 | 0.000 | 0.000 | 0.000 |
| strict_consensus_edge | 0 | 0.000 | 0.000 | inf bps | inf% | 0.000 | 0.000 | 0.000 | 0.000 |

## By Timeframe

| tier | timeframe | selected | coverage | direction hit | MAE return | MAPE |
|---|---|---:|---:|---:|---:|---:|
| all_forecasts | 1h | 1440 | 1.000 | 0.665 | 440.4 bps | 4.71% |
| all_forecasts | 4h | 1440 | 1.000 | 0.517 | 344.5 bps | 3.39% |
| broad_trade_quality | 1h | 285 | 0.198 | 0.502 | 662.4 bps | 7.64% |
| broad_trade_quality | 4h | 88 | 0.061 | 0.625 | 323.7 bps | 3.20% |
| strong_trade_quality | 1h | 253 | 0.176 | 0.514 | 685.8 bps | 8.00% |
| strong_trade_quality | 4h | 14 | 0.010 | 0.714 | 394.9 bps | 3.90% |
| high_conviction | 1h | 206 | 0.143 | 0.553 | 728.1 bps | 8.63% |
| high_conviction | 4h | 1 | 0.001 | 1.000 | 327.2 bps | 3.14% |
| large_move_directional_edge | 1h | 39 | 0.027 | 0.872 | 771.2 bps | 10.53% |
| large_move_directional_edge | 4h | 0 | 0.000 | 0.000 | inf bps | inf% |
| consensus_edge | 1h | 0 | 0.000 | 0.000 | inf bps | inf% |
| consensus_edge | 4h | 0 | 0.000 | 0.000 | inf bps | inf% |
| strict_consensus_edge | 1h | 0 | 0.000 | 0.000 | inf bps | inf% |
| strict_consensus_edge | 4h | 0 | 0.000 | 0.000 | inf bps | inf% |

Interpretation: higher tiers are diagnostics, not guarantees. Some tiers optimize direction hit, others should also improve target error. A high tier with tiny coverage is evidence of selective edge, not a standalone trading system.
