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
| Momentum baseline | 0 bps | 50.7% | 315 | 53.0% | 47.5% | 100.0% | 31.1% | 49.5% | no |
| Momentum baseline | 50 bps | 49.8% | 144 | 54.9% | 46.7% | 45.7% | 25.9% | 52.6% | no |
| Momentum baseline | 100 bps | 48.0% | 62 | 53.2% | 41.0% | 19.7% | 20.0% | 40.0% | no |
| Momentum baseline | 150 bps | 51.0% | 31 | 58.1% | 40.8% | 9.8% | 50.0% | 58.8% | no |
| Momentum baseline | 200 bps | 54.4% | 13 | 53.8% | 29.1% | 4.1% | 40.0% | 62.5% | no |
| Momentum baseline | 250 bps | 51.7% | 5 | 60.0% | 23.1% | 1.6% | n/a | n/a | no |
| WaveMind guarded state-field target | 0 bps | 50.9% | 315 | 56.2% | 50.7% | 100.0% | 40.0% | 55.2% | no |
| WaveMind guarded state-field target | 50 bps | 52.8% | 99 | 58.6% | 48.7% | 31.4% | 41.2% | 50.0% | no |
| WaveMind guarded state-field target | 100 bps | 54.5% | 22 | 59.1% | 38.7% | 7.0% | 33.3% | 55.6% | no |
| WaveMind guarded state-field target | 150 bps | 56.5% | 3 | 66.7% | 20.8% | 1.0% | n/a | n/a | no |
| WaveMind guarded state-field target | 200 bps | 50.0% | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind guarded state-field target | 250 bps | n/a | 0 | n/a | n/a | 0.0% | n/a | n/a | no |
| WaveMind independent-expert target | 0 bps | 51.3% | 315 | 48.9% | 43.4% | 100.0% | 33.3% | 43.8% | no |
| WaveMind independent-expert target | 50 bps | 49.2% | 50 | 52.0% | 38.5% | 15.9% | 36.4% | 48.1% | no |
| WaveMind independent-expert target | 100 bps | 56.2% | 6 | 83.3% | 43.6% | 1.9% | n/a | 80.0% | no |
| WaveMind independent-expert target | 150 bps | 80.0% | 2 | 50.0% | 9.5% | 0.6% | n/a | n/a | no |
| WaveMind independent-expert target | 200 bps | 100.0% | 1 | 100.0% | 20.7% | 0.3% | n/a | n/a | no |
| WaveMind independent-expert target | 250 bps | 100.0% | 1 | 100.0% | 20.7% | 0.3% | n/a | n/a | no |
| WaveMind market-field target | 0 bps | 49.3% | 315 | 47.0% | 41.5% | 100.0% | 28.9% | 44.8% | no |
| WaveMind market-field target | 50 bps | 50.2% | 144 | 45.1% | 37.2% | 45.7% | 23.1% | 42.9% | no |
| WaveMind market-field target | 100 bps | 52.0% | 62 | 46.8% | 34.9% | 19.7% | 20.0% | 44.0% | no |
| WaveMind market-field target | 150 bps | 49.0% | 31 | 41.9% | 26.4% | 9.8% | 20.0% | 36.4% | no |
| WaveMind market-field target | 200 bps | 45.6% | 13 | 46.2% | 23.2% | 4.1% | 40.0% | 37.5% | no |
| WaveMind market-field target | 250 bps | 48.3% | 5 | 40.0% | 11.8% | 1.6% | n/a | n/a | no |
| WaveMind online-expert target | 0 bps | 54.2% | 315 | 52.7% | 47.2% | 100.0% | 44.4% | 48.6% | no |
| WaveMind online-expert target | 50 bps | 50.1% | 55 | 47.3% | 34.7% | 17.5% | 20.0% | 44.0% | no |
| WaveMind online-expert target | 100 bps | 65.0% | 10 | 100.0% | 72.2% | 3.2% | n/a | 100.0% | no |
| WaveMind online-expert target | 150 bps | 76.5% | 3 | 100.0% | 43.9% | 1.0% | n/a | n/a | no |
| WaveMind online-expert target | 200 bps | 91.7% | 3 | 100.0% | 43.9% | 1.0% | n/a | n/a | no |
| WaveMind online-expert target | 250 bps | 100.0% | 2 | 100.0% | 34.2% | 0.6% | n/a | n/a | no |

## Verdict

No engine currently passes the 80% admission gate.
