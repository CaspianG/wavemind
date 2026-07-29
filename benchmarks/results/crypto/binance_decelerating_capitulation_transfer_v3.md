# Frozen Decelerating-Capitulation Transfer

This is a one-read asset-disjoint holdout. The protocol was committed before all 16 holdout assets were downloaded or evaluated.

- protocol SHA-256: `9b52cc90e94468963a66f40e5944cf351a990d08989f06ec8cc8660f95cfdfa3`;
- assets: 1INCHUSDT, ARUSDT, BALUSDT, CHRUSDT, CHZUSDT, ENJUSDT, FLOWUSDT, GALAUSDT, GMTUSDT, ICPUSDT, IOTAUSDT, KNCUSDT, MKRUSDT, ONEUSDT, SUSHIUSDT, ZILUSDT;
- prediction: rebound over the next 24 hours;
- overlap: one signal per asset until the 24h target matures.

| view | observations | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| asset signals | 55 | 76.4% | 63.7% |
| UTC market blocks | 19 | 73.7% | 51.2% |
| market episodes | 16 | 75.0% | 50.5% |

Strict 70% gate: **rejected**

## Fold Stability

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 0 | 21 | 76.2% | 54.9% |
| 1 | 12 | 75.0% | 46.8% |
| 2 | 7 | 100.0% | 64.6% |
| 3 | 12 | 66.7% | 39.1% |
| 4 | 3 | 66.7% | 20.8% |

## Asset Stability

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| 1INCHUSDT | 3 | 66.7% | 20.8% |
| ARUSDT | 7 | 71.4% | 35.9% |
| BALUSDT | 2 | 100.0% | 34.2% |
| CHRUSDT | 2 | 100.0% | 34.2% |
| CHZUSDT | 4 | 50.0% | 15.0% |
| ENJUSDT | 4 | 100.0% | 51.0% |
| FLOWUSDT | 2 | 100.0% | 34.2% |
| GALAUSDT | 5 | 80.0% | 37.6% |
| GMTUSDT | 6 | 66.7% | 30.0% |
| ICPUSDT | 2 | 100.0% | 34.2% |
| IOTAUSDT | 3 | 66.7% | 20.8% |
| KNCUSDT | 4 | 50.0% | 15.0% |
| ONEUSDT | 3 | 100.0% | 43.9% |
| SUSHIUSDT | 4 | 100.0% | 51.0% |
| ZILUSDT | 4 | 50.0% | 15.0% |

No threshold, asset, direction, fold, or gate is changed after the holdout is read. A failed gate remains part of the report.
