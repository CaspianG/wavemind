# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind robust target | 8640 | 0.545 | 376.8 bps | 554.6 bps | 3.90% | 0.124 | 0.367 | 10.32% |
| WaveMind calibrated target | 8640 | 0.531 | 390.9 bps | 573.8 bps | 4.05% | 0.117 | 0.222 | 10.89% |
| WaveMind price target | 8640 | 0.480 | 394.5 bps | 579.9 bps | 4.09% | 0.113 | 0.211 | 10.71% |
| Momentum baseline | 8640 | 0.497 | 398.7 bps | 581.2 bps | 4.11% | 0.116 | 0.244 | 10.35% |
| Regime mean baseline | 8640 | 0.495 | 400.1 bps | 579.6 bps | 4.13% | 0.113 | 0.133 | 10.63% |
| Historical mean baseline | 8640 | 0.474 | 396.6 bps | 581.1 bps | 4.13% | 0.107 | 0.133 | 10.65% |
| Naive last-outcome baseline | 8640 | 0.492 | 531.5 bps | 783.1 bps | 5.44% | 0.091 | 0.256 | 15.90% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind robust target | BTC/USDT | 1h | 0 | 90 | 0.911 | 282.4 bps | 2.96% | 282.3 bps |
| WaveMind calibrated target | BTC/USDT | 1h | 0 | 90 | 1.000 | 304.1 bps | 3.19% | 301.7 bps |
| WaveMind price target | BTC/USDT | 1h | 0 | 90 | 1.000 | 317.5 bps | 3.33% | 316.7 bps |
| Momentum baseline | BTC/USDT | 1h | 0 | 90 | 0.878 | 334.9 bps | 3.51% | 334.9 bps |
| Regime mean baseline | BTC/USDT | 1h | 0 | 90 | 0.789 | 275.0 bps | 2.88% | 271.6 bps |
| Historical mean baseline | BTC/USDT | 1h | 0 | 90 | 1.000 | 320.8 bps | 3.36% | 320.2 bps |
| Naive last-outcome baseline | BTC/USDT | 1h | 0 | 90 | 0.833 | 226.6 bps | 2.36% | 119.5 bps |
| WaveMind robust target | BTC/USDT | 1h | 1 | 90 | 0.589 | 130.8 bps | 1.28% | -107.8 bps |
| WaveMind calibrated target | BTC/USDT | 1h | 1 | 90 | 0.656 | 121.7 bps | 1.19% | -117.6 bps |
| WaveMind price target | BTC/USDT | 1h | 1 | 90 | 0.389 | 146.8 bps | 1.44% | -145.2 bps |
| Momentum baseline | BTC/USDT | 1h | 1 | 90 | 0.578 | 123.3 bps | 1.21% | -106.3 bps |
| Regime mean baseline | BTC/USDT | 1h | 1 | 90 | 0.500 | 120.7 bps | 1.19% | -94.0 bps |
| Historical mean baseline | BTC/USDT | 1h | 1 | 90 | 0.133 | 198.3 bps | 1.95% | -198.3 bps |
| Naive last-outcome baseline | BTC/USDT | 1h | 1 | 90 | 0.622 | 208.0 bps | 2.05% | -80.5 bps |
| WaveMind robust target | BTC/USDT | 1h | 2 | 90 | 0.589 | 138.5 bps | 1.40% | 23.0 bps |
| WaveMind calibrated target | BTC/USDT | 1h | 2 | 90 | 0.311 | 146.2 bps | 1.48% | 8.5 bps |
| WaveMind price target | BTC/USDT | 1h | 2 | 90 | 0.311 | 146.2 bps | 1.48% | 8.5 bps |
| Momentum baseline | BTC/USDT | 1h | 2 | 90 | 0.589 | 133.6 bps | 1.35% | 21.5 bps |
| Regime mean baseline | BTC/USDT | 1h | 2 | 90 | 0.267 | 207.3 bps | 2.09% | -39.4 bps |
| Historical mean baseline | BTC/USDT | 1h | 2 | 90 | 0.378 | 154.1 bps | 1.55% | -43.9 bps |
| Naive last-outcome baseline | BTC/USDT | 1h | 2 | 90 | 0.522 | 174.0 bps | 1.76% | 61.9 bps |
| WaveMind robust target | BTC/USDT | 1h | 3 | 90 | 0.556 | 193.1 bps | 1.90% | -85.6 bps |
| WaveMind calibrated target | BTC/USDT | 1h | 3 | 90 | 0.367 | 209.5 bps | 2.06% | -135.8 bps |
| WaveMind price target | BTC/USDT | 1h | 3 | 90 | 0.378 | 206.4 bps | 2.03% | -128.3 bps |
| Momentum baseline | BTC/USDT | 1h | 3 | 90 | 0.567 | 187.7 bps | 1.85% | -68.3 bps |
| Regime mean baseline | BTC/USDT | 1h | 3 | 90 | 0.222 | 226.3 bps | 2.23% | -107.3 bps |
| Historical mean baseline | BTC/USDT | 1h | 3 | 90 | 0.367 | 210.0 bps | 2.06% | -137.3 bps |
| Naive last-outcome baseline | BTC/USDT | 1h | 3 | 90 | 0.544 | 238.3 bps | 2.36% | -41.9 bps |
| WaveMind robust target | BTC/USDT | 4h | 0 | 90 | 0.489 | 262.6 bps | 2.58% | -98.2 bps |
| WaveMind calibrated target | BTC/USDT | 4h | 0 | 90 | 0.489 | 270.4 bps | 2.64% | -151.5 bps |
| WaveMind price target | BTC/USDT | 4h | 0 | 90 | 0.444 | 264.5 bps | 2.60% | -84.0 bps |
| Momentum baseline | BTC/USDT | 4h | 0 | 90 | 0.367 | 293.7 bps | 2.90% | -34.6 bps |
| Regime mean baseline | BTC/USDT | 4h | 0 | 90 | 0.400 | 266.8 bps | 2.63% | -63.2 bps |
| Historical mean baseline | BTC/USDT | 4h | 0 | 90 | 0.489 | 259.5 bps | 2.55% | -85.5 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 0 | 90 | 0.400 | 388.5 bps | 3.85% | 3.1 bps |
| WaveMind robust target | BTC/USDT | 4h | 1 | 90 | 0.467 | 182.1 bps | 1.79% | -84.4 bps |
| WaveMind calibrated target | BTC/USDT | 4h | 1 | 90 | 0.511 | 183.2 bps | 1.80% | -79.4 bps |
| WaveMind price target | BTC/USDT | 4h | 1 | 90 | 0.511 | 183.2 bps | 1.80% | -79.4 bps |
| Momentum baseline | BTC/USDT | 4h | 1 | 90 | 0.378 | 199.2 bps | 1.97% | -46.6 bps |
| Regime mean baseline | BTC/USDT | 4h | 1 | 90 | 0.556 | 177.2 bps | 1.75% | -62.3 bps |
| Historical mean baseline | BTC/USDT | 4h | 1 | 90 | 0.400 | 181.4 bps | 1.78% | -90.5 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 1 | 90 | 0.367 | 291.3 bps | 2.89% | -16.0 bps |
| WaveMind robust target | BTC/USDT | 4h | 2 | 90 | 0.422 | 123.2 bps | 1.24% | 39.0 bps |
| WaveMind calibrated target | BTC/USDT | 4h | 2 | 90 | 0.500 | 130.8 bps | 1.32% | 62.8 bps |
| WaveMind price target | BTC/USDT | 4h | 2 | 90 | 0.411 | 128.8 bps | 1.30% | 42.2 bps |
| Momentum baseline | BTC/USDT | 4h | 2 | 90 | 0.422 | 133.1 bps | 1.34% | 13.5 bps |
| Regime mean baseline | BTC/USDT | 4h | 2 | 90 | 0.556 | 123.7 bps | 1.24% | 29.1 bps |
| Historical mean baseline | BTC/USDT | 4h | 2 | 90 | 0.533 | 119.9 bps | 1.21% | 26.0 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 2 | 90 | 0.522 | 179.7 bps | 1.80% | -6.0 bps |
| WaveMind robust target | BTC/USDT | 4h | 3 | 90 | 0.544 | 156.0 bps | 1.57% | 12.7 bps |
| WaveMind calibrated target | BTC/USDT | 4h | 3 | 90 | 0.556 | 159.2 bps | 1.60% | 6.7 bps |
| WaveMind price target | BTC/USDT | 4h | 3 | 90 | 0.556 | 159.2 bps | 1.60% | 6.7 bps |
| Momentum baseline | BTC/USDT | 4h | 3 | 90 | 0.489 | 162.8 bps | 1.64% | 2.3 bps |
| Regime mean baseline | BTC/USDT | 4h | 3 | 90 | 0.533 | 167.0 bps | 1.68% | 14.5 bps |
| Historical mean baseline | BTC/USDT | 4h | 3 | 90 | 0.544 | 153.9 bps | 1.55% | 20.0 bps |
| Naive last-outcome baseline | BTC/USDT | 4h | 3 | 90 | 0.556 | 184.9 bps | 1.85% | -28.0 bps |
| WaveMind robust target | BTC/USDT | 1d | 0 | 90 | 0.456 | 432.5 bps | 4.41% | 120.7 bps |
| WaveMind calibrated target | BTC/USDT | 1d | 0 | 90 | 0.456 | 465.2 bps | 4.80% | 270.6 bps |
| WaveMind price target | BTC/USDT | 1d | 0 | 90 | 0.422 | 423.6 bps | 4.32% | 100.3 bps |
| Momentum baseline | BTC/USDT | 1d | 0 | 90 | 0.389 | 443.4 bps | 4.49% | 44.4 bps |
| Regime mean baseline | BTC/USDT | 1d | 0 | 90 | 0.422 | 441.9 bps | 4.49% | 91.0 bps |
| Historical mean baseline | BTC/USDT | 1d | 0 | 90 | 0.456 | 442.3 bps | 4.53% | 189.4 bps |
| Naive last-outcome baseline | BTC/USDT | 1d | 0 | 90 | 0.389 | 664.8 bps | 6.74% | 38.5 bps |
| WaveMind robust target | BTC/USDT | 1d | 1 | 90 | 0.478 | 420.6 bps | 4.35% | 80.3 bps |
| WaveMind calibrated target | BTC/USDT | 1d | 1 | 90 | 0.444 | 425.1 bps | 4.41% | 111.5 bps |
| WaveMind price target | BTC/USDT | 1d | 1 | 90 | 0.467 | 435.9 bps | 4.53% | 124.8 bps |
| Momentum baseline | BTC/USDT | 1d | 1 | 90 | 0.478 | 428.8 bps | 4.41% | 50.7 bps |
| Regime mean baseline | BTC/USDT | 1d | 1 | 90 | 0.522 | 464.4 bps | 4.75% | -36.5 bps |
| Historical mean baseline | BTC/USDT | 1d | 1 | 90 | 0.433 | 431.3 bps | 4.51% | 214.9 bps |
| Naive last-outcome baseline | BTC/USDT | 1d | 1 | 90 | 0.400 | 607.5 bps | 6.18% | 13.0 bps |
| WaveMind robust target | BTC/USDT | 1d | 2 | 90 | 0.589 | 508.4 bps | 5.36% | 102.6 bps |
| WaveMind calibrated target | BTC/USDT | 1d | 2 | 90 | 0.589 | 502.0 bps | 5.27% | 59.1 bps |
| WaveMind price target | BTC/USDT | 1d | 2 | 90 | 0.333 | 556.7 bps | 5.88% | 138.7 bps |
| Momentum baseline | BTC/USDT | 1d | 2 | 90 | 0.456 | 551.2 bps | 5.77% | 72.8 bps |
| Regime mean baseline | BTC/USDT | 1d | 2 | 90 | 0.522 | 543.5 bps | 5.67% | -24.3 bps |
| Historical mean baseline | BTC/USDT | 1d | 2 | 90 | 0.411 | 523.5 bps | 5.57% | 220.0 bps |
| Naive last-outcome baseline | BTC/USDT | 1d | 2 | 90 | 0.556 | 656.5 bps | 6.79% | -24.2 bps |
| WaveMind robust target | BTC/USDT | 1d | 3 | 90 | 0.567 | 459.8 bps | 4.75% | 35.4 bps |
| WaveMind calibrated target | BTC/USDT | 1d | 3 | 90 | 0.511 | 467.7 bps | 4.78% | -66.1 bps |
| WaveMind price target | BTC/USDT | 1d | 3 | 90 | 0.500 | 474.0 bps | 4.89% | 41.7 bps |
| Momentum baseline | BTC/USDT | 1d | 3 | 90 | 0.622 | 458.0 bps | 4.72% | 47.7 bps |
| Regime mean baseline | BTC/USDT | 1d | 3 | 90 | 0.400 | 496.8 bps | 5.14% | 77.0 bps |
| Historical mean baseline | BTC/USDT | 1d | 3 | 90 | 0.489 | 457.5 bps | 4.76% | 104.8 bps |
| Naive last-outcome baseline | BTC/USDT | 1d | 3 | 90 | 0.611 | 595.0 bps | 6.04% | 11.6 bps |
| WaveMind robust target | ETH/USDT | 1h | 0 | 90 | 0.811 | 266.4 bps | 2.80% | 244.1 bps |
| WaveMind calibrated target | ETH/USDT | 1h | 0 | 90 | 0.967 | 264.5 bps | 2.78% | 244.6 bps |
| WaveMind price target | ETH/USDT | 1h | 0 | 90 | 0.756 | 293.1 bps | 3.08% | 280.3 bps |
| Momentum baseline | ETH/USDT | 1h | 0 | 90 | 0.789 | 290.5 bps | 3.06% | 283.6 bps |
| Regime mean baseline | ETH/USDT | 1h | 0 | 90 | 0.811 | 261.1 bps | 2.75% | 257.3 bps |
| Historical mean baseline | ETH/USDT | 1h | 0 | 90 | 0.967 | 269.4 bps | 2.84% | 256.4 bps |
| Naive last-outcome baseline | ETH/USDT | 1h | 0 | 90 | 0.789 | 249.8 bps | 2.61% | 114.6 bps |
| WaveMind robust target | ETH/USDT | 1h | 1 | 90 | 0.389 | 145.1 bps | 1.43% | -79.6 bps |
| WaveMind calibrated target | ETH/USDT | 1h | 1 | 90 | 0.356 | 156.6 bps | 1.54% | -128.1 bps |
| WaveMind price target | ETH/USDT | 1h | 1 | 90 | 0.356 | 156.6 bps | 1.54% | -128.1 bps |
| Momentum baseline | ETH/USDT | 1h | 1 | 90 | 0.389 | 126.2 bps | 1.25% | -67.5 bps |
| Regime mean baseline | ETH/USDT | 1h | 1 | 90 | 0.578 | 126.5 bps | 1.25% | -26.1 bps |
| Historical mean baseline | ETH/USDT | 1h | 1 | 90 | 0.289 | 178.6 bps | 1.76% | -171.5 bps |
| Naive last-outcome baseline | ETH/USDT | 1h | 1 | 90 | 0.389 | 214.8 bps | 2.12% | -77.8 bps |
| WaveMind robust target | ETH/USDT | 1h | 2 | 90 | 0.456 | 197.4 bps | 2.02% | 52.8 bps |
| WaveMind calibrated target | ETH/USDT | 1h | 2 | 90 | 0.400 | 199.3 bps | 2.03% | 23.8 bps |
| WaveMind price target | ETH/USDT | 1h | 2 | 90 | 0.400 | 199.3 bps | 2.03% | 23.8 bps |
| Momentum baseline | ETH/USDT | 1h | 2 | 90 | 0.467 | 184.1 bps | 1.88% | 49.8 bps |
| Regime mean baseline | ETH/USDT | 1h | 2 | 90 | 0.222 | 257.4 bps | 2.61% | 1.9 bps |
| Historical mean baseline | ETH/USDT | 1h | 2 | 90 | 0.411 | 200.4 bps | 2.03% | -21.3 bps |
| Naive last-outcome baseline | ETH/USDT | 1h | 2 | 90 | 0.344 | 262.5 bps | 2.67% | 86.5 bps |
| WaveMind robust target | ETH/USDT | 1h | 3 | 90 | 0.533 | 269.2 bps | 2.61% | -188.5 bps |
| WaveMind calibrated target | ETH/USDT | 1h | 3 | 90 | 0.378 | 307.9 bps | 2.97% | -254.0 bps |
| WaveMind price target | ETH/USDT | 1h | 3 | 90 | 0.256 | 311.3 bps | 3.01% | -261.2 bps |
| Momentum baseline | ETH/USDT | 1h | 3 | 90 | 0.544 | 269.6 bps | 2.61% | -188.9 bps |
| Regime mean baseline | ETH/USDT | 1h | 3 | 90 | 0.656 | 266.9 bps | 2.58% | -193.9 bps |
| Historical mean baseline | ETH/USDT | 1h | 3 | 90 | 0.233 | 319.4 bps | 3.08% | -280.4 bps |
| Naive last-outcome baseline | ETH/USDT | 1h | 3 | 90 | 0.511 | 275.3 bps | 2.69% | -101.6 bps |
| WaveMind robust target | ETH/USDT | 4h | 0 | 90 | 0.511 | 342.2 bps | 3.34% | -108.0 bps |
| WaveMind calibrated target | ETH/USDT | 4h | 0 | 90 | 0.511 | 350.4 bps | 3.40% | -170.2 bps |
| WaveMind price target | ETH/USDT | 4h | 0 | 90 | 0.500 | 346.2 bps | 3.39% | -76.4 bps |
| Momentum baseline | ETH/USDT | 4h | 0 | 90 | 0.400 | 386.6 bps | 3.81% | -35.5 bps |
| Regime mean baseline | ETH/USDT | 4h | 0 | 90 | 0.433 | 350.6 bps | 3.44% | -61.3 bps |
| Historical mean baseline | ETH/USDT | 4h | 0 | 90 | 0.511 | 339.2 bps | 3.31% | -105.0 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 0 | 90 | 0.411 | 535.5 bps | 5.29% | 3.1 bps |
| WaveMind robust target | ETH/USDT | 4h | 1 | 90 | 0.533 | 252.7 bps | 2.46% | -99.3 bps |
| WaveMind calibrated target | ETH/USDT | 4h | 1 | 90 | 0.556 | 248.5 bps | 2.43% | -59.1 bps |
| WaveMind price target | ETH/USDT | 4h | 1 | 90 | 0.556 | 251.4 bps | 2.45% | -91.3 bps |
| Momentum baseline | ETH/USDT | 4h | 1 | 90 | 0.367 | 293.6 bps | 2.88% | -60.6 bps |
| Regime mean baseline | ETH/USDT | 4h | 1 | 90 | 0.533 | 261.4 bps | 2.56% | -76.8 bps |
| Historical mean baseline | ETH/USDT | 4h | 1 | 90 | 0.456 | 259.0 bps | 2.52% | -123.3 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 1 | 90 | 0.344 | 429.2 bps | 4.24% | -19.3 bps |
| WaveMind robust target | ETH/USDT | 4h | 2 | 90 | 0.400 | 159.2 bps | 1.61% | 61.4 bps |
| WaveMind calibrated target | ETH/USDT | 4h | 2 | 90 | 0.356 | 158.1 bps | 1.60% | 57.5 bps |
| WaveMind price target | ETH/USDT | 4h | 2 | 90 | 0.411 | 169.7 bps | 1.72% | 83.7 bps |
| Momentum baseline | ETH/USDT | 4h | 2 | 90 | 0.456 | 168.4 bps | 1.70% | 24.2 bps |
| Regime mean baseline | ETH/USDT | 4h | 2 | 90 | 0.567 | 158.9 bps | 1.60% | 22.1 bps |
| Historical mean baseline | ETH/USDT | 4h | 2 | 90 | 0.567 | 154.2 bps | 1.56% | 45.8 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 2 | 90 | 0.444 | 233.2 bps | 2.34% | -7.1 bps |
| WaveMind robust target | ETH/USDT | 4h | 3 | 90 | 0.456 | 201.4 bps | 2.02% | 2.7 bps |
| WaveMind calibrated target | ETH/USDT | 4h | 3 | 90 | 0.467 | 204.8 bps | 2.06% | -11.4 bps |
| WaveMind price target | ETH/USDT | 4h | 3 | 90 | 0.411 | 205.8 bps | 2.07% | 12.3 bps |
| Momentum baseline | ETH/USDT | 4h | 3 | 90 | 0.433 | 210.0 bps | 2.11% | -7.1 bps |
| Regime mean baseline | ETH/USDT | 4h | 3 | 90 | 0.400 | 230.0 bps | 2.31% | 12.6 bps |
| Historical mean baseline | ETH/USDT | 4h | 3 | 90 | 0.533 | 198.0 bps | 1.99% | 1.6 bps |
| Naive last-outcome baseline | ETH/USDT | 4h | 3 | 90 | 0.478 | 253.7 bps | 2.55% | -41.6 bps |
| WaveMind robust target | ETH/USDT | 1d | 0 | 90 | 0.456 | 755.2 bps | 7.70% | 187.7 bps |
| WaveMind calibrated target | ETH/USDT | 1d | 0 | 90 | 0.456 | 900.9 bps | 9.43% | 596.6 bps |
| WaveMind price target | ETH/USDT | 1d | 0 | 90 | 0.400 | 804.2 bps | 8.19% | 179.8 bps |
| Momentum baseline | ETH/USDT | 1d | 0 | 90 | 0.444 | 802.4 bps | 8.11% | 75.1 bps |
| Regime mean baseline | ETH/USDT | 1d | 0 | 90 | 0.500 | 827.9 bps | 8.54% | 391.8 bps |
| Historical mean baseline | ETH/USDT | 1d | 0 | 90 | 0.456 | 751.6 bps | 7.63% | 147.6 bps |
| Naive last-outcome baseline | ETH/USDT | 1d | 0 | 90 | 0.367 | 1220.8 bps | 12.34% | 111.4 bps |
| WaveMind robust target | ETH/USDT | 1d | 1 | 90 | 0.467 | 599.2 bps | 6.32% | 166.6 bps |
| WaveMind calibrated target | ETH/USDT | 1d | 1 | 90 | 0.478 | 667.4 bps | 7.19% | 474.6 bps |
| WaveMind price target | ETH/USDT | 1d | 1 | 90 | 0.367 | 634.9 bps | 6.64% | 104.0 bps |
| Momentum baseline | ETH/USDT | 1d | 1 | 90 | 0.422 | 645.4 bps | 6.72% | 55.4 bps |
| Regime mean baseline | ETH/USDT | 1d | 1 | 90 | 0.522 | 644.1 bps | 6.62% | -88.3 bps |
| Historical mean baseline | ETH/USDT | 1d | 1 | 90 | 0.478 | 606.5 bps | 6.43% | 235.0 bps |
| Naive last-outcome baseline | ETH/USDT | 1d | 1 | 90 | 0.456 | 874.3 bps | 9.02% | 12.4 bps |
| WaveMind robust target | ETH/USDT | 1d | 2 | 90 | 0.533 | 694.5 bps | 7.65% | 149.0 bps |
| WaveMind calibrated target | ETH/USDT | 1d | 2 | 90 | 0.567 | 693.1 bps | 7.57% | 62.2 bps |
| WaveMind price target | ETH/USDT | 1d | 2 | 90 | 0.378 | 727.9 bps | 8.04% | 188.4 bps |
| Momentum baseline | ETH/USDT | 1d | 2 | 90 | 0.478 | 726.8 bps | 7.94% | 90.0 bps |
| Regime mean baseline | ETH/USDT | 1d | 2 | 90 | 0.467 | 780.7 bps | 8.47% | -30.9 bps |
| Historical mean baseline | ETH/USDT | 1d | 2 | 90 | 0.433 | 697.2 bps | 7.77% | 264.7 bps |
| Naive last-outcome baseline | ETH/USDT | 1d | 2 | 90 | 0.544 | 956.4 bps | 10.24% | -19.8 bps |
| WaveMind robust target | ETH/USDT | 1d | 3 | 90 | 0.522 | 529.6 bps | 5.55% | 109.7 bps |
| WaveMind calibrated target | ETH/USDT | 1d | 3 | 90 | 0.600 | 520.7 bps | 5.41% | -7.0 bps |
| WaveMind price target | ETH/USDT | 1d | 3 | 90 | 0.567 | 540.2 bps | 5.64% | 95.6 bps |
| Momentum baseline | ETH/USDT | 1d | 3 | 90 | 0.567 | 539.6 bps | 5.62% | 101.1 bps |
| Regime mean baseline | ETH/USDT | 1d | 3 | 90 | 0.422 | 613.8 bps | 6.40% | 122.5 bps |
| Historical mean baseline | ETH/USDT | 1d | 3 | 90 | 0.367 | 536.1 bps | 5.66% | 179.4 bps |
| Naive last-outcome baseline | ETH/USDT | 1d | 3 | 90 | 0.533 | 704.3 bps | 7.22% | 10.4 bps |
| WaveMind robust target | SOL/USDT | 1h | 0 | 90 | 0.833 | 336.9 bps | 3.58% | 332.8 bps |
| WaveMind calibrated target | SOL/USDT | 1h | 0 | 90 | 1.000 | 369.5 bps | 3.92% | 368.5 bps |
| WaveMind price target | SOL/USDT | 1h | 0 | 90 | 0.700 | 376.7 bps | 3.99% | 375.5 bps |
| Momentum baseline | SOL/USDT | 1h | 0 | 90 | 0.800 | 369.0 bps | 3.92% | 369.0 bps |
| Regime mean baseline | SOL/USDT | 1h | 0 | 90 | 0.756 | 336.5 bps | 3.56% | 334.9 bps |
| Historical mean baseline | SOL/USDT | 1h | 0 | 90 | 1.000 | 367.0 bps | 3.90% | 366.5 bps |
| Naive last-outcome baseline | SOL/USDT | 1h | 0 | 90 | 0.844 | 246.8 bps | 2.61% | 149.1 bps |
| WaveMind robust target | SOL/USDT | 1h | 1 | 90 | 0.589 | 237.5 bps | 2.31% | -164.7 bps |
| WaveMind calibrated target | SOL/USDT | 1h | 1 | 90 | 0.222 | 258.5 bps | 2.52% | -222.9 bps |
| WaveMind price target | SOL/USDT | 1h | 1 | 90 | 0.222 | 258.5 bps | 2.52% | -222.9 bps |
| Momentum baseline | SOL/USDT | 1h | 1 | 90 | 0.578 | 216.3 bps | 2.11% | -149.5 bps |
| Regime mean baseline | SOL/USDT | 1h | 1 | 90 | 0.489 | 228.1 bps | 2.23% | -130.1 bps |
| Historical mean baseline | SOL/USDT | 1h | 1 | 90 | 0.178 | 290.3 bps | 2.83% | -261.9 bps |
| Naive last-outcome baseline | SOL/USDT | 1h | 1 | 90 | 0.589 | 310.5 bps | 3.03% | -129.5 bps |
| WaveMind robust target | SOL/USDT | 1h | 2 | 90 | 0.611 | 315.5 bps | 3.18% | 18.6 bps |
| WaveMind calibrated target | SOL/USDT | 1h | 2 | 90 | 0.511 | 324.7 bps | 3.26% | -14.1 bps |
| WaveMind price target | SOL/USDT | 1h | 2 | 90 | 0.511 | 324.7 bps | 3.26% | -14.1 bps |
| Momentum baseline | SOL/USDT | 1h | 2 | 90 | 0.611 | 317.2 bps | 3.19% | 1.3 bps |
| Regime mean baseline | SOL/USDT | 1h | 2 | 90 | 0.133 | 493.2 bps | 4.95% | -23.5 bps |
| Historical mean baseline | SOL/USDT | 1h | 2 | 90 | 0.444 | 341.6 bps | 3.42% | -70.5 bps |
| Naive last-outcome baseline | SOL/USDT | 1h | 2 | 90 | 0.556 | 396.2 bps | 3.98% | 114.6 bps |
| WaveMind robust target | SOL/USDT | 1h | 3 | 90 | 0.744 | 295.0 bps | 2.85% | -138.1 bps |
| WaveMind calibrated target | SOL/USDT | 1h | 3 | 90 | 0.822 | 259.1 bps | 2.50% | -125.3 bps |
| WaveMind price target | SOL/USDT | 1h | 3 | 90 | 0.567 | 327.8 bps | 3.15% | -241.6 bps |
| Momentum baseline | SOL/USDT | 1h | 3 | 90 | 0.711 | 320.2 bps | 3.08% | -219.9 bps |
| Regime mean baseline | SOL/USDT | 1h | 3 | 90 | 0.822 | 247.0 bps | 2.39% | -109.0 bps |
| Historical mean baseline | SOL/USDT | 1h | 3 | 90 | 0.178 | 351.5 bps | 3.37% | -303.4 bps |
| Naive last-outcome baseline | SOL/USDT | 1h | 3 | 90 | 0.667 | 381.1 bps | 3.73% | 13.6 bps |
| WaveMind robust target | SOL/USDT | 4h | 0 | 90 | 0.444 | 404.2 bps | 3.95% | -136.2 bps |
| WaveMind calibrated target | SOL/USDT | 4h | 0 | 90 | 0.433 | 422.8 bps | 4.11% | -224.6 bps |
| WaveMind price target | SOL/USDT | 4h | 0 | 90 | 0.467 | 399.2 bps | 3.92% | -104.0 bps |
| Momentum baseline | SOL/USDT | 4h | 0 | 90 | 0.400 | 440.0 bps | 4.34% | -52.4 bps |
| Regime mean baseline | SOL/USDT | 4h | 0 | 90 | 0.289 | 409.0 bps | 4.03% | -64.8 bps |
| Historical mean baseline | SOL/USDT | 4h | 0 | 90 | 0.433 | 402.6 bps | 3.94% | -121.8 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 0 | 90 | 0.456 | 605.3 bps | 5.98% | -8.9 bps |
| WaveMind robust target | SOL/USDT | 4h | 1 | 90 | 0.456 | 245.6 bps | 2.45% | -36.0 bps |
| WaveMind calibrated target | SOL/USDT | 4h | 1 | 90 | 0.500 | 249.5 bps | 2.50% | -16.1 bps |
| WaveMind price target | SOL/USDT | 4h | 1 | 90 | 0.478 | 247.7 bps | 2.48% | -27.8 bps |
| Momentum baseline | SOL/USDT | 4h | 1 | 90 | 0.322 | 284.0 bps | 2.84% | -19.0 bps |
| Regime mean baseline | SOL/USDT | 4h | 1 | 90 | 0.511 | 249.6 bps | 2.48% | -58.9 bps |
| Historical mean baseline | SOL/USDT | 4h | 1 | 90 | 0.400 | 244.7 bps | 2.44% | -51.1 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 1 | 90 | 0.333 | 417.3 bps | 4.17% | -5.5 bps |
| WaveMind robust target | SOL/USDT | 4h | 2 | 90 | 0.444 | 215.9 bps | 2.19% | 43.8 bps |
| WaveMind calibrated target | SOL/USDT | 4h | 2 | 90 | 0.500 | 214.1 bps | 2.18% | 87.1 bps |
| WaveMind price target | SOL/USDT | 4h | 2 | 90 | 0.444 | 224.0 bps | 2.27% | 34.9 bps |
| Momentum baseline | SOL/USDT | 4h | 2 | 90 | 0.489 | 232.9 bps | 2.36% | 37.6 bps |
| Regime mean baseline | SOL/USDT | 4h | 2 | 90 | 0.411 | 233.2 bps | 2.37% | 72.8 bps |
| Historical mean baseline | SOL/USDT | 4h | 2 | 90 | 0.500 | 212.2 bps | 2.15% | 31.6 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 2 | 90 | 0.433 | 322.7 bps | 3.25% | 19.9 bps |
| WaveMind robust target | SOL/USDT | 4h | 3 | 90 | 0.544 | 303.2 bps | 2.98% | -94.3 bps |
| WaveMind calibrated target | SOL/USDT | 4h | 3 | 90 | 0.522 | 309.4 bps | 3.05% | -87.7 bps |
| WaveMind price target | SOL/USDT | 4h | 3 | 90 | 0.522 | 305.9 bps | 3.01% | -87.4 bps |
| Momentum baseline | SOL/USDT | 4h | 3 | 90 | 0.500 | 304.4 bps | 3.00% | -60.3 bps |
| Regime mean baseline | SOL/USDT | 4h | 3 | 90 | 0.478 | 316.2 bps | 3.13% | -28.0 bps |
| Historical mean baseline | SOL/USDT | 4h | 3 | 90 | 0.422 | 303.6 bps | 2.98% | -102.6 bps |
| Naive last-outcome baseline | SOL/USDT | 4h | 3 | 90 | 0.589 | 383.7 bps | 3.80% | -47.3 bps |
| WaveMind robust target | SOL/USDT | 1d | 0 | 90 | 0.533 | 878.7 bps | 9.07% | 55.2 bps |
| WaveMind calibrated target | SOL/USDT | 1d | 0 | 90 | 0.533 | 862.2 bps | 9.07% | 248.3 bps |
| WaveMind price target | SOL/USDT | 1d | 0 | 90 | 0.444 | 898.0 bps | 9.26% | 60.1 bps |
| Momentum baseline | SOL/USDT | 1d | 0 | 90 | 0.500 | 931.0 bps | 9.55% | 14.6 bps |
| Regime mean baseline | SOL/USDT | 1d | 0 | 90 | 0.533 | 892.4 bps | 9.35% | 223.3 bps |
| Historical mean baseline | SOL/USDT | 1d | 0 | 90 | 0.533 | 873.9 bps | 9.03% | 69.1 bps |
| Naive last-outcome baseline | SOL/USDT | 1d | 0 | 90 | 0.411 | 1366.9 bps | 13.95% | 88.6 bps |
| WaveMind robust target | SOL/USDT | 1d | 1 | 90 | 0.522 | 625.1 bps | 6.70% | 217.0 bps |
| WaveMind calibrated target | SOL/USDT | 1d | 1 | 90 | 0.378 | 697.3 bps | 7.57% | 449.9 bps |
| WaveMind price target | SOL/USDT | 1d | 1 | 90 | 0.489 | 648.8 bps | 6.92% | 182.7 bps |
| Momentum baseline | SOL/USDT | 1d | 1 | 90 | 0.633 | 619.8 bps | 6.57% | 89.2 bps |
| Regime mean baseline | SOL/USDT | 1d | 1 | 90 | 0.567 | 709.1 bps | 7.42% | -59.3 bps |
| Historical mean baseline | SOL/USDT | 1d | 1 | 90 | 0.378 | 645.1 bps | 6.95% | 296.5 bps |
| Naive last-outcome baseline | SOL/USDT | 1d | 1 | 90 | 0.533 | 863.3 bps | 9.02% | 34.3 bps |
| WaveMind robust target | SOL/USDT | 1d | 2 | 90 | 0.600 | 695.1 bps | 7.72% | 234.2 bps |
| WaveMind calibrated target | SOL/USDT | 1d | 2 | 90 | 0.600 | 687.0 bps | 7.53% | 92.9 bps |
| WaveMind price target | SOL/USDT | 1d | 2 | 90 | 0.411 | 748.3 bps | 8.32% | 262.4 bps |
| Momentum baseline | SOL/USDT | 1d | 2 | 90 | 0.500 | 758.8 bps | 8.31% | 178.9 bps |
| Regime mean baseline | SOL/USDT | 1d | 2 | 90 | 0.600 | 755.3 bps | 8.24% | 37.4 bps |
| Historical mean baseline | SOL/USDT | 1d | 2 | 90 | 0.422 | 708.1 bps | 7.94% | 345.7 bps |
| Naive last-outcome baseline | SOL/USDT | 1d | 2 | 90 | 0.500 | 931.8 bps | 9.91% | 37.7 bps |
| WaveMind robust target | SOL/USDT | 1d | 3 | 90 | 0.533 | 621.4 bps | 6.49% | 53.0 bps |
| WaveMind calibrated target | SOL/USDT | 1d | 3 | 90 | 0.578 | 612.7 bps | 6.30% | -101.0 bps |
| WaveMind price target | SOL/USDT | 1d | 3 | 90 | 0.411 | 666.1 bps | 6.92% | 36.3 bps |
| Momentum baseline | SOL/USDT | 1d | 3 | 90 | 0.400 | 692.4 bps | 7.20% | 56.8 bps |
| Regime mean baseline | SOL/USDT | 1d | 3 | 90 | 0.489 | 650.2 bps | 6.77% | 29.1 bps |
| Historical mean baseline | SOL/USDT | 1d | 3 | 90 | 0.567 | 619.1 bps | 6.50% | 114.0 bps |
| Naive last-outcome baseline | SOL/USDT | 1d | 3 | 90 | 0.478 | 935.8 bps | 9.55% | -15.5 bps |
| WaveMind robust target | ADA/USDT | 1h | 0 | 90 | 0.811 | 404.8 bps | 4.37% | 404.4 bps |
| WaveMind calibrated target | ADA/USDT | 1h | 0 | 90 | 0.989 | 436.4 bps | 4.70% | 433.1 bps |
| WaveMind price target | ADA/USDT | 1h | 0 | 90 | 0.778 | 443.4 bps | 4.77% | 437.7 bps |
| Momentum baseline | ADA/USDT | 1h | 0 | 90 | 0.789 | 440.2 bps | 4.74% | 440.2 bps |
| Regime mean baseline | ADA/USDT | 1h | 0 | 90 | 0.678 | 392.9 bps | 4.21% | 392.7 bps |
| Historical mean baseline | ADA/USDT | 1h | 0 | 90 | 0.989 | 418.4 bps | 4.51% | 416.6 bps |
| Naive last-outcome baseline | ADA/USDT | 1h | 0 | 90 | 0.867 | 288.6 bps | 3.11% | 230.2 bps |
| WaveMind robust target | ADA/USDT | 1h | 1 | 90 | 0.544 | 249.1 bps | 2.43% | -130.3 bps |
| WaveMind calibrated target | ADA/USDT | 1h | 1 | 90 | 0.533 | 233.4 bps | 2.28% | -126.7 bps |
| WaveMind price target | ADA/USDT | 1h | 1 | 90 | 0.300 | 292.7 bps | 2.85% | -242.9 bps |
| Momentum baseline | ADA/USDT | 1h | 1 | 90 | 0.544 | 230.8 bps | 2.25% | -137.6 bps |
| Regime mean baseline | ADA/USDT | 1h | 1 | 90 | 0.533 | 240.9 bps | 2.37% | -84.6 bps |
| Historical mean baseline | ADA/USDT | 1h | 1 | 90 | 0.233 | 334.2 bps | 3.25% | -306.7 bps |
| Naive last-outcome baseline | ADA/USDT | 1h | 1 | 90 | 0.533 | 345.7 bps | 3.38% | -105.1 bps |
| WaveMind robust target | ADA/USDT | 1h | 2 | 90 | 0.444 | 206.6 bps | 2.13% | 97.1 bps |
| WaveMind calibrated target | ADA/USDT | 1h | 2 | 90 | 0.656 | 178.2 bps | 1.83% | 16.1 bps |
| WaveMind price target | ADA/USDT | 1h | 2 | 90 | 0.644 | 194.5 bps | 2.00% | 89.3 bps |
| Momentum baseline | ADA/USDT | 1h | 2 | 90 | 0.411 | 196.0 bps | 2.03% | 126.1 bps |
| Regime mean baseline | ADA/USDT | 1h | 2 | 90 | 0.656 | 249.3 bps | 2.55% | -5.6 bps |
| Historical mean baseline | ADA/USDT | 1h | 2 | 90 | 0.656 | 178.6 bps | 1.83% | 15.6 bps |
| Naive last-outcome baseline | ADA/USDT | 1h | 2 | 90 | 0.389 | 258.5 bps | 2.64% | 79.0 bps |
| WaveMind robust target | ADA/USDT | 1h | 3 | 90 | 0.600 | 365.8 bps | 3.47% | -319.4 bps |
| WaveMind calibrated target | ADA/USDT | 1h | 3 | 90 | 0.267 | 446.9 bps | 4.24% | -432.7 bps |
| WaveMind price target | ADA/USDT | 1h | 3 | 90 | 0.267 | 446.9 bps | 4.24% | -432.7 bps |
| Momentum baseline | ADA/USDT | 1h | 3 | 90 | 0.633 | 367.6 bps | 3.49% | -316.5 bps |
| Regime mean baseline | ADA/USDT | 1h | 3 | 90 | 0.611 | 344.5 bps | 3.27% | -307.8 bps |
| Historical mean baseline | ADA/USDT | 1h | 3 | 90 | 0.178 | 482.1 bps | 4.57% | -472.3 bps |
| Naive last-outcome baseline | ADA/USDT | 1h | 3 | 90 | 0.611 | 325.5 bps | 3.11% | -134.3 bps |
| WaveMind robust target | ADA/USDT | 4h | 0 | 90 | 0.644 | 357.9 bps | 3.51% | -40.9 bps |
| WaveMind calibrated target | ADA/USDT | 4h | 0 | 90 | 0.644 | 352.4 bps | 3.44% | -72.4 bps |
| WaveMind price target | ADA/USDT | 4h | 0 | 90 | 0.589 | 358.2 bps | 3.52% | -33.3 bps |
| Momentum baseline | ADA/USDT | 4h | 0 | 90 | 0.422 | 427.2 bps | 4.22% | -4.3 bps |
| Regime mean baseline | ADA/USDT | 4h | 0 | 90 | 0.289 | 391.6 bps | 3.87% | 17.3 bps |
| Historical mean baseline | ADA/USDT | 4h | 0 | 90 | 0.644 | 361.5 bps | 3.55% | -32.9 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 0 | 90 | 0.433 | 581.9 bps | 5.76% | -0.5 bps |
| WaveMind robust target | ADA/USDT | 4h | 1 | 90 | 0.533 | 264.2 bps | 2.63% | -21.4 bps |
| WaveMind calibrated target | ADA/USDT | 4h | 1 | 90 | 0.589 | 265.6 bps | 2.65% | -15.9 bps |
| WaveMind price target | ADA/USDT | 4h | 1 | 90 | 0.589 | 266.1 bps | 2.65% | -19.5 bps |
| Momentum baseline | ADA/USDT | 4h | 1 | 90 | 0.311 | 324.1 bps | 3.24% | 1.9 bps |
| Regime mean baseline | ADA/USDT | 4h | 1 | 90 | 0.389 | 272.7 bps | 2.72% | -17.8 bps |
| Historical mean baseline | ADA/USDT | 4h | 1 | 90 | 0.511 | 265.6 bps | 2.65% | -25.2 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 1 | 90 | 0.256 | 485.1 bps | 4.85% | 5.3 bps |
| WaveMind robust target | ADA/USDT | 4h | 2 | 90 | 0.411 | 201.1 bps | 2.04% | 74.7 bps |
| WaveMind calibrated target | ADA/USDT | 4h | 2 | 90 | 0.411 | 216.6 bps | 2.21% | 126.9 bps |
| WaveMind price target | ADA/USDT | 4h | 2 | 90 | 0.478 | 207.4 bps | 2.10% | 73.0 bps |
| Momentum baseline | ADA/USDT | 4h | 2 | 90 | 0.422 | 233.2 bps | 2.36% | 49.1 bps |
| Regime mean baseline | ADA/USDT | 4h | 2 | 90 | 0.444 | 221.9 bps | 2.25% | 84.5 bps |
| Historical mean baseline | ADA/USDT | 4h | 2 | 90 | 0.589 | 195.0 bps | 1.97% | 52.7 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 2 | 90 | 0.378 | 336.5 bps | 3.39% | 21.5 bps |
| WaveMind robust target | ADA/USDT | 4h | 3 | 90 | 0.589 | 260.8 bps | 2.59% | -50.4 bps |
| WaveMind calibrated target | ADA/USDT | 4h | 3 | 90 | 0.589 | 286.8 bps | 2.84% | -132.3 bps |
| WaveMind price target | ADA/USDT | 4h | 3 | 90 | 0.456 | 275.7 bps | 2.74% | -51.3 bps |
| Momentum baseline | ADA/USDT | 4h | 3 | 90 | 0.600 | 241.2 bps | 2.40% | -31.1 bps |
| Regime mean baseline | ADA/USDT | 4h | 3 | 90 | 0.489 | 267.1 bps | 2.66% | -46.7 bps |
| Historical mean baseline | ADA/USDT | 4h | 3 | 90 | 0.589 | 245.3 bps | 2.45% | -13.3 bps |
| Naive last-outcome baseline | ADA/USDT | 4h | 3 | 90 | 0.511 | 297.2 bps | 2.97% | -56.6 bps |
| WaveMind robust target | ADA/USDT | 1d | 0 | 90 | 0.478 | 809.2 bps | 8.64% | 272.9 bps |
| WaveMind calibrated target | ADA/USDT | 1d | 0 | 90 | 0.411 | 853.6 bps | 9.20% | 411.2 bps |
| WaveMind price target | ADA/USDT | 1d | 0 | 90 | 0.411 | 884.0 bps | 9.48% | 407.9 bps |
| Momentum baseline | ADA/USDT | 1d | 0 | 90 | 0.444 | 843.9 bps | 8.92% | 153.4 bps |
| Regime mean baseline | ADA/USDT | 1d | 0 | 90 | 0.467 | 871.4 bps | 9.32% | 384.3 bps |
| Historical mean baseline | ADA/USDT | 1d | 0 | 90 | 0.411 | 877.7 bps | 9.50% | 479.6 bps |
| Naive last-outcome baseline | ADA/USDT | 1d | 0 | 90 | 0.433 | 1246.5 bps | 13.10% | 126.9 bps |
| WaveMind robust target | ADA/USDT | 1d | 1 | 90 | 0.678 | 764.1 bps | 8.29% | 339.8 bps |
| WaveMind calibrated target | ADA/USDT | 1d | 1 | 90 | 0.322 | 821.7 bps | 9.01% | 498.4 bps |
| WaveMind price target | ADA/USDT | 1d | 1 | 90 | 0.511 | 825.2 bps | 9.01% | 439.2 bps |
| Momentum baseline | ADA/USDT | 1d | 1 | 90 | 0.533 | 794.6 bps | 8.49% | 187.8 bps |
| Regime mean baseline | ADA/USDT | 1d | 1 | 90 | 0.689 | 770.5 bps | 8.04% | -73.1 bps |
| Historical mean baseline | ADA/USDT | 1d | 1 | 90 | 0.311 | 856.2 bps | 9.41% | 570.3 bps |
| Naive last-outcome baseline | ADA/USDT | 1d | 1 | 90 | 0.500 | 1081.4 bps | 11.38% | 85.7 bps |
| WaveMind robust target | ADA/USDT | 1d | 2 | 90 | 0.611 | 648.0 bps | 6.95% | 196.0 bps |
| WaveMind calibrated target | ADA/USDT | 1d | 2 | 90 | 0.611 | 622.3 bps | 6.49% | -94.2 bps |
| WaveMind price target | ADA/USDT | 1d | 2 | 90 | 0.444 | 675.9 bps | 7.30% | 261.0 bps |
| Momentum baseline | ADA/USDT | 1d | 2 | 90 | 0.422 | 716.7 bps | 7.63% | 169.1 bps |
| Regime mean baseline | ADA/USDT | 1d | 2 | 90 | 0.611 | 647.4 bps | 6.83% | 11.9 bps |
| Historical mean baseline | ADA/USDT | 1d | 2 | 90 | 0.389 | 692.3 bps | 7.55% | 413.1 bps |
| Naive last-outcome baseline | ADA/USDT | 1d | 2 | 90 | 0.400 | 936.3 bps | 9.78% | 6.0 bps |
| WaveMind robust target | ADA/USDT | 1d | 3 | 90 | 0.611 | 690.7 bps | 7.81% | 249.7 bps |
| WaveMind calibrated target | ADA/USDT | 1d | 3 | 90 | 0.611 | 675.5 bps | 7.53% | 74.9 bps |
| WaveMind price target | ADA/USDT | 1d | 3 | 90 | 0.478 | 704.4 bps | 7.94% | 209.4 bps |
| Momentum baseline | ADA/USDT | 1d | 3 | 90 | 0.567 | 715.7 bps | 7.99% | 185.0 bps |
| Regime mean baseline | ADA/USDT | 1d | 3 | 90 | 0.511 | 698.0 bps | 7.86% | 187.5 bps |
| Historical mean baseline | ADA/USDT | 1d | 3 | 90 | 0.389 | 713.0 bps | 8.15% | 397.0 bps |
| Naive last-outcome baseline | ADA/USDT | 1d | 3 | 90 | 0.489 | 1010.6 bps | 10.84% | 20.8 bps |
| WaveMind robust target | XRP/USDT | 1h | 0 | 90 | 0.844 | 279.8 bps | 2.92% | 247.4 bps |
| WaveMind calibrated target | XRP/USDT | 1h | 0 | 90 | 0.667 | 301.3 bps | 3.15% | 291.6 bps |
| WaveMind price target | XRP/USDT | 1h | 0 | 90 | 0.667 | 301.3 bps | 3.15% | 291.6 bps |
| Momentum baseline | XRP/USDT | 1h | 0 | 90 | 0.844 | 292.3 bps | 3.05% | 276.3 bps |
| Regime mean baseline | XRP/USDT | 1h | 0 | 90 | 0.500 | 288.6 bps | 3.00% | 255.1 bps |
| Historical mean baseline | XRP/USDT | 1h | 0 | 90 | 0.967 | 274.6 bps | 2.87% | 264.8 bps |
| Naive last-outcome baseline | XRP/USDT | 1h | 0 | 90 | 0.911 | 240.6 bps | 2.49% | 73.3 bps |
| WaveMind robust target | XRP/USDT | 1h | 1 | 90 | 0.444 | 191.7 bps | 1.90% | -92.7 bps |
| WaveMind calibrated target | XRP/USDT | 1h | 1 | 90 | 0.400 | 184.6 bps | 1.82% | -115.0 bps |
| WaveMind price target | XRP/USDT | 1h | 1 | 90 | 0.400 | 184.6 bps | 1.82% | -115.0 bps |
| Momentum baseline | XRP/USDT | 1h | 1 | 90 | 0.444 | 175.0 bps | 1.73% | -68.9 bps |
| Regime mean baseline | XRP/USDT | 1h | 1 | 90 | 0.344 | 221.5 bps | 2.20% | -86.8 bps |
| Historical mean baseline | XRP/USDT | 1h | 1 | 90 | 0.333 | 196.9 bps | 1.94% | -145.7 bps |
| Naive last-outcome baseline | XRP/USDT | 1h | 1 | 90 | 0.433 | 279.0 bps | 2.76% | -120.2 bps |
| WaveMind robust target | XRP/USDT | 1h | 2 | 90 | 0.444 | 153.6 bps | 1.55% | 45.6 bps |
| WaveMind calibrated target | XRP/USDT | 1h | 2 | 90 | 0.389 | 157.7 bps | 1.59% | 35.6 bps |
| WaveMind price target | XRP/USDT | 1h | 2 | 90 | 0.389 | 157.7 bps | 1.59% | 35.6 bps |
| Momentum baseline | XRP/USDT | 1h | 2 | 90 | 0.444 | 136.4 bps | 1.38% | 55.1 bps |
| Regime mean baseline | XRP/USDT | 1h | 2 | 90 | 0.444 | 223.7 bps | 2.25% | -78.1 bps |
| Historical mean baseline | XRP/USDT | 1h | 2 | 90 | 0.656 | 125.8 bps | 1.27% | 3.6 bps |
| Naive last-outcome baseline | XRP/USDT | 1h | 2 | 90 | 0.444 | 198.2 bps | 2.00% | 29.9 bps |
| WaveMind robust target | XRP/USDT | 1h | 3 | 90 | 0.478 | 183.2 bps | 1.80% | -110.6 bps |
| WaveMind calibrated target | XRP/USDT | 1h | 3 | 90 | 0.267 | 213.8 bps | 2.09% | -173.1 bps |
| WaveMind price target | XRP/USDT | 1h | 3 | 90 | 0.211 | 226.0 bps | 2.21% | -177.4 bps |
| Momentum baseline | XRP/USDT | 1h | 3 | 90 | 0.522 | 174.3 bps | 1.71% | -99.8 bps |
| Regime mean baseline | XRP/USDT | 1h | 3 | 90 | 0.344 | 195.8 bps | 1.92% | -122.0 bps |
| Historical mean baseline | XRP/USDT | 1h | 3 | 90 | 0.267 | 214.2 bps | 2.10% | -176.1 bps |
| Naive last-outcome baseline | XRP/USDT | 1h | 3 | 90 | 0.522 | 195.6 bps | 1.93% | -57.7 bps |
| WaveMind robust target | XRP/USDT | 4h | 0 | 90 | 0.578 | 283.4 bps | 2.81% | -38.5 bps |
| WaveMind calibrated target | XRP/USDT | 4h | 0 | 90 | 0.578 | 280.1 bps | 2.77% | -77.2 bps |
| WaveMind price target | XRP/USDT | 4h | 0 | 90 | 0.489 | 290.0 bps | 2.88% | -24.3 bps |
| Momentum baseline | XRP/USDT | 4h | 0 | 90 | 0.411 | 324.4 bps | 3.23% | -10.3 bps |
| Regime mean baseline | XRP/USDT | 4h | 0 | 90 | 0.300 | 291.7 bps | 2.90% | -12.0 bps |
| Historical mean baseline | XRP/USDT | 4h | 0 | 90 | 0.578 | 281.0 bps | 2.79% | -32.3 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 0 | 90 | 0.433 | 446.6 bps | 4.45% | -6.2 bps |
| WaveMind robust target | XRP/USDT | 4h | 1 | 90 | 0.511 | 182.7 bps | 1.82% | -31.6 bps |
| WaveMind calibrated target | XRP/USDT | 4h | 1 | 90 | 0.533 | 182.2 bps | 1.81% | -28.0 bps |
| WaveMind price target | XRP/USDT | 4h | 1 | 90 | 0.511 | 183.4 bps | 1.83% | -19.5 bps |
| Momentum baseline | XRP/USDT | 4h | 1 | 90 | 0.244 | 222.2 bps | 2.21% | -13.7 bps |
| Regime mean baseline | XRP/USDT | 4h | 1 | 90 | 0.522 | 186.0 bps | 1.85% | -44.1 bps |
| Historical mean baseline | XRP/USDT | 4h | 1 | 90 | 0.511 | 184.2 bps | 1.83% | -42.5 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 1 | 90 | 0.289 | 336.2 bps | 3.36% | -7.6 bps |
| WaveMind robust target | XRP/USDT | 4h | 2 | 90 | 0.467 | 175.5 bps | 1.76% | 23.1 bps |
| WaveMind calibrated target | XRP/USDT | 4h | 2 | 90 | 0.522 | 175.3 bps | 1.76% | 26.3 bps |
| WaveMind price target | XRP/USDT | 4h | 2 | 90 | 0.433 | 180.5 bps | 1.81% | 34.6 bps |
| Momentum baseline | XRP/USDT | 4h | 2 | 90 | 0.456 | 196.1 bps | 1.96% | 16.4 bps |
| Regime mean baseline | XRP/USDT | 4h | 2 | 90 | 0.467 | 184.6 bps | 1.85% | 36.4 bps |
| Historical mean baseline | XRP/USDT | 4h | 2 | 90 | 0.600 | 173.5 bps | 1.74% | 12.7 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 2 | 90 | 0.500 | 283.7 bps | 2.85% | 4.6 bps |
| WaveMind robust target | XRP/USDT | 4h | 3 | 90 | 0.611 | 173.6 bps | 1.75% | 33.6 bps |
| WaveMind calibrated target | XRP/USDT | 4h | 3 | 90 | 0.611 | 171.2 bps | 1.73% | 22.5 bps |
| WaveMind price target | XRP/USDT | 4h | 3 | 90 | 0.500 | 179.0 bps | 1.81% | 35.1 bps |
| Momentum baseline | XRP/USDT | 4h | 3 | 90 | 0.600 | 177.3 bps | 1.79% | 15.1 bps |
| Regime mean baseline | XRP/USDT | 4h | 3 | 90 | 0.389 | 207.5 bps | 2.09% | 22.0 bps |
| Historical mean baseline | XRP/USDT | 4h | 3 | 90 | 0.611 | 172.1 bps | 1.74% | 37.3 bps |
| Naive last-outcome baseline | XRP/USDT | 4h | 3 | 90 | 0.522 | 209.7 bps | 2.10% | -34.4 bps |
| WaveMind robust target | XRP/USDT | 1d | 0 | 90 | 0.400 | 653.5 bps | 6.94% | 278.3 bps |
| WaveMind calibrated target | XRP/USDT | 1d | 0 | 90 | 0.378 | 716.0 bps | 7.69% | 476.6 bps |
| WaveMind price target | XRP/USDT | 1d | 0 | 90 | 0.489 | 621.3 bps | 6.59% | 240.4 bps |
| Momentum baseline | XRP/USDT | 1d | 0 | 90 | 0.422 | 693.5 bps | 7.27% | 144.1 bps |
| Regime mean baseline | XRP/USDT | 1d | 0 | 90 | 0.422 | 721.6 bps | 7.64% | 342.7 bps |
| Historical mean baseline | XRP/USDT | 1d | 0 | 90 | 0.378 | 795.2 bps | 8.57% | 619.3 bps |
| Naive last-outcome baseline | XRP/USDT | 1d | 0 | 90 | 0.367 | 1061.9 bps | 11.06% | 111.4 bps |
| WaveMind robust target | XRP/USDT | 1d | 1 | 90 | 0.589 | 644.9 bps | 6.56% | 140.7 bps |
| WaveMind calibrated target | XRP/USDT | 1d | 1 | 90 | 0.667 | 657.8 bps | 6.70% | 175.4 bps |
| WaveMind price target | XRP/USDT | 1d | 1 | 90 | 0.667 | 657.8 bps | 6.70% | 175.4 bps |
| Momentum baseline | XRP/USDT | 1d | 1 | 90 | 0.478 | 715.9 bps | 7.26% | 103.0 bps |
| Regime mean baseline | XRP/USDT | 1d | 1 | 90 | 0.700 | 615.8 bps | 6.15% | -36.2 bps |
| Historical mean baseline | XRP/USDT | 1d | 1 | 90 | 0.300 | 799.0 bps | 8.33% | 488.8 bps |
| Naive last-outcome baseline | XRP/USDT | 1d | 1 | 90 | 0.467 | 1038.4 bps | 10.53% | 110.7 bps |
| WaveMind robust target | XRP/USDT | 1d | 2 | 90 | 0.678 | 553.8 bps | 6.04% | 223.7 bps |
| WaveMind calibrated target | XRP/USDT | 1d | 2 | 90 | 0.656 | 539.1 bps | 5.85% | 133.2 bps |
| WaveMind price target | XRP/USDT | 1d | 2 | 90 | 0.422 | 606.7 bps | 6.67% | 314.2 bps |
| Momentum baseline | XRP/USDT | 1d | 2 | 90 | 0.544 | 588.7 bps | 6.34% | 157.8 bps |
| Regime mean baseline | XRP/USDT | 1d | 2 | 90 | 0.678 | 580.9 bps | 6.24% | 53.4 bps |
| Historical mean baseline | XRP/USDT | 1d | 2 | 90 | 0.322 | 674.0 bps | 7.44% | 535.4 bps |
| Naive last-outcome baseline | XRP/USDT | 1d | 2 | 90 | 0.522 | 755.6 bps | 7.91% | -10.7 bps |
| WaveMind robust target | XRP/USDT | 1d | 3 | 90 | 0.622 | 450.9 bps | 4.69% | 84.2 bps |
| WaveMind calibrated target | XRP/USDT | 1d | 3 | 90 | 0.633 | 453.6 bps | 4.65% | -74.1 bps |
| WaveMind price target | XRP/USDT | 1d | 3 | 90 | 0.411 | 500.1 bps | 5.23% | 155.7 bps |
| Momentum baseline | XRP/USDT | 1d | 3 | 90 | 0.567 | 475.8 bps | 4.94% | 96.8 bps |
| Regime mean baseline | XRP/USDT | 1d | 3 | 90 | 0.589 | 486.2 bps | 5.05% | 79.9 bps |
| Historical mean baseline | XRP/USDT | 1d | 3 | 90 | 0.367 | 512.9 bps | 5.43% | 349.4 bps |
| Naive last-outcome baseline | XRP/USDT | 1d | 3 | 90 | 0.511 | 651.9 bps | 6.70% | 14.6 bps |
| WaveMind robust target | DOGE/USDT | 1h | 0 | 90 | 0.622 | 261.4 bps | 2.76% | 236.7 bps |
| WaveMind calibrated target | DOGE/USDT | 1h | 0 | 90 | 0.500 | 292.9 bps | 3.08% | 286.3 bps |
| WaveMind price target | DOGE/USDT | 1h | 0 | 90 | 0.633 | 280.2 bps | 2.95% | 268.6 bps |
| Momentum baseline | DOGE/USDT | 1h | 0 | 90 | 0.656 | 272.3 bps | 2.87% | 254.1 bps |
| Regime mean baseline | DOGE/USDT | 1h | 0 | 90 | 0.511 | 262.7 bps | 2.77% | 250.7 bps |
| Historical mean baseline | DOGE/USDT | 1h | 0 | 90 | 0.889 | 253.8 bps | 2.68% | 222.6 bps |
| Naive last-outcome baseline | DOGE/USDT | 1h | 0 | 90 | 0.767 | 262.7 bps | 2.75% | 82.5 bps |
| WaveMind robust target | DOGE/USDT | 1h | 1 | 90 | 0.567 | 171.4 bps | 1.68% | -97.7 bps |
| WaveMind calibrated target | DOGE/USDT | 1h | 1 | 90 | 0.556 | 162.5 bps | 1.60% | -104.3 bps |
| WaveMind price target | DOGE/USDT | 1h | 1 | 90 | 0.222 | 207.9 bps | 2.04% | -176.8 bps |
| Momentum baseline | DOGE/USDT | 1h | 1 | 90 | 0.556 | 169.4 bps | 1.66% | -104.6 bps |
| Regime mean baseline | DOGE/USDT | 1h | 1 | 90 | 0.456 | 188.8 bps | 1.86% | -80.4 bps |
| Historical mean baseline | DOGE/USDT | 1h | 1 | 90 | 0.211 | 231.5 bps | 2.27% | -206.0 bps |
| Naive last-outcome baseline | DOGE/USDT | 1h | 1 | 90 | 0.567 | 245.4 bps | 2.41% | -73.4 bps |
| WaveMind robust target | DOGE/USDT | 1h | 2 | 90 | 0.389 | 179.0 bps | 1.85% | 91.6 bps |
| WaveMind calibrated target | DOGE/USDT | 1h | 2 | 90 | 0.589 | 171.1 bps | 1.75% | 17.6 bps |
| WaveMind price target | DOGE/USDT | 1h | 2 | 90 | 0.567 | 164.8 bps | 1.70% | 61.7 bps |
| Momentum baseline | DOGE/USDT | 1h | 2 | 90 | 0.389 | 172.9 bps | 1.79% | 106.1 bps |
| Regime mean baseline | DOGE/USDT | 1h | 2 | 90 | 0.389 | 233.7 bps | 2.39% | 8.1 bps |
| Historical mean baseline | DOGE/USDT | 1h | 2 | 90 | 0.589 | 169.3 bps | 1.74% | 32.8 bps |
| Naive last-outcome baseline | DOGE/USDT | 1h | 2 | 90 | 0.333 | 228.5 bps | 2.34% | 103.3 bps |
| WaveMind robust target | DOGE/USDT | 1h | 3 | 90 | 0.667 | 183.3 bps | 1.81% | -101.6 bps |
| WaveMind calibrated target | DOGE/USDT | 1h | 3 | 90 | 0.389 | 227.6 bps | 2.24% | -180.2 bps |
| WaveMind price target | DOGE/USDT | 1h | 3 | 90 | 0.400 | 212.3 bps | 2.09% | -148.2 bps |
| Momentum baseline | DOGE/USDT | 1h | 3 | 90 | 0.633 | 178.7 bps | 1.77% | -69.5 bps |
| Regime mean baseline | DOGE/USDT | 1h | 3 | 90 | 0.444 | 219.0 bps | 2.16% | -154.1 bps |
| Historical mean baseline | DOGE/USDT | 1h | 3 | 90 | 0.389 | 216.6 bps | 2.13% | -160.2 bps |
| Naive last-outcome baseline | DOGE/USDT | 1h | 3 | 90 | 0.644 | 204.0 bps | 2.02% | -80.9 bps |
| WaveMind robust target | DOGE/USDT | 4h | 0 | 90 | 0.556 | 361.5 bps | 3.57% | -8.3 bps |
| WaveMind calibrated target | DOGE/USDT | 4h | 0 | 90 | 0.478 | 363.7 bps | 3.60% | -1.7 bps |
| WaveMind price target | DOGE/USDT | 4h | 0 | 90 | 0.467 | 364.1 bps | 3.60% | -2.9 bps |
| Momentum baseline | DOGE/USDT | 4h | 0 | 90 | 0.433 | 427.9 bps | 4.24% | 1.7 bps |
| Regime mean baseline | DOGE/USDT | 4h | 0 | 90 | 0.478 | 376.0 bps | 3.72% | 12.4 bps |
| Historical mean baseline | DOGE/USDT | 4h | 0 | 90 | 0.633 | 359.3 bps | 3.55% | -15.4 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 0 | 90 | 0.433 | 583.1 bps | 5.81% | 11.8 bps |
| WaveMind robust target | DOGE/USDT | 4h | 1 | 90 | 0.478 | 174.1 bps | 1.73% | -29.7 bps |
| WaveMind calibrated target | DOGE/USDT | 4h | 1 | 90 | 0.600 | 172.3 bps | 1.72% | -16.5 bps |
| WaveMind price target | DOGE/USDT | 4h | 1 | 90 | 0.578 | 172.9 bps | 1.72% | -25.2 bps |
| Momentum baseline | DOGE/USDT | 4h | 1 | 90 | 0.278 | 210.3 bps | 2.10% | -9.6 bps |
| Regime mean baseline | DOGE/USDT | 4h | 1 | 90 | 0.511 | 175.9 bps | 1.75% | -17.2 bps |
| Historical mean baseline | DOGE/USDT | 4h | 1 | 90 | 0.433 | 177.8 bps | 1.77% | -39.1 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 1 | 90 | 0.311 | 312.9 bps | 3.13% | -2.7 bps |
| WaveMind robust target | DOGE/USDT | 4h | 2 | 90 | 0.578 | 198.6 bps | 2.02% | 63.6 bps |
| WaveMind calibrated target | DOGE/USDT | 4h | 2 | 90 | 0.544 | 219.7 bps | 2.25% | 143.1 bps |
| WaveMind price target | DOGE/USDT | 4h | 2 | 90 | 0.589 | 198.4 bps | 2.02% | 57.4 bps |
| Momentum baseline | DOGE/USDT | 4h | 2 | 90 | 0.411 | 225.6 bps | 2.28% | 17.4 bps |
| Regime mean baseline | DOGE/USDT | 4h | 2 | 90 | 0.578 | 202.4 bps | 2.05% | 46.4 bps |
| Historical mean baseline | DOGE/USDT | 4h | 2 | 90 | 0.467 | 201.7 bps | 2.05% | 33.0 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 2 | 90 | 0.467 | 303.8 bps | 3.07% | 8.3 bps |
| WaveMind robust target | DOGE/USDT | 4h | 3 | 90 | 0.600 | 192.1 bps | 1.96% | 70.9 bps |
| WaveMind calibrated target | DOGE/USDT | 4h | 3 | 90 | 0.622 | 183.3 bps | 1.86% | 33.8 bps |
| WaveMind price target | DOGE/USDT | 4h | 3 | 90 | 0.500 | 200.9 bps | 2.05% | 85.7 bps |
| Momentum baseline | DOGE/USDT | 4h | 3 | 90 | 0.600 | 189.5 bps | 1.92% | 29.5 bps |
| Regime mean baseline | DOGE/USDT | 4h | 3 | 90 | 0.544 | 193.9 bps | 1.97% | 21.1 bps |
| Historical mean baseline | DOGE/USDT | 4h | 3 | 90 | 0.622 | 191.4 bps | 1.95% | 75.8 bps |
| Naive last-outcome baseline | DOGE/USDT | 4h | 3 | 90 | 0.522 | 235.5 bps | 2.38% | -26.0 bps |
| WaveMind robust target | DOGE/USDT | 1d | 0 | 90 | 0.456 | 911.4 bps | 9.61% | 220.6 bps |
| WaveMind calibrated target | DOGE/USDT | 1d | 0 | 90 | 0.433 | 971.8 bps | 10.40% | 434.5 bps |
| WaveMind price target | DOGE/USDT | 1d | 0 | 90 | 0.411 | 945.3 bps | 9.97% | 259.6 bps |
| Momentum baseline | DOGE/USDT | 1d | 0 | 90 | 0.467 | 967.9 bps | 10.13% | 113.9 bps |
| Regime mean baseline | DOGE/USDT | 1d | 0 | 90 | 0.500 | 965.5 bps | 10.30% | 360.6 bps |
| Historical mean baseline | DOGE/USDT | 1d | 0 | 90 | 0.433 | 964.7 bps | 10.32% | 412.0 bps |
| Naive last-outcome baseline | DOGE/USDT | 1d | 0 | 90 | 0.367 | 1520.6 bps | 15.90% | 141.0 bps |
| WaveMind robust target | DOGE/USDT | 1d | 1 | 90 | 0.611 | 720.3 bps | 7.46% | 255.1 bps |
| WaveMind calibrated target | DOGE/USDT | 1d | 1 | 90 | 0.500 | 759.7 bps | 7.92% | 340.4 bps |
| WaveMind price target | DOGE/USDT | 1d | 1 | 90 | 0.589 | 728.2 bps | 7.52% | 218.9 bps |
| Momentum baseline | DOGE/USDT | 1d | 1 | 90 | 0.533 | 777.7 bps | 7.97% | 152.4 bps |
| Regime mean baseline | DOGE/USDT | 1d | 1 | 90 | 0.733 | 685.2 bps | 6.93% | -15.4 bps |
| Historical mean baseline | DOGE/USDT | 1d | 1 | 90 | 0.267 | 828.2 bps | 8.72% | 495.2 bps |
| Naive last-outcome baseline | DOGE/USDT | 1d | 1 | 90 | 0.478 | 1081.0 bps | 10.99% | 102.5 bps |
| WaveMind robust target | DOGE/USDT | 1d | 2 | 90 | 0.667 | 562.7 bps | 6.02% | 184.8 bps |
| WaveMind calibrated target | DOGE/USDT | 1d | 2 | 90 | 0.667 | 550.3 bps | 5.77% | -30.5 bps |
| WaveMind price target | DOGE/USDT | 1d | 2 | 90 | 0.556 | 577.4 bps | 6.19% | 183.7 bps |
| Momentum baseline | DOGE/USDT | 1d | 2 | 90 | 0.467 | 615.8 bps | 6.52% | 144.9 bps |
| Regime mean baseline | DOGE/USDT | 1d | 2 | 90 | 0.667 | 571.3 bps | 6.02% | 19.6 bps |
| Historical mean baseline | DOGE/USDT | 1d | 2 | 90 | 0.333 | 635.9 bps | 6.89% | 408.4 bps |
| Naive last-outcome baseline | DOGE/USDT | 1d | 2 | 90 | 0.522 | 792.4 bps | 8.25% | -18.0 bps |
| WaveMind robust target | DOGE/USDT | 1d | 3 | 90 | 0.522 | 555.8 bps | 5.77% | 80.5 bps |
| WaveMind calibrated target | DOGE/USDT | 1d | 3 | 90 | 0.511 | 560.9 bps | 5.72% | -95.4 bps |
| WaveMind price target | DOGE/USDT | 1d | 3 | 90 | 0.478 | 613.7 bps | 6.36% | 113.8 bps |
| Momentum baseline | DOGE/USDT | 1d | 3 | 90 | 0.656 | 546.8 bps | 5.67% | 101.3 bps |
| Regime mean baseline | DOGE/USDT | 1d | 3 | 90 | 0.344 | 618.7 bps | 6.44% | 129.6 bps |
| Historical mean baseline | DOGE/USDT | 1d | 3 | 90 | 0.489 | 559.2 bps | 5.88% | 224.4 bps |
| Naive last-outcome baseline | DOGE/USDT | 1d | 3 | 90 | 0.633 | 682.9 bps | 7.01% | 62.2 bps |
| WaveMind robust target | LINK/USDT | 1h | 0 | 90 | 0.767 | 262.9 bps | 2.75% | 235.0 bps |
| WaveMind calibrated target | LINK/USDT | 1h | 0 | 90 | 0.956 | 261.6 bps | 2.74% | 250.3 bps |
| WaveMind price target | LINK/USDT | 1h | 0 | 90 | 0.756 | 273.4 bps | 2.86% | 268.0 bps |
| Momentum baseline | LINK/USDT | 1h | 0 | 90 | 0.744 | 287.8 bps | 3.02% | 273.9 bps |
| Regime mean baseline | LINK/USDT | 1h | 0 | 90 | 0.500 | 280.9 bps | 2.93% | 266.8 bps |
| Historical mean baseline | LINK/USDT | 1h | 0 | 90 | 0.956 | 269.5 bps | 2.83% | 259.9 bps |
| Naive last-outcome baseline | LINK/USDT | 1h | 0 | 90 | 0.778 | 250.6 bps | 2.60% | 92.4 bps |
| WaveMind robust target | LINK/USDT | 1h | 1 | 90 | 0.478 | 173.1 bps | 1.71% | -56.1 bps |
| WaveMind calibrated target | LINK/USDT | 1h | 1 | 90 | 0.533 | 143.9 bps | 1.43% | -21.3 bps |
| WaveMind price target | LINK/USDT | 1h | 1 | 90 | 0.400 | 186.6 bps | 1.84% | -134.9 bps |
| Momentum baseline | LINK/USDT | 1h | 1 | 90 | 0.467 | 164.5 bps | 1.63% | -70.4 bps |
| Regime mean baseline | LINK/USDT | 1h | 1 | 90 | 0.433 | 192.5 bps | 1.92% | -43.1 bps |
| Historical mean baseline | LINK/USDT | 1h | 1 | 90 | 0.344 | 198.2 bps | 1.95% | -152.7 bps |
| Naive last-outcome baseline | LINK/USDT | 1h | 1 | 90 | 0.444 | 254.6 bps | 2.51% | -81.4 bps |
| WaveMind robust target | LINK/USDT | 1h | 2 | 90 | 0.433 | 164.6 bps | 1.69% | 78.1 bps |
| WaveMind calibrated target | LINK/USDT | 1h | 2 | 90 | 0.500 | 164.2 bps | 1.69% | 69.9 bps |
| WaveMind price target | LINK/USDT | 1h | 2 | 90 | 0.489 | 161.5 bps | 1.66% | 54.5 bps |
| Momentum baseline | LINK/USDT | 1h | 2 | 90 | 0.433 | 160.6 bps | 1.66% | 79.5 bps |
| Regime mean baseline | LINK/USDT | 1h | 2 | 90 | 0.267 | 220.4 bps | 2.25% | -2.4 bps |
| Historical mean baseline | LINK/USDT | 1h | 2 | 90 | 0.500 | 163.5 bps | 1.67% | 23.9 bps |
| Naive last-outcome baseline | LINK/USDT | 1h | 2 | 90 | 0.344 | 220.8 bps | 2.26% | 79.4 bps |
| WaveMind robust target | LINK/USDT | 1h | 3 | 90 | 0.489 | 269.3 bps | 2.62% | -150.1 bps |
| WaveMind calibrated target | LINK/USDT | 1h | 3 | 90 | 0.356 | 288.6 bps | 2.80% | -217.8 bps |
| WaveMind price target | LINK/USDT | 1h | 3 | 90 | 0.356 | 288.6 bps | 2.80% | -217.8 bps |
| Momentum baseline | LINK/USDT | 1h | 3 | 90 | 0.444 | 259.2 bps | 2.52% | -140.8 bps |
| Regime mean baseline | LINK/USDT | 1h | 3 | 90 | 0.367 | 270.6 bps | 2.63% | -160.4 bps |
| Historical mean baseline | LINK/USDT | 1h | 3 | 90 | 0.333 | 289.0 bps | 2.80% | -224.7 bps |
| Naive last-outcome baseline | LINK/USDT | 1h | 3 | 90 | 0.456 | 303.3 bps | 2.98% | -65.8 bps |
| WaveMind robust target | LINK/USDT | 4h | 0 | 90 | 0.544 | 355.7 bps | 3.46% | -105.2 bps |
| WaveMind calibrated target | LINK/USDT | 4h | 0 | 90 | 0.544 | 358.9 bps | 3.48% | -148.6 bps |
| WaveMind price target | LINK/USDT | 4h | 0 | 90 | 0.544 | 360.1 bps | 3.51% | -85.4 bps |
| Momentum baseline | LINK/USDT | 4h | 0 | 90 | 0.378 | 410.4 bps | 4.03% | -39.3 bps |
| Regime mean baseline | LINK/USDT | 4h | 0 | 90 | 0.300 | 371.2 bps | 3.64% | -42.1 bps |
| Historical mean baseline | LINK/USDT | 4h | 0 | 90 | 0.544 | 353.8 bps | 3.45% | -101.3 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 0 | 90 | 0.433 | 570.1 bps | 5.62% | -6.7 bps |
| WaveMind robust target | LINK/USDT | 4h | 1 | 90 | 0.422 | 265.5 bps | 2.64% | -45.6 bps |
| WaveMind calibrated target | LINK/USDT | 4h | 1 | 90 | 0.444 | 267.2 bps | 2.66% | -31.6 bps |
| WaveMind price target | LINK/USDT | 4h | 1 | 90 | 0.444 | 267.2 bps | 2.66% | -31.6 bps |
| Momentum baseline | LINK/USDT | 4h | 1 | 90 | 0.244 | 317.1 bps | 3.17% | -21.6 bps |
| Regime mean baseline | LINK/USDT | 4h | 1 | 90 | 0.511 | 265.4 bps | 2.64% | -37.5 bps |
| Historical mean baseline | LINK/USDT | 4h | 1 | 90 | 0.456 | 265.1 bps | 2.63% | -62.8 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 1 | 90 | 0.289 | 469.8 bps | 4.70% | 2.7 bps |
| WaveMind robust target | LINK/USDT | 4h | 2 | 90 | 0.422 | 233.0 bps | 2.37% | 64.2 bps |
| WaveMind calibrated target | LINK/USDT | 4h | 2 | 90 | 0.489 | 241.5 bps | 2.46% | 114.6 bps |
| WaveMind price target | LINK/USDT | 4h | 2 | 90 | 0.456 | 238.5 bps | 2.42% | 60.0 bps |
| Momentum baseline | LINK/USDT | 4h | 2 | 90 | 0.411 | 272.3 bps | 2.76% | 44.5 bps |
| Regime mean baseline | LINK/USDT | 4h | 2 | 90 | 0.422 | 260.8 bps | 2.65% | 92.0 bps |
| Historical mean baseline | LINK/USDT | 4h | 2 | 90 | 0.511 | 230.8 bps | 2.34% | 45.1 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 2 | 90 | 0.356 | 390.6 bps | 3.95% | 26.4 bps |
| WaveMind robust target | LINK/USDT | 4h | 3 | 90 | 0.467 | 196.4 bps | 1.97% | 17.4 bps |
| WaveMind calibrated target | LINK/USDT | 4h | 3 | 90 | 0.411 | 202.1 bps | 2.03% | 20.4 bps |
| WaveMind price target | LINK/USDT | 4h | 3 | 90 | 0.411 | 202.1 bps | 2.03% | 20.4 bps |
| Momentum baseline | LINK/USDT | 4h | 3 | 90 | 0.456 | 199.4 bps | 2.00% | -6.4 bps |
| Regime mean baseline | LINK/USDT | 4h | 3 | 90 | 0.422 | 212.3 bps | 2.13% | 2.8 bps |
| Historical mean baseline | LINK/USDT | 4h | 3 | 90 | 0.556 | 190.4 bps | 1.91% | 13.8 bps |
| Naive last-outcome baseline | LINK/USDT | 4h | 3 | 90 | 0.400 | 247.2 bps | 2.48% | -41.6 bps |
| WaveMind robust target | LINK/USDT | 1d | 0 | 90 | 0.444 | 864.6 bps | 9.02% | 263.2 bps |
| WaveMind calibrated target | LINK/USDT | 1d | 0 | 90 | 0.422 | 968.3 bps | 10.28% | 523.9 bps |
| WaveMind price target | LINK/USDT | 1d | 0 | 90 | 0.622 | 817.7 bps | 8.54% | 264.7 bps |
| Momentum baseline | LINK/USDT | 1d | 0 | 90 | 0.578 | 872.6 bps | 9.06% | 184.1 bps |
| Regime mean baseline | LINK/USDT | 1d | 0 | 90 | 0.489 | 1008.0 bps | 10.63% | 512.1 bps |
| Historical mean baseline | LINK/USDT | 1d | 0 | 90 | 0.422 | 908.9 bps | 9.55% | 370.0 bps |
| Naive last-outcome baseline | LINK/USDT | 1d | 0 | 90 | 0.433 | 1368.8 bps | 14.08% | 262.9 bps |
| WaveMind robust target | LINK/USDT | 1d | 1 | 90 | 0.556 | 669.6 bps | 7.10% | 184.0 bps |
| WaveMind calibrated target | LINK/USDT | 1d | 1 | 90 | 0.633 | 679.3 bps | 7.19% | 168.1 bps |
| WaveMind price target | LINK/USDT | 1d | 1 | 90 | 0.633 | 679.3 bps | 7.19% | 168.1 bps |
| Momentum baseline | LINK/USDT | 1d | 1 | 90 | 0.467 | 725.7 bps | 7.62% | 130.6 bps |
| Regime mean baseline | LINK/USDT | 1d | 1 | 90 | 0.611 | 693.4 bps | 7.14% | -100.1 bps |
| Historical mean baseline | LINK/USDT | 1d | 1 | 90 | 0.389 | 724.0 bps | 7.79% | 393.3 bps |
| Naive last-outcome baseline | LINK/USDT | 1d | 1 | 90 | 0.456 | 964.2 bps | 10.04% | 106.9 bps |
| WaveMind robust target | LINK/USDT | 1d | 2 | 90 | 0.544 | 622.6 bps | 6.77% | 160.3 bps |
| WaveMind calibrated target | LINK/USDT | 1d | 2 | 90 | 0.511 | 750.4 bps | 7.99% | -25.8 bps |
| WaveMind price target | LINK/USDT | 1d | 2 | 90 | 0.411 | 707.0 bps | 7.68% | 195.3 bps |
| Momentum baseline | LINK/USDT | 1d | 2 | 90 | 0.456 | 660.1 bps | 7.10% | 123.7 bps |
| Regime mean baseline | LINK/USDT | 1d | 2 | 90 | 0.600 | 674.2 bps | 7.23% | -6.6 bps |
| Historical mean baseline | LINK/USDT | 1d | 2 | 90 | 0.400 | 627.6 bps | 6.93% | 341.5 bps |
| Naive last-outcome baseline | LINK/USDT | 1d | 2 | 90 | 0.522 | 799.5 bps | 8.43% | -15.4 bps |
| WaveMind robust target | LINK/USDT | 1d | 3 | 90 | 0.500 | 562.3 bps | 5.76% | 57.8 bps |
| WaveMind calibrated target | LINK/USDT | 1d | 3 | 90 | 0.567 | 551.7 bps | 5.57% | -89.4 bps |
| WaveMind price target | LINK/USDT | 1d | 3 | 90 | 0.467 | 587.5 bps | 6.03% | 66.5 bps |
| Momentum baseline | LINK/USDT | 1d | 3 | 90 | 0.522 | 597.4 bps | 6.11% | 63.7 bps |
| Regime mean baseline | LINK/USDT | 1d | 3 | 90 | 0.344 | 610.3 bps | 6.28% | 89.7 bps |
| Historical mean baseline | LINK/USDT | 1d | 3 | 90 | 0.433 | 568.8 bps | 5.89% | 160.6 bps |
| Naive last-outcome baseline | LINK/USDT | 1d | 3 | 90 | 0.489 | 791.3 bps | 8.03% | 25.2 bps |
| WaveMind robust target | AVAX/USDT | 1h | 0 | 90 | 0.689 | 288.8 bps | 3.05% | 258.2 bps |
| WaveMind calibrated target | AVAX/USDT | 1h | 0 | 90 | 0.911 | 291.9 bps | 3.08% | 270.3 bps |
| WaveMind price target | AVAX/USDT | 1h | 0 | 90 | 0.689 | 320.0 bps | 3.38% | 313.1 bps |
| Momentum baseline | AVAX/USDT | 1h | 0 | 90 | 0.689 | 315.0 bps | 3.33% | 296.4 bps |
| Regime mean baseline | AVAX/USDT | 1h | 0 | 90 | 0.578 | 291.9 bps | 3.08% | 273.8 bps |
| Historical mean baseline | AVAX/USDT | 1h | 0 | 90 | 0.911 | 312.3 bps | 3.30% | 296.3 bps |
| Naive last-outcome baseline | AVAX/USDT | 1h | 0 | 90 | 0.711 | 292.1 bps | 3.06% | 121.9 bps |
| WaveMind robust target | AVAX/USDT | 1h | 1 | 90 | 0.367 | 192.2 bps | 1.90% | -103.1 bps |
| WaveMind calibrated target | AVAX/USDT | 1h | 1 | 90 | 0.356 | 256.5 bps | 2.53% | -231.7 bps |
| WaveMind price target | AVAX/USDT | 1h | 1 | 90 | 0.356 | 224.2 bps | 2.21% | -192.0 bps |
| Momentum baseline | AVAX/USDT | 1h | 1 | 90 | 0.356 | 167.6 bps | 1.66% | -58.2 bps |
| Regime mean baseline | AVAX/USDT | 1h | 1 | 90 | 0.356 | 176.6 bps | 1.75% | -106.6 bps |
| Historical mean baseline | AVAX/USDT | 1h | 1 | 90 | 0.356 | 217.9 bps | 2.15% | -182.1 bps |
| Naive last-outcome baseline | AVAX/USDT | 1h | 1 | 90 | 0.356 | 265.3 bps | 2.62% | -96.2 bps |
| WaveMind robust target | AVAX/USDT | 1h | 2 | 90 | 0.389 | 280.9 bps | 2.74% | -214.7 bps |
| WaveMind calibrated target | AVAX/USDT | 1h | 2 | 90 | 0.289 | 352.5 bps | 3.43% | -343.4 bps |
| WaveMind price target | AVAX/USDT | 1h | 2 | 90 | 0.322 | 268.3 bps | 2.61% | -239.6 bps |
| Momentum baseline | AVAX/USDT | 1h | 2 | 90 | 0.356 | 224.0 bps | 2.19% | -140.4 bps |
| Regime mean baseline | AVAX/USDT | 1h | 2 | 90 | 0.267 | 424.5 bps | 4.15% | -362.9 bps |
| Historical mean baseline | AVAX/USDT | 1h | 2 | 90 | 0.289 | 264.9 bps | 2.58% | -247.7 bps |
| Naive last-outcome baseline | AVAX/USDT | 1h | 2 | 90 | 0.422 | 405.4 bps | 3.97% | -165.6 bps |
| WaveMind robust target | AVAX/USDT | 1h | 3 | 90 | 0.656 | 172.9 bps | 1.72% | -16.7 bps |
| WaveMind calibrated target | AVAX/USDT | 1h | 3 | 90 | 0.811 | 127.8 bps | 1.27% | -4.5 bps |
| WaveMind price target | AVAX/USDT | 1h | 3 | 90 | 0.389 | 186.5 bps | 1.84% | -135.8 bps |
| Momentum baseline | AVAX/USDT | 1h | 3 | 90 | 0.611 | 168.7 bps | 1.67% | -61.2 bps |
| Regime mean baseline | AVAX/USDT | 1h | 3 | 90 | 0.811 | 142.4 bps | 1.42% | 19.9 bps |
| Historical mean baseline | AVAX/USDT | 1h | 3 | 90 | 0.189 | 207.5 bps | 2.04% | -162.6 bps |
| Naive last-outcome baseline | AVAX/USDT | 1h | 3 | 90 | 0.622 | 284.9 bps | 2.84% | 66.6 bps |
| WaveMind robust target | AVAX/USDT | 4h | 0 | 90 | 0.489 | 343.4 bps | 3.34% | -95.8 bps |
| WaveMind calibrated target | AVAX/USDT | 4h | 0 | 90 | 0.489 | 347.1 bps | 3.37% | -138.4 bps |
| WaveMind price target | AVAX/USDT | 4h | 0 | 90 | 0.500 | 346.6 bps | 3.38% | -87.6 bps |
| Momentum baseline | AVAX/USDT | 4h | 0 | 90 | 0.433 | 384.5 bps | 3.77% | -34.9 bps |
| Regime mean baseline | AVAX/USDT | 4h | 0 | 90 | 0.389 | 351.2 bps | 3.44% | -42.6 bps |
| Historical mean baseline | AVAX/USDT | 4h | 0 | 90 | 0.489 | 341.0 bps | 3.33% | -83.2 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 0 | 90 | 0.478 | 526.3 bps | 5.18% | -6.6 bps |
| WaveMind robust target | AVAX/USDT | 4h | 1 | 90 | 0.400 | 323.1 bps | 3.21% | -64.2 bps |
| WaveMind calibrated target | AVAX/USDT | 4h | 1 | 90 | 0.400 | 328.2 bps | 3.26% | -62.0 bps |
| WaveMind price target | AVAX/USDT | 4h | 1 | 90 | 0.400 | 328.2 bps | 3.26% | -62.0 bps |
| Momentum baseline | AVAX/USDT | 4h | 1 | 90 | 0.278 | 388.9 bps | 3.88% | -27.2 bps |
| Regime mean baseline | AVAX/USDT | 4h | 1 | 90 | 0.500 | 320.7 bps | 3.19% | -50.9 bps |
| Historical mean baseline | AVAX/USDT | 4h | 1 | 90 | 0.422 | 318.6 bps | 3.17% | -66.9 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 1 | 90 | 0.356 | 576.7 bps | 5.76% | 3.8 bps |
| WaveMind robust target | AVAX/USDT | 4h | 2 | 90 | 0.567 | 205.2 bps | 2.07% | 25.0 bps |
| WaveMind calibrated target | AVAX/USDT | 4h | 2 | 90 | 0.533 | 207.5 bps | 2.10% | 22.3 bps |
| WaveMind price target | AVAX/USDT | 4h | 2 | 90 | 0.533 | 207.5 bps | 2.10% | 22.3 bps |
| Momentum baseline | AVAX/USDT | 4h | 2 | 90 | 0.467 | 231.1 bps | 2.33% | 28.6 bps |
| Regime mean baseline | AVAX/USDT | 4h | 2 | 90 | 0.400 | 225.1 bps | 2.28% | 55.8 bps |
| Historical mean baseline | AVAX/USDT | 4h | 2 | 90 | 0.522 | 204.5 bps | 2.07% | 28.2 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 2 | 90 | 0.433 | 343.1 bps | 3.46% | 16.4 bps |
| WaveMind robust target | AVAX/USDT | 4h | 3 | 90 | 0.433 | 306.6 bps | 3.08% | -56.2 bps |
| WaveMind calibrated target | AVAX/USDT | 4h | 3 | 90 | 0.433 | 326.2 bps | 3.26% | -126.8 bps |
| WaveMind price target | AVAX/USDT | 4h | 3 | 90 | 0.489 | 308.3 bps | 3.10% | -47.3 bps |
| Momentum baseline | AVAX/USDT | 4h | 3 | 90 | 0.400 | 332.1 bps | 3.34% | -11.0 bps |
| Regime mean baseline | AVAX/USDT | 4h | 3 | 90 | 0.456 | 303.8 bps | 3.06% | -23.7 bps |
| Historical mean baseline | AVAX/USDT | 4h | 3 | 90 | 0.433 | 300.0 bps | 3.02% | -31.7 bps |
| Naive last-outcome baseline | AVAX/USDT | 4h | 3 | 90 | 0.456 | 454.1 bps | 4.54% | -16.1 bps |
| WaveMind robust target | AVAX/USDT | 1d | 0 | 90 | 0.656 | 951.3 bps | 10.32% | 231.7 bps |
| WaveMind calibrated target | AVAX/USDT | 1d | 0 | 90 | 0.456 | 995.6 bps | 10.89% | 360.8 bps |
| WaveMind price target | AVAX/USDT | 1d | 0 | 90 | 0.600 | 980.2 bps | 10.71% | 284.6 bps |
| Momentum baseline | AVAX/USDT | 1d | 0 | 90 | 0.589 | 957.1 bps | 10.35% | 121.6 bps |
| Regime mean baseline | AVAX/USDT | 1d | 0 | 90 | 0.600 | 956.2 bps | 10.57% | 403.8 bps |
| Historical mean baseline | AVAX/USDT | 1d | 0 | 90 | 0.456 | 979.2 bps | 10.65% | 282.4 bps |
| Naive last-outcome baseline | AVAX/USDT | 1d | 0 | 90 | 0.533 | 1307.4 bps | 14.04% | 109.6 bps |
| WaveMind robust target | AVAX/USDT | 1d | 1 | 90 | 0.600 | 760.9 bps | 8.14% | 271.1 bps |
| WaveMind calibrated target | AVAX/USDT | 1d | 1 | 90 | 0.333 | 808.7 bps | 8.75% | 444.7 bps |
| WaveMind price target | AVAX/USDT | 1d | 1 | 90 | 0.656 | 762.9 bps | 8.11% | 234.2 bps |
| Momentum baseline | AVAX/USDT | 1d | 1 | 90 | 0.544 | 797.6 bps | 8.41% | 120.8 bps |
| Regime mean baseline | AVAX/USDT | 1d | 1 | 90 | 0.667 | 812.9 bps | 8.41% | -112.8 bps |
| Historical mean baseline | AVAX/USDT | 1d | 1 | 90 | 0.333 | 786.4 bps | 8.47% | 368.7 bps |
| Naive last-outcome baseline | AVAX/USDT | 1d | 1 | 90 | 0.544 | 1093.3 bps | 11.40% | 68.1 bps |
| WaveMind robust target | AVAX/USDT | 1d | 2 | 90 | 0.589 | 632.8 bps | 6.76% | 156.5 bps |
| WaveMind calibrated target | AVAX/USDT | 1d | 2 | 90 | 0.589 | 650.3 bps | 6.77% | -92.5 bps |
| WaveMind price target | AVAX/USDT | 1d | 2 | 90 | 0.411 | 711.2 bps | 7.63% | 219.5 bps |
| Momentum baseline | AVAX/USDT | 1d | 2 | 90 | 0.444 | 688.7 bps | 7.29% | 134.5 bps |
| Regime mean baseline | AVAX/USDT | 1d | 2 | 90 | 0.589 | 659.0 bps | 6.94% | 0.9 bps |
| Historical mean baseline | AVAX/USDT | 1d | 2 | 90 | 0.389 | 645.5 bps | 6.97% | 265.9 bps |
| Naive last-outcome baseline | AVAX/USDT | 1d | 2 | 90 | 0.478 | 813.8 bps | 8.44% | -31.3 bps |
| WaveMind robust target | AVAX/USDT | 1d | 3 | 90 | 0.556 | 580.3 bps | 6.29% | 128.4 bps |
| WaveMind calibrated target | AVAX/USDT | 1d | 3 | 90 | 0.578 | 579.1 bps | 6.19% | -28.7 bps |
| WaveMind price target | AVAX/USDT | 1d | 3 | 90 | 0.467 | 617.8 bps | 6.67% | 112.3 bps |
| Momentum baseline | AVAX/USDT | 1d | 3 | 90 | 0.422 | 658.0 bps | 7.03% | 77.6 bps |
| Regime mean baseline | AVAX/USDT | 1d | 3 | 90 | 0.533 | 612.0 bps | 6.62% | 121.2 bps |
| Historical mean baseline | AVAX/USDT | 1d | 3 | 90 | 0.578 | 572.1 bps | 6.24% | 179.8 bps |
| Naive last-outcome baseline | AVAX/USDT | 1d | 3 | 90 | 0.389 | 896.4 bps | 9.34% | -72.9 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
