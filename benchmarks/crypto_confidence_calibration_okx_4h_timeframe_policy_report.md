# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 79
- raw Brier if treated as probability: 0.230
- raw expected calibration error: 0.244
- monotonic Brier: 0.301
- monotonic expected calibration error: 0.380
- monotonic out-of-sample: true
- base-rate probability: 0.772
- base-rate Brier: 0.281
- base-rate expected calibration error: 0.368
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 2 | 0.533 | 0.891 | 0.239 | false |
| symbol | 3 | 0.680 | 0.833 | 0.092 | true |
| timeframe | 1 | 0.772 | 0.772 | 0.000 | true |
| symbol_timeframe | 3 | 0.680 | 0.833 | 0.092 | true |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.4-0.6 | 22 | 0.538 | 0.773 | 0.235 | 277.40 |
| 0.6-0.8 | 12 | 0.725 | 1.000 | 0.275 | 298.01 |
| 0.8-1.0 | 45 | 0.951 | 0.711 | 0.240 | 156.99 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.4-1.0 | 79 | 0.802 | 0.772 |
