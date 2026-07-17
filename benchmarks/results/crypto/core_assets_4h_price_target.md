# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind guarded state-field target | 1080 | 0.537 | 223.5 bps | 292.0 bps | 2.23% | 0.155 | 0.444 | 3.25% |
| WaveMind price target | 1080 | 0.504 | 225.7 bps | 293.9 bps | 2.25% | 0.160 | 0.389 | 3.33% |
| WaveMind robust target | 1080 | 0.498 | 224.6 bps | 293.2 bps | 2.24% | 0.151 | 0.367 | 3.36% |
| Momentum baseline | 1080 | 0.499 | 236.1 bps | 304.5 bps | 2.36% | 0.154 | 0.356 | 3.17% |
| Naive last-outcome baseline | 1080 | 0.511 | 321.9 bps | 410.9 bps | 3.22% | 0.103 | 0.289 | 4.44% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind guarded state-field target | BTC/USDT | 4h | 0 | 90 | 0.511 | 188.1 bps | 1.89% | -1.6 bps |
| WaveMind price target | BTC/USDT | 4h | 0 | 90 | 0.489 | 187.6 bps | 1.89% | 5.2 bps |
| WaveMind robust target | BTC/USDT | 4h | 0 | 90 | 0.511 | 188.3 bps | 1.89% | -6.2 bps |
| Momentum baseline | BTC/USDT | 4h | 0 | 90 | 0.522 | 191.2 bps | 1.93% | 32.0 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 0 | 90 | 0.567 | 262.0 bps | 2.63% | 15.5 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 1 | 90 | 0.544 | 182.4 bps | 1.79% | -97.7 bps |
| WaveMind price target | BTC/USDT | 4h | 1 | 90 | 0.489 | 184.7 bps | 1.81% | -90.1 bps |
| WaveMind robust target | BTC/USDT | 4h | 1 | 90 | 0.467 | 184.9 bps | 1.81% | -95.6 bps |
| Momentum baseline | BTC/USDT | 4h | 1 | 90 | 0.489 | 200.7 bps | 1.98% | -39.0 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 1 | 90 | 0.389 | 301.5 bps | 2.99% | 11.1 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 2 | 90 | 0.522 | 119.5 bps | 1.20% | 11.1 bps |
| WaveMind price target | BTC/USDT | 4h | 2 | 90 | 0.400 | 125.5 bps | 1.26% | 34.2 bps |
| WaveMind robust target | BTC/USDT | 4h | 2 | 90 | 0.422 | 120.3 bps | 1.21% | 31.2 bps |
| Momentum baseline | BTC/USDT | 4h | 2 | 90 | 0.511 | 121.7 bps | 1.22% | 23.9 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 2 | 90 | 0.567 | 164.5 bps | 1.65% | 10.1 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 3 | 90 | 0.622 | 190.6 bps | 1.92% | -12.1 bps |
| WaveMind price target | BTC/USDT | 4h | 3 | 90 | 0.489 | 196.7 bps | 1.98% | -6.4 bps |
| WaveMind robust target | BTC/USDT | 4h | 3 | 90 | 0.500 | 196.1 bps | 1.97% | -18.8 bps |
| Momentum baseline | BTC/USDT | 4h | 3 | 90 | 0.589 | 195.7 bps | 1.97% | -6.7 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 3 | 90 | 0.644 | 249.0 bps | 2.50% | -12.9 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 0 | 90 | 0.489 | 264.0 bps | 2.62% | -38.1 bps |
| WaveMind price target | ETH/USDT | 4h | 0 | 90 | 0.522 | 261.5 bps | 2.59% | -50.3 bps |
| WaveMind robust target | ETH/USDT | 4h | 0 | 90 | 0.511 | 263.7 bps | 2.61% | -58.7 bps |
| Momentum baseline | ETH/USDT | 4h | 0 | 90 | 0.489 | 274.1 bps | 2.74% | 19.7 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 0 | 90 | 0.567 | 370.5 bps | 3.70% | 26.6 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 1 | 90 | 0.533 | 251.5 bps | 2.45% | -117.4 bps |
| WaveMind price target | ETH/USDT | 4h | 1 | 90 | 0.567 | 250.1 bps | 2.44% | -100.2 bps |
| WaveMind robust target | ETH/USDT | 4h | 1 | 90 | 0.533 | 251.7 bps | 2.45% | -106.6 bps |
| Momentum baseline | ETH/USDT | 4h | 1 | 90 | 0.378 | 300.4 bps | 2.95% | -38.2 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 1 | 90 | 0.289 | 448.6 bps | 4.44% | 14.5 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 2 | 90 | 0.556 | 141.1 bps | 1.43% | 31.5 bps |
| WaveMind price target | ETH/USDT | 4h | 2 | 90 | 0.444 | 151.9 bps | 1.54% | 78.3 bps |
| WaveMind robust target | ETH/USDT | 4h | 2 | 90 | 0.467 | 143.7 bps | 1.46% | 62.2 bps |
| Momentum baseline | ETH/USDT | 4h | 2 | 90 | 0.444 | 151.7 bps | 1.54% | 46.2 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 2 | 90 | 0.544 | 201.9 bps | 2.04% | 9.7 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 3 | 90 | 0.556 | 293.0 bps | 2.96% | -13.5 bps |
| WaveMind price target | ETH/USDT | 4h | 3 | 90 | 0.578 | 294.1 bps | 2.97% | -11.5 bps |
| WaveMind robust target | ETH/USDT | 4h | 3 | 90 | 0.567 | 288.1 bps | 2.91% | -16.6 bps |
| Momentum baseline | ETH/USDT | 4h | 3 | 90 | 0.533 | 294.2 bps | 2.96% | -7.2 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 3 | 90 | 0.556 | 381.8 bps | 3.83% | -23.3 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 0 | 90 | 0.522 | 251.3 bps | 2.50% | -21.0 bps |
| WaveMind price target | SOL/USDT | 4h | 0 | 90 | 0.589 | 242.1 bps | 2.41% | -13.8 bps |
| WaveMind robust target | SOL/USDT | 4h | 0 | 90 | 0.589 | 242.9 bps | 2.42% | -7.8 bps |
| Momentum baseline | SOL/USDT | 4h | 0 | 90 | 0.511 | 265.4 bps | 2.65% | 21.0 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 0 | 90 | 0.556 | 359.6 bps | 3.60% | 8.8 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 1 | 90 | 0.444 | 249.6 bps | 2.47% | -70.8 bps |
| WaveMind price target | SOL/USDT | 4h | 1 | 90 | 0.600 | 235.6 bps | 2.33% | -63.3 bps |
| WaveMind robust target | SOL/USDT | 4h | 1 | 90 | 0.533 | 245.1 bps | 2.42% | -78.4 bps |
| Momentum baseline | SOL/USDT | 4h | 1 | 90 | 0.356 | 288.2 bps | 2.86% | -17.2 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 1 | 90 | 0.356 | 415.5 bps | 4.14% | 20.2 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 2 | 90 | 0.578 | 226.1 bps | 2.26% | -34.6 bps |
| WaveMind price target | SOL/USDT | 4h | 2 | 90 | 0.389 | 245.9 bps | 2.46% | -28.5 bps |
| WaveMind robust target | SOL/USDT | 4h | 2 | 90 | 0.367 | 234.7 bps | 2.34% | -29.8 bps |
| Momentum baseline | SOL/USDT | 4h | 2 | 90 | 0.578 | 232.6 bps | 2.33% | 6.0 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 2 | 90 | 0.500 | 315.3 bps | 3.15% | 3.7 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 3 | 90 | 0.567 | 324.9 bps | 3.25% | -33.2 bps |
| WaveMind price target | SOL/USDT | 4h | 3 | 90 | 0.489 | 332.9 bps | 3.33% | -28.7 bps |
| WaveMind robust target | SOL/USDT | 4h | 3 | 90 | 0.511 | 335.8 bps | 3.36% | -35.8 bps |
| Momentum baseline | SOL/USDT | 4h | 3 | 90 | 0.589 | 317.6 bps | 3.17% | -16.9 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 3 | 90 | 0.600 | 392.4 bps | 3.91% | -21.3 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
