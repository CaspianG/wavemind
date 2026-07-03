# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 204
- raw Brier if treated as probability: 0.256
- raw expected calibration error: 0.266
- monotonic Brier: 0.343
- monotonic expected calibration error: 0.361
- monotonic out-of-sample: true
- base-rate probability: 0.740
- base-rate Brier: 0.259
- base-rate expected calibration error: 0.298
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 3 | 0.154 | 0.851 | 0.586 | false |
| symbol | 7 | 0.679 | 0.833 | 0.093 | false |
| timeframe | 1 | 0.740 | 0.740 | 0.000 | true |
| symbol_timeframe | 8 | 0.579 | 0.833 | 0.161 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 8 | 0.350 | 0.875 | 0.525 | 668.00 |
| 0.4-0.6 | 55 | 0.541 | 0.764 | 0.222 | 259.33 |
| 0.6-0.8 | 16 | 0.708 | 1.000 | 0.292 | 405.19 |
| 0.8-1.0 | 125 | 0.953 | 0.688 | 0.265 | 179.83 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.2-1.0 | 204 | 0.799 | 0.740 |
