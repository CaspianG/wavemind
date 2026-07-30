# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 7d | 2026-07-30T00:00:00+00:00 | up | 0.75% | 64435 | no_trade | 63955.1 | 0.000 | unsupported_timeframe:1d | flat | flat | 63955.1 |  | none |
| ETH/USDT:USDT | 7d | 2026-07-30T00:00:00+00:00 | down | -0.81% | 1894.3 | no_trade | 1909.77 | 0.000 | unsupported_timeframe:1d | flat | flat | 1909.77 |  | none |
| SOL/USDT:USDT | 7d | 2026-07-30T00:00:00+00:00 | down | -1.02% | 72.8821 | no_trade | 73.63 | 0.000 | unsupported_timeframe:1d | flat | flat | 73.63 |  | none |
| GRAM/USDT:USDT | 7d | 2026-07-30T00:00:00+00:00 | up | 0.18% | 1.40554 | no_trade | 1.403 | 0.000 | unsupported_timeframe:1d | flat | flat | 1.403 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
