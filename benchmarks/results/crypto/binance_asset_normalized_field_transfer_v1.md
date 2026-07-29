# Frozen Asset-Normalized WaveField Transfer

This is a one-read asset-and-time-disjoint WaveField holdout. The protocol was committed before all 8 holdout assets were downloaded or evaluated.

- protocol SHA-256: `ad4375c7bf61b9f512e6eef48a89436526ebb921976c5c989aea38c3b4b99614`;
- assets: ARUSDT, BALUSDT, CHRUSDT, FLOWUSDT, GALAUSDT, GMTUSDT, KNCUSDT, ONEUSDT;
- prediction: rebound over the next 24 hours;
- overlap: one signal per asset until the 24h target matures.

| view | observations | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| asset signals | 41 | 70.7% | 55.5% |
| UTC market blocks | 31 | 67.7% | 50.1% |
| market episodes | 23 | 73.9% | 53.5% |

Strict 70% gate: **rejected**

## Fold Stability

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 0 | 11 | 100.0% | 74.1% |
| 1 | 15 | 60.0% | 35.7% |
| 2 | 8 | 75.0% | 40.9% |
| 3 | 4 | 50.0% | 15.0% |
| 4 | 3 | 33.3% | 6.1% |

## Asset Stability

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| ARUSDT | 6 | 50.0% | 18.8% |
| BALUSDT | 7 | 71.4% | 35.9% |
| CHRUSDT | 5 | 100.0% | 56.6% |
| FLOWUSDT | 3 | 33.3% | 6.1% |
| GALAUSDT | 4 | 50.0% | 15.0% |
| GMTUSDT | 4 | 75.0% | 30.1% |
| KNCUSDT | 4 | 75.0% | 30.1% |
| ONEUSDT | 8 | 87.5% | 52.9% |

No threshold, asset, direction, fold, or gate is changed after the holdout is read. A failed gate remains part of the report.
