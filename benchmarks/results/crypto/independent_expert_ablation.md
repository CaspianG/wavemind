# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind independent-expert target | 2880 | 0.498 | 244.7 bps | 319.4 bps | 2.45% | 0.134 | 0.378 | 4.87% |
| WaveMind online-expert target | 2880 | 0.491 | 244.0 bps | 317.4 bps | 2.45% | 0.135 | 0.322 | 4.92% |
| WaveMind guarded state-field target | 2880 | 0.514 | 245.9 bps | 320.8 bps | 2.46% | 0.138 | 0.378 | 4.92% |
| WaveMind market-field target | 2880 | 0.520 | 253.1 bps | 338.9 bps | 2.55% | 0.147 | 0.411 | 5.47% |
| WaveMind robust target | 2880 | 0.494 | 245.0 bps | 320.2 bps | 2.45% | 0.134 | 0.367 | 4.87% |
| Momentum baseline | 2880 | 0.480 | 260.9 bps | 336.1 bps | 2.62% | 0.141 | 0.344 | 5.11% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind independent-expert target | BTC/USDT | 4h | 0 | 90 | 0.500 | 188.6 bps | 1.89% | -6.0 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 0 | 90 | 0.367 | 192.2 bps | 1.93% | 1.6 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 0 | 90 | 0.511 | 188.1 bps | 1.89% | -1.6 bps |
| WaveMind market-field target | BTC/USDT | 4h | 0 | 90 | 0.478 | 189.2 bps | 1.90% | -3.9 bps |
| WaveMind robust target | BTC/USDT | 4h | 0 | 90 | 0.511 | 188.3 bps | 1.89% | -6.2 bps |
| Momentum baseline | BTC/USDT | 4h | 0 | 90 | 0.522 | 191.2 bps | 1.93% | 32.0 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 1 | 90 | 0.456 | 186.3 bps | 1.83% | -96.2 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 1 | 90 | 0.433 | 189.4 bps | 1.86% | -85.8 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 1 | 90 | 0.533 | 182.4 bps | 1.79% | -97.7 bps |
| WaveMind market-field target | BTC/USDT | 4h | 1 | 90 | 0.511 | 183.1 bps | 1.79% | -123.0 bps |
| WaveMind robust target | BTC/USDT | 4h | 1 | 90 | 0.467 | 184.9 bps | 1.81% | -95.6 bps |
| Momentum baseline | BTC/USDT | 4h | 1 | 90 | 0.489 | 200.7 bps | 1.98% | -39.0 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 2 | 90 | 0.422 | 120.3 bps | 1.21% | 31.2 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 2 | 90 | 0.500 | 124.2 bps | 1.25% | 38.5 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 2 | 90 | 0.522 | 119.5 bps | 1.20% | 11.1 bps |
| WaveMind market-field target | BTC/USDT | 4h | 2 | 90 | 0.489 | 125.4 bps | 1.26% | 20.5 bps |
| WaveMind robust target | BTC/USDT | 4h | 2 | 90 | 0.422 | 120.3 bps | 1.21% | 31.2 bps |
| Momentum baseline | BTC/USDT | 4h | 2 | 90 | 0.511 | 121.7 bps | 1.22% | 23.9 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 3 | 90 | 0.489 | 196.2 bps | 1.97% | -22.4 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 3 | 90 | 0.522 | 194.5 bps | 1.96% | -6.2 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 3 | 90 | 0.611 | 190.7 bps | 1.92% | -12.2 bps |
| WaveMind market-field target | BTC/USDT | 4h | 3 | 90 | 0.411 | 226.0 bps | 2.29% | 54.9 bps |
| WaveMind robust target | BTC/USDT | 4h | 3 | 90 | 0.500 | 196.1 bps | 1.97% | -18.8 bps |
| Momentum baseline | BTC/USDT | 4h | 3 | 90 | 0.589 | 195.7 bps | 1.97% | -6.7 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 0 | 90 | 0.533 | 262.8 bps | 2.60% | -59.1 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 0 | 90 | 0.389 | 279.7 bps | 2.78% | -35.0 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 0 | 90 | 0.500 | 263.5 bps | 2.61% | -39.5 bps |
| WaveMind market-field target | ETH/USDT | 4h | 0 | 90 | 0.511 | 282.0 bps | 2.80% | -51.6 bps |
| WaveMind robust target | ETH/USDT | 4h | 0 | 90 | 0.511 | 263.7 bps | 2.61% | -58.7 bps |
| Momentum baseline | ETH/USDT | 4h | 0 | 90 | 0.489 | 274.1 bps | 2.74% | 19.7 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 1 | 90 | 0.533 | 248.0 bps | 2.41% | -108.6 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 1 | 90 | 0.556 | 240.7 bps | 2.34% | -112.7 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 1 | 90 | 0.500 | 253.7 bps | 2.47% | -119.7 bps |
| WaveMind market-field target | ETH/USDT | 4h | 1 | 90 | 0.622 | 224.2 bps | 2.17% | -138.6 bps |
| WaveMind robust target | ETH/USDT | 4h | 1 | 90 | 0.533 | 251.7 bps | 2.45% | -106.6 bps |
| Momentum baseline | ETH/USDT | 4h | 1 | 90 | 0.378 | 300.4 bps | 2.95% | -38.2 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 2 | 90 | 0.444 | 145.9 bps | 1.48% | 61.8 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 2 | 90 | 0.389 | 148.2 bps | 1.50% | 66.3 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 2 | 90 | 0.556 | 141.1 bps | 1.43% | 31.5 bps |
| WaveMind market-field target | ETH/USDT | 4h | 2 | 90 | 0.556 | 151.5 bps | 1.54% | 87.6 bps |
| WaveMind robust target | ETH/USDT | 4h | 2 | 90 | 0.467 | 143.7 bps | 1.46% | 62.2 bps |
| Momentum baseline | ETH/USDT | 4h | 2 | 90 | 0.444 | 151.7 bps | 1.54% | 46.2 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 3 | 90 | 0.567 | 288.1 bps | 2.91% | -16.6 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 3 | 90 | 0.556 | 291.5 bps | 2.94% | -7.9 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 3 | 90 | 0.556 | 293.0 bps | 2.96% | -13.5 bps |
| WaveMind market-field target | ETH/USDT | 4h | 3 | 90 | 0.467 | 328.0 bps | 3.35% | 79.7 bps |
| WaveMind robust target | ETH/USDT | 4h | 3 | 90 | 0.567 | 288.1 bps | 2.91% | -16.6 bps |
| Momentum baseline | ETH/USDT | 4h | 3 | 90 | 0.533 | 294.2 bps | 2.96% | -7.2 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 0 | 90 | 0.600 | 242.3 bps | 2.42% | -9.1 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 0 | 90 | 0.456 | 253.9 bps | 2.54% | 3.2 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 0 | 90 | 0.522 | 251.3 bps | 2.50% | -21.0 bps |
| WaveMind market-field target | SOL/USDT | 4h | 0 | 90 | 0.489 | 254.4 bps | 2.54% | -14.6 bps |
| WaveMind robust target | SOL/USDT | 4h | 0 | 90 | 0.589 | 242.9 bps | 2.42% | -7.8 bps |
| Momentum baseline | SOL/USDT | 4h | 0 | 90 | 0.511 | 265.4 bps | 2.65% | 21.0 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 1 | 90 | 0.567 | 248.1 bps | 2.45% | -65.4 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 1 | 90 | 0.556 | 223.4 bps | 2.21% | -55.1 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 1 | 90 | 0.433 | 249.5 bps | 2.46% | -74.1 bps |
| WaveMind market-field target | SOL/USDT | 4h | 1 | 90 | 0.644 | 220.7 bps | 2.18% | -74.1 bps |
| WaveMind robust target | SOL/USDT | 4h | 1 | 90 | 0.533 | 245.1 bps | 2.42% | -78.4 bps |
| Momentum baseline | SOL/USDT | 4h | 1 | 90 | 0.356 | 288.2 bps | 2.86% | -17.2 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 2 | 90 | 0.400 | 230.8 bps | 2.31% | -22.0 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 2 | 90 | 0.467 | 222.9 bps | 2.23% | 6.5 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 2 | 90 | 0.567 | 227.2 bps | 2.27% | -35.7 bps |
| WaveMind market-field target | SOL/USDT | 4h | 2 | 90 | 0.422 | 256.0 bps | 2.56% | -18.7 bps |
| WaveMind robust target | SOL/USDT | 4h | 2 | 90 | 0.367 | 234.7 bps | 2.34% | -29.8 bps |
| Momentum baseline | SOL/USDT | 4h | 2 | 90 | 0.578 | 232.6 bps | 2.33% | 6.0 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 3 | 90 | 0.511 | 335.8 bps | 3.36% | -35.8 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 3 | 90 | 0.556 | 325.0 bps | 3.25% | -24.0 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 3 | 90 | 0.567 | 324.9 bps | 3.25% | -33.2 bps |
| WaveMind market-field target | SOL/USDT | 4h | 3 | 90 | 0.411 | 383.7 bps | 3.88% | 56.5 bps |
| WaveMind robust target | SOL/USDT | 4h | 3 | 90 | 0.511 | 335.8 bps | 3.36% | -35.8 bps |
| Momentum baseline | SOL/USDT | 4h | 3 | 90 | 0.589 | 317.6 bps | 3.17% | -16.9 bps |
| WaveMind independent-expert target | ADA/USDT | 4h | 0 | 90 | 0.467 | 261.7 bps | 2.60% | -41.3 bps |
| WaveMind online-expert target | ADA/USDT | 4h | 0 | 90 | 0.433 | 261.7 bps | 2.61% | 10.4 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 0 | 90 | 0.567 | 260.5 bps | 2.59% | -30.9 bps |
| WaveMind market-field target | ADA/USDT | 4h | 0 | 90 | 0.467 | 273.9 bps | 2.73% | 0.9 bps |
| WaveMind robust target | ADA/USDT | 4h | 0 | 90 | 0.478 | 265.7 bps | 2.64% | -40.2 bps |
| Momentum baseline | ADA/USDT | 4h | 0 | 90 | 0.533 | 275.3 bps | 2.75% | 13.4 bps |
| WaveMind independent-expert target | ADA/USDT | 4h | 1 | 90 | 0.489 | 279.6 bps | 2.78% | -42.4 bps |
| WaveMind online-expert target | ADA/USDT | 4h | 1 | 90 | 0.556 | 253.4 bps | 2.52% | -35.1 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 1 | 90 | 0.444 | 285.7 bps | 2.84% | -52.5 bps |
| WaveMind market-field target | ADA/USDT | 4h | 1 | 90 | 0.611 | 251.4 bps | 2.50% | -23.2 bps |
| WaveMind robust target | ADA/USDT | 4h | 1 | 90 | 0.511 | 275.1 bps | 2.73% | -52.7 bps |
| Momentum baseline | ADA/USDT | 4h | 1 | 90 | 0.389 | 317.5 bps | 3.17% | 3.7 bps |
| WaveMind independent-expert target | ADA/USDT | 4h | 2 | 90 | 0.456 | 233.0 bps | 2.32% | -17.8 bps |
| WaveMind online-expert target | ADA/USDT | 4h | 2 | 90 | 0.456 | 235.6 bps | 2.35% | 5.3 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 2 | 90 | 0.556 | 230.8 bps | 2.30% | -30.3 bps |
| WaveMind market-field target | ADA/USDT | 4h | 2 | 90 | 0.500 | 243.3 bps | 2.43% | -11.9 bps |
| WaveMind robust target | ADA/USDT | 4h | 2 | 90 | 0.433 | 234.5 bps | 2.34% | -18.0 bps |
| Momentum baseline | ADA/USDT | 4h | 2 | 90 | 0.500 | 252.6 bps | 2.52% | 8.2 bps |
| WaveMind independent-expert target | ADA/USDT | 4h | 3 | 90 | 0.556 | 465.3 bps | 4.87% | 75.5 bps |
| WaveMind online-expert target | ADA/USDT | 4h | 3 | 90 | 0.489 | 469.4 bps | 4.92% | 98.6 bps |
| WaveMind guarded state-field target | ADA/USDT | 4h | 3 | 90 | 0.578 | 471.0 bps | 4.92% | 73.1 bps |
| WaveMind market-field target | ADA/USDT | 4h | 3 | 90 | 0.522 | 514.6 bps | 5.47% | 245.9 bps |
| WaveMind robust target | ADA/USDT | 4h | 3 | 90 | 0.556 | 465.3 bps | 4.87% | 75.5 bps |
| Momentum baseline | ADA/USDT | 4h | 3 | 90 | 0.478 | 492.7 bps | 5.11% | 47.6 bps |
| WaveMind independent-expert target | AVAX/USDT | 4h | 0 | 90 | 0.522 | 244.7 bps | 2.45% | -30.0 bps |
| WaveMind online-expert target | AVAX/USDT | 4h | 0 | 90 | 0.422 | 258.0 bps | 2.58% | -26.4 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 0 | 90 | 0.500 | 251.7 bps | 2.51% | -55.2 bps |
| WaveMind market-field target | AVAX/USDT | 4h | 0 | 90 | 0.489 | 264.2 bps | 2.64% | -37.2 bps |
| WaveMind robust target | AVAX/USDT | 4h | 0 | 90 | 0.522 | 244.7 bps | 2.45% | -30.0 bps |
| Momentum baseline | AVAX/USDT | 4h | 0 | 90 | 0.511 | 252.9 bps | 2.54% | 15.4 bps |
| WaveMind independent-expert target | AVAX/USDT | 4h | 1 | 90 | 0.489 | 299.3 bps | 2.97% | -67.6 bps |
| WaveMind online-expert target | AVAX/USDT | 4h | 1 | 90 | 0.611 | 273.8 bps | 2.72% | -58.9 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 1 | 90 | 0.378 | 309.9 bps | 3.08% | -47.3 bps |
| WaveMind market-field target | AVAX/USDT | 4h | 1 | 90 | 0.633 | 259.1 bps | 2.58% | -58.4 bps |
| WaveMind robust target | AVAX/USDT | 4h | 1 | 90 | 0.489 | 299.8 bps | 2.98% | -66.1 bps |
| Momentum baseline | AVAX/USDT | 4h | 1 | 90 | 0.367 | 350.0 bps | 3.50% | -5.1 bps |
| WaveMind independent-expert target | AVAX/USDT | 4h | 2 | 90 | 0.533 | 212.8 bps | 2.13% | -31.1 bps |
| WaveMind online-expert target | AVAX/USDT | 4h | 2 | 90 | 0.489 | 211.3 bps | 2.11% | -14.5 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 2 | 90 | 0.478 | 214.8 bps | 2.15% | -36.4 bps |
| WaveMind market-field target | AVAX/USDT | 4h | 2 | 90 | 0.456 | 219.2 bps | 2.19% | -10.7 bps |
| WaveMind robust target | AVAX/USDT | 4h | 2 | 90 | 0.533 | 212.3 bps | 2.12% | -29.6 bps |
| Momentum baseline | AVAX/USDT | 4h | 2 | 90 | 0.544 | 215.9 bps | 2.16% | 6.2 bps |
| WaveMind independent-expert target | AVAX/USDT | 4h | 3 | 90 | 0.578 | 296.8 bps | 3.09% | 75.1 bps |
| WaveMind online-expert target | AVAX/USDT | 4h | 3 | 90 | 0.544 | 299.7 bps | 3.12% | 78.4 bps |
| WaveMind guarded state-field target | AVAX/USDT | 4h | 3 | 90 | 0.544 | 300.7 bps | 3.13% | 87.2 bps |
| WaveMind market-field target | AVAX/USDT | 4h | 3 | 90 | 0.511 | 356.5 bps | 3.74% | 228.2 bps |
| WaveMind robust target | AVAX/USDT | 4h | 3 | 90 | 0.578 | 296.8 bps | 3.09% | 75.1 bps |
| Momentum baseline | AVAX/USDT | 4h | 3 | 90 | 0.489 | 307.9 bps | 3.18% | 47.9 bps |
| WaveMind independent-expert target | DOGE/USDT | 4h | 0 | 90 | 0.522 | 242.8 bps | 2.41% | -47.2 bps |
| WaveMind online-expert target | DOGE/USDT | 4h | 0 | 90 | 0.433 | 248.8 bps | 2.48% | -28.8 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 0 | 90 | 0.622 | 239.2 bps | 2.38% | -37.0 bps |
| WaveMind market-field target | DOGE/USDT | 4h | 0 | 90 | 0.511 | 244.5 bps | 2.44% | -9.1 bps |
| WaveMind robust target | DOGE/USDT | 4h | 0 | 90 | 0.511 | 244.9 bps | 2.43% | -49.0 bps |
| Momentum baseline | DOGE/USDT | 4h | 0 | 90 | 0.489 | 267.1 bps | 2.68% | 25.4 bps |
| WaveMind independent-expert target | DOGE/USDT | 4h | 1 | 90 | 0.444 | 197.9 bps | 1.96% | -60.1 bps |
| WaveMind online-expert target | DOGE/USDT | 4h | 1 | 90 | 0.578 | 193.0 bps | 1.92% | -42.8 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 1 | 90 | 0.400 | 209.7 bps | 2.08% | -51.0 bps |
| WaveMind market-field target | DOGE/USDT | 4h | 1 | 90 | 0.622 | 189.8 bps | 1.89% | -47.3 bps |
| WaveMind robust target | DOGE/USDT | 4h | 1 | 90 | 0.467 | 199.9 bps | 1.98% | -67.6 bps |
| Momentum baseline | DOGE/USDT | 4h | 1 | 90 | 0.378 | 229.8 bps | 2.30% | -4.2 bps |
| WaveMind independent-expert target | DOGE/USDT | 4h | 2 | 90 | 0.589 | 217.6 bps | 2.21% | 53.9 bps |
| WaveMind online-expert target | DOGE/USDT | 4h | 2 | 90 | 0.589 | 221.2 bps | 2.25% | 63.1 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 2 | 90 | 0.533 | 219.8 bps | 2.22% | 6.5 bps |
| WaveMind market-field target | DOGE/USDT | 4h | 2 | 90 | 0.533 | 225.1 bps | 2.28% | 34.9 bps |
| WaveMind robust target | DOGE/USDT | 4h | 2 | 90 | 0.600 | 216.6 bps | 2.20% | 53.8 bps |
| Momentum baseline | DOGE/USDT | 4h | 2 | 90 | 0.467 | 246.8 bps | 2.50% | 39.9 bps |
| WaveMind independent-expert target | DOGE/USDT | 4h | 3 | 90 | 0.511 | 248.4 bps | 2.52% | 34.7 bps |
| WaveMind online-expert target | DOGE/USDT | 4h | 3 | 90 | 0.533 | 262.8 bps | 2.67% | 26.7 bps |
| WaveMind guarded state-field target | DOGE/USDT | 4h | 3 | 90 | 0.578 | 250.5 bps | 2.54% | 24.8 bps |
| WaveMind market-field target | DOGE/USDT | 4h | 3 | 90 | 0.422 | 276.8 bps | 2.83% | 104.0 bps |
| WaveMind robust target | DOGE/USDT | 4h | 3 | 90 | 0.511 | 248.4 bps | 2.52% | 34.7 bps |
| Momentum baseline | DOGE/USDT | 4h | 3 | 90 | 0.578 | 246.9 bps | 2.50% | 15.4 bps |
| WaveMind independent-expert target | LINK/USDT | 4h | 0 | 90 | 0.467 | 243.4 bps | 2.44% | -29.3 bps |
| WaveMind online-expert target | LINK/USDT | 4h | 0 | 90 | 0.322 | 258.9 bps | 2.60% | 2.9 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 0 | 90 | 0.511 | 233.4 bps | 2.34% | -16.8 bps |
| WaveMind market-field target | LINK/USDT | 4h | 0 | 90 | 0.478 | 258.9 bps | 2.60% | -8.5 bps |
| WaveMind robust target | LINK/USDT | 4h | 0 | 90 | 0.456 | 241.7 bps | 2.42% | -27.0 bps |
| Momentum baseline | LINK/USDT | 4h | 0 | 90 | 0.522 | 249.8 bps | 2.51% | 28.6 bps |
| WaveMind independent-expert target | LINK/USDT | 4h | 1 | 90 | 0.378 | 267.0 bps | 2.65% | -64.7 bps |
| WaveMind online-expert target | LINK/USDT | 4h | 1 | 90 | 0.533 | 249.5 bps | 2.47% | -63.0 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 1 | 90 | 0.411 | 265.6 bps | 2.63% | -68.5 bps |
| WaveMind market-field target | LINK/USDT | 4h | 1 | 90 | 0.633 | 236.3 bps | 2.34% | -75.7 bps |
| WaveMind robust target | LINK/USDT | 4h | 1 | 90 | 0.400 | 264.5 bps | 2.62% | -67.2 bps |
| Momentum baseline | LINK/USDT | 4h | 1 | 90 | 0.367 | 299.4 bps | 2.98% | -17.0 bps |
| WaveMind independent-expert target | LINK/USDT | 4h | 2 | 90 | 0.400 | 257.5 bps | 2.56% | -36.9 bps |
| WaveMind online-expert target | LINK/USDT | 4h | 2 | 90 | 0.433 | 252.2 bps | 2.52% | -13.8 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 2 | 90 | 0.411 | 266.2 bps | 2.64% | -61.1 bps |
| WaveMind market-field target | LINK/USDT | 4h | 2 | 90 | 0.456 | 265.2 bps | 2.64% | -44.3 bps |
| WaveMind robust target | LINK/USDT | 4h | 2 | 90 | 0.400 | 256.8 bps | 2.56% | -34.5 bps |
| Momentum baseline | LINK/USDT | 4h | 2 | 90 | 0.544 | 267.9 bps | 2.68% | -1.3 bps |
| WaveMind independent-expert target | LINK/USDT | 4h | 3 | 90 | 0.467 | 288.9 bps | 2.91% | -19.1 bps |
| WaveMind online-expert target | LINK/USDT | 4h | 3 | 90 | 0.522 | 285.6 bps | 2.87% | -14.6 bps |
| WaveMind guarded state-field target | LINK/USDT | 4h | 3 | 90 | 0.500 | 285.5 bps | 2.87% | -10.5 bps |
| WaveMind market-field target | LINK/USDT | 4h | 3 | 90 | 0.533 | 309.0 bps | 3.14% | 57.1 bps |
| WaveMind robust target | LINK/USDT | 4h | 3 | 90 | 0.467 | 288.9 bps | 2.91% | -19.1 bps |
| Momentum baseline | LINK/USDT | 4h | 3 | 90 | 0.467 | 297.6 bps | 2.99% | -4.6 bps |
| WaveMind independent-expert target | XRP/USDT | 4h | 0 | 90 | 0.567 | 188.9 bps | 1.87% | -41.3 bps |
| WaveMind online-expert target | XRP/USDT | 4h | 0 | 90 | 0.400 | 203.6 bps | 2.02% | -31.9 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 0 | 90 | 0.489 | 194.4 bps | 1.92% | -39.3 bps |
| WaveMind market-field target | XRP/USDT | 4h | 0 | 90 | 0.522 | 197.2 bps | 1.95% | -37.1 bps |
| WaveMind robust target | XRP/USDT | 4h | 0 | 90 | 0.556 | 189.1 bps | 1.87% | -41.5 bps |
| Momentum baseline | XRP/USDT | 4h | 0 | 90 | 0.478 | 205.7 bps | 2.05% | 7.5 bps |
| WaveMind independent-expert target | XRP/USDT | 4h | 1 | 90 | 0.467 | 206.3 bps | 2.04% | -73.4 bps |
| WaveMind online-expert target | XRP/USDT | 4h | 1 | 90 | 0.611 | 203.3 bps | 2.01% | -74.6 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 1 | 90 | 0.422 | 214.3 bps | 2.11% | -77.0 bps |
| WaveMind market-field target | XRP/USDT | 4h | 1 | 90 | 0.656 | 191.3 bps | 1.88% | -86.3 bps |
| WaveMind robust target | XRP/USDT | 4h | 1 | 90 | 0.444 | 209.9 bps | 2.07% | -76.8 bps |
| Momentum baseline | XRP/USDT | 4h | 1 | 90 | 0.344 | 227.3 bps | 2.26% | -28.3 bps |
| WaveMind independent-expert target | XRP/USDT | 4h | 2 | 90 | 0.522 | 178.9 bps | 1.79% | -0.2 bps |
| WaveMind online-expert target | XRP/USDT | 4h | 2 | 90 | 0.467 | 184.3 bps | 1.84% | 2.9 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 2 | 90 | 0.578 | 179.9 bps | 1.80% | 4.2 bps |
| WaveMind market-field target | XRP/USDT | 4h | 2 | 90 | 0.556 | 181.4 bps | 1.81% | 1.5 bps |
| WaveMind robust target | XRP/USDT | 4h | 2 | 90 | 0.422 | 185.7 bps | 1.86% | 0.0 bps |
| Momentum baseline | XRP/USDT | 4h | 2 | 90 | 0.444 | 199.5 bps | 2.00% | 16.4 bps |
| WaveMind independent-expert target | XRP/USDT | 4h | 3 | 90 | 0.500 | 304.8 bps | 3.04% | -16.9 bps |
| WaveMind online-expert target | XRP/USDT | 4h | 3 | 90 | 0.544 | 296.9 bps | 2.96% | -14.0 bps |
| WaveMind guarded state-field target | XRP/USDT | 4h | 3 | 90 | 0.556 | 298.9 bps | 2.98% | -12.1 bps |
| WaveMind market-field target | XRP/USDT | 4h | 3 | 90 | 0.522 | 317.6 bps | 3.19% | 49.1 bps |
| WaveMind robust target | XRP/USDT | 4h | 3 | 90 | 0.500 | 304.8 bps | 3.04% | -16.9 bps |
| Momentum baseline | XRP/USDT | 4h | 3 | 90 | 0.478 | 312.5 bps | 3.12% | -1.6 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
