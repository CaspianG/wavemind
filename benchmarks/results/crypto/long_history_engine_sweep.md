# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind independent-expert target | 1890 | 0.513 | 218.5 bps | 300.6 bps | 2.20% | 0.186 | 0.367 | 4.10% |
| WaveMind online-expert target | 1890 | 0.542 | 217.2 bps | 299.9 bps | 2.19% | 0.189 | 0.400 | 4.04% |
| WaveMind guarded state-field target | 1890 | 0.509 | 220.9 bps | 300.0 bps | 2.22% | 0.179 | 0.311 | 4.10% |
| WaveMind market-field target | 1890 | 0.493 | 229.0 bps | 321.7 bps | 2.32% | 0.203 | 0.322 | 4.26% |
| Momentum baseline | 1890 | 0.507 | 226.9 bps | 309.7 bps | 2.29% | 0.188 | 0.356 | 4.49% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind independent-expert target | BTC/USDT | 4h | 0 | 90 | 0.456 | 109.1 bps | 1.09% | -43.7 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 0 | 90 | 0.556 | 104.9 bps | 1.04% | -43.9 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 0 | 90 | 0.311 | 119.6 bps | 1.19% | -45.0 bps |
| WaveMind market-field target | BTC/USDT | 4h | 0 | 90 | 0.511 | 108.0 bps | 1.07% | -46.4 bps |
| Momentum baseline | BTC/USDT | 4h | 0 | 90 | 0.489 | 111.2 bps | 1.11% | -28.1 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 1 | 90 | 0.533 | 210.8 bps | 2.19% | 118.8 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 1 | 90 | 0.556 | 210.6 bps | 2.18% | 116.9 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 1 | 90 | 0.600 | 205.4 bps | 2.13% | 100.8 bps |
| WaveMind market-field target | BTC/USDT | 4h | 1 | 90 | 0.444 | 240.8 bps | 2.50% | 202.8 bps |
| Momentum baseline | BTC/USDT | 4h | 1 | 90 | 0.556 | 217.5 bps | 2.24% | 71.7 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 2 | 90 | 0.544 | 278.5 bps | 2.75% | -53.2 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 2 | 90 | 0.411 | 278.8 bps | 2.76% | -50.4 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 2 | 90 | 0.456 | 280.5 bps | 2.77% | -45.2 bps |
| WaveMind market-field target | BTC/USDT | 4h | 2 | 90 | 0.611 | 260.0 bps | 2.58% | -32.9 bps |
| Momentum baseline | BTC/USDT | 4h | 2 | 90 | 0.389 | 312.4 bps | 3.10% | 3.0 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 3 | 90 | 0.567 | 162.8 bps | 1.63% | -4.2 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 3 | 90 | 0.578 | 160.6 bps | 1.61% | -3.7 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 3 | 90 | 0.489 | 168.5 bps | 1.68% | -22.7 bps |
| WaveMind market-field target | BTC/USDT | 4h | 3 | 90 | 0.644 | 154.2 bps | 1.55% | 24.5 bps |
| Momentum baseline | BTC/USDT | 4h | 3 | 90 | 0.356 | 185.9 bps | 1.86% | -13.0 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 4 | 90 | 0.444 | 118.8 bps | 1.18% | -49.8 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 4 | 90 | 0.533 | 116.1 bps | 1.15% | -47.2 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 4 | 90 | 0.433 | 125.7 bps | 1.24% | -63.7 bps |
| WaveMind market-field target | BTC/USDT | 4h | 4 | 90 | 0.456 | 124.6 bps | 1.23% | -66.0 bps |
| Momentum baseline | BTC/USDT | 4h | 4 | 90 | 0.544 | 122.9 bps | 1.22% | -30.6 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 5 | 90 | 0.667 | 177.5 bps | 1.83% | 123.4 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 5 | 90 | 0.611 | 178.2 bps | 1.84% | 126.6 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 5 | 90 | 0.700 | 172.6 bps | 1.78% | 107.5 bps |
| WaveMind market-field target | BTC/USDT | 4h | 5 | 90 | 0.378 | 217.7 bps | 2.25% | 178.9 bps |
| Momentum baseline | BTC/USDT | 4h | 5 | 90 | 0.622 | 167.1 bps | 1.72% | 89.2 bps |
| WaveMind independent-expert target | BTC/USDT | 4h | 6 | 90 | 0.544 | 142.8 bps | 1.43% | -15.9 bps |
| WaveMind online-expert target | BTC/USDT | 4h | 6 | 90 | 0.500 | 149.2 bps | 1.50% | -11.2 bps |
| WaveMind guarded state-field target | BTC/USDT | 4h | 6 | 90 | 0.467 | 152.4 bps | 1.52% | -33.1 bps |
| WaveMind market-field target | BTC/USDT | 4h | 6 | 90 | 0.433 | 161.4 bps | 1.62% | 19.7 bps |
| Momentum baseline | BTC/USDT | 4h | 6 | 90 | 0.567 | 142.7 bps | 1.43% | -13.1 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 0 | 90 | 0.367 | 122.2 bps | 1.21% | -60.1 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 0 | 90 | 0.589 | 110.7 bps | 1.10% | -48.2 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 0 | 90 | 0.389 | 130.6 bps | 1.29% | -76.1 bps |
| WaveMind market-field target | ETH/USDT | 4h | 0 | 90 | 0.422 | 125.8 bps | 1.25% | -61.9 bps |
| Momentum baseline | ETH/USDT | 4h | 0 | 90 | 0.578 | 120.4 bps | 1.20% | -30.2 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 1 | 90 | 0.656 | 331.9 bps | 3.48% | 181.2 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 1 | 90 | 0.678 | 331.0 bps | 3.47% | 176.5 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 1 | 90 | 0.678 | 332.9 bps | 3.48% | 151.6 bps |
| WaveMind market-field target | ETH/USDT | 4h | 1 | 90 | 0.322 | 403.4 bps | 4.26% | 333.5 bps |
| Momentum baseline | ETH/USDT | 4h | 1 | 90 | 0.678 | 327.4 bps | 3.41% | 93.5 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 2 | 90 | 0.522 | 365.1 bps | 3.59% | -67.9 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 2 | 90 | 0.489 | 361.0 bps | 3.55% | -77.8 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 2 | 90 | 0.500 | 367.8 bps | 3.62% | -59.8 bps |
| WaveMind market-field target | ETH/USDT | 4h | 2 | 90 | 0.600 | 338.2 bps | 3.34% | -39.6 bps |
| Momentum baseline | ETH/USDT | 4h | 2 | 90 | 0.400 | 412.4 bps | 4.08% | -4.5 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 3 | 90 | 0.556 | 217.2 bps | 2.17% | -23.9 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 3 | 90 | 0.578 | 215.6 bps | 2.15% | -21.0 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 3 | 90 | 0.522 | 225.3 bps | 2.25% | -43.8 bps |
| WaveMind market-field target | ETH/USDT | 4h | 3 | 90 | 0.578 | 210.0 bps | 2.11% | 15.5 bps |
| Momentum baseline | ETH/USDT | 4h | 3 | 90 | 0.422 | 240.1 bps | 2.40% | -20.0 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 4 | 90 | 0.478 | 138.7 bps | 1.38% | -17.8 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 4 | 90 | 0.400 | 144.4 bps | 1.44% | -15.0 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 4 | 90 | 0.367 | 150.0 bps | 1.49% | -53.7 bps |
| WaveMind market-field target | ETH/USDT | 4h | 4 | 90 | 0.589 | 138.2 bps | 1.38% | -18.9 bps |
| Momentum baseline | ETH/USDT | 4h | 4 | 90 | 0.411 | 159.1 bps | 1.59% | -18.8 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 5 | 90 | 0.533 | 199.2 bps | 2.06% | 120.4 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 5 | 90 | 0.544 | 200.5 bps | 2.07% | 122.1 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 5 | 90 | 0.656 | 192.2 bps | 1.98% | 101.3 bps |
| WaveMind market-field target | ETH/USDT | 4h | 5 | 90 | 0.433 | 226.7 bps | 2.35% | 181.5 bps |
| Momentum baseline | ETH/USDT | 4h | 5 | 90 | 0.567 | 199.5 bps | 2.05% | 88.2 bps |
| WaveMind independent-expert target | ETH/USDT | 4h | 6 | 90 | 0.400 | 213.5 bps | 2.12% | -59.7 bps |
| WaveMind online-expert target | ETH/USDT | 4h | 6 | 90 | 0.467 | 211.2 bps | 2.10% | -59.4 bps |
| WaveMind guarded state-field target | ETH/USDT | 4h | 6 | 90 | 0.500 | 206.1 bps | 2.05% | -54.5 bps |
| WaveMind market-field target | ETH/USDT | 4h | 6 | 90 | 0.489 | 236.0 bps | 2.35% | -18.6 bps |
| Momentum baseline | ETH/USDT | 4h | 6 | 90 | 0.511 | 199.8 bps | 1.99% | -36.2 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 0 | 90 | 0.422 | 160.1 bps | 1.58% | -89.0 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 0 | 90 | 0.600 | 149.6 bps | 1.48% | -71.8 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 0 | 90 | 0.444 | 171.4 bps | 1.69% | -89.6 bps |
| WaveMind market-field target | SOL/USDT | 4h | 0 | 90 | 0.433 | 163.6 bps | 1.62% | -82.0 bps |
| Momentum baseline | SOL/USDT | 4h | 0 | 90 | 0.567 | 145.6 bps | 1.44% | -42.0 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 1 | 90 | 0.633 | 336.3 bps | 3.53% | 173.5 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 1 | 90 | 0.644 | 341.6 bps | 3.59% | 178.2 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 1 | 90 | 0.667 | 333.1 bps | 3.50% | 148.1 bps |
| WaveMind market-field target | SOL/USDT | 4h | 1 | 90 | 0.356 | 385.9 bps | 4.08% | 316.3 bps |
| Momentum baseline | SOL/USDT | 4h | 1 | 90 | 0.644 | 348.0 bps | 3.63% | 95.9 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 2 | 90 | 0.489 | 416.4 bps | 4.10% | -81.9 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 2 | 90 | 0.533 | 409.5 bps | 4.04% | -68.7 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 2 | 90 | 0.489 | 416.0 bps | 4.10% | -65.6 bps |
| WaveMind market-field target | SOL/USDT | 4h | 2 | 90 | 0.567 | 397.6 bps | 3.93% | -52.8 bps |
| Momentum baseline | SOL/USDT | 4h | 2 | 90 | 0.433 | 453.1 bps | 4.49% | -6.4 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 3 | 90 | 0.444 | 247.4 bps | 2.51% | 33.5 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 3 | 90 | 0.567 | 239.4 bps | 2.43% | 43.8 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 3 | 90 | 0.467 | 248.7 bps | 2.51% | 2.3 bps |
| WaveMind market-field target | SOL/USDT | 4h | 3 | 90 | 0.589 | 234.7 bps | 2.39% | 93.5 bps |
| Momentum baseline | SOL/USDT | 4h | 3 | 90 | 0.411 | 266.8 bps | 2.70% | 9.5 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 4 | 90 | 0.422 | 125.0 bps | 1.24% | -23.4 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 4 | 90 | 0.456 | 127.9 bps | 1.27% | -17.0 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 4 | 90 | 0.433 | 122.3 bps | 1.22% | -33.5 bps |
| WaveMind market-field target | SOL/USDT | 4h | 4 | 90 | 0.589 | 116.8 bps | 1.16% | -6.4 bps |
| Momentum baseline | SOL/USDT | 4h | 4 | 90 | 0.411 | 137.8 bps | 1.38% | -20.6 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 5 | 90 | 0.611 | 230.8 bps | 2.40% | 153.8 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 5 | 90 | 0.689 | 226.7 bps | 2.36% | 156.4 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 5 | 90 | 0.644 | 225.1 bps | 2.33% | 123.9 bps |
| WaveMind market-field target | SOL/USDT | 4h | 5 | 90 | 0.433 | 262.4 bps | 2.73% | 202.8 bps |
| Momentum baseline | SOL/USDT | 4h | 5 | 90 | 0.567 | 215.4 bps | 2.23% | 106.7 bps |
| WaveMind independent-expert target | SOL/USDT | 4h | 6 | 90 | 0.489 | 283.6 bps | 2.77% | -126.8 bps |
| WaveMind online-expert target | SOL/USDT | 4h | 6 | 90 | 0.411 | 294.3 bps | 2.88% | -133.2 bps |
| WaveMind guarded state-field target | SOL/USDT | 4h | 6 | 90 | 0.478 | 293.2 bps | 2.87% | -128.9 bps |
| WaveMind market-field target | SOL/USDT | 4h | 6 | 90 | 0.467 | 303.0 bps | 2.96% | -151.9 bps |
| Momentum baseline | SOL/USDT | 4h | 6 | 90 | 0.533 | 280.9 bps | 2.76% | -55.2 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
