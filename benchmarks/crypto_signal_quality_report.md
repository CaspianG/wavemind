# WaveMind Crypto Signal Quality Benchmark

Walk-forward benchmark for separating always-on price forecasts from trade-quality subsets. This is not financial advice.

The price forecast always exists. The signal tier is a historical evidence filter, not a calibrated probability.

## Summary

| tier | selected | coverage | direction hit | MAE return | MAPE | within 50 bps | worst slice hit | mean agreement | mean strength |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_forecasts | 8640 | 1.000 | 0.562 | 367.4 bps | 3.80% | 0.128 | 0.178 | 0.646 | 0.897 |
| broad_trade_quality | 4224 | 0.489 | 0.576 | 261.3 bps | 2.64% | 0.156 | 0.150 | 0.727 | 1.235 |
| strong_trade_quality | 3231 | 0.374 | 0.578 | 246.0 bps | 2.46% | 0.163 | 0.162 | 0.725 | 1.500 |
| high_conviction | 2540 | 0.294 | 0.578 | 245.6 bps | 2.45% | 0.162 | 0.190 | 0.723 | 1.742 |
| consensus_edge | 328 | 0.038 | 0.738 | 228.9 bps | 2.25% | 0.128 | 0.000 | 1.000 | 1.383 |
| strict_consensus_edge | 216 | 0.025 | 0.750 | 213.1 bps | 2.11% | 0.148 | 0.000 | 1.000 | 1.695 |

## By Timeframe

| tier | timeframe | selected | coverage | direction hit | MAE return | MAPE |
|---|---|---:|---:|---:|---:|---:|
| all_forecasts | 1d | 2880 | 1.000 | 0.587 | 632.5 bps | 6.66% |
| all_forecasts | 1h | 2880 | 1.000 | 0.557 | 189.1 bps | 1.87% |
| all_forecasts | 4h | 2880 | 1.000 | 0.542 | 280.5 bps | 2.86% |
| broad_trade_quality | 1d | 447 | 0.155 | 0.622 | 516.9 bps | 5.42% |
| broad_trade_quality | 1h | 2019 | 0.701 | 0.589 | 191.1 bps | 1.88% |
| broad_trade_quality | 4h | 1758 | 0.610 | 0.549 | 277.0 bps | 2.81% |
| strong_trade_quality | 1d | 202 | 0.070 | 0.569 | 487.1 bps | 4.98% |
| strong_trade_quality | 1h | 1823 | 0.633 | 0.592 | 190.7 bps | 1.88% |
| strong_trade_quality | 4h | 1206 | 0.419 | 0.559 | 289.3 bps | 2.91% |
| high_conviction | 1d | 140 | 0.049 | 0.593 | 489.8 bps | 5.02% |
| high_conviction | 1h | 1593 | 0.553 | 0.586 | 192.1 bps | 1.89% |
| high_conviction | 4h | 807 | 0.280 | 0.560 | 308.8 bps | 3.11% |
| consensus_edge | 1d | 0 | 0.000 | 0.000 | inf bps | inf% |
| consensus_edge | 1h | 248 | 0.086 | 0.790 | 224.7 bps | 2.19% |
| consensus_edge | 4h | 80 | 0.028 | 0.575 | 242.1 bps | 2.44% |
| strict_consensus_edge | 1d | 0 | 0.000 | 0.000 | inf bps | inf% |
| strict_consensus_edge | 1h | 163 | 0.057 | 0.828 | 199.3 bps | 1.96% |
| strict_consensus_edge | 4h | 53 | 0.018 | 0.509 | 255.6 bps | 2.58% |

Interpretation: higher tiers should improve direction hit and target error while reducing coverage. A high tier with tiny coverage is evidence of selective edge, not a standalone trading system.
