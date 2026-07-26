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
| first asset-disjoint holdout | 8 | 58 | 0.9% | 82.8% | 71.1% | yes | no |
| second asset-disjoint replication | 8 | 60 | 0.9% | 83.3% | 72.0% | yes | no |
| early-2023 temporal stress | 8 | 3 | 0.2% | 33.3% | 6.1% | no | no |
| combined asset replications | 16 | 118 | 0.9% | 83.1% | 75.3% | yes | no |

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

## Replication Slices

| period | asset | signals | accuracy | Wilson low 95% |
|---|---|---:|---:|---:|
| 2024-2026 | COMPUSDT | 4 | 100.0% | 51.0% |
| 2024-2026 | DASHUSDT | 5 | 80.0% | 37.6% |
| 2024-2026 | GRTUSDT | 9 | 77.8% | 45.3% |
| 2024-2026 | HBARUSDT | 8 | 87.5% | 52.9% |
| 2024-2026 | RUNEUSDT | 14 | 71.4% | 45.4% |
| 2024-2026 | THETAUSDT | 8 | 87.5% | 52.9% |
| 2024-2026 | VETUSDT | 6 | 100.0% | 61.0% |
| 2024-2026 | XMRUSDT | 6 | 83.3% | 43.6% |
| 2023 | COMPUSDT | 1 | 100.0% | 20.7% |
| 2023 | HBARUSDT | 1 | 0.0% | 0.0% |
| 2023 | RUNEUSDT | 1 | 0.0% | 0.0% |

The early-2023 result is a frozen retrospective time stress on previously unused assets. It is not prospective post-freeze market evidence.

This is a sparse conditional rebound signal, not a universal price forecast. Aggregate evidence and stable admission are separate: the stable gate remains false unless the untouched asset holdout also clears the predeclared fold and asset checks.
