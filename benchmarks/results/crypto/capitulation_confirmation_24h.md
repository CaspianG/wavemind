# Post-Capitulation Confirmation Transfer

This benchmark tests whether waiting for a causal stabilization signal improves extreme return/open-interest rebounds.

- source: official Binance USD-M futures archives;
- development cutoff: 2024-10-15;
- final period: 2024-10-15 through 2026-06-30;
- selected: return q0.02, OI q0.30, decelerating_selloff.

| split | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|---:|
| development selected | 138 | 2.4% | 71.0% | 63.0% | 59.2% | 50.0% |
| final selected | 149 | 1.9% | 64.4% | 56.5% | 23.1% | 45.5% |
| final without confirmation | 315 | 4.1% | 63.5% | 58.0% | 27.3% | 48.4% |

70% admission: **rejected**

## Development Leaderboard

| return q | OI q | confirmation | signals | accuracy | Wilson low | worst fold |
|---:|---:|---|---:|---:|---:|---:|
| 0.01 | 0.10 | green_4h | 15 | 80.0% | 54.8% | 85.7% |
| 0.01 | 0.10 | green_absorption | 12 | 75.0% | 46.8% | 80.0% |
| 0.03 | 0.20 | green_flow | 11 | 72.7% | 43.4% | 80.0% |
| 0.01 | 0.50 | green_flow | 21 | 66.7% | 45.4% | 71.4% |
| 0.01 | 0.10 | decelerating_selloff | 50 | 86.0% | 73.8% | 70.0% |
| 0.01 | 0.10 | green_12h | 26 | 80.8% | 62.1% | 70.0% |
| 0.03 | 0.20 | green_4h | 56 | 73.2% | 60.4% | 70.0% |
| 0.02 | 0.10 | green_12h | 33 | 78.8% | 62.2% | 66.7% |
| 0.01 | 0.20 | green_12h | 46 | 73.9% | 59.7% | 66.7% |
| 0.02 | 0.20 | green_4h | 46 | 71.7% | 57.5% | 66.7% |

The final folds are absent from configuration ranking. The admission gate still requires aggregate, Wilson, fold, asset, and support checks.
