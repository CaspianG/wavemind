# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 173
- raw Brier if treated as probability: 0.323
- raw expected calibration error: 0.334
- monotonic Brier: 0.244
- monotonic expected calibration error: 0.123
- monotonic out-of-sample: true
- base-rate probability: 0.676
- base-rate Brier: 0.230
- base-rate expected calibration error: 0.029
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 4 | 0.533 | 0.742 | 0.143 | true |
| symbol | 5 | 0.600 | 0.697 | 0.076 | true |
| timeframe | 2 | 0.562 | 0.720 | 0.114 | true |
| symbol_timeframe | 6 | 0.579 | 0.788 | 0.112 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 8 | 0.350 | 0.875 | 0.525 | 668.00 |
| 0.4-0.6 | 41 | 0.541 | 0.780 | 0.239 | 214.46 |
| 0.6-0.8 | 10 | 0.646 | 0.900 | 0.254 | 330.15 |
| 0.8-1.0 | 114 | 0.968 | 0.605 | 0.362 | 129.92 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.2-1.0 | 173 | 0.819 | 0.676 |
