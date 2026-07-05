# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT | 7d | 2026-07-04T00:00:00+00:00 | up | 0.31% | 63334 | no_trade | 63140.6 | 0.000 | unsupported_timeframe:1d | flat | flat | 63140.6 |  | none |
| ETH/USDT | 7d | 2026-07-04T00:00:00+00:00 | up | 1.36% | 1804.83 | no_trade | 1780.64 | 0.000 | unsupported_timeframe:1d | flat | flat | 1780.64 |  | none |
| SOL/USDT | 7d | 2026-07-04T00:00:00+00:00 | down | -1.55% | 80.5292 | no_trade | 81.8 | 0.000 | unsupported_timeframe:1d | flat | flat | 81.8 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
