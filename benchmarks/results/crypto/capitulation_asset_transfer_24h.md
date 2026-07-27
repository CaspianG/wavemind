# Frozen Post-Capitulation Asset Transfer

A 13-asset development result is transferred unchanged to 16 different Binance futures assets.

- source: official Binance USD-M futures archives;
- horizon: 24h from completed 4h candles;
- frozen rule: return q0.01, OI q0.10, decelerating_selloff;
- period: July 2023 through June 2026.

| split | assets | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | 13 | 107 | 0.8% | 80.4% | 71.9% | 40.0% | 70.0% |
| asset-disjoint holdout | 16 | 137 | 0.8% | 74.5% | 66.6% | 50.0% | 42.9% |
| holdout without confirmation | 16 | 339 | 2.1% | 70.8% | 65.7% | 47.1% | 62.1% |

Aggregate 70% evidence: **passed**

Stable 70% admission: **rejected**

## Holdout Folds

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 0 | 3 | 66.7% | 20.8% |
| 1 | 2 | 50.0% | 9.5% |
| 2 | 7 | 100.0% | 64.6% |
| 3 | 31 | 71.0% | 53.4% |
| 4 | 20 | 75.0% | 53.1% |
| 5 | 21 | 61.9% | 40.9% |
| 6 | 19 | 78.9% | 56.7% |
| 7 | 1 | 100.0% | 20.7% |
| 8 | 15 | 80.0% | 54.8% |
| 9 | 6 | 50.0% | 18.8% |
| 10 | 10 | 100.0% | 72.2% |
| 11 | 2 | 50.0% | 9.5% |

## Holdout Assets

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| AAVEUSDT | 10 | 80.0% | 49.0% |
| ALGOUSDT | 9 | 88.9% | 56.5% |
| COMPUSDT | 5 | 100.0% | 56.6% |
| DASHUSDT | 7 | 42.9% | 15.8% |
| FILUSDT | 10 | 70.0% | 39.7% |
| GRTUSDT | 8 | 50.0% | 21.5% |
| HBARUSDT | 8 | 75.0% | 40.9% |
| MANAUSDT | 7 | 57.1% | 25.0% |
| RUNEUSDT | 19 | 68.4% | 46.0% |
| SANDUSDT | 7 | 71.4% | 35.9% |
| THETAUSDT | 8 | 87.5% | 52.9% |
| UNIUSDT | 9 | 77.8% | 45.3% |
| VETUSDT | 7 | 100.0% | 64.6% |
| XMRUSDT | 6 | 100.0% | 61.0% |
| XTZUSDT | 5 | 60.0% | 23.1% |
| ZECUSDT | 12 | 75.0% | 46.8% |

The aggregate and stable gates are separate: a high average does not become a production claim when a supported time or asset slice remains below 65%.
