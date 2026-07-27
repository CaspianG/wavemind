# Dynamic Analogue Reliability Field Transfer

A 40-asset causal development stream freezes a decayed reliability router before evaluation on eight new Bybit assets.

- development assets: 40;
- holdout assets: 1INCHUSDT, AXSUSDT, BLURUSDT, CFXUSDT, KNCUSDT, MINAUSDT, STXUSDT, SUSHIUSDT;
- feedback: 60d half-life, prior=20, gate=0.10, bucket=trend, WaveField weight=0.00;
- holdout SHA-256: `7e69ec332d266a47ce517dbab93528fa8187b8c5ffd4bbf73b1b10326b4dbc26`.

| split / control | signals | accuracy | Wilson low 95% | worst fold | worst asset |
|---|---:|---:|---:|---:|---:|
| development selected | 86 | 94.2% | 87.1% | 66.7% | 80.0% |
| asset-disjoint holdout | 9 | 88.9% | 56.5% | 100.0% | n/a |
| holdout statistical-only | 9 | 88.9% | 56.5% | 100.0% | n/a |
| holdout without online updates | 13 | 92.3% | 66.7% | 100.0% | n/a |

Aggregate 70% evidence: **rejected**

Stable 70% admission: **rejected**

## Development WaveField Ablation

| field weight | signals | accuracy | Wilson low | worst fold | worst asset |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 86 | 94.2% | 87.1% | 66.7% | 80.0% |
| 0.15 | 70 | 91.4% | 82.5% | 66.7% | 100.0% |
| 0.30 | 67 | 86.6% | 76.4% | 33.3% | n/a |

## Holdout Folds

| fold | signals | accuracy | Wilson low 95% |
|---:|---:|---:|---:|
| 6 | 3 | 100.0% | 43.9% |
| 8 | 5 | 100.0% | 56.6% |
| 9 | 1 | 0.0% | 0.0% |

## Holdout Assets

| asset | signals | accuracy | Wilson low 95% |
|---|---:|---:|---:|
| AXSUSDT | 1 | 100.0% | 20.7% |
| BLURUSDT | 1 | 100.0% | 20.7% |
| CFXUSDT | 3 | 100.0% | 43.9% |
| MINAUSDT | 2 | 50.0% | 9.5% |
| STXUSDT | 2 | 100.0% | 34.2% |
