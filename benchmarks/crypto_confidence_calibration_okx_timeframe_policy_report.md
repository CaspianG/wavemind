# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 162
- raw Brier if treated as probability: 0.345
- raw expected calibration error: 0.258
- monotonic Brier: 0.285
- monotonic expected calibration error: 0.155
- monotonic out-of-sample: true
- base-rate probability: 0.512
- base-rate Brier: 0.277
- base-rate expected calibration error: 0.009
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 4 | 0.294 | 0.755 | 0.243 | false |
| symbol | 3 | 0.395 | 0.660 | 0.148 | false |
| timeframe | 2 | 0.418 | 0.579 | 0.094 | false |
| symbol_timeframe | 6 | 0.346 | 0.742 | 0.230 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 6 | 0.350 | 0.167 | 0.183 | -66.96 |
| 0.4-0.6 | 44 | 0.545 | 0.545 | 0.000 | 69.62 |
| 0.6-0.8 | 35 | 0.658 | 0.486 | 0.173 | -10.01 |
| 0.8-1.0 | 77 | 0.982 | 0.532 | 0.449 | 18.70 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.2-0.4 | 6 | 0.350 | 0.167 |
| 0.4-0.8 | 79 | 0.595 | 0.519 |
| 0.8-1.0 | 77 | 0.982 | 0.532 |
