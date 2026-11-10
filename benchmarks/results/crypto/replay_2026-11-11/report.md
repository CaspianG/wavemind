# Three-month daily seven-day forecast replay

Frozen model: `b8341ec5b2ba4d28a6b71c7cbb32aaf1b23ae9ba540e1a5b5186cb495a768a5e`. Protocol: `0ce70c40d7d826c697e9c97f563d113dab671b0e31d9ea8f20956f189f5133e0`.
Daily origins: 2026-08-11T00:00:00+00:00 to 2026-11-11T00:00:00+00:00 (exclusive).
As of 2026-11-10T23:15:49.365007+00:00: 680 matured and 56 pending asset forecasts.

Every forecast reuses the unchanged live runner with only the preceding 800 completed daily candles.
The weekly entry policy is unsupported; research estimates are scored separately from admitted trades.
This replay reconstructs historical predictions. It is not a record of predictions published on those dates.

## Overall

| model | forecasts | direction accuracy | target-price MAPE | interval coverage |
|---|---:|---:|---:|---:|
| WaveMind research | 680 | 47.8% | 7.09% | 77.9% |
| WaveMind validated | 0 | n/a | n/a | n/a |
| Last price | 680 | n/a | 6.72% | n/a |
| Always up | 680 | 41.0% | 6.72% | n/a |
| Weekly momentum | 680 | 51.3% | 10.51% | n/a |
| Weekly mean reversion | 680 | 48.7% | 10.48% | n/a |

## By asset

| symbol | forecasts | WaveMind accuracy | always up | momentum | mean reversion | WaveMind MAPE |
|---|---:|---:|---:|---:|---:|---:|
| ADA/USDT:USDT | 85 | 45.9% | 38.8% | 48.2% | 51.8% | 9.19% |
| AVAX/USDT:USDT | 85 | 48.2% | 43.5% | 51.8% | 48.2% | 8.61% |
| BTC/USDT:USDT | 85 | 44.7% | 44.7% | 44.7% | 55.3% | 4.34% |
| DOGE/USDT:USDT | 85 | 50.6% | 32.9% | 52.9% | 47.1% | 7.88% |
| ETH/USDT:USDT | 85 | 54.1% | 45.9% | 56.5% | 43.5% | 5.13% |
| GRAM/USDT:USDT | 85 | 37.6% | 40.0% | 47.1% | 52.9% | 6.48% |
| SOL/USDT:USDT | 85 | 60.0% | 44.7% | 65.9% | 34.1% | 6.69% |
| XRP/USDT:USDT | 85 | 41.2% | 37.6% | 43.5% | 56.5% | 8.42% |

## By origin month

| month | forecasts | WaveMind accuracy | always up | momentum | mean reversion | WaveMind MAPE |
|---|---:|---:|---:|---:|---:|---:|
| 2026-08 | 168 | 39.9% | 66.1% | 34.5% | 65.5% | 10.20% |
| 2026-09 | 240 | 47.5% | 62.9% | 34.2% | 65.8% | 6.50% |
| 2026-10 | 248 | 52.0% | 6.5% | 75.0% | 25.0% | 5.58% |
| 2026-11 | 24 | 62.5% | 4.2% | 95.8% | 4.2% | 6.85% |

## By observable market regime

| regime | forecasts | WaveMind accuracy | always up | momentum | mean reversion | WaveMind MAPE |
|---|---:|---:|---:|---:|---:|---:|
| falling | 139 | 61.9% | 19.4% | 79.1% | 20.9% | 6.40% |
| rising | 393 | 46.8% | 44.5% | 38.7% | 61.3% | 6.90% |
| sideways | 148 | 37.2% | 52.0% | 58.8% | 41.2% | 8.24% |

## Non-overlapping weekly phases

| phase | forecasts | WaveMind accuracy | always up | momentum | mean reversion | WaveMind MAPE |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 104 | 46.2% | 43.3% | 44.2% | 55.8% | 7.30% |
| 1 | 96 | 40.6% | 40.6% | 44.8% | 55.2% | 7.69% |
| 2 | 96 | 49.0% | 49.0% | 37.5% | 62.5% | 6.04% |
| 3 | 96 | 58.3% | 37.5% | 65.6% | 34.4% | 6.09% |
| 4 | 96 | 46.9% | 38.5% | 61.5% | 38.5% | 7.04% |
| 5 | 96 | 50.0% | 39.6% | 54.2% | 45.8% | 6.90% |
| 6 | 96 | 43.8% | 38.5% | 52.1% | 47.9% | 8.58% |

Daily seven-day forecasts overlap. Each phase has disjoint horizons within each asset,
but assets still share market exposure. Asset rows and phases are not independent replications.
Regimes use only the preceding 30-day return: rising above +5%, falling below -5%, otherwise sideways.
Always-up is a direction control with a fixed +1 bp target. Last price is the zero-return price control.
No thresholds, coins, months, or best phase were selected after observing the outcomes.
Price errors and direction accuracy do not include execution costs and are not trading returns.
