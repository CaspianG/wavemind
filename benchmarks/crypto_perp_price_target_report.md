# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind perp field target | 2880 | 0.591 | 392.4 bps | 612.6 bps | 4.05% | 0.096 | 0.411 | 22.39% |
| WaveMind market-field target | 2880 | 0.436 | 466.6 bps | 660.5 bps | 4.78% | 0.086 | 0.000 | 20.31% |
| WaveMind robust target | 2880 | 0.591 | 392.4 bps | 612.6 bps | 4.05% | 0.096 | 0.411 | 22.39% |
| Momentum baseline | 2880 | 0.564 | 409.2 bps | 621.4 bps | 4.21% | 0.096 | 0.267 | 21.70% |
| Regime mean baseline | 2880 | 0.540 | 415.8 bps | 647.9 bps | 4.31% | 0.099 | 0.267 | 25.29% |
| Historical mean baseline | 2880 | 0.511 | 406.9 bps | 628.4 bps | 4.21% | 0.101 | 0.078 | 22.43% |
| Naive last-outcome baseline | 2880 | 0.570 | 522.0 bps | 802.5 bps | 5.31% | 0.081 | 0.300 | 27.15% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind perp field target | HYPE/USDT:USDT | 1h | 0 | 90 | 0.556 | 661.5 bps | 7.22% | 482.0 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 1h | 0 | 90 | 0.378 | 802.0 bps | 8.62% | 497.4 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1h | 0 | 90 | 0.556 | 661.5 bps | 7.22% | 482.0 bps |
| Momentum baseline | HYPE/USDT:USDT | 1h | 0 | 90 | 0.544 | 602.2 bps | 6.56% | 400.7 bps |
| Regime mean baseline | HYPE/USDT:USDT | 1h | 0 | 90 | 0.622 | 608.6 bps | 6.67% | 491.8 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1h | 0 | 90 | 0.233 | 832.2 bps | 9.11% | 781.4 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1h | 0 | 90 | 0.556 | 730.9 bps | 7.82% | 50.4 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 1h | 1 | 90 | 0.578 | 493.4 bps | 4.59% | -350.3 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 1h | 1 | 90 | 0.133 | 716.9 bps | 6.66% | -588.3 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1h | 1 | 90 | 0.578 | 493.4 bps | 4.59% | -350.3 bps |
| Momentum baseline | HYPE/USDT:USDT | 1h | 1 | 90 | 0.567 | 510.1 bps | 4.73% | -407.9 bps |
| Regime mean baseline | HYPE/USDT:USDT | 1h | 1 | 90 | 0.867 | 422.9 bps | 3.92% | -364.6 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1h | 1 | 90 | 0.811 | 463.4 bps | 4.29% | -353.6 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1h | 1 | 90 | 0.644 | 489.0 bps | 4.67% | -91.7 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 1h | 2 | 90 | 0.578 | 342.5 bps | 3.53% | 45.0 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 1h | 2 | 90 | 0.444 | 391.1 bps | 4.09% | 366.0 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1h | 2 | 90 | 0.578 | 342.5 bps | 3.53% | 45.0 bps |
| Momentum baseline | HYPE/USDT:USDT | 1h | 2 | 90 | 0.556 | 326.7 bps | 3.39% | 129.1 bps |
| Regime mean baseline | HYPE/USDT:USDT | 1h | 2 | 90 | 0.556 | 403.5 bps | 4.13% | -10.7 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1h | 2 | 90 | 0.367 | 382.6 bps | 4.01% | 298.3 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1h | 2 | 90 | 0.589 | 492.5 bps | 5.03% | -118.5 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 1h | 3 | 90 | 0.456 | 394.8 bps | 3.82% | -168.4 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 1h | 3 | 90 | 0.556 | 390.7 bps | 3.74% | -366.9 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1h | 3 | 90 | 0.456 | 394.8 bps | 3.82% | -168.4 bps |
| Momentum baseline | HYPE/USDT:USDT | 1h | 3 | 90 | 0.456 | 387.0 bps | 3.73% | -199.4 bps |
| Regime mean baseline | HYPE/USDT:USDT | 1h | 3 | 90 | 0.444 | 453.3 bps | 4.42% | -101.9 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1h | 3 | 90 | 0.633 | 365.3 bps | 3.54% | -136.0 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1h | 3 | 90 | 0.444 | 496.6 bps | 4.88% | -7.5 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 4h | 0 | 90 | 0.511 | 399.4 bps | 3.96% | 9.6 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 4h | 0 | 90 | 0.522 | 397.6 bps | 3.93% | -44.2 bps |
| WaveMind robust target | HYPE/USDT:USDT | 4h | 0 | 90 | 0.511 | 399.4 bps | 3.96% | 9.6 bps |
| Momentum baseline | HYPE/USDT:USDT | 4h | 0 | 90 | 0.478 | 440.2 bps | 4.36% | 10.5 bps |
| Regime mean baseline | HYPE/USDT:USDT | 4h | 0 | 90 | 0.356 | 432.3 bps | 4.28% | -12.5 bps |
| Historical mean baseline | HYPE/USDT:USDT | 4h | 0 | 90 | 0.456 | 405.3 bps | 4.03% | 27.4 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 4h | 0 | 90 | 0.456 | 604.8 bps | 5.96% | 31.8 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 4h | 1 | 90 | 0.600 | 313.1 bps | 3.07% | -91.2 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 4h | 1 | 90 | 0.589 | 310.5 bps | 3.02% | -193.3 bps |
| WaveMind robust target | HYPE/USDT:USDT | 4h | 1 | 90 | 0.600 | 313.1 bps | 3.07% | -91.2 bps |
| Momentum baseline | HYPE/USDT:USDT | 4h | 1 | 90 | 0.411 | 352.4 bps | 3.47% | -76.5 bps |
| Regime mean baseline | HYPE/USDT:USDT | 4h | 1 | 90 | 0.489 | 318.8 bps | 3.12% | -106.1 bps |
| Historical mean baseline | HYPE/USDT:USDT | 4h | 1 | 90 | 0.633 | 299.1 bps | 2.94% | -78.2 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 4h | 1 | 90 | 0.356 | 515.9 bps | 5.10% | 5.2 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 4h | 2 | 90 | 0.478 | 619.6 bps | 5.85% | -216.4 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 4h | 2 | 90 | 0.433 | 682.3 bps | 6.40% | -411.9 bps |
| WaveMind robust target | HYPE/USDT:USDT | 4h | 2 | 90 | 0.478 | 619.6 bps | 5.85% | -216.4 bps |
| Momentum baseline | HYPE/USDT:USDT | 4h | 2 | 90 | 0.567 | 649.2 bps | 6.17% | -136.8 bps |
| Regime mean baseline | HYPE/USDT:USDT | 4h | 2 | 90 | 0.433 | 646.1 bps | 6.16% | -131.1 bps |
| Historical mean baseline | HYPE/USDT:USDT | 4h | 2 | 90 | 0.533 | 613.6 bps | 5.79% | -216.8 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 4h | 2 | 90 | 0.533 | 908.0 bps | 8.77% | 7.7 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 4h | 3 | 90 | 0.511 | 326.9 bps | 3.28% | 47.8 bps |
| WaveMind market-field target | HYPE/USDT:USDT | 4h | 3 | 90 | 0.511 | 328.4 bps | 3.28% | -5.4 bps |
| WaveMind robust target | HYPE/USDT:USDT | 4h | 3 | 90 | 0.511 | 326.9 bps | 3.28% | 47.8 bps |
| Momentum baseline | HYPE/USDT:USDT | 4h | 3 | 90 | 0.489 | 335.9 bps | 3.35% | -16.2 bps |
| Regime mean baseline | HYPE/USDT:USDT | 4h | 3 | 90 | 0.467 | 359.1 bps | 3.59% | 11.5 bps |
| Historical mean baseline | HYPE/USDT:USDT | 4h | 3 | 90 | 0.478 | 324.1 bps | 3.25% | 56.0 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 4h | 3 | 90 | 0.478 | 465.5 bps | 4.66% | 20.6 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1h | 0 | 90 | 0.911 | 231.6 bps | 2.42% | 149.8 bps |
| WaveMind market-field target | XRP/USDT:USDT | 1h | 0 | 90 | 0.044 | 614.3 bps | 6.41% | 614.3 bps |
| WaveMind robust target | XRP/USDT:USDT | 1h | 0 | 90 | 0.911 | 231.6 bps | 2.42% | 149.8 bps |
| Momentum baseline | XRP/USDT:USDT | 1h | 0 | 90 | 0.911 | 288.1 bps | 3.02% | 259.8 bps |
| Regime mean baseline | XRP/USDT:USDT | 1h | 0 | 90 | 0.956 | 153.1 bps | 1.59% | 45.3 bps |
| Historical mean baseline | XRP/USDT:USDT | 1h | 0 | 90 | 0.956 | 264.9 bps | 2.78% | 248.3 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1h | 0 | 90 | 0.922 | 300.9 bps | 3.10% | -42.3 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1h | 1 | 90 | 0.489 | 307.2 bps | 2.91% | -204.3 bps |
| WaveMind market-field target | XRP/USDT:USDT | 1h | 1 | 90 | 0.356 | 339.6 bps | 3.21% | -262.2 bps |
| WaveMind robust target | XRP/USDT:USDT | 1h | 1 | 90 | 0.489 | 307.2 bps | 2.91% | -204.3 bps |
| Momentum baseline | XRP/USDT:USDT | 1h | 1 | 90 | 0.478 | 300.5 bps | 2.84% | -218.9 bps |
| Regime mean baseline | XRP/USDT:USDT | 1h | 1 | 90 | 0.644 | 276.5 bps | 2.61% | -227.1 bps |
| Historical mean baseline | XRP/USDT:USDT | 1h | 1 | 90 | 0.244 | 336.7 bps | 3.18% | -316.8 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1h | 1 | 90 | 0.489 | 352.5 bps | 3.37% | -94.5 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1h | 2 | 90 | 0.811 | 171.7 bps | 1.77% | 145.7 bps |
| WaveMind market-field target | XRP/USDT:USDT | 1h | 2 | 90 | 0.322 | 292.1 bps | 3.01% | 290.5 bps |
| WaveMind robust target | XRP/USDT:USDT | 1h | 2 | 90 | 0.811 | 171.7 bps | 1.77% | 145.7 bps |
| Momentum baseline | XRP/USDT:USDT | 1h | 2 | 90 | 0.789 | 208.3 bps | 2.15% | 196.3 bps |
| Regime mean baseline | XRP/USDT:USDT | 1h | 2 | 90 | 0.678 | 175.3 bps | 1.81% | 152.1 bps |
| Historical mean baseline | XRP/USDT:USDT | 1h | 2 | 90 | 0.956 | 180.6 bps | 1.86% | 165.5 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1h | 2 | 90 | 0.878 | 147.2 bps | 1.51% | 57.7 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1h | 3 | 90 | 0.733 | 256.3 bps | 2.51% | -133.3 bps |
| WaveMind market-field target | XRP/USDT:USDT | 1h | 3 | 90 | 0.444 | 332.0 bps | 3.22% | -329.0 bps |
| WaveMind robust target | XRP/USDT:USDT | 1h | 3 | 90 | 0.733 | 256.3 bps | 2.51% | -133.3 bps |
| Momentum baseline | XRP/USDT:USDT | 1h | 3 | 90 | 0.733 | 266.2 bps | 2.60% | -168.2 bps |
| Regime mean baseline | XRP/USDT:USDT | 1h | 3 | 90 | 0.556 | 305.1 bps | 3.00% | -99.9 bps |
| Historical mean baseline | XRP/USDT:USDT | 1h | 3 | 90 | 0.178 | 319.5 bps | 3.10% | -265.6 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1h | 3 | 90 | 0.778 | 261.0 bps | 2.59% | 55.0 bps |
| WaveMind perp field target | XRP/USDT:USDT | 4h | 0 | 90 | 0.622 | 281.3 bps | 2.80% | -6.4 bps |
| WaveMind market-field target | XRP/USDT:USDT | 4h | 0 | 90 | 0.544 | 266.3 bps | 2.66% | 40.9 bps |
| WaveMind robust target | XRP/USDT:USDT | 4h | 0 | 90 | 0.622 | 281.3 bps | 2.80% | -6.4 bps |
| Momentum baseline | XRP/USDT:USDT | 4h | 0 | 90 | 0.456 | 322.6 bps | 3.22% | 19.3 bps |
| Regime mean baseline | XRP/USDT:USDT | 4h | 0 | 90 | 0.311 | 296.3 bps | 2.95% | 13.1 bps |
| Historical mean baseline | XRP/USDT:USDT | 4h | 0 | 90 | 0.633 | 280.7 bps | 2.79% | -7.8 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 4h | 0 | 90 | 0.500 | 428.6 bps | 4.28% | 14.6 bps |
| WaveMind perp field target | XRP/USDT:USDT | 4h | 1 | 90 | 0.456 | 192.4 bps | 1.90% | -58.3 bps |
| WaveMind market-field target | XRP/USDT:USDT | 4h | 1 | 90 | 0.733 | 166.9 bps | 1.65% | -54.1 bps |
| WaveMind robust target | XRP/USDT:USDT | 4h | 1 | 90 | 0.456 | 192.4 bps | 1.90% | -58.3 bps |
| Momentum baseline | XRP/USDT:USDT | 4h | 1 | 90 | 0.267 | 225.3 bps | 2.24% | -33.7 bps |
| Regime mean baseline | XRP/USDT:USDT | 4h | 1 | 90 | 0.567 | 188.8 bps | 1.87% | -56.9 bps |
| Historical mean baseline | XRP/USDT:USDT | 4h | 1 | 90 | 0.500 | 192.5 bps | 1.90% | -69.9 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 4h | 1 | 90 | 0.300 | 337.1 bps | 3.36% | -16.3 bps |
| WaveMind perp field target | XRP/USDT:USDT | 4h | 2 | 90 | 0.556 | 158.9 bps | 1.60% | 50.5 bps |
| WaveMind market-field target | XRP/USDT:USDT | 4h | 2 | 90 | 0.578 | 158.5 bps | 1.60% | 69.9 bps |
| WaveMind robust target | XRP/USDT:USDT | 4h | 2 | 90 | 0.556 | 158.9 bps | 1.60% | 50.5 bps |
| Momentum baseline | XRP/USDT:USDT | 4h | 2 | 90 | 0.422 | 181.5 bps | 1.83% | 39.1 bps |
| Regime mean baseline | XRP/USDT:USDT | 4h | 2 | 90 | 0.444 | 171.2 bps | 1.72% | 51.9 bps |
| Historical mean baseline | XRP/USDT:USDT | 4h | 2 | 90 | 0.656 | 156.6 bps | 1.57% | 39.5 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 4h | 2 | 90 | 0.467 | 272.5 bps | 2.74% | 23.0 bps |
| WaveMind perp field target | XRP/USDT:USDT | 4h | 3 | 90 | 0.489 | 184.6 bps | 1.84% | -45.0 bps |
| WaveMind market-field target | XRP/USDT:USDT | 4h | 3 | 90 | 0.356 | 206.4 bps | 2.06% | 11.0 bps |
| WaveMind robust target | XRP/USDT:USDT | 4h | 3 | 90 | 0.489 | 184.6 bps | 1.84% | -45.0 bps |
| Momentum baseline | XRP/USDT:USDT | 4h | 3 | 90 | 0.644 | 174.7 bps | 1.74% | -35.5 bps |
| Regime mean baseline | XRP/USDT:USDT | 4h | 3 | 90 | 0.400 | 209.9 bps | 2.09% | -66.0 bps |
| Historical mean baseline | XRP/USDT:USDT | 4h | 3 | 90 | 0.489 | 183.3 bps | 1.82% | -37.0 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 4h | 3 | 90 | 0.556 | 201.2 bps | 2.01% | -17.7 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1h | 0 | 90 | 0.567 | 1708.3 bps | 22.39% | 807.4 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 1h | 0 | 90 | 0.689 | 1496.4 bps | 20.31% | 978.0 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1h | 0 | 90 | 0.567 | 1708.3 bps | 22.39% | 807.4 bps |
| Momentum baseline | ZEC/USDT:USDT | 1h | 0 | 90 | 0.567 | 1642.7 bps | 21.70% | 792.1 bps |
| Regime mean baseline | ZEC/USDT:USDT | 1h | 0 | 90 | 0.311 | 1905.4 bps | 25.29% | 1016.8 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1h | 0 | 90 | 0.267 | 1651.0 bps | 22.43% | 1032.3 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1h | 0 | 90 | 0.567 | 2315.3 bps | 27.15% | 105.7 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1h | 1 | 90 | 0.556 | 759.3 bps | 6.82% | -428.9 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 1h | 1 | 90 | 0.611 | 808.4 bps | 7.20% | -512.4 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1h | 1 | 90 | 0.556 | 759.3 bps | 6.82% | -428.9 bps |
| Momentum baseline | ZEC/USDT:USDT | 1h | 1 | 90 | 0.567 | 782.7 bps | 6.98% | -513.1 bps |
| Regime mean baseline | ZEC/USDT:USDT | 1h | 1 | 90 | 0.389 | 806.9 bps | 7.14% | -639.2 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1h | 1 | 90 | 0.256 | 812.6 bps | 7.20% | -607.6 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1h | 1 | 90 | 0.500 | 992.8 bps | 9.22% | -231.1 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1h | 2 | 90 | 0.667 | 300.7 bps | 3.14% | 86.9 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 1h | 2 | 90 | 0.178 | 445.9 bps | 4.65% | 420.4 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1h | 2 | 90 | 0.667 | 300.7 bps | 3.14% | 86.9 bps |
| Momentum baseline | ZEC/USDT:USDT | 1h | 2 | 90 | 0.644 | 270.8 bps | 2.85% | 186.2 bps |
| Regime mean baseline | ZEC/USDT:USDT | 1h | 2 | 90 | 0.822 | 309.5 bps | 3.23% | 63.8 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1h | 2 | 90 | 0.822 | 277.6 bps | 2.93% | 234.0 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1h | 2 | 90 | 0.656 | 467.9 bps | 4.83% | -85.8 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1h | 3 | 90 | 0.689 | 328.8 bps | 3.13% | -184.5 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 1h | 3 | 90 | 0.256 | 651.1 bps | 6.24% | -651.1 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1h | 3 | 90 | 0.689 | 328.8 bps | 3.13% | -184.5 bps |
| Momentum baseline | ZEC/USDT:USDT | 1h | 3 | 90 | 0.678 | 336.7 bps | 3.19% | -241.3 bps |
| Regime mean baseline | ZEC/USDT:USDT | 1h | 3 | 90 | 0.744 | 394.1 bps | 3.82% | 13.5 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1h | 3 | 90 | 0.078 | 378.3 bps | 3.58% | -327.7 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1h | 3 | 90 | 0.722 | 375.9 bps | 3.64% | 103.9 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 4h | 0 | 90 | 0.611 | 454.8 bps | 4.64% | 100.3 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 4h | 0 | 90 | 0.478 | 465.3 bps | 4.80% | 242.1 bps |
| WaveMind robust target | ZEC/USDT:USDT | 4h | 0 | 90 | 0.611 | 454.8 bps | 4.64% | 100.3 bps |
| Momentum baseline | ZEC/USDT:USDT | 4h | 0 | 90 | 0.522 | 487.6 bps | 4.96% | 88.3 bps |
| Regime mean baseline | ZEC/USDT:USDT | 4h | 0 | 90 | 0.533 | 472.3 bps | 4.79% | 83.3 bps |
| Historical mean baseline | ZEC/USDT:USDT | 4h | 0 | 90 | 0.644 | 445.3 bps | 4.54% | 95.4 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 4h | 0 | 90 | 0.478 | 601.4 bps | 6.08% | 34.3 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 4h | 1 | 90 | 0.411 | 539.0 bps | 4.93% | -226.2 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 4h | 1 | 90 | 0.567 | 587.0 bps | 5.35% | -405.4 bps |
| WaveMind robust target | ZEC/USDT:USDT | 4h | 1 | 90 | 0.411 | 539.0 bps | 4.93% | -226.2 bps |
| Momentum baseline | ZEC/USDT:USDT | 4h | 1 | 90 | 0.433 | 602.7 bps | 5.61% | -82.0 bps |
| Regime mean baseline | ZEC/USDT:USDT | 4h | 1 | 90 | 0.456 | 635.3 bps | 5.99% | 27.3 bps |
| Historical mean baseline | ZEC/USDT:USDT | 4h | 1 | 90 | 0.289 | 517.5 bps | 4.70% | -257.8 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 4h | 1 | 90 | 0.511 | 771.3 bps | 7.31% | 21.8 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 4h | 2 | 90 | 0.478 | 549.9 bps | 5.48% | -18.5 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 4h | 2 | 90 | 0.511 | 558.3 bps | 5.50% | -117.6 bps |
| WaveMind robust target | ZEC/USDT:USDT | 4h | 2 | 90 | 0.478 | 549.9 bps | 5.48% | -18.5 bps |
| Momentum baseline | ZEC/USDT:USDT | 4h | 2 | 90 | 0.489 | 583.4 bps | 5.79% | -42.3 bps |
| Regime mean baseline | ZEC/USDT:USDT | 4h | 2 | 90 | 0.289 | 643.3 bps | 6.45% | 117.0 bps |
| Historical mean baseline | ZEC/USDT:USDT | 4h | 2 | 90 | 0.522 | 536.0 bps | 5.32% | -38.3 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 4h | 2 | 90 | 0.556 | 786.6 bps | 7.82% | 6.4 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 4h | 3 | 90 | 0.533 | 346.1 bps | 3.47% | 36.3 bps |
| WaveMind market-field target | ZEC/USDT:USDT | 4h | 3 | 90 | 0.389 | 391.3 bps | 3.91% | 13.6 bps |
| WaveMind robust target | ZEC/USDT:USDT | 4h | 3 | 90 | 0.533 | 346.1 bps | 3.47% | 36.3 bps |
| Momentum baseline | ZEC/USDT:USDT | 4h | 3 | 90 | 0.611 | 345.8 bps | 3.44% | -35.0 bps |
| Regime mean baseline | ZEC/USDT:USDT | 4h | 3 | 90 | 0.333 | 367.6 bps | 3.65% | -58.3 bps |
| Historical mean baseline | ZEC/USDT:USDT | 4h | 3 | 90 | 0.478 | 338.3 bps | 3.38% | 16.5 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 4h | 3 | 90 | 0.533 | 493.0 bps | 4.93% | 11.1 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1h | 0 | 90 | 0.989 | 343.0 bps | 3.66% | 324.9 bps |
| WaveMind market-field target | SOL/USDT:USDT | 1h | 0 | 90 | 0.000 | 899.7 bps | 9.55% | 899.7 bps |
| WaveMind robust target | SOL/USDT:USDT | 1h | 0 | 90 | 0.989 | 343.0 bps | 3.66% | 324.9 bps |
| Momentum baseline | SOL/USDT:USDT | 1h | 0 | 90 | 0.989 | 434.0 bps | 4.63% | 431.1 bps |
| Regime mean baseline | SOL/USDT:USDT | 1h | 0 | 90 | 1.000 | 234.3 bps | 2.49% | 165.6 bps |
| Historical mean baseline | SOL/USDT:USDT | 1h | 0 | 90 | 1.000 | 447.4 bps | 4.76% | 445.9 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1h | 0 | 90 | 1.000 | 261.7 bps | 2.76% | 3.8 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1h | 1 | 90 | 0.667 | 293.5 bps | 2.78% | -204.7 bps |
| WaveMind market-field target | SOL/USDT:USDT | 1h | 1 | 90 | 0.211 | 419.2 bps | 3.98% | -404.8 bps |
| WaveMind robust target | SOL/USDT:USDT | 1h | 1 | 90 | 0.667 | 293.5 bps | 2.78% | -204.7 bps |
| Momentum baseline | SOL/USDT:USDT | 1h | 1 | 90 | 0.633 | 302.8 bps | 2.87% | -253.8 bps |
| Regime mean baseline | SOL/USDT:USDT | 1h | 1 | 90 | 0.789 | 246.1 bps | 2.34% | -174.5 bps |
| Historical mean baseline | SOL/USDT:USDT | 1h | 1 | 90 | 0.178 | 379.0 bps | 3.60% | -373.5 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1h | 1 | 90 | 0.644 | 323.5 bps | 3.09% | -73.7 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1h | 2 | 90 | 0.622 | 259.8 bps | 2.70% | 191.1 bps |
| WaveMind market-field target | SOL/USDT:USDT | 1h | 2 | 90 | 0.567 | 253.9 bps | 2.62% | 202.7 bps |
| WaveMind robust target | SOL/USDT:USDT | 1h | 2 | 90 | 0.622 | 259.8 bps | 2.70% | 191.1 bps |
| Momentum baseline | SOL/USDT:USDT | 1h | 2 | 90 | 0.611 | 258.3 bps | 2.69% | 209.1 bps |
| Regime mean baseline | SOL/USDT:USDT | 1h | 2 | 90 | 0.433 | 353.1 bps | 3.67% | 269.8 bps |
| Historical mean baseline | SOL/USDT:USDT | 1h | 2 | 90 | 0.856 | 231.1 bps | 2.41% | 193.8 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1h | 2 | 90 | 0.611 | 334.4 bps | 3.44% | 67.3 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1h | 3 | 90 | 0.767 | 194.8 bps | 1.90% | -15.9 bps |
| WaveMind market-field target | SOL/USDT:USDT | 1h | 3 | 90 | 0.322 | 428.5 bps | 4.17% | -428.5 bps |
| WaveMind robust target | SOL/USDT:USDT | 1h | 3 | 90 | 0.767 | 194.8 bps | 1.90% | -15.9 bps |
| Momentum baseline | SOL/USDT:USDT | 1h | 3 | 90 | 0.767 | 224.2 bps | 2.18% | -100.2 bps |
| Regime mean baseline | SOL/USDT:USDT | 1h | 3 | 90 | 0.678 | 306.9 bps | 3.04% | 125.6 bps |
| Historical mean baseline | SOL/USDT:USDT | 1h | 3 | 90 | 0.322 | 253.7 bps | 2.46% | -161.5 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1h | 3 | 90 | 0.689 | 250.3 bps | 2.47% | 148.7 bps |
| WaveMind perp field target | SOL/USDT:USDT | 4h | 0 | 90 | 0.533 | 407.4 bps | 4.02% | -33.1 bps |
| WaveMind market-field target | SOL/USDT:USDT | 4h | 0 | 90 | 0.522 | 401.6 bps | 3.98% | -16.3 bps |
| WaveMind robust target | SOL/USDT:USDT | 4h | 0 | 90 | 0.533 | 407.4 bps | 4.02% | -33.1 bps |
| Momentum baseline | SOL/USDT:USDT | 4h | 0 | 90 | 0.478 | 443.5 bps | 4.40% | 18.9 bps |
| Regime mean baseline | SOL/USDT:USDT | 4h | 0 | 90 | 0.267 | 436.4 bps | 4.34% | 25.8 bps |
| Historical mean baseline | SOL/USDT:USDT | 4h | 0 | 90 | 0.556 | 408.1 bps | 4.02% | -50.2 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 4h | 0 | 90 | 0.511 | 598.1 bps | 5.93% | 31.0 bps |
| WaveMind perp field target | SOL/USDT:USDT | 4h | 1 | 90 | 0.467 | 254.9 bps | 2.53% | -64.6 bps |
| WaveMind market-field target | SOL/USDT:USDT | 4h | 1 | 90 | 0.678 | 215.1 bps | 2.13% | -50.6 bps |
| WaveMind robust target | SOL/USDT:USDT | 4h | 1 | 90 | 0.467 | 254.9 bps | 2.53% | -64.6 bps |
| Momentum baseline | SOL/USDT:USDT | 4h | 1 | 90 | 0.322 | 298.8 bps | 2.98% | -34.5 bps |
| Regime mean baseline | SOL/USDT:USDT | 4h | 1 | 90 | 0.544 | 258.5 bps | 2.57% | -65.9 bps |
| Historical mean baseline | SOL/USDT:USDT | 4h | 1 | 90 | 0.378 | 258.2 bps | 2.56% | -75.0 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 4h | 1 | 90 | 0.311 | 442.7 bps | 4.42% | -21.9 bps |
| WaveMind perp field target | SOL/USDT:USDT | 4h | 2 | 90 | 0.556 | 197.9 bps | 2.01% | 76.0 bps |
| WaveMind market-field target | SOL/USDT:USDT | 4h | 2 | 90 | 0.567 | 205.0 bps | 2.09% | 103.3 bps |
| WaveMind robust target | SOL/USDT:USDT | 4h | 2 | 90 | 0.556 | 197.9 bps | 2.01% | 76.0 bps |
| Momentum baseline | SOL/USDT:USDT | 4h | 2 | 90 | 0.433 | 224.1 bps | 2.27% | 53.5 bps |
| Regime mean baseline | SOL/USDT:USDT | 4h | 2 | 90 | 0.389 | 228.2 bps | 2.32% | 78.8 bps |
| Historical mean baseline | SOL/USDT:USDT | 4h | 2 | 90 | 0.567 | 198.0 bps | 2.01% | 60.7 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 4h | 2 | 90 | 0.433 | 307.5 bps | 3.10% | 22.2 bps |
| WaveMind perp field target | SOL/USDT:USDT | 4h | 3 | 90 | 0.456 | 285.2 bps | 2.78% | -135.9 bps |
| WaveMind market-field target | SOL/USDT:USDT | 4h | 3 | 90 | 0.467 | 308.2 bps | 3.01% | -157.7 bps |
| WaveMind robust target | SOL/USDT:USDT | 4h | 3 | 90 | 0.456 | 285.2 bps | 2.78% | -135.9 bps |
| Momentum baseline | SOL/USDT:USDT | 4h | 3 | 90 | 0.533 | 284.3 bps | 2.79% | -64.4 bps |
| Regime mean baseline | SOL/USDT:USDT | 4h | 3 | 90 | 0.522 | 288.4 bps | 2.83% | -63.4 bps |
| Historical mean baseline | SOL/USDT:USDT | 4h | 3 | 90 | 0.378 | 288.8 bps | 2.82% | -134.4 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 4h | 3 | 90 | 0.578 | 376.6 bps | 3.72% | 8.7 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
