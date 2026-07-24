# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-07-24T20:00:00+00:00 | down | -0.20% | 64064.6 | no_trade | 64196.2 | 0.958 | adaptive_field_opposition | flat | down | 64196.2 |  | none |
| ETH/USDT:USDT | 24h | 2026-07-24T20:00:00+00:00 | down | -0.13% | 1860.35 | no_trade | 1862.71 | 0.544 | low_expected_edge | flat | down | 1862.71 |  | none |
| SOL/USDT:USDT | 24h | 2026-07-24T20:00:00+00:00 | down | -0.20% | 73.7736 | no_trade | 73.92 | 0.456 | ta_conflict | flat | down | 73.92 |  | none |
| XRP/USDT:USDT | 24h | 2026-07-24T20:00:00+00:00 | down | -0.03% | 1.08828 | no_trade | 1.0886 | 0.736 | low_expected_edge | flat | down | 1.0886 |  | none |
| HYPE/USDT:USDT | 24h | 2026-07-24T20:00:00+00:00 | down | -0.54% | 57.8254 | no_trade | 58.14 | 0.886 | adaptive_trend_mismatch | flat | up | 58.14 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
