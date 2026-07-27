# Causal Analogue-Memory Capitulation Transfer

A high-confidence local analogue policy is selected on eight Bybit assets, then evaluated without holdout-label updates on eight different assets.

- development assets: APTUSDT, CRVUSDT, ENJUSDT, IOTAUSDT, KAVAUSDT, NEARUSDT, OPUSDT, SNXUSDT;
- holdout assets: ADAUSDT, AVAXUSDT, BCHUSDT, DOTUSDT, ETCUSDT, LINKUSDT, LTCUSDT, XLMUSDT;
- frozen memory: k=15, margin=0.25, WaveField weight=0.00;
- development selection support: underpowered; deterministic kNN control retained;
- development SHA-256: `2c71a93229d61148a863df4fbf7527bd10b4c1ebf67c87b9abb596fa34713552`;
- holdout SHA-256: `b48c93a07af86ad207d121ffa1ff1ac871c7ca1b6fe13d2c69213ab957d81ae7`.

| split / ablation | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|---:|
| development selected | 32 | 0.4% | 75.0% | 57.9% | 69.2% | 75.0% |
| asset-disjoint holdout | 6 | 0.1% | 83.3% | 43.6% | n/a | n/a |
| holdout kNN control | 6 | 0.1% | 83.3% | 43.6% | n/a | n/a |
| holdout 30% WaveField | 1 | 0.0% | 0.0% | 0.0% | n/a | n/a |

Aggregate 70% evidence: **rejected**

Stable 70% admission: **rejected**

## Development WaveField Ablation

| field weight | signals | accuracy | Wilson low | worst fold |
|---:|---:|---:|---:|---:|
| 0.00 | 32 | 75.0% | 57.9% | 69.2% |
| 0.15 | 24 | 87.5% | 69.0% | 87.5% |
| 0.30 | 14 | 85.7% | 60.1% | n/a |

## Holdout Folds

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 6 | 4 | 100.0% | 51.0% |
| 8 | 1 | 100.0% | 20.7% |
| 11 | 1 | 0.0% | 0.0% |

## Holdout Assets

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| ADAUSDT | 1 | 0.0% | 0.0% |
| BCHUSDT | 1 | 100.0% | 20.7% |
| DOTUSDT | 1 | 100.0% | 20.7% |
| LTCUSDT | 3 | 100.0% | 43.9% |

The holdout memory contains only matured development-asset outcomes. A high development score is not promoted unless it survives the asset-disjoint holdout and every stability gate.
