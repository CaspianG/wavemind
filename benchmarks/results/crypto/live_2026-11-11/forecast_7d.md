# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
A point target is published only when the trade-quality policy validates a signal.
`no_trade` is a new-entry gate, not an instruction to close an existing position.
When entry validation returns `no_trade`, the report shows an adaptive conformal price range instead of a false-precision target.

| symbol | horizon | data end UTC | status | validated forecast | target price | calibrated price range | new-entry validation | last close | evidence strength | validation reason |
|---|---:|---|---|---|---:|---|---|---:|---:|---|
| BTC/USDT:USDT | 7d | 2026-11-10T00:00:00+00:00 | uncertain_range_only | uncertain | n/a | 71685 to 78955 (80% nominal) | no_trade | 75320 | 0.000 | unsupported_timeframe:1d |
| ETH/USDT:USDT | 7d | 2026-11-10T00:00:00+00:00 | uncertain_range_only | uncertain | n/a | 1956.85 to 2311.03 (80% nominal) | no_trade | 2133.94 | 0.000 | unsupported_timeframe:1d |
| SOL/USDT:USDT | 7d | 2026-11-10T00:00:00+00:00 | uncertain_range_only | uncertain | n/a | 76.9737 to 96.3663 (80% nominal) | no_trade | 86.67 | 0.000 | unsupported_timeframe:1d |
| GRAM/USDT:USDT | 7d | 2026-11-10T00:00:00+00:00 | uncertain_range_only | uncertain | n/a | 0.905656 to 1.16634 (80% nominal) | no_trade | 1.036 | 0.000 | unsupported_timeframe:1d |

Current-state fingerprint: 32 completed 1d candles. Historical memory: 800 candles beginning 2024-09-01T00:00:00+00:00.

## Best Available Opportunity Ranking

This section always ranks the supplied markets. `research_candidate` means best available, not independently validated or guaranteed profitable.

| rank | symbol | direction | research move | target | risk boundary | reward / uncertainty | strict status |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | SOL/USDT:USDT | down | -3.93% | 83.2662 | 96.3663 | 0.35 | research_candidate |
| 2 | ETH/USDT:USDT | down | -1.78% | 2095.91 | 2311.03 | 0.21 | research_candidate |
| 3 | BTC/USDT:USDT | down | -0.65% | 74828.2 | 78955 | 0.14 | research_candidate |
| 4 | GRAM/USDT:USDT | down | -0.85% | 1.02716 | 1.16634 | 0.07 | research_candidate |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
The JSON keeps the old forced up/down estimate under `research_forced_*` for diagnostics; it is not a validated market forecast.
Calibrated probability is profile-level and still not financial advice.
