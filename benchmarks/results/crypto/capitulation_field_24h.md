# Frozen Asset-Transfer Capitulation Field

A causal, asset-disjoint test of a frozen extreme-state memory rule on verified Binance USD-M futures archives.

## Frozen Rule

- direction: **up**;
- `return_12` in the low 1.0% tail;
- `oi_change_1` in the low 10.0% tail;
- thresholds use matured past observations only;
- one independent signal per asset per 24-hour horizon.

## Results

| split | assets | signals | coverage | accuracy | Wilson low 95% | aggregate 70% | stable gate |
|---|---:|---:|---:|---:|---:|---:|---:|
| development walk-forward | 16 | 112 | 0.8% | 92.9% | 86.5% | yes | yes |
| asset-disjoint holdout | 8 | 58 | 0.9% | 82.8% | 71.1% | yes | no |

## Holdout Slices

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| AAVEUSDT | 4 | 100.0% | 51.0% |
| ALGOUSDT | 5 | 80.0% | 37.6% |
| FILUSDT | 11 | 63.6% | 35.4% |
| MANAUSDT | 7 | 100.0% | 64.6% |
| SANDUSDT | 8 | 87.5% | 52.9% |
| UNIUSDT | 7 | 71.4% | 35.9% |
| XTZUSDT | 5 | 80.0% | 37.6% |
| ZECUSDT | 11 | 90.9% | 62.3% |

This is a sparse conditional rebound signal, not a universal price forecast. Aggregate evidence and stable admission are separate: the stable gate remains false unless the untouched asset holdout also clears the predeclared fold and asset checks.
