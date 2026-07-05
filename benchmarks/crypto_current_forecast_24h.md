# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT | 24h | 2026-07-05T08:00:00+00:00 | up | 0.20% | 62781.1 | no_trade | 62656.2 | 0.630 | flat_candidate | flat | flat | 62656.2 |  | none |
| ETH/USDT | 24h | 2026-07-05T08:00:00+00:00 | down | -0.53% | 1751 | no_trade | 1760.32 | 0.939 | flat_candidate | flat | flat | 1760.32 |  | none |
| SOL/USDT | 24h | 2026-07-05T08:00:00+00:00 | up | 1.19% | 81.5183 | no_trade | 80.56 | 1.000 | adaptive_trend_mismatch | flat | down | 80.56 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
