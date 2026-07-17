# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind guarded state-field target | 1800 | 0.506 | 258.9 bps | 336.7 bps | 2.60% | 0.128 | 0.389 | 4.92% |
| WaveMind price target | 1800 | 0.469 | 261.3 bps | 338.9 bps | 2.63% | 0.121 | 0.311 | 5.03% |
| WaveMind robust target | 1800 | 0.492 | 257.3 bps | 335.3 bps | 2.58% | 0.123 | 0.400 | 4.87% |
| Momentum baseline | 1800 | 0.468 | 275.8 bps | 353.6 bps | 2.77% | 0.133 | 0.344 | 5.11% |
| Naive last-outcome baseline | 1800 | 0.482 | 375.2 bps | 477.5 bps | 3.77% | 0.081 | 0.356 | 5.93% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind guarded state-field target | ADA/USDT | 4h | 0 | 90 | 0.567 | 260.5 bps | 2.59% | -30.9 bps |
| WaveMind price target | ADA/USDT | 4h | 0 | 90 | 0.511 | 270.9 bps | 2.69% | -37.0 bps |
| WaveMind robust target | ADA/USDT | 4h | 0 | 90 | 0.478 | 265.7 bps | 2.64% | -40.2 bps |
| Momentum baseline | ADA/USDT | 4h | 0 | 90 | 0.533 | 275.3 bps | 2.75% | 13.4 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 0 | 90 | 0.533 | 384.6 bps | 3.86% | 12.2 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 1 | 90 | 0.444 | 285.7 bps | 2.84% | -52.5 bps |
| WaveMind price target | ADA/USDT | 4h | 1 | 90 | 0.500 | 277.1 bps | 2.75% | -48.4 bps |
| WaveMind robust target | ADA/USDT | 4h | 1 | 90 | 0.511 | 275.1 bps | 2.73% | -52.7 bps |
| Momentum baseline | ADA/USDT | 4h | 1 | 90 | 0.389 | 317.5 bps | 3.17% | 3.7 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 1 | 90 | 0.356 | 450.6 bps | 4.51% | 23.0 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 2 | 90 | 0.556 | 230.8 bps | 2.30% | -30.3 bps |
| WaveMind price target | ADA/USDT | 4h | 2 | 90 | 0.422 | 243.4 bps | 2.42% | -24.5 bps |
| WaveMind robust target | ADA/USDT | 4h | 2 | 90 | 0.433 | 234.5 bps | 2.34% | -18.0 bps |
| Momentum baseline | ADA/USDT | 4h | 2 | 90 | 0.500 | 252.6 bps | 2.52% | 8.2 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 2 | 90 | 0.433 | 350.9 bps | 3.51% | 3.2 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 3 | 90 | 0.578 | 471.0 bps | 4.92% | 73.1 bps |
| WaveMind price target | ADA/USDT | 4h | 3 | 90 | 0.411 | 480.6 bps | 5.03% | 80.2 bps |
| WaveMind robust target | ADA/USDT | 4h | 3 | 90 | 0.556 | 465.3 bps | 4.87% | 75.5 bps |
| Momentum baseline | ADA/USDT | 4h | 3 | 90 | 0.478 | 492.7 bps | 5.11% | 47.6 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 3 | 90 | 0.600 | 579.6 bps | 5.93% | -10.6 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 0 | 90 | 0.511 | 250.3 bps | 2.50% | -52.6 bps |
| WaveMind price target | AVAX/USDT | 4h | 0 | 90 | 0.489 | 247.2 bps | 2.47% | -40.8 bps |
| WaveMind robust target | AVAX/USDT | 4h | 0 | 90 | 0.522 | 244.7 bps | 2.45% | -30.0 bps |
| Momentum baseline | AVAX/USDT | 4h | 0 | 90 | 0.511 | 252.9 bps | 2.54% | 15.4 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 0 | 90 | 0.611 | 345.2 bps | 3.46% | 7.0 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 1 | 90 | 0.389 | 309.3 bps | 3.08% | -46.7 bps |
| WaveMind price target | AVAX/USDT | 4h | 1 | 90 | 0.478 | 299.9 bps | 2.98% | -64.5 bps |
| WaveMind robust target | AVAX/USDT | 4h | 1 | 90 | 0.489 | 299.8 bps | 2.98% | -66.1 bps |
| Momentum baseline | AVAX/USDT | 4h | 1 | 90 | 0.367 | 350.0 bps | 3.50% | -5.1 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 1 | 90 | 0.411 | 507.4 bps | 5.07% | 21.4 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 2 | 90 | 0.478 | 214.8 bps | 2.15% | -36.4 bps |
| WaveMind price target | AVAX/USDT | 4h | 2 | 90 | 0.500 | 221.5 bps | 2.21% | -32.6 bps |
| WaveMind robust target | AVAX/USDT | 4h | 2 | 90 | 0.533 | 212.3 bps | 2.12% | -29.6 bps |
| Momentum baseline | AVAX/USDT | 4h | 2 | 90 | 0.544 | 215.9 bps | 2.16% | 6.2 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 2 | 90 | 0.478 | 315.5 bps | 3.17% | 4.8 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 3 | 90 | 0.544 | 300.7 bps | 3.13% | 87.2 bps |
| WaveMind price target | AVAX/USDT | 4h | 3 | 90 | 0.522 | 302.8 bps | 3.15% | 81.3 bps |
| WaveMind robust target | AVAX/USDT | 4h | 3 | 90 | 0.578 | 296.8 bps | 3.09% | 75.1 bps |
| Momentum baseline | AVAX/USDT | 4h | 3 | 90 | 0.489 | 307.9 bps | 3.18% | 47.9 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 3 | 90 | 0.467 | 397.4 bps | 4.05% | -5.6 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 0 | 90 | 0.633 | 238.0 bps | 2.37% | -35.8 bps |
| WaveMind price target | DOGE/USDT | 4h | 0 | 90 | 0.522 | 247.4 bps | 2.46% | -47.1 bps |
| WaveMind robust target | DOGE/USDT | 4h | 0 | 90 | 0.511 | 244.9 bps | 2.43% | -49.0 bps |
| Momentum baseline | DOGE/USDT | 4h | 0 | 90 | 0.489 | 267.1 bps | 2.68% | 25.4 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 0 | 90 | 0.544 | 382.8 bps | 3.86% | 17.7 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 1 | 90 | 0.422 | 209.1 bps | 2.08% | -50.4 bps |
| WaveMind price target | DOGE/USDT | 4h | 1 | 90 | 0.600 | 195.7 bps | 1.94% | -69.4 bps |
| WaveMind robust target | DOGE/USDT | 4h | 1 | 90 | 0.467 | 199.9 bps | 1.98% | -67.6 bps |
| Momentum baseline | DOGE/USDT | 4h | 1 | 90 | 0.378 | 229.8 bps | 2.30% | -4.2 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 1 | 90 | 0.367 | 327.2 bps | 3.27% | 20.2 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 2 | 90 | 0.544 | 219.5 bps | 2.22% | 6.8 bps |
| WaveMind price target | DOGE/USDT | 4h | 2 | 90 | 0.622 | 211.5 bps | 2.14% | 40.5 bps |
| WaveMind robust target | DOGE/USDT | 4h | 2 | 90 | 0.600 | 216.6 bps | 2.20% | 53.8 bps |
| Momentum baseline | DOGE/USDT | 4h | 2 | 90 | 0.467 | 246.8 bps | 2.50% | 39.9 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 2 | 90 | 0.467 | 330.3 bps | 3.34% | 24.1 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 3 | 90 | 0.556 | 251.8 bps | 2.55% | 26.1 bps |
| WaveMind price target | DOGE/USDT | 4h | 3 | 90 | 0.456 | 252.3 bps | 2.56% | 37.7 bps |
| WaveMind robust target | DOGE/USDT | 4h | 3 | 90 | 0.511 | 248.4 bps | 2.52% | 34.7 bps |
| Momentum baseline | DOGE/USDT | 4h | 3 | 90 | 0.578 | 246.9 bps | 2.50% | 15.4 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 3 | 90 | 0.578 | 305.6 bps | 3.07% | -17.1 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 0 | 90 | 0.511 | 233.4 bps | 2.34% | -16.8 bps |
| WaveMind price target | LINK/USDT | 4h | 0 | 90 | 0.411 | 239.2 bps | 2.39% | -16.4 bps |
| WaveMind robust target | LINK/USDT | 4h | 0 | 90 | 0.456 | 241.7 bps | 2.42% | -27.0 bps |
| Momentum baseline | LINK/USDT | 4h | 0 | 90 | 0.522 | 249.8 bps | 2.51% | 28.6 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 0 | 90 | 0.544 | 357.9 bps | 3.60% | 16.1 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 1 | 90 | 0.422 | 264.0 bps | 2.61% | -66.8 bps |
| WaveMind price target | LINK/USDT | 4h | 1 | 90 | 0.478 | 265.6 bps | 2.63% | -56.0 bps |
| WaveMind robust target | LINK/USDT | 4h | 1 | 90 | 0.400 | 264.5 bps | 2.62% | -67.2 bps |
| Momentum baseline | LINK/USDT | 4h | 1 | 90 | 0.367 | 299.4 bps | 2.98% | -17.0 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 1 | 90 | 0.378 | 431.5 bps | 4.31% | 16.5 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 2 | 90 | 0.411 | 266.2 bps | 2.64% | -61.1 bps |
| WaveMind price target | LINK/USDT | 4h | 2 | 90 | 0.344 | 269.2 bps | 2.68% | -33.7 bps |
| WaveMind robust target | LINK/USDT | 4h | 2 | 90 | 0.400 | 256.8 bps | 2.56% | -34.5 bps |
| Momentum baseline | LINK/USDT | 4h | 2 | 90 | 0.544 | 267.9 bps | 2.68% | -1.3 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 2 | 90 | 0.422 | 353.1 bps | 3.54% | 7.0 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 3 | 90 | 0.500 | 285.5 bps | 2.87% | -10.5 bps |
| WaveMind price target | LINK/USDT | 4h | 3 | 90 | 0.456 | 289.5 bps | 2.92% | 3.9 bps |
| WaveMind robust target | LINK/USDT | 4h | 3 | 90 | 0.467 | 288.9 bps | 2.91% | -19.1 bps |
| Momentum baseline | LINK/USDT | 4h | 3 | 90 | 0.467 | 297.6 bps | 2.99% | -4.6 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 3 | 90 | 0.511 | 390.5 bps | 3.91% | -10.9 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 0 | 90 | 0.489 | 194.4 bps | 1.92% | -39.3 bps |
| WaveMind price target | XRP/USDT | 4h | 0 | 90 | 0.533 | 192.5 bps | 1.91% | -43.5 bps |
| WaveMind robust target | XRP/USDT | 4h | 0 | 90 | 0.556 | 189.1 bps | 1.87% | -41.5 bps |
| Momentum baseline | XRP/USDT | 4h | 0 | 90 | 0.478 | 205.7 bps | 2.05% | 7.5 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 0 | 90 | 0.544 | 277.6 bps | 2.78% | 14.6 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 1 | 90 | 0.422 | 214.3 bps | 2.11% | -77.0 bps |
| WaveMind price target | XRP/USDT | 4h | 1 | 90 | 0.411 | 211.0 bps | 2.09% | -55.2 bps |
| WaveMind robust target | XRP/USDT | 4h | 1 | 90 | 0.444 | 209.9 bps | 2.07% | -76.8 bps |
| Momentum baseline | XRP/USDT | 4h | 1 | 90 | 0.344 | 227.3 bps | 2.26% | -28.3 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 1 | 90 | 0.400 | 328.6 bps | 3.27% | 9.5 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 2 | 90 | 0.578 | 179.9 bps | 1.80% | 4.2 bps |
| WaveMind price target | XRP/USDT | 4h | 2 | 90 | 0.311 | 195.8 bps | 1.96% | 6.0 bps |
| WaveMind robust target | XRP/USDT | 4h | 2 | 90 | 0.422 | 185.7 bps | 1.86% | 0.0 bps |
| Momentum baseline | XRP/USDT | 4h | 2 | 90 | 0.444 | 199.5 bps | 2.00% | 16.4 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 2 | 90 | 0.478 | 288.1 bps | 2.89% | 10.4 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 3 | 90 | 0.556 | 298.9 bps | 2.98% | -12.1 bps |
| WaveMind price target | XRP/USDT | 4h | 3 | 90 | 0.400 | 313.6 bps | 3.13% | 0.8 bps |
| WaveMind robust target | XRP/USDT | 4h | 3 | 90 | 0.500 | 304.8 bps | 3.04% | -16.9 bps |
| Momentum baseline | XRP/USDT | 4h | 3 | 90 | 0.478 | 312.5 bps | 3.12% | -1.6 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 3 | 90 | 0.522 | 399.5 bps | 3.99% | 1.4 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
