# WaveMind Crypto 80% Accuracy Admission Gate

This report prevents overlapping forecasts or tiny samples from being presented as an 80% edge.

## Admission Rule

- direction accuracy >= 80%;
- >= 40 non-overlapping signals;
- >= 5% effective coverage;
- 95% Wilson lower bound >= 70%;
- every fold has >= 5 signals and >= 70% accuracy.
- every symbol/timeframe slice has >= 5 signals and >= 70% accuracy.

## Frontier

| engine | threshold | raw accuracy | effective signals | effective accuracy | Wilson low | coverage | worst fold | worst slice | admitted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Momentum baseline | 0 bps | 48.0% | 480 | 51.2% | 46.8% | 100.0% | 35.8% | 45.0% | no |
| Momentum baseline | 50 bps | 46.2% | 279 | 48.7% | 42.9% | 58.1% | 28.6% | 40.6% | no |
| Momentum baseline | 100 bps | 46.7% | 136 | 51.5% | 43.1% | 28.3% | 18.8% | 38.1% | no |
| Momentum baseline | 150 bps | 46.7% | 68 | 42.6% | 31.6% | 14.2% | 0.0% | 25.0% | no |
| Momentum baseline | 200 bps | 48.1% | 38 | 50.0% | 34.8% | 7.9% | 0.0% | 40.0% | no |
| Momentum baseline | 250 bps | 50.5% | 17 | 41.2% | 21.6% | 3.5% | 0.0% | n/a | no |
| WaveMind guarded state-field target | 0 bps | 51.4% | 480 | 52.7% | 48.2% | 100.0% | 33.3% | 41.7% | no |
| WaveMind guarded state-field target | 50 bps | 51.4% | 188 | 52.7% | 45.5% | 39.2% | 32.7% | 40.0% | no |
| WaveMind guarded state-field target | 100 bps | 53.9% | 56 | 51.8% | 39.0% | 11.7% | 25.0% | 12.5% | no |
| WaveMind guarded state-field target | 150 bps | 60.6% | 11 | 54.5% | 28.0% | 2.3% | 80.0% | n/a | no |
| WaveMind guarded state-field target | 200 bps | 69.2% | 1 | 100.0% | 20.7% | 0.2% | n/a | n/a | no |
| WaveMind guarded state-field target | 250 bps | 66.7% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind independent-expert target | 0 bps | 49.8% | 480 | 49.6% | 45.1% | 100.0% | 44.2% | 46.7% | no |
| WaveMind independent-expert target | 50 bps | 49.9% | 140 | 47.1% | 39.1% | 29.2% | 44.0% | 25.0% | no |
| WaveMind independent-expert target | 100 bps | 59.5% | 17 | 64.7% | 41.3% | 3.5% | 80.0% | n/a | no |
| WaveMind independent-expert target | 150 bps | 69.6% | 3 | 100.0% | 43.9% | 0.6% | n/a | n/a | no |
| WaveMind independent-expert target | 200 bps | 90.9% | 2 | 100.0% | 34.2% | 0.4% | n/a | n/a | no |
| WaveMind independent-expert target | 250 bps | 50.0% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind market-field target | 0 bps | 52.0% | 480 | 48.8% | 44.3% | 100.0% | 37.5% | 36.7% | no |
| WaveMind market-field target | 50 bps | 53.8% | 279 | 51.3% | 45.4% | 58.1% | 38.9% | 44.0% | no |
| WaveMind market-field target | 100 bps | 53.3% | 136 | 48.5% | 40.3% | 28.3% | 31.7% | 39.1% | no |
| WaveMind market-field target | 150 bps | 53.3% | 68 | 57.4% | 45.5% | 14.2% | 29.0% | 40.0% | no |
| WaveMind market-field target | 200 bps | 51.9% | 38 | 50.0% | 34.8% | 7.9% | 25.0% | 40.0% | no |
| WaveMind market-field target | 250 bps | 49.5% | 17 | 58.8% | 36.0% | 3.5% | 30.0% | n/a | no |
| WaveMind online-expert target | 0 bps | 49.1% | 480 | 49.4% | 44.9% | 100.0% | 35.0% | 41.7% | no |
| WaveMind online-expert target | 50 bps | 53.0% | 147 | 54.4% | 46.4% | 30.6% | 40.0% | 38.5% | no |
| WaveMind online-expert target | 100 bps | 58.0% | 48 | 58.3% | 44.3% | 10.0% | 50.0% | 33.3% | no |
| WaveMind online-expert target | 150 bps | 72.0% | 16 | 87.5% | 64.0% | 3.3% | 100.0% | n/a | no |
| WaveMind online-expert target | 200 bps | 82.9% | 11 | 90.9% | 62.3% | 2.3% | 100.0% | n/a | no |
| WaveMind online-expert target | 250 bps | 92.3% | 5 | 100.0% | 56.6% | 1.0% | n/a | n/a | no |
| WaveMind robust target | 0 bps | 49.4% | 480 | 49.6% | 45.1% | 100.0% | 45.0% | 46.7% | no |
| WaveMind robust target | 50 bps | 49.2% | 132 | 46.2% | 37.9% | 27.5% | 36.8% | 26.7% | no |
| WaveMind robust target | 100 bps | 59.8% | 13 | 61.5% | 35.5% | 2.7% | 71.4% | n/a | no |
| WaveMind robust target | 150 bps | 50.0% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind robust target | 200 bps | 80.0% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind robust target | 250 bps | 0.0% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |

## Verdict

No engine currently passes the 80% admission gate.
