# Capitulation Coverage Transfer

A development-only search tests whether causal liquidation context can broaden the frozen return/open-interest rebound signal.

- source: official Binance USD-M futures bundles and checksum-verified Binance COIN-M liquidation snapshots;
- horizon: 24h from completed 4h candles;
- final period: April 2024 through October 14, 2024;
- selected policy: return q0.01, OI q0.10, none.

| split | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|---:|
| development selected | 50 | 1.6% | 82.0% | 69.2% | 63.6% | 37.5% |
| final selected | 79 | 3.1% | 63.3% | 52.3% | 53.8% | 20.0% |
| final legacy event | 79 | 3.1% | 63.3% | 52.3% | 53.8% | 20.0% |

70% admission: **rejected**

## Development Leaderboard

| return q | OI q | liquidation policy | signals | accuracy | Wilson low | worst fold |
|---:|---:|---|---:|---:|---:|---:|
| 0.01 | 0.10 | none | 50 | 82.0% | 69.2% | 63.6% |
| 0.01 | 0.10 | rolling_burst | 50 | 82.0% | 69.2% | 63.6% |
| 0.01 | 0.20 | none | 61 | 83.6% | 72.4% | 61.5% |
| 0.01 | 0.20 | rolling_burst | 61 | 83.6% | 72.4% | 61.5% |
| 0.01 | 0.10 | current_sell | 45 | 84.4% | 71.2% | 60.0% |
| 0.01 | 0.10 | rolling_sell | 49 | 81.6% | 68.6% | 60.0% |
| 0.01 | 0.10 | rolling_sell_burst | 49 | 81.6% | 68.6% | 60.0% |
| 0.01 | 0.30 | none | 64 | 82.8% | 71.8% | 57.1% |
| 0.01 | 0.30 | rolling_burst | 63 | 82.5% | 71.4% | 57.1% |
| 0.01 | 0.50 | rolling_burst | 67 | 80.6% | 69.6% | 57.1% |

The final period is not part of configuration ranking. A positive average does not pass unless Wilson, fold, asset, and support checks also pass.
