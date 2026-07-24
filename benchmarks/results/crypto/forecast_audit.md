# WaveMind Forecast Audit

Outcomes are evaluated at the forecast horizon using completed exchange candles only.
This is research evidence, not financial advice.

## Summary

| metric | value |
|---|---:|
| forecasts | 25 |
| evaluated | 15 |
| pending | 10 |
| market direction accuracy | 0.267 |
| direction Wilson low 95% | 0.109 |
| worst symbol accuracy | 0.000 |
| strict 70% admission | no |
| trade direction accuracy | n/a |
| target touch rate | 0.533 |
| mean absolute target error | 216.1 bps |

## Ledger Integrity

| status | records | legacy | hashed | anchored legacy | tip hash |
|---|---:|---:|---:|---:|---|
| verified | 25 | 15 | 10 | 15 | `2ac9e53c138830eb...` |

## By Model

| model | forecasts | evaluated | direction accuracy | Wilson low | worst symbol | admitted 70% | target MAE |
|---|---:|---:|---:|---:|---:|---|---:|
| guarded_state_field_v1 | 10 | 5 | 0.200 | 0.036 | 0.000 | no | 119.1 bps |
| regime_analogue_weighted | 15 | 10 | 0.300 | 0.108 | 0.000 | no | 264.6 bps |

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
| 2026-07-24T20:00:00+00:00 | BTC/USDT:USDT | 24h | down | 64064.623 | no_trade | pending |  |  |  |  |
| 2026-07-24T20:00:00+00:00 | ETH/USDT:USDT | 24h | down | 1860.3476 | no_trade | pending |  |  |  |  |
| 2026-07-24T20:00:00+00:00 | SOL/USDT:USDT | 24h | down | 73.773607 | no_trade | pending |  |  |  |  |
| 2026-07-24T20:00:00+00:00 | XRP/USDT:USDT | 24h | down | 1.0882798 | no_trade | pending |  |  |  |  |
| 2026-07-24T20:00:00+00:00 | HYPE/USDT:USDT | 24h | down | 57.825363 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | BTC/USDT:USDT | 7d | up | 65363.758 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | ETH/USDT:USDT | 7d | down | 1863.1776 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | SOL/USDT:USDT | 7d | up | 76.318752 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | XRP/USDT:USDT | 7d | down | 1.0880976 | no_trade | pending |  |  |  |  |
| 2026-07-24T00:00:00+00:00 | HYPE/USDT:USDT | 7d | up | 60.458109 | no_trade | pending |  |  |  |  |
