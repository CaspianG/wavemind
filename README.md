# WaveMind Crypto Pattern Research

Experimental market-pattern memory built on top of
[WaveMind](https://github.com/CaspianG/wavemind/tree/main).

This branch is separate from the main WaveMind product branch. The goal here is
to test whether WaveMind's dynamic memory layer can help retrieve historical
OHLCV regimes, compare similar market states, and support research-grade
backtesting.

This is not financial advice, not a trading bot, and not a profit claim.

## Relationship To WaveMind

| branch | purpose |
|---|---|
| [`main`](https://github.com/CaspianG/wavemind/tree/main) | Core WaveMind library: dynamic memory, SQLite/Postgres storage, indexes, APIs, integrations, agent-memory benchmarks. |
| `research/crypto-pattern-memory` | Crypto/market research layer: OHLCV pattern memory, historical analogue retrieval, future backtest experiments. |

The crypto branch depends on the core WaveMind engine. It intentionally keeps
market research, trading language, and backtest work out of the main README.

## Current Status

Implemented in this branch:

- `docs/CRYPTO_RESEARCH.md` - research scope, caveats, and roadmap.
- `docs/CRYPTO_MARKET_DIRECTION_2026_2027.md` - market-backed direction for
  building this branch without turning it into a generic trading bot.
- `benchmarks/crypto_pattern_benchmark.py` - deterministic OHLCV-pattern
  retrieval benchmark scaffold.
- `benchmarks/crypto_pattern_results.json` - first checked-in synthetic result.
- `benchmarks/crypto_ohlcv.py` - CSV, CCXT, synthetic OHLCV, feature windows,
  CCXT cache, richer numeric features, future outcome labels, and no-leakage
  pattern text.
- `benchmarks/crypto_walk_forward_benchmark.py` - BTC/ETH/SOL walk-forward
  benchmark with fees, slippage, field-on/field-off ablation,
  calibrated false-positive suppression, market/time-series baselines, optional
  storage controls, and analogue explorer output.
- `benchmarks/crypto_relationship_miner.py` - explainable regime relationship
  miner for finding feature/outcome links in historical OHLCV windows.
- `benchmarks/data/crypto_ohlcv/okx/*.csv` - checked-in real OKX OHLCV fixtures.
- `benchmarks/crypto_walk_forward_okx_real_results.json` - checked-in real
  OKX walk-forward result.
- `benchmarks/crypto_okx_real_analogue_explorer.html` - local visual analogue
  explorer for the real OKX run.
- `benchmarks/crypto_walk_forward_okx_4h_trend_risk_results.json` - expanded
  4h fold benchmark for WaveMind trend-risk vs market baselines.
- `benchmarks/crypto_okx_4h_trend_risk_analogue_explorer.html` - visual
  analogue explorer for the trend-risk run.
- `benchmarks/crypto_walk_forward_okx_4h_adaptive_field_results.json` -
  checked-in BTC/ETH/SOL adaptive-field 4h result with slice robustness.
- `benchmarks/crypto_walk_forward_okx_4h_more_assets_results.json` -
  checked-in XRP/DOGE/ADA/LINK/AVAX adaptive-field 4h cross-asset result.
- `benchmarks/crypto_okx_4h_more_assets_analogue_explorer.html` - visual
  analogue explorer for the additional 5-asset run.
- `benchmarks/crypto_walk_forward_okx_1h_microstructure_results.json` -
  checked-in BTC/ETH/SOL 1h microstructure overlay result.
- `benchmarks/crypto_walk_forward_okx_1h_microstructure_more_assets_results.json`
  - checked-in XRP/DOGE/ADA/LINK/AVAX 1h microstructure cross-asset result.
- `benchmarks/crypto_walk_forward_okx_timeframe_policy_results.json` -
  checked-in BTC/ETH/SOL 1h/4h/1d timeframe-aware policy result.
- `benchmarks/crypto_walk_forward_okx_timeframe_policy_2000_results.json` -
  longer BTC/ETH/SOL 1h/4h 2000-bar robustness check.
- `benchmarks/crypto_walk_forward_okx_timeframe_policy_8asset_results.json` -
  expanded BTC/ETH/SOL/ADA/AVAX/DOGE/LINK/XRP 1h/4h stress check.
- `benchmarks/crypto_walk_forward_okx_timeframe_policy_8asset_2000_results.json`
  - longer 8-asset 1h/4h 2000-bar stress check.
- `benchmarks/crypto_okx_timeframe_policy_analogue_explorer.html` - visual
  analogue explorer for the timeframe-aware policy run.
- `benchmarks/crypto_current_forecast.py` - current-market research forecast
  runner that uses completed candles only and embeds the validation profile.
- `benchmarks/crypto_current_forecast_24h.json` and
  `benchmarks/crypto_current_forecast_24h.md` - checked-in 24h forecast
  snapshot for BTC/ETH/SOL.
- `benchmarks/crypto_current_forecast_7d.json` and
  `benchmarks/crypto_current_forecast_7d.md` - checked-in 7d abstention
  snapshot while 1d policy remains unvalidated.
- `benchmarks/crypto_confidence_calibration.py` - evidence-strength calibration
  diagnostic over walk-forward event metrics.
- `benchmarks/crypto_confidence_calibration_okx_timeframe_policy_results.json`
  and `.md` - checked-in calibration report for the timeframe policy.
- `benchmarks/crypto_confidence_calibration_okx_timeframe_policy_2000_results.json`
  and `.md` - longer 2000-bar calibration diagnostic for the timeframe policy.
- `benchmarks/crypto_confidence_calibration_okx_alt_timeframe_policy_results.json`
  and `.md` - calibration report for the additional XRP/DOGE/ADA/LINK/AVAX
  OKX check.
- `benchmarks/crypto_confidence_calibration_okx_8asset_timeframe_policy_results.json`
  and `.md` - combined 8-asset calibration report.
- `benchmarks/crypto_confidence_calibration_okx_4h_timeframe_policy_results.json`
  and `.md` - 4h-only calibration report for BTC/ETH/SOL.
- `benchmarks/crypto_confidence_calibration_okx_8asset_4h_timeframe_policy_results.json`
  and `.md` - 4h-only calibration report for the combined 8-asset check.
- `benchmarks/crypto_relationships_okx_4h_results.json` - checked-in OKX 4h
  relationship-mining result.
- `benchmarks/crypto_relationships_okx_4h_report.md` - readable relationship
  report with positive, negative, and large-move regimes.
- `benchmarks/crypto_relationship_validation.py` - train/test validator for
  mined relationships.
- `benchmarks/crypto_relationship_validation_okx_4h_results.json` - checked-in
  out-of-sample validation result for OKX 4h relationships.
- `benchmarks/crypto_relationship_validation_okx_4h_report.md` - readable
  validation report.
- `examples/freqtrade_wavemind_strategy.py` - dry-run first Freqtrade scaffold.
- `tests/test_crypto_pattern_benchmark.py` - regression tests for the benchmark.
- `tests/test_crypto_ohlcv.py` - importer/windowing tests.
- `tests/test_crypto_walk_forward_benchmark.py` - walk-forward runner tests.
- `tests/test_crypto_current_forecast.py` - current forecast pipeline tests.
- `tests/test_crypto_confidence_calibration.py` - evidence calibration tests.

The scaffold benchmark is synthetic. The current walk-forward benchmark uses
real cached OKX OHLCV. It now shows a selective timeframe-aware research edge,
but it is still not a deployable trading system.

## How It Works In Plain English

WaveMind Crypto turns market history into a memory of comparable situations:

1. It splits OHLCV candles into rolling windows.
2. Each window becomes a compact market description: trend, RSI bucket,
   volatility, drawdown, MACD-like spread, Bollinger-like position, volume, and
   range compression.
3. Past windows are stored with their known future outcome: what happened after
   that pattern, including return, favorable excursion, adverse excursion, and
   drawdown.
4. For the current market, WaveMind retrieves similar historical windows.
5. The wave-field layer does not magically predict price by itself. It changes
   memory priority: validated regimes can reinforce a signal, conflicting
   relationships can suppress it, and unsupported timeframes abstain instead
   of forcing a prediction.
6. The forecast is the expected return implied by the retrieved analogues after
   the timeframe policy and filters are applied.

In short: it asks, "when the market looked like this before, what usually
happened next, and do the validated memory relationships agree or disagree?"

## What The Current Forecast Means

The `24h` runner is the first supported current-forecast path because it maps
to the validated 4h policy. The `7d` path intentionally abstains until a
separate 1d / weekly policy is validated.

The output field `evidence_strength` is not a probability of being right. It is
an internal agreement score from analogue and regime matching. The checked-in
timeframe policy routes 1h through the microstructure field, 4h through the
adaptive field, blocks unvalidated 1d forecasts, and uses a simple TA conflict
veto plus regime-specific squeeze/falling-knife guards and a live drawdown
circuit breaker. The checked validation profile is the important number:
historical active direction accuracy `0.680`, signal rate `0.023`, profit
factor `14.206`, and positive market slices `13/36` on the BTC/ETH/SOL OKX
run.

The calibration diagnostic is now checked in: it buckets forecasts by evidence
strength, measures realized hit rate and return in each bucket, runs
cross-fold monotonic calibration, runs a conservative active-signal base-rate
calibration, and checks stability across folds, symbols, timeframes, and
symbol/timeframe pairs. The output exposes a probability only when all required
stability checks pass.

Current calibration result for the checked OKX timeframe policy:

| metric | value |
|---|---:|
| signal events | 56 |
| active direction hit rate | 0.679 |
| Brier if evidence is treated as probability | 0.272 |
| raw expected calibration error | 0.216 |
| base-rate probability | 0.679 |
| base-rate expected calibration error | 0.182 |
| fold / symbol / timeframe stable | false / false / false |
| symbol-timeframe stable | false |
| probability ready | false |

The useful finding is not a finished probability model yet. The policy is now
much better at reducing false positives and drawdown than the broad baselines,
but stability still fails across folds, symbols, and symbol/timeframe pairs.
Probability remains disabled until those stability checks pass.

## Quick Run

```sh
pip install -e ".[dev,crypto,bench]"
python benchmarks/crypto_pattern_benchmark.py --engines wavemind static --history 250 --queries 60
```

Real walk-forward run, using checked-in OKX CSV cache:

```sh
python benchmarks/crypto_walk_forward_benchmark.py --dataset ccxt --exchange okx --cache-dir benchmarks/data/crypto_ohlcv --symbols BTC/USDT ETH/USDT SOL/USDT --timeframes 1h 4h 1d --engines timeframe-policy naive ta-rules --bars 720 --train-windows 360 --test-windows 60 --folds 4 --memory-store memory --output benchmarks/crypto_walk_forward_okx_timeframe_policy_results.json
```

Current research forecast snapshot, using live OKX candles:

```sh
python benchmarks/crypto_current_forecast.py --exchange okx --symbols BTC/USDT ETH/USDT SOL/USDT --horizon 24h --bars 720 --output benchmarks/crypto_current_forecast_24h.json --report benchmarks/crypto_current_forecast_24h.md
```

For the crypto branch, Chroma and Qdrant are not the main competitors. They are
optional storage controls. The important comparison is whether the wave-field
layer beats field-off memory and market/time-series baselines.

Current checked-in synthetic result:

| engine | direction@1 | direction@3 | family@1 | avg latency |
|---|---:|---:|---:|---:|
| WaveMind | 1.000 | 1.000 | 1.000 | 6.69 ms |
| Static vector | 1.000 | 1.000 | 1.000 | 0.03 ms |

Interpretation: both systems recover the deterministic synthetic pattern
families. This is a scaffold validation only.

Current checked-in real OKX timeframe-policy result:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | filtered | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind timeframe policy | 2160 | 0.680 | 0.023 | 2.84 | 14.206 | 139.4 | 13/36 | -1.23 | 0.015 | 0.977 | 0.95 ms |

Longer 2000-bar robustness profile on BTC/ETH/SOL, 1h/4h only:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | filtered | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind timeframe policy | 3600 | 0.533 | 0.008 | 0.11 | 1.347 | 571.8 | 5/30 | -2.51 | 0.004 | 0.992 | 2.61 ms |
| Naive last-regime | 3600 | 0.396 | 0.806 | -32.37 | 0.612 | 122011.5 | 6/30 | -147.93 | 0.489 | 0.000 | 0.00 ms |
| TA rules | 3600 | 0.433 | 0.439 | -8.82 | 0.773 | 37024.2 | 8/30 | -41.67 | 0.147 | 0.000 | 0.00 ms |

Expanded 8-asset stress profile on BTC/ETH/SOL/ADA/AVAX/DOGE/LINK/XRP,
1h/4h only:

| profile | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | filtered | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 720 bars | 3840 | 0.616 | 0.033 | 2.69 | 3.301 | 1540.8 | 25/64 | -12.97 | 0.017 | 0.967 | 1.33 ms |
| 2000 bars | 9600 | 0.594 | 0.010 | 0.27 | 1.838 | 571.8 | 19/80 | -2.51 | 0.005 | 0.990 | 1.83 ms |

Interpretation: this is a selective research policy, not a general predictor.
It allows only a small active subset, abstains on unsupported regimes, and has
lower false-positive and drawdown behavior than the broad baselines in these
checked profiles. The newer regime guards materially improve the fresh long
8-asset stress profile (`-0.06` to `0.27` sized bps/query, profit factor
`0.924` to `1.838`, max drawdown `2257.9` to `571.8`). This is still not a
finished trading edge: the unresolved work is higher support, calibration, and
per-symbol/timeframe robustness, not adding more forced forecasts.

Multi-fold 4h robustness check:

| engine | folds | queries | active d1 | signal rate | sized net bps | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static kNN | 3 | 270 | 0.489 | 0.863 | 2.06 | 0.631 | 2.36 ms |
| WaveMind field-off | 3 | 270 | 0.473 | 0.893 | 1.46 | 0.643 | 7.90 ms |
| WaveMind 4h profile | 3 | 270 | 0.356 | 0.374 | -20.39 | 0.381 | 11.33 ms |
| WaveMind field | 3 | 270 | 0.459 | 1.000 | -14.42 | 1.000 | 11.64 ms |
| Naive last-regime | 3 | 270 | 0.345 | 0.848 | -64.94 | 0.643 | 0.00 ms |

Interpretation: this is not a breakout yet. The single-fold 4h profile is
interesting, but it does not survive the first multi-fold robustness check.
The current wave-field scoring hurts this market benchmark; field-off retrieval
is closer to the static vector baseline, while the field-on variant overfires.
The next research target is a better market-specific field dynamic, not a
trading claim.

Expanded BTC/ETH/SOL 4h check, 4 folds x 60 windows:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind adaptive-field | 720 | 0.636 | 0.260 | 37.94 | 2.937 | 5305.3 | 5/12 | -19.75 | 0.167 |
| WaveMind trend-risk | 720 | 0.541 | 0.554 | 25.30 | 1.472 | 9096.9 | 6/12 | -77.66 | 0.365 |
| Trend persistence | 720 | 0.538 | 0.568 | 25.23 | 1.462 | 9318.8 | 6/12 | -77.66 | 0.380 |
| WaveMind risk-overlay | 720 | 0.501 | 0.843 | 17.40 | 1.205 | 9911.2 | 4/12 | -78.82 | 0.651 |
| Naive last-regime | 720 | 0.497 | 0.869 | 15.36 | 1.174 | 11769.1 | 3/12 | -78.82 | 0.688 |
| Static kNN | 720 | 0.470 | 0.833 | -9.75 | 0.898 | 12777.0 | 5/12 | -87.45 | 0.651 |

Additional OKX 4h cross-asset check on XRP/DOGE/ADA/LINK/AVAX:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind adaptive-field | 1200 | 0.640 | 0.287 | 44.75 | 2.962 | 3643.4 | 10/20 | -23.45 | 0.177 |
| Trend persistence | 1200 | 0.500 | 0.587 | 21.41 | 1.321 | 13888.9 | 8/20 | -118.79 | 0.535 |

Interpretation: the strongest current result is `WaveMind adaptive-field`.
It uses the relationship field as a dynamic overlay on top of a trend-aligned
mature-regime candidate, then adds self-feedback from its own matured signals.
It improves average fixed-size net return (`37.94` vs `25.23` bps for trend
persistence), profit factor (`2.937` vs `1.462`), max drawdown (`5305.3` vs
`9318.8` bps), and large false positives (`0.167` vs `0.380`). On the
additional five-asset check it improves net return (`44.75` vs `21.41` bps)
and cuts worst-slice loss from `-118.79` to `-23.45` bps. This is real
signal-shaping evidence, but not a live-trading claim: the next milestone is
raising the positive slice rate across more assets, exchanges, and timeframes.

1h microstructure check, 4 folds x 60 windows:

| dataset | engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC/ETH/SOL | WaveMind microstructure | 720 | 0.574 | 0.244 | 6.98 | 1.514 | 3250.2 | 8/12 | -51.18 | 0.086 |
| BTC/ETH/SOL | TA rules | 720 | 0.525 | 0.410 | 6.41 | 1.285 | 3780.2 | 7/12 | -51.95 | 0.098 |
| XRP/DOGE/ADA/LINK/AVAX | WaveMind microstructure | 1200 | 0.543 | 0.263 | 6.44 | 1.418 | 2740.8 | 12/20 | -25.45 | 0.125 |
| XRP/DOGE/ADA/LINK/AVAX | TA rules | 1200 | 0.490 | 0.410 | 3.11 | 1.121 | 4932.2 | 10/20 | -51.68 | 0.117 |

Interpretation: the 1h layer is now separate from the 4h layer. It starts with
a simple microstructure candidate from TA rules, then uses the WaveMind
relationship field to veto regimes with validated opposition and to require
positive expected edge after fees/slippage. The result is lower signal rate,
higher active direction accuracy, higher profit factor, and lower drawdown
than raw TA on both checked asset groups.

Timeframe-aware BTC/ETH/SOL check after TA conflict veto, local reliability,
mid-confidence suppression, 1h squeeze/falling-knife guards, 4h exhaustion
guards, and a live drawdown circuit breaker,
1h/4h/1d, 4 folds x 60 windows per market:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind timeframe policy | 2160 | 0.680 | 0.023 | 2.84 | 14.206 | 139.4 | 13/36 | -1.23 | 0.015 | 0.95 ms |

Expanded 8-asset stress check:

| profile | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 720 bars | 3840 | 0.616 | 0.033 | 2.69 | 3.301 | 1540.8 | 25/64 | -12.97 | 0.017 | 1.33 ms |
| 2000 bars | 9600 | 0.594 | 0.010 | 0.27 | 1.838 | 571.8 | 19/80 | -2.51 | 0.005 | 1.83 ms |

Interpretation: the policy routes 1h through microstructure, 4h through
adaptive-field, blocks unvalidated 1d forecasts, and vetoes active WaveMind
signals when the TA baseline or local regime evidence is unsafe. It also pauses
a market slice after live policy drawdown breaches the circuit-breaker
threshold. This keeps the signal rate low and reduces large false positives,
but the edge is still selective research evidence, not universal alpha.

## Current Forecast Snapshot

The branch now includes a current-market research forecast runner. It uses the
same `WaveMind timeframe policy` engine as the checked-in walk-forward
benchmark, trains on the latest completed candles, queries the latest completed
window, and writes both JSON and Markdown. The JSON output embeds the
validation profile used to judge whether the engine is credible enough for that
horizon.

The checked-in 24h snapshot uses data through the completed
`2026-07-05T08:00:00+00:00` 4h candle:

| symbol | horizon | decision | signal direction | candidate direction | last close | signal return | candidate return | evidence strength | probability kind | filter |
|---|---:|---|---|---|---:|---:|---:|---:|---|---|
| BTC/USDT | 24h | abstain | flat | flat | 62656.2 | 0.00% | 0.00% | 0.630 | none | flat_candidate |
| ETH/USDT | 24h | abstain | flat | flat | 1760.32 | 0.00% | 0.00% | 0.939 | none | flat_candidate |
| SOL/USDT | 24h | abstain | flat | down | 80.56 | 0.00% | 0.00% | 1.000 | none | adaptive_trend_mismatch |

The checked-in 7d snapshot returns `flat` for BTC/ETH/SOL because the current
policy routes unvalidated `1d` forecasts to abstention:

| symbol | horizon | direction | reason |
|---|---:|---|---|
| BTC/USDT | 7d | flat | unsupported_timeframe:1d |
| ETH/USDT | 7d | flat | unsupported_timeframe:1d |
| SOL/USDT | 7d | flat | unsupported_timeframe:1d |

This is still research output, not financial advice. The current snapshot is
an abstention, not a bullish or bearish call: WaveMind did not find a validated
trade-quality 24h signal.
The weekly path intentionally refuses to forecast until a separate daily/weekly
policy passes walk-forward validation.

## Relationship Mining

WaveMind Crypto now includes an explainable regime miner. It does not claim a
trade by itself; it finds historical feature/outcome relationships that can be
validated in later walk-forward tests.

Checked-in OKX BTC/ETH/SOL 4h relationship result:

| relationship | support | lift bps | avg return bps | large move |
|---|---:|---:|---:|---:|
| `rsi_bucket=neutral & trend=up` | 516 | 61.79 | 51.35 | 0.727 |
| `close_position_bucket=middle & trend=up` | 287 | 71.66 | 61.22 | 0.728 |
| `bollinger_bucket=upper_band & drawdown_bucket=deep` | 257 | -90.69 | -101.13 | 0.739 |
| `macd_bucket=up & rsi_bucket=overbought` | 365 | -75.34 | -85.78 | 0.762 |

This is the direction for making the branch useful beyond a single strategy:
discover relationships, explain them, then test whether they survive
walk-forward evaluation.

Out-of-sample validation now mines relationships on past windows and tests them
on future windows. Current OKX BTC/ETH/SOL 4h validation:

| metric | value |
|---|---:|
| validated relationships | 74 |
| sign preservation rate | 0.622 |
| avg signed test lift | 18.32 bps |
| median signed test lift | 15.29 bps |

Top aggregated validated relationships:

| relationship | expected | occurrences | sign preserved | avg signed test lift |
|---|---|---:|---:|---:|
| `close_position_bucket=near_high & rsi_bucket=overbought` | negative | 3 | 1.000 | 138.81 |
| `macd_bucket=up & rsi_bucket=overbought` | negative | 3 | 1.000 | 133.12 |
| `rsi_bucket=neutral & trend=up` | positive | 2 | 1.000 | 62.31 |
| `bollinger_bucket=middle & rsi_bucket=neutral` | positive | 4 | 0.750 | 29.68 |

Interpretation: this is better than raw in-sample mining, but not enough for a
trading claim. About 62% of mined relationships preserved their sign on future
windows; the rest are unstable and should be filtered out or studied further.

## Research Plan

The product direction is documented here:

[`docs/CRYPTO_MARKET_DIRECTION_2026_2027.md`](docs/CRYPTO_MARKET_DIRECTION_2026_2027.md)

Near-term execution plan:

1. Done: real OHLCV CSV and CCXT import.
2. Done: explicit train/test and walk-forward splits.
3. Done: fees, slippage, and fixed/confidence position sizing.
4. Done: richer OHLCV features and future outcome labels.
5. Done: compare WaveMind field-on against field-off memory, OHLCV shape matching,
   DTW on small samples, naive regimes, and technical-analysis baselines.
6. Done: Freqtrade research adapter before any live-trading integration.
7. Done: initial false-positive suppression with stricter analogue agreement,
   regime filters, and confidence thresholds.
8. Done: real OKX OHLCV validation with checked-in CSV cache.
9. Done: first positive single-fold real-data profile (`WaveMind 4h profile`)
   that beats the included baselines after costs on checked-in OKX data.
10. Done: first multi-fold 4h robustness check. It fails for the current
    profile, so the result is not yet robust.
11. Done: larger 4h check shows WaveMind risk-overlay beats static retrieval
    and naive under fixed-size signals, but confidence sizing is not calibrated.
12. Done: trend-risk profile adds memory opposition to a strong trend baseline;
    it slightly improves average fixed-size return and lowers false positives,
    but is only positive on 6/12 symbol-fold slices.
13. Done: relationship miner finds explainable regime/outcome links on real
    OKX 4h data and writes JSON/Markdown reports.
14. Done: train/test relationship validator shows which mined links survive
    future windows and which fail.
15. Done: adaptive relationship-field overlay uses past train/holdout
    relationship memory as a dynamic veto over trend-aligned candidates; it
    improves average checked-in 4h return, profit factor, drawdown, and false
    positives, adds slice-robustness metrics, and validates on an additional
    5-asset OKX 4h cross-check.
16. Done: timeframe-aware policy routes 1h to microstructure, 4h to
    adaptive-field, and unvalidated 1d to abstention.
17. Done: current forecast runner generates 24h research snapshots from
    completed live candles and embeds the validation profile.
18. Done: evidence-strength calibration diagnostic reports raw buckets,
    cross-fold monotonic calibration, active-signal base-rate calibration, and
    fold/symbol/timeframe stability checks.
19. Done: TA conflict veto, local reliability checks, mid-confidence
    suppression, 1h squeeze/falling-knife guards, 4h exhaustion guards, and a
    live drawdown circuit breaker supersede the earlier strict downside/volume
    filter. The current checked BTC/ETH/SOL OKX run has active direction
    accuracy `0.680`, signal rate `0.023`, profit factor `14.206`, and large
    false positives `0.015`; the longer BTC/ETH/SOL 2000-bar profile remains
    positive but weak at `0.11` sized bps/query and profit factor `1.347`; the
    expanded 8-asset 2000-bar stress profile is `0.27` sized bps/query and
    profit factor `1.838`.
20. Next: increase per-symbol/timeframe support so calibrated probability can
    be enabled without hiding weak slices.
21. Next: build and validate a separate 1d / weekly trend-memory dynamic before
    enabling 7d forecasts.
22. Next: improve upside support without losing the new downside robustness,
    then validate on more date ranges, exchanges, assets, and walk-forward
    folds.
23. Only after robustness holds, test signal construction and backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>

For migration from Chroma to the core memory layer, see
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).
