# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 31
- raw Brier if treated as probability: 0.380
- raw expected calibration error: 0.375
- monotonic Brier: 0.311
- monotonic expected calibration error: 0.364
- monotonic out-of-sample: true
- base-rate probability: 0.613
- base-rate Brier: 0.311
- base-rate expected calibration error: 0.364
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 2 | 0.444 | 1.000 | 0.387 | false |
| symbol | 0 | 0.000 | 0.000 | 0.000 | false |
| timeframe | 1 | 0.577 | 0.577 | 0.036 | false |
| symbol_timeframe | 0 | 0.000 | 0.000 | 0.000 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.4-0.6 | 8 | 0.548 | 0.750 | 0.202 | 63.24 |
| 0.6-0.8 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.8-1.0 | 23 | 1.000 | 0.565 | 0.435 | 5.41 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.4-1.0 | 31 | 0.883 | 0.613 |
