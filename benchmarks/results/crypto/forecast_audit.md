# WaveMind Forecast Audit

Outcomes are evaluated at the forecast horizon using completed exchange candles only.
This is research evidence, not financial advice.

## Summary

| metric | value |
|---|---:|
| forecasts | 45 |
| evaluated | 26 |
| pending | 19 |
| market direction accuracy | 0.231 |
| direction Wilson low 95% | 0.110 |
| worst symbol accuracy | 0.000 |
| strict 70% admission | no |
| trade direction accuracy | n/a |
| target touch rate | 0.654 |
| mean absolute target error | 175.8 bps |

## Ledger Integrity

| status | records | legacy | hashed | anchored legacy | tip hash |
|---|---:|---:|---:|---:|---|
| verified | 45 | 15 | 30 | 15 | `9e5b7baa0d53d444...` |

## By Model

| model | forecasts | evaluated | direction accuracy | Wilson low | worst symbol | admitted 70% | target MAE |
|---|---:|---:|---:|---:|---:|---|---:|
| guarded_state_field_v1 | 20 | 16 | 0.188 | 0.066 | 0.000 | no | 120.3 bps |
| regime_analogue_weighted | 25 | 10 | 0.300 | 0.108 | 0.000 | no | 264.6 bps |

## Forecasts

