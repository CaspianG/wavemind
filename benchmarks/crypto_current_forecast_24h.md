# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-07-30T08:00:00+00:00 | down | -0.39% | 63731.3 | no_trade | 63980.4 | 0.929 | adaptive_trend_mismatch | flat | down | 63980.4 |  | none |
| ETH/USDT:USDT | 24h | 2026-07-30T08:00:00+00:00 | down | -0.49% | 1893.12 | no_trade | 1902.38 | 0.836 | adaptive_trend_mismatch | flat | down | 1902.38 |  | none |
| SOL/USDT:USDT | 24h | 2026-07-30T08:00:00+00:00 | down | -0.15% | 73.268 | no_trade | 73.38 | 0.430 | local_regime_negative:support=160,hit=0.430,net=-2.09 | flat | down | 73.38 |  | none |
| GRAM/USDT:USDT | 24h | 2026-07-30T08:00:00+00:00 | down | -0.68% | 1.40738 | no_trade | 1.417 | 0.748 | flat_candidate | flat | flat | 1.417 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
