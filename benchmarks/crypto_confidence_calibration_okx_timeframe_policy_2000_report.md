# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 10
- raw Brier if treated as probability: 0.368
- raw expected calibration error: 0.336
- monotonic Brier: 0.519
- monotonic expected calibration error: 0.648
- monotonic out-of-sample: true
- base-rate probability: 0.600
- base-rate Brier: 0.519
- base-rate expected calibration error: 0.648
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 0 | 0.000 | 0.000 | 0.000 | false |
| symbol | 0 | 0.000 | 0.000 | 0.000 | false |
| timeframe | 0 | 0.000 | 0.000 | 0.000 | false |
| symbol_timeframe | 0 | 0.000 | 0.000 | 0.000 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.4-0.6 | 3 | 0.548 | 0.667 | 0.119 | 31.38 |
| 0.6-0.8 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.8-1.0 | 7 | 1.000 | 0.571 | 0.429 | 25.24 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.4-1.0 | 10 | 0.864 | 0.600 |
