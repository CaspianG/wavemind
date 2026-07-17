# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-07-17T16:00:00+00:00 | down | -0.26% | 63270.9 | no_trade | 63436.7 | 0.447 | local_regime_negative:support=159,hit=0.447,net=-42.78 | flat | down | 63436.7 |  | none |
| ETH/USDT:USDT | 24h | 2026-07-17T16:00:00+00:00 | down | -0.28% | 1824.82 | no_trade | 1829.95 | 0.608 | adaptive_trend_mismatch | flat | down | 1829.95 |  | none |
| SOL/USDT:USDT | 24h | 2026-07-17T16:00:00+00:00 | down | -1.11% | 73.8938 | no_trade | 74.72 | 0.785 | ta_conflict | flat | down | 74.72 |  | none |
| XRP/USDT:USDT | 24h | 2026-07-17T16:00:00+00:00 | down | -0.11% | 1.08159 | no_trade | 1.0828 | 0.967 | short_squeeze_guard | flat | down | 1.0828 |  | none |
| HYPE/USDT:USDT | 24h | 2026-07-17T16:00:00+00:00 | down | -0.71% | 60.339 | no_trade | 60.77 | 0.731 | ta_conflict | flat | down | 60.77 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
