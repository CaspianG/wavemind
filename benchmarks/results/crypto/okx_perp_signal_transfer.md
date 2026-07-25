# Nested Signal-Policy Transfer Benchmark

Forecasts are collapsed to one independent observation per horizon. A threshold policy is selected from earlier folds only and then frozen for the next fold.

- raw events: 2880;
- independent events: 304;
- transferred signals: 148;
- transferred accuracy: 48.6%;
- Wilson lower 95%: 40.7%;
- admitted at 70%: no.

## Fold Transfer

| timeframe | test fold | selection | train signals | train accuracy | policy | test signals | test accuracy | Wilson low |
|---|---:|---|---:|---:|---|---:|---:|---:|
| 1h | 1 | insufficient_history | 16 | 87.5% | a>=0.00, s>=0.00, m>=0, v<=inf | 16 | 62.5% | 38.6% |
| 1h | 2 | target_reached | 32 | 75.0% | a>=0.00, s>=0.00, m>=0, v<=inf | 16 | 37.5% | 18.5% |
| 1h | 3 | target_reached | 38 | 73.7% | a>=0.00, s>=0.00, m>=50, v<=inf | 13 | 69.2% | 42.4% |
| 4h | 1 | target_reached | 27 | 74.1% | a>=0.00, s>=0.25, m>=0, v<=inf | 29 | 41.4% | 25.5% |
| 4h | 2 | best_available | 47 | 63.8% | a>=0.00, s>=0.25, m>=0, v<=250 | 17 | 41.2% | 21.6% |
| 4h | 3 | best_available | 153 | 54.2% | a>=0.00, s>=0.00, m>=0, v<=250 | 57 | 49.1% | 36.6% |

## Transferred Slices

| symbol | timeframe | signals | accuracy | Wilson low |
|---|---|---:|---:|---:|
| HYPE/USDT:USDT | 1h | 11 | 63.6% | 35.4% |
| HYPE/USDT:USDT | 4h | 27 | 44.4% | 27.6% |
| SOL/USDT:USDT | 1h | 12 | 50.0% | 25.4% |
| SOL/USDT:USDT | 4h | 23 | 39.1% | 22.2% |
| XRP/USDT:USDT | 1h | 11 | 54.5% | 28.0% |
| XRP/USDT:USDT | 4h | 25 | 52.0% | 33.5% |
| ZEC/USDT:USDT | 1h | 11 | 54.5% | 28.0% |
| ZEC/USDT:USDT | 4h | 28 | 46.4% | 29.5% |

No policy passes the independent 70% transfer gate.
