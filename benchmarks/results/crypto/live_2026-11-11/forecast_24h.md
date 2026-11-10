# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
A point target is published only when the trade-quality policy validates a signal.
`no_trade` is a new-entry gate, not an instruction to close an existing position.
When entry validation returns `no_trade`, the report shows an adaptive conformal price range instead of a false-precision target.

| symbol | horizon | data end UTC | status | validated forecast | target price | calibrated price range | new-entry validation | last close | evidence strength | validation reason |
|---|---:|---|---|---|---:|---|---|---:|---:|---|
| BTC/USDT:USDT | 24h | 2026-11-10T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 71154.9 to 75726.1 (80% nominal) | no_trade | 73440.5 | 0.350 | ta_conflict |
| ETH/USDT:USDT | 24h | 2026-11-10T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 1905.42 to 2181.52 (80% nominal) | no_trade | 2043.47 | 0.350 | ta_conflict |
| SOL/USDT:USDT | 24h | 2026-11-10T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 79.4288 to 86.3712 (80% nominal) | no_trade | 82.9 | 0.661 | ta_conflict |
| GRAM/USDT:USDT | 24h | 2026-11-10T20:00:00+00:00 | uncertain_range_only | uncertain | n/a | 1.04089 to 1.16311 (80% nominal) | no_trade | 1.102 | 0.689 | adaptive_trend_mismatch |

Current-state fingerprint: 32 completed 4h candles. Historical memory: 2000 candles beginning 2025-12-12T12:00:00+00:00.

## Best Available Opportunity Ranking

This section always ranks the supplied markets. `research_candidate` means best available, not independently validated or guaranteed profitable.

| rank | symbol | direction | research move | target | risk boundary | reward / uncertainty | strict status |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | SOL/USDT:USDT | down | -0.68% | 82.3365 | 86.3712 | 0.16 | research_candidate |
| 2 | BTC/USDT:USDT | down | -0.45% | 73110.7 | 75726.1 | 0.14 | research_candidate |
| 3 | ETH/USDT:USDT | down | -0.75% | 2028.07 | 2181.52 | 0.11 | research_candidate |
| 4 | GRAM/USDT:USDT | up | +0.14% | 1.10351 | 1.04089 | 0.02 | research_candidate |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
The JSON keeps the old forced up/down estimate under `research_forced_*` for diagnostics; it is not a validated market forecast.
Calibrated probability is profile-level and still not financial advice.
