# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| HYPE/USDT:USDT | 7d | 2026-07-05T00:00:00+00:00 | up | 0.52% | 71.7088 | no_trade | 71.339 | 0.000 | unsupported_timeframe:1d | flat | flat | 71.339 |  | none |
| XRP/USDT:USDT | 7d | 2026-07-05T00:00:00+00:00 | down | -0.93% | 1.14597 | no_trade | 1.1567 | 0.000 | unsupported_timeframe:1d | flat | flat | 1.1567 |  | none |
| ZEC/USDT:USDT | 7d | 2026-07-05T00:00:00+00:00 | up | 10.80% | 512.041 | no_trade | 462.13 | 0.000 | unsupported_timeframe:1d | flat | flat | 462.13 |  | none |
| SOL/USDT:USDT | 7d | 2026-07-05T00:00:00+00:00 | down | -1.48% | 80.3392 | no_trade | 81.55 | 0.000 | unsupported_timeframe:1d | flat | flat | 81.55 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
