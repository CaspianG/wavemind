# WaveMind Crypto Current Forecast

Research forecast from completed candles only. Not financial advice.
Evidence strength is analogue/regime agreement, not a calibrated probability.
The market forecast is always up/down with a target price because a future close is never exactly flat.
`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.

| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |
|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|
| HYPE/USDT:USDT | 24h | 2026-07-05T20:00:00+00:00 | up | 1.17% | 72.1703 | no_trade | 71.339 | 0.863 | four_hour_mid_band_near_high_long_exhaustion | flat | up | 71.339 |  | none |
| XRP/USDT:USDT | 24h | 2026-07-05T20:00:00+00:00 | up | 0.07% | 1.15748 | no_trade | 1.1567 | 0.956 | flat_candidate | flat | flat | 1.1567 |  | none |
| ZEC/USDT:USDT | 24h | 2026-07-05T20:00:00+00:00 | up | 0.68% | 465.256 | no_trade | 462.13 | 0.968 | flat_candidate | flat | flat | 462.13 |  | none |
| SOL/USDT:USDT | 24h | 2026-07-05T20:00:00+00:00 | up | 0.56% | 82.0037 | no_trade | 81.55 | 0.995 | flat_candidate | flat | flat | 81.55 |  | none |

Validation profile: historical active direction accuracy 0.586, signal rate 0.018, positive market slices 7/27.

Validation profile is embedded in the JSON output for each row.
Calibrated probability is profile-level and still not financial advice.
