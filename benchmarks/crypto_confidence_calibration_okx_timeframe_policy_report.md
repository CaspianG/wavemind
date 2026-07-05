# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 29
- raw Brier if treated as probability: 0.375
- raw expected calibration error: 0.335
- monotonic Brier: 0.386
- monotonic expected calibration error: 0.275
- monotonic out-of-sample: true
- base-rate probability: 0.586
- base-rate Brier: 0.276
- base-rate expected calibration error: 0.208
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 2 | 0.375 | 0.688 | 0.211 | false |
| symbol | 0 | 0.000 | 0.000 | 0.000 | false |
| timeframe | 1 | 0.609 | 0.609 | 0.022 | false |
| symbol_timeframe | 1 | 0.500 | 0.500 | 0.086 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.4-0.6 | 8 | 0.536 | 0.625 | 0.089 | 116.99 |
| 0.6-0.8 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.8-1.0 | 21 | 1.000 | 0.571 | 0.429 | 2.14 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.4-1.0 | 29 | 0.872 | 0.586 |
