# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 52
- raw Brier if treated as probability: 0.271
- raw expected calibration error: 0.293
- monotonic Brier: 0.192
- monotonic expected calibration error: 0.017
- monotonic out-of-sample: true
- base-rate probability: 0.750
- base-rate Brier: 0.192
- base-rate expected calibration error: 0.017
- probability ready: false
- probability kind: none

### Stability Checks

| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |
|---|---:|---:|---:|---:|---|
| fold | 3 | 0.733 | 0.810 | 0.060 | false |
| symbol | 0 | 0.000 | 0.000 | 0.000 | false |
| timeframe | 1 | 0.733 | 0.733 | 0.017 | false |
| symbol_timeframe | 1 | 0.857 | 0.857 | 0.107 | false |

### Raw Evidence Buckets

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.4-0.6 | 9 | 0.528 | 0.889 | 0.361 | 60.34 |
| 0.6-0.8 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.8-1.0 | 43 | 1.000 | 0.721 | 0.279 | 104.17 |

### Monotonic Calibration Blocks

| evidence range | train count | avg evidence | calibrated probability |
|---|---:|---:|---:|
| 0.4-1.0 | 52 | 0.918 | 0.750 |
