# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | up | 1.14% | 65077.5 | no_trade | 64344.3 | 0.000 | unsupported_timeframe:1d | flat | flat | 64344.3 |  | none |
| ETH/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | up | 2.14% | 1913.83 | no_trade | 1873.8 | 0.000 | unsupported_timeframe:1d | flat | flat | 1873.8 |  | none |
| SOL/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | down | -0.44% | 74.15 | no_trade | 74.48 | 0.000 | unsupported_timeframe:1d | flat | flat | 74.48 |  | none |
| XRP/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | down | -2.36% | 1.0712 | no_trade | 1.0971 | 0.000 | unsupported_timeframe:1d | flat | flat | 1.0971 |  | none |
| BNB/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | down | -0.35% | 566.695 | no_trade | 568.7 | 0.000 | unsupported_timeframe:1d | flat | flat | 568.7 |  | none |
| DOGE/USDT:USDT | 7d | 2026-07-26T00:00:00+00:00 | down | -1.97% | 0.0702674 | no_trade | 0.07168 | 0.000 | unsupported_timeframe:1d | flat | flat | 0.07168 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
