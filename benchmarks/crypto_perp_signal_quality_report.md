# WaveMind Crypto Signal Quality Benchmark

Walk-forward benchmark for separating always-on price forecasts from trade-quality subsets. This is not financial advice.

The price forecast always exists. The signal tier is a historical evidence filter, not a calibrated probability.

## Summary

| tier | selected | coverage | direction hit | MAE return | MAPE | within 50 bps | worst slice hit | mean agreement | mean strength |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_forecasts | 2880 | 1.000 | 0.591 | 392.4 bps | 4.05% | 0.096 | 0.411 | 0.743 | 0.945 |
| broad_trade_quality | 1879 | 0.652 | 0.639 | 397.2 bps | 4.15% | 0.089 | 0.346 | 0.764 | 1.352 |
| strong_trade_quality | 1392 | 0.483 | 0.677 | 410.7 bps | 4.37% | 0.082 | 0.000 | 0.759 | 1.699 |
| high_conviction | 1171 | 0.407 | 0.711 | 398.4 bps | 4.27% | 0.088 | 0.000 | 0.764 | 1.904 |
| large_move_directional_edge | 94 | 0.033 | 0.734 | 674.7 bps | 8.13% | 0.074 | 0.000 | 0.807 | 2.907 |
| consensus_edge | 0 | 0.000 | 0.000 | inf bps | inf% | 0.000 | 0.000 | 0.000 | 0.000 |
| strict_consensus_edge | 0 | 0.000 | 0.000 | inf bps | inf% | 0.000 | 0.000 | 0.000 | 0.000 |

## By Timeframe

| tier | timeframe | selected | coverage | direction hit | MAE return | MAPE |
|---|---|---:|---:|---:|---:|---:|
| all_forecasts | 1h | 1440 | 1.000 | 0.665 | 440.4 bps | 4.71% |
| all_forecasts | 4h | 1440 | 1.000 | 0.517 | 344.5 bps | 3.39% |
| broad_trade_quality | 1h | 1324 | 0.919 | 0.686 | 408.5 bps | 4.37% |
| broad_trade_quality | 4h | 555 | 0.385 | 0.526 | 370.2 bps | 3.63% |
| strong_trade_quality | 1h | 1233 | 0.856 | 0.701 | 409.0 bps | 4.40% |
| strong_trade_quality | 4h | 159 | 0.110 | 0.497 | 423.5 bps | 4.15% |
| high_conviction | 1h | 1125 | 0.781 | 0.724 | 396.8 bps | 4.27% |
| high_conviction | 4h | 46 | 0.032 | 0.391 | 437.7 bps | 4.40% |
| large_move_directional_edge | 1h | 93 | 0.065 | 0.742 | 677.1 bps | 8.17% |
| large_move_directional_edge | 4h | 1 | 0.001 | 0.000 | 448.8 bps | 4.55% |
| consensus_edge | 1h | 0 | 0.000 | 0.000 | inf bps | inf% |
| consensus_edge | 4h | 0 | 0.000 | 0.000 | inf bps | inf% |
| strict_consensus_edge | 1h | 0 | 0.000 | 0.000 | inf bps | inf% |
| strict_consensus_edge | 4h | 0 | 0.000 | 0.000 | inf bps | inf% |

Interpretation: higher tiers are diagnostics, not guarantees. Some tiers optimize direction hit, others should also improve target error. A high tier with tiny coverage is evidence of selective edge, not a standalone trading system.

## Coverage Frontier

Best observed coverage at each minimum historical direction-hit target. This is a diagnostic frontier, not a calibrated probability and not a forward guarantee.

| target hit | status | selected | coverage | direction hit | worst slice hit | MAPE | thresholds |
|---:|---|---:|---:|---:|---:|---:|---|
| 0.60 | found | 2482 | 0.862 | 0.600 | 0.235 | 3.75% | agreement>=0.625, strength>=0.000, magnitude>=0bps, vol<=250bps |
| 0.70 | found | 1236 | 0.429 | 0.701 | 0.000 | 3.93% | agreement>=0.625, strength>=0.500, magnitude>=0bps, vol<=200bps |
| 0.75 | found | 702 | 0.244 | 0.751 | 0.176 | 2.93% | agreement>=0.625, strength>=1.000, magnitude>=0bps, vol<=100bps |
| 0.80 | found | 273 | 0.095 | 0.806 | 0.000 | 2.79% | agreement>=0.875, strength>=0.750, magnitude>=50bps, vol<=100bps |
| 0.85 | found | 34 | 0.012 | 0.882 | 0.000 | 4.59% | agreement>=0.875, strength>=0.000, magnitude>=300bps, vol<=150bps |

## Slice-Stable Frontier

Same search, but each selected policy must cover at least 75% of market slices and keep worst-slice direction hit at or above 0.50. This is the stricter test for broad usefulness.

| target hit | status | selected | coverage | slice coverage | direction hit | worst slice hit | MAPE | thresholds |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 0.60 | not_found | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00% | agreement>=0.000, strength>=0.000, magnitude>=0bps, vol<=inf |
| 0.70 | not_found | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00% | agreement>=0.000, strength>=0.000, magnitude>=0bps, vol<=inf |
| 0.75 | not_found | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00% | agreement>=0.000, strength>=0.000, magnitude>=0bps, vol<=inf |
| 0.80 | not_found | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00% | agreement>=0.000, strength>=0.000, magnitude>=0bps, vol<=inf |
| 0.85 | not_found | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00% | agreement>=0.000, strength>=0.000, magnitude>=0bps, vol<=inf |
