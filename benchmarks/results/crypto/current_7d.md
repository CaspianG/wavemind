# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 7d | 2026-07-24T00:00:00+00:00 | up | 0.46% | 65363.8 | no_trade | 65066 | 0.000 | unsupported_timeframe:1d | flat | flat | 65066 |  | none |
| ETH/USDT:USDT | 7d | 2026-07-24T00:00:00+00:00 | down | -0.76% | 1863.18 | no_trade | 1877.45 | 0.000 | unsupported_timeframe:1d | flat | flat | 1877.45 |  | none |
| SOL/USDT:USDT | 7d | 2026-07-24T00:00:00+00:00 | up | 0.64% | 76.3188 | no_trade | 75.83 | 0.000 | unsupported_timeframe:1d | flat | flat | 75.83 |  | none |
| XRP/USDT:USDT | 7d | 2026-07-24T00:00:00+00:00 | down | -1.73% | 1.0881 | no_trade | 1.1073 | 0.000 | unsupported_timeframe:1d | flat | flat | 1.1073 |  | none |
| HYPE/USDT:USDT | 7d | 2026-07-24T00:00:00+00:00 | up | 5.21% | 60.4581 | no_trade | 57.466 | 0.000 | unsupported_timeframe:1d | flat | flat | 57.466 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
