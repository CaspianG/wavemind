# Dynamic Asset-Disjoint WaveField Transfer

The ExtraTrees event head and WaveField memory are rebuilt before each fold from outcomes that matured on training assets only.

- training assets: 13;
- unseen holdout assets: 20;
- signals: 193 / 508 candidates;
- accuracy: 73.1%;
- Wilson low 95%: 66.4%;
- market episodes: 43, accuracy 69.8%;
- strict 70% gate: **rejected**.

## Fold Stability

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 0 | 51 | 70.6% | 57.0% |
| 1 | 45 | 64.4% | 49.8% |
| 2 | 36 | 86.1% | 71.3% |
| 3 | 28 | 85.7% | 68.5% |
| 4 | 33 | 63.6% | 46.6% |

## Asset Stability

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| AAVEUSDT | 15 | 80.0% | 54.8% |
| ALGOUSDT | 8 | 62.5% | 30.6% |
| APEUSDT | 10 | 80.0% | 49.0% |
| APTUSDT | 9 | 77.8% | 45.3% |
| AVAXUSDT | 9 | 77.8% | 45.3% |
| COMPUSDT | 8 | 62.5% | 30.6% |
| CRVUSDT | 7 | 57.1% | 25.0% |
| FILUSDT | 7 | 85.7% | 48.7% |
| LDOUSDT | 12 | 75.0% | 46.8% |
| MANAUSDT | 9 | 77.8% | 45.3% |
| NEARUSDT | 11 | 54.5% | 28.0% |
| OPUSDT | 11 | 63.6% | 35.4% |
| RUNEUSDT | 10 | 70.0% | 39.7% |
| SANDUSDT | 8 | 100.0% | 67.6% |
| THETAUSDT | 11 | 63.6% | 35.4% |
| TRXUSDT | 5 | 60.0% | 23.1% |
| UNIUSDT | 14 | 71.4% | 45.4% |
| WOOUSDT | 6 | 83.3% | 43.6% |
| XLMUSDT | 9 | 77.8% | 45.3% |
| XTZUSDT | 14 | 78.6% | 52.4% |

## Frozen-Threshold Diagnostic Ablation

This diagnostic was added after the primary holdout read and does not affect the strict gate.

| policy | signals | accuracy | Wilson low 95% | episodes | episode accuracy |
|---|---:|---:|---:|---:|---:|
| all_candidates | 508 | 66.3% | 62.1% | 57 | 77.2% |
| extra_trees_only | 248 | 73.8% | 68.0% | 46 | 69.6% |
| wavefield_only | 332 | 73.2% | 68.2% | 51 | 76.5% |
| joint_veto | 193 | 73.1% | 66.4% | 43 | 69.8% |

No holdout labels are used to rebuild either model. A failed gate remains part of the report.
