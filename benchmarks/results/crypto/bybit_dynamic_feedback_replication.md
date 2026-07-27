# Dynamic Feedback Expanded Replication Audit

> Exploratory expanded audit, not a preregistered confirmation.

## Result

| policy | signals | accuracy | Wilson low | market blocks | block-bootstrap low | always-up | paired edge low | admitted |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| online feedback | 87 | 82.8% | 73.5% | 25 | 50.8% | 82.8% | 0.0% | no |
| frozen feedback | 83 | 86.7% | 77.8% | 24 | 53.5% | 86.7% | 0.0% | no |

## Interpretation

The ordinary signal-level score is not sufficient because crypto assets co-move. The admission decision therefore requires a positive paired block-bootstrap edge over always-up, in addition to asset, fold, support, and Wilson gates.

## Reproduction

```bash
python benchmarks/crypto_dynamic_feedback_replication_benchmark.py --output-json benchmarks/results/crypto/bybit_dynamic_feedback_replication.json --output-markdown benchmarks/results/crypto/bybit_dynamic_feedback_replication.md
```
