# WaveMind Crypto Price Target Benchmark

Walk-forward benchmark for predicted future close price. This is not financial advice.

## Summary

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind perp field target | 240 | 0.533 | 952.3 bps | 1491.7 bps | 8.45% | 0.046 | 0.250 | 19.70% |
| WaveMind robust target | 240 | 0.533 | 952.3 bps | 1491.7 bps | 8.45% | 0.046 | 0.250 | 19.70% |
| Historical mean baseline | 240 | 0.546 | 958.1 bps | 1511.1 bps | 8.50% | 0.029 | 0.300 | 19.67% |
| Naive last-outcome baseline | 240 | 0.358 | 1590.8 bps | 2174.1 bps | 15.05% | 0.021 | 0.200 | 37.82% |

## By Market

| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WaveMind perp field target | HYPE/USDT:USDT | 1d | 0 | 20 | 0.300 | 645.3 bps | 6.59% | 255.8 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1d | 0 | 20 | 0.300 | 645.3 bps | 6.59% | 255.8 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1d | 0 | 20 | 0.300 | 723.6 bps | 7.45% | 396.1 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1d | 0 | 20 | 0.450 | 1184.9 bps | 11.82% | 317.4 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 1d | 1 | 20 | 0.750 | 858.5 bps | 7.37% | -555.5 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1d | 1 | 20 | 0.750 | 858.5 bps | 7.37% | -555.5 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1d | 1 | 20 | 0.750 | 821.8 bps | 7.11% | -424.7 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1d | 1 | 20 | 0.500 | 1143.5 bps | 10.06% | -586.7 bps |
| WaveMind perp field target | HYPE/USDT:USDT | 1d | 2 | 20 | 0.550 | 1042.0 bps | 9.76% | -266.0 bps |
| WaveMind robust target | HYPE/USDT:USDT | 1d | 2 | 20 | 0.550 | 1042.0 bps | 9.76% | -266.0 bps |
| Historical mean baseline | HYPE/USDT:USDT | 1d | 2 | 20 | 0.550 | 1031.9 bps | 9.90% | 4.9 bps |
| Naive last-outcome baseline | HYPE/USDT:USDT | 1d | 2 | 20 | 0.200 | 2239.9 bps | 21.63% | -384.9 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1d | 0 | 20 | 0.850 | 341.9 bps | 3.59% | 218.0 bps |
| WaveMind robust target | XRP/USDT:USDT | 1d | 0 | 20 | 0.850 | 341.9 bps | 3.59% | 218.0 bps |
| Historical mean baseline | XRP/USDT:USDT | 1d | 0 | 20 | 0.850 | 319.6 bps | 3.32% | 89.1 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1d | 0 | 20 | 0.500 | 681.1 bps | 7.10% | 195.8 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1d | 1 | 20 | 0.450 | 350.7 bps | 3.52% | -20.7 bps |
| WaveMind robust target | XRP/USDT:USDT | 1d | 1 | 20 | 0.450 | 350.7 bps | 3.52% | -20.7 bps |
| Historical mean baseline | XRP/USDT:USDT | 1d | 1 | 20 | 0.450 | 385.9 bps | 3.82% | -154.2 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1d | 1 | 20 | 0.300 | 592.2 bps | 5.98% | 56.7 bps |
| WaveMind perp field target | XRP/USDT:USDT | 1d | 2 | 20 | 0.550 | 590.1 bps | 6.09% | 120.9 bps |
| WaveMind robust target | XRP/USDT:USDT | 1d | 2 | 20 | 0.550 | 590.1 bps | 6.09% | 120.9 bps |
| Historical mean baseline | XRP/USDT:USDT | 1d | 2 | 20 | 0.550 | 546.7 bps | 5.60% | 44.6 bps |
| Naive last-outcome baseline | XRP/USDT:USDT | 1d | 2 | 20 | 0.300 | 1067.6 bps | 10.83% | -147.8 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1d | 0 | 20 | 0.350 | 1891.7 bps | 14.37% | -1592.8 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1d | 0 | 20 | 0.350 | 1891.7 bps | 14.37% | -1592.8 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1d | 0 | 20 | 0.350 | 1975.1 bps | 14.94% | -1773.0 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1d | 0 | 20 | 0.400 | 2177.8 bps | 18.46% | -1160.5 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1d | 1 | 20 | 0.750 | 2663.6 bps | 19.70% | -1974.1 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1d | 1 | 20 | 0.750 | 2663.6 bps | 19.70% | -1974.1 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1d | 1 | 20 | 0.750 | 2670.9 bps | 19.67% | -2019.8 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1d | 1 | 20 | 0.550 | 4301.6 bps | 37.82% | -91.4 bps |
| WaveMind perp field target | ZEC/USDT:USDT | 1d | 2 | 20 | 0.500 | 1097.0 bps | 11.32% | 135.6 bps |
| WaveMind robust target | ZEC/USDT:USDT | 1d | 2 | 20 | 0.500 | 1097.0 bps | 11.32% | 135.6 bps |
| Historical mean baseline | ZEC/USDT:USDT | 1d | 2 | 20 | 0.500 | 1116.9 bps | 11.67% | 268.0 bps |
| Naive last-outcome baseline | ZEC/USDT:USDT | 1d | 2 | 20 | 0.250 | 2181.0 bps | 22.08% | -300.2 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1d | 0 | 20 | 0.700 | 472.1 bps | 4.95% | 179.5 bps |
| WaveMind robust target | SOL/USDT:USDT | 1d | 0 | 20 | 0.700 | 472.1 bps | 4.95% | 179.5 bps |
| Historical mean baseline | SOL/USDT:USDT | 1d | 0 | 20 | 0.700 | 428.7 bps | 4.46% | 87.1 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1d | 0 | 20 | 0.450 | 867.8 bps | 8.98% | 163.3 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1d | 1 | 20 | 0.400 | 741.5 bps | 7.34% | -78.9 bps |
| WaveMind robust target | SOL/USDT:USDT | 1d | 1 | 20 | 0.400 | 741.5 bps | 7.34% | -78.9 bps |
| Historical mean baseline | SOL/USDT:USDT | 1d | 1 | 20 | 0.500 | 751.5 bps | 7.29% | -281.7 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1d | 1 | 20 | 0.200 | 1166.1 bps | 11.84% | 229.6 bps |
| WaveMind perp field target | SOL/USDT:USDT | 1d | 2 | 20 | 0.250 | 733.1 bps | 6.83% | -548.3 bps |
| WaveMind robust target | SOL/USDT:USDT | 1d | 2 | 20 | 0.250 | 733.1 bps | 6.83% | -548.3 bps |
| Historical mean baseline | SOL/USDT:USDT | 1d | 2 | 20 | 0.300 | 724.1 bps | 6.71% | -624.4 bps |
| Naive last-outcome baseline | SOL/USDT:USDT | 1d | 2 | 20 | 0.200 | 1486.7 bps | 14.05% | -651.8 bps |

The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.
