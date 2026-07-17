# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 7d | 2026-07-17T00:00:00+00:00 | up | 1.08% | 64482.7 | no_trade | 63795.9 | 0.000 | unsupported_timeframe:1d | flat | flat | 63795.9 |  | none |
| ETH/USDT:USDT | 7d | 2026-07-17T00:00:00+00:00 | up | 0.06% | 1865.01 | no_trade | 1863.86 | 0.000 | unsupported_timeframe:1d | flat | flat | 1863.86 |  | none |
| SOL/USDT:USDT | 7d | 2026-07-17T00:00:00+00:00 | down | -0.76% | 74.697 | no_trade | 75.27 | 0.000 | unsupported_timeframe:1d | flat | flat | 75.27 |  | none |
| XRP/USDT:USDT | 7d | 2026-07-17T00:00:00+00:00 | down | -0.48% | 1.08128 | no_trade | 1.0865 | 0.000 | unsupported_timeframe:1d | flat | flat | 1.0865 |  | none |
| HYPE/USDT:USDT | 7d | 2026-07-17T00:00:00+00:00 | up | 8.78% | 66.0689 | no_trade | 60.734 | 0.000 | unsupported_timeframe:1d | flat | flat | 60.734 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
