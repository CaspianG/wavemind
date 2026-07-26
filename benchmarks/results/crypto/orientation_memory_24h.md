# Universal Direction Orientation Benchmark

A full-coverage, causal 24h benchmark. Every independent market window receives an up/down prediction.

| engine | signals | accuracy | Wilson low 95% | worst fold | worst asset | admitted 70% |
|---|---:|---:|---:|---:|---:|---:|
| always_up | 29152 | 49.4% | 48.9% | 46.2% | 46.2% | no |
| guarded_state | 29152 | 49.7% | 49.1% | 47.6% | 43.2% | no |
| inverse_guarded_state | 29152 | 50.3% | 49.8% | 46.5% | 46.2% | no |
| mean_reversion | 29152 | 52.2% | 51.6% | 49.0% | 49.1% | no |
| momentum | 29152 | 47.8% | 47.2% | 44.8% | 44.3% | no |
| orientation_memory | 29152 | 48.6% | 48.0% | 45.1% | 45.3% | no |

The orientation-memory engine can invert the guard only from already matured historical outcomes. Failure to reach the gate is retained as evidence against a universal 70% claim.
