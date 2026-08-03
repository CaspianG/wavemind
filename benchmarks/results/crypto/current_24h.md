# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
A point target is published only when the trade-quality policy validates a signal.
When validation returns `no_trade`, the report shows an adaptive conformal price range instead of a false-precision target.

| symbol | horizon | data end UTC | status | validated forecast | target price | calibrated price range | trade validation | last close | evidence strength | validation reason |
|---|---:|---|---|---|---:|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-08-03T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 62737.4 to 64920.2 (80% nominal) | no_trade | 63828.8 | 0.904 | adaptive_trend_mismatch |
| ETH/USDT:USDT | 24h | 2026-08-03T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 1823.96 to 1914.04 (80% nominal) | no_trade | 1869 | 0.495 | low_expected_edge |
| SOL/USDT:USDT | 24h | 2026-08-03T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 72.1736 to 75.7864 (80% nominal) | no_trade | 73.98 | 0.572 | low_expected_edge |
| GRAM/USDT:USDT | 24h | 2026-08-03T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 1.38475 to 1.44125 (80% nominal) | no_trade | 1.413 | 0.964 | adaptive_trend_mismatch |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
The JSON keeps the old forced up/down estimate under `research_forced_*` for diagnostics; it is not a validated market forecast.
Calibrated probability is profile-level and still not financial advice.
