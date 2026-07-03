# WaveMind Crypto Confidence Calibration

This report checks whether evidence strength behaves like a calibrated probability.
It is a research diagnostic, not a trading signal.

## WaveMind timeframe policy

- signal events: 363
- Brier if treated as probability: 0.347
- expected calibration error: 0.299
- probability ready: false

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.0-0.2 | 0 | 0.000 | 0.000 | 0.000 | 0.00 |
| 0.2-0.4 | 13 | 0.350 | 0.462 | 0.112 | 35.18 |
| 0.4-0.6 | 78 | 0.535 | 0.718 | 0.183 | 185.03 |
| 0.6-0.8 | 60 | 0.671 | 0.717 | 0.045 | 141.52 |
| 0.8-1.0 | 212 | 0.968 | 0.542 | 0.426 | 42.26 |
