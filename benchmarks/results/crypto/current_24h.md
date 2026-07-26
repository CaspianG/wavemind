# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.64% | 64065.8 | no_trade | 64477.7 | 0.884 | adaptive_trend_mismatch | flat | up | 64477.7 |  | none |
| ETH/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.18% | 1881.67 | no_trade | 1884.98 | 0.894 | adaptive_trend_mismatch | flat | up | 1884.98 |  | none |
| SOL/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.24% | 74.7296 | no_trade | 74.91 | 0.507 | adaptive_trend_mismatch | flat | up | 74.91 |  | none |
| XRP/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.18% | 1.09789 | no_trade | 1.0999 | 0.789 | adaptive_trend_mismatch | flat | up | 1.0999 |  | none |
| BNB/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.25% | 568.994 | no_trade | 570.4 | 0.616 | adaptive_trend_mismatch | flat | up | 570.4 |  | none |
| DOGE/USDT:USDT | 24h | 2026-07-26T12:00:00+00:00 | down | -0.57% | 0.0727802 | no_trade | 0.0732 | 0.924 | adaptive_trend_mismatch | flat | up | 0.0732 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
