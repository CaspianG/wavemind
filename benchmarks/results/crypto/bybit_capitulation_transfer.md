# Frozen Cross-Exchange Post-Capitulation Transfer

The Binance-derived rule is evaluated unchanged on official Bybit data, new assets, four forecast horizons, and a new July 2026 fold.

- assets: APTUSDT, CRVUSDT, ENJUSDT, IOTAUSDT, KAVAUSDT, NEARUSDT, OPUSDT, SNXUSDT;
- frozen rule: return q0.01, OI q0.10, decelerating_selloff;
- source interval: 4h completed candles and 4h open interest;
- dataset SHA-256: `2c71a93229d61148a863df4fbf7527bd10b4c1ebf67c87b9abb596fa34713552`.

| horizon | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|---:|
| 12h | 60 | 0.3% | 66.7% | 54.1% | 20.0% | 37.5% |
| 24h | 56 | 0.6% | 60.7% | 47.6% | 33.3% | 42.9% |
| 48h | 48 | 1.1% | 64.6% | 50.4% | 50.0% | 28.6% |
| 7d | 50 | 3.8% | 52.0% | 38.5% | 28.6% | 28.6% |

24h aggregate 70% evidence: **rejected**

24h stable admission: **rejected**

All-horizon aggregate 70% evidence: **rejected**

## 24h Time Folds

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 2 | 3 | 0.0% | 0.0% |
| 3 | 13 | 84.6% | 57.8% |
| 4 | 7 | 100.0% | 64.6% |
| 5 | 6 | 33.3% | 9.7% |
| 6 | 6 | 50.0% | 18.8% |
| 8 | 12 | 66.7% | 39.1% |
| 9 | 4 | 25.0% | 4.6% |
| 10 | 2 | 100.0% | 34.2% |
| 11 | 3 | 0.0% | 0.0% |

## 24h Assets

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| APTUSDT | 4 | 100.0% | 51.0% |
| CRVUSDT | 6 | 83.3% | 43.6% |
| ENJUSDT | 7 | 71.4% | 35.9% |
| IOTAUSDT | 7 | 42.9% | 15.8% |
| KAVAUSDT | 7 | 57.1% | 25.0% |
| NEARUSDT | 7 | 71.4% | 35.9% |
| OPUSDT | 9 | 44.4% | 18.9% |
| SNXUSDT | 9 | 44.4% | 18.9% |

This is a transfer test, not a threshold search. A result is not admitted merely because its average exceeds 70%; the Wilson, fold, asset, and support gates remain binding.
