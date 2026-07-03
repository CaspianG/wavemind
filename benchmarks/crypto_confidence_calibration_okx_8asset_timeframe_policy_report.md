# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 281
- raw Brier if treated as probability: 0.290
- raw expected calibration error: 0.292
- monotonic Brier: 0.236
- monotonic expected calibration error: 0.089
- monotonic out-of-sample: true
- base-rate probability: 0.705
- base-rate Brier: 0.225
- base-rate expected calibration error: 0.043
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 4 | 0.577 | 0.780 | 0.128 | true |
| symbol | 8 | 0.600 | 0.794 | 0.105 | true |
| timeframe | 2 | 0.610 | 0.740 | 0.094 | true |
| symbol_timeframe | 10 | 0.579 | 0.833 | 0.129 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 9 | 0.350 | 0.889 | 0.539 | 604.16 |
| 0.4-0.6 | 68 | 0.539 | 0.750 | 0.211 | 215.27 |
| 0.6-0.8 | 30 | 0.676 | 0.900 | 0.224 | 258.76 |
| 0.8-1.0 | 174 | 0.966 | 0.644 | 0.322 | 131.42 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.2-1.0 | 281 | 0.812 | 0.705 |