| data end UTC | symbol | horizon | forecast | target | trade | status | actual | direction correct | target touched | target error |
|---|---|---:|---|---:|---|---|---:|---|---|---:|
| 2026-07-17T16:00:00+00:00 | BTC/USDT:USDT | 24h | down | 63270.936 | no_trade | evaluated | 64093 | no | no | 129.6 bps |
| 2026-07-17T16:00:00+00:00 | ETH/USDT:USDT | 24h | up | 1835.0831 | no_trade | evaluated | 1843.07 | yes | yes | 43.6 bps |
| 2026-07-17T16:00:00+00:00 | SOL/USDT:USDT | 24h | down | 73.893788 | no_trade | evaluated | 74.92 | no | no | 137.3 bps |
| 2026-07-17T16:00:00+00:00 | XRP/USDT:USDT | 24h | down | 1.0815926 | no_trade | evaluated | 1.0859 | no | yes | 39.8 bps |
| 2026-07-17T16:00:00+00:00 | HYPE/USDT:USDT | 24h | up | 61.20104 | no_trade | evaluated | 59.189 | no | no | 331.1 bps |
| 2026-07-17T16:00:00+00:00 | BTC/USDT:USDT | 24h | down | 63270.936 | no_trade | evaluated | 64093 | no | no | 129.6 bps |
| 2026-07-17T16:00:00+00:00 | ETH/USDT:USDT | 24h | down | 1824.8169 | no_trade | evaluated | 1843.07 | no | no | 99.7 bps |
| 2026-07-17T16:00:00+00:00 | SOL/USDT:USDT | 24h | down | 73.893788 | no_trade | evaluated | 74.92 | no | no | 137.3 bps |
| 2026-07-17T16:00:00+00:00 | XRP/USDT:USDT | 24h | down | 1.0815926 | no_trade | evaluated | 1.0859 | no | yes | 39.8 bps |
| 2026-07-17T16:00:00+00:00 | HYPE/USDT:USDT | 24h | down | 60.33896 | no_trade | evaluated | 59.189 | yes | yes | 189.2 bps |
| 2026-07-17T00:00:00+00:00 | BTC/USDT:USDT | 7d | up | 64482.727 | no_trade | evaluated | 65066 | yes | yes | 91.4 bps |
| 2026-07-17T00:00:00+00:00 | ETH/USDT:USDT | 7d | up | 1865.0056 | no_trade | evaluated | 1877.45 | yes | yes | 66.8 bps |
| 2026-07-17T00:00:00+00:00 | SOL/USDT:USDT | 7d | down | 74.696989 | no_trade | evaluated | 75.83 | no | yes | 150.5 bps |
| 2026-07-17T00:00:00+00:00 | XRP/USDT:USDT | 7d | down | 1.0812834 | no_trade | evaluated | 1.1073 | no | yes | 239.5 bps |
| 2026-07-17T00:00:00+00:00 | HYPE/USDT:USDT | 7d | up | 66.06888 | no_trade | evaluated | 57.466 | no | no | 1416.5 bps |
| 2026-07-24T20:00:00+00:00 | BTC/USDT:USDT | 24h | down | 64064.623 | no_trade | evaluated | 64362.7 | no | yes | 46.4 bps |
| 2026-07-24T20:00:00+00:00 | ETH/USDT:USDT | 24h | down | 1860.3476 | no_trade | evaluated | 1873.91 | no | yes | 72.8 bps |
| 2026-07-24T20:00:00+00:00 | SOL/USDT:USDT | 24h | down | 73.773607 | no_trade | evaluated | 74.51 | no | yes | 99.6 bps |
| 2026-07-24T20:00:00+00:00 | XRP/USDT:USDT | 24h | down | 1.0882798 | no_trade | evaluated | 1.1 | no | yes | 107.7 bps |
| 2026-07-24T20:00:00+00:00 | HYPE/USDT:USDT | 24h | down | 57.825363 | no_trade | evaluated | 58.064 | yes | yes | 41.0 bps |
| 2026-07-24T00:00:00+00:00 | BTC/USDT:USDT | 7d | up | 65363.758 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | ETH/USDT:USDT | 7d | down | 1863.1776 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | SOL/USDT:USDT | 7d | up | 76.318752 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | XRP/USDT:USDT | 7d | down | 1.0880976 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | HYPE/USDT:USDT | 7d | up | 60.458109 | no_trade | pending |  |  |  |  |
| 2026-07-26T12:00:00+00:00 | BTC/USDT:USDT | 24h | down | 64065.765 | no_trade | evaluated | 65081.9 | no | no | 157.6 bps |
| 2026-07-26T12:00:00+00:00 | ETH/USDT:USDT | 24h | down | 1881.6712 | no_trade | evaluated | 1958.8 | no | yes | 409.2 bps |
| 2026-07-26T12:00:00+00:00 | SOL/USDT:USDT | 24h | down | 74.729624 | no_trade | evaluated | 76.47 | no | yes | 232.3 bps |
| 2026-07-26T12:00:00+00:00 | XRP/USDT:USDT | 24h | down | 1.0978914 | no_trade | evaluated | 1.1047 | no | yes | 61.9 bps |
| 2026-07-26T12:00:00+00:00 | BNB/USDT:USDT | 24h | down | 568.9935 | no_trade | evaluated | 572.8 | no | no | 66.7 bps |
| 2026-07-26T12:00:00+00:00 | DOGE/USDT:USDT | 24h | down | 0.072780244 | no_trade | evaluated | 0.07253 | yes | yes | 34.2 bps |
| 2026-07-26T00:00:00+00:00 | BTC/USDT:USDT | 7d | up | 65077.504 | no_trade | pending |  |  |  |  |
| 2026-07-26T00:00:00+00:00 | ETH/USDT:USDT | 7d | up | 1913.8296 | no_trade | pending |  |  |  |  |
| 2026-07-26T00:00:00+00:00 | SOL/USDT:USDT | 7d | down | 74.149964 | no_trade | pending |  |  |  |  |
| 2026-07-26T00:00:00+00:00 | XRP/USDT:USDT | 7d | down | 1.0711999 | no_trade | pending |  |  |  |  |
| 2026-07-26T00:00:00+00:00 | BNB/USDT:USDT | 7d | down | 566.69464 | no_trade | pending |  |  |  |  |
| 2026-07-26T00:00:00+00:00 | DOGE/USDT:USDT | 7d | down | 0.070267378 | no_trade | pending |  |  |  |  |
| 2026-07-30T08:00:00+00:00 | BTC/USDT:USDT | 24h | down | 63731.287 | no_trade | pending |  |  |  |  |
| 2026-07-30T08:00:00+00:00 | ETH/USDT:USDT | 24h | down | 1893.1206 | no_trade | pending |  |  |  |  |
| 2026-07-30T08:00:00+00:00 | SOL/USDT:USDT | 24h | down | 73.268034 | no_trade | pending |  |  |  |  |
| 2026-07-30T08:00:00+00:00 | GRAM/USDT:USDT | 24h | down | 1.4073754 | no_trade | pending |  |  |  |  |
| 2026-07-30T00:00:00+00:00 | BTC/USDT:USDT | 7d | up | 64434.981 | no_trade | pending |  |  |  |  |
| 2026-07-30T00:00:00+00:00 | ETH/USDT:USDT | 7d | down | 1894.3027 | no_trade | pending |  |  |  |  |
| 2026-07-30T00:00:00+00:00 | SOL/USDT:USDT | 7d | down | 72.882082 | no_trade | pending |  |  |  |  |
| 2026-07-30T00:00:00+00:00 | GRAM/USDT:USDT | 7d | up | 1.405538 | no_trade | pending |  |  |  |  |
