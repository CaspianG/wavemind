# WaveMind Crypto Pattern Research

This branch explores whether WaveMind can be useful for market-pattern memory:
remembering historical OHLCV patterns, retrieving similar regimes, and using the
retrieved evidence for research-grade analysis.

This is not financial advice and not a trading system. The first goal is a
reproducible benchmark layer, not live prediction.

## Scope

WaveMind is not positioned as a replacement for a backtesting engine or exchange
connector. The useful role is narrower:

- convert OHLCV windows into compact pattern descriptions;
- store historical patterns with outcome metadata;
- retrieve similar past regimes for a new market window;
- compare the wave-field layer against field-off, time-series, and market-rule
  baselines;
- later feed retrieved evidence into a proper backtest and risk model.

Chroma and Qdrant are not crypto competitors here. They are storage/retrieval
controls: useful for checking whether a plain vector substrate changes the
retrieval result, but not the benchmark that validates the market hypothesis.
The important comparison is WaveMind field-on vs field-off and against
time-series or trading-research baselines.

## Plain-English Model

The crypto branch treats the market as a memory problem, not as a price oracle.

For every symbol and timeframe it builds rolling OHLCV windows. Each window is
converted into a small description of the current regime: trend, recent trend,
RSI bucket, volatility bucket, drawdown bucket, MACD-like spread, Bollinger-like
position, volume bucket, and range compression. Historical windows are stored
with their future outcome, but the future outcome is not included in the query
text.

When the current market is queried, the system looks for historical windows
that looked similar. The wave-field layer then acts as a policy overlay:

- similar memories propose historical analogues;
- validated regime relationships can reinforce or veto the proposal;
- recently bad mature signals can suppress new signals;
- unsupported trade regimes are marked `no_trade` instead of being promoted to
  a validated signal.

The resulting price target is a research estimate:

```text
latest close * (1 + expected_return_bps / 10000)
```

The system is useful only if the same process survives walk-forward validation.
If a profile does not survive future folds, it should be treated as a failed
hypothesis, even if a single current forecast looks plausible.

## Price Targets

The branch now has a dedicated target-price benchmark:

```sh
python benchmarks/crypto_price_target_benchmark.py \
  --dataset cached \
  --exchange okx \
  --symbols BTC/USDT ETH/USDT SOL/USDT ADA/USDT XRP/USDT DOGE/USDT LINK/USDT AVAX/USDT \
  --timeframes 1h 4h 1d \
  --engines wavemind-market-field-target wavemind-robust-target \
  --bars 2000 \
  --output benchmarks/crypto_price_target_results.json \
  --report benchmarks/crypto_price_target_report.md
```

This benchmark does not ask only "up or down". For every historical query it
computes:

```text
predicted_price = last_close * (1 + predicted_return_bps / 10000)
actual_price    = last_close * (1 + actual_future_return_bps / 10000)
```

Then it reports target-price error across symbols, timeframes, and
walk-forward folds. The benchmark uses only matured historical windows for each
query, so future outcomes are never available to the predictor.

Checked-in OKX stress result: 8 assets, 2000 bars per market, 1h/4h/1d, 4
folds per symbol/timeframe, 8640 target-price predictions per engine.

| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind market-field target | 8640 | 0.562 | 367.4 bps | 553.9 bps | 3.80% | 0.128 | 0.178 | 10.21% |
| WaveMind robust target | 8640 | 0.502 | 373.7 bps | 560.9 bps | 3.88% | 0.128 | 0.267 | 10.32% |

The market-field target is the best aggregate result in this run. It is
deliberately timeframe-aware:

- `1h`: regime reversion, because the short-horizon analogue field is often
  mean-reverting in the checked OKX history.
- `4h`: momentum reversion, which improved aggregate swing direction hit.
- `1d`: historical reversion, which improved the daily aggregate profile.

This is progress, not a production trading claim. Aggregate direction hit
improved from 0.502 to 0.562 and target MAPE improved from 3.88% to 3.80%, but
worst-slice direction hit worsened. The next research target is worst-slice
robustness: raising weak symbol/timeframe/fold slices without losing the
aggregate edge.

Failures are now measured explicitly: worst-slice hit rate, worst-slice MAPE,
per-symbol breakdowns, and a bounded event-level sample are stored in
`benchmarks/crypto_price_target_results.json`. Use `--events-output` when a
full compact JSONL dump of every event-level prediction is needed locally.

## Signal Quality Benchmark

The signal-quality benchmark separates the always-on target-price forecast from
trade-quality research signals:

```sh
python benchmarks/crypto_signal_quality_benchmark.py \
  --dataset cached \
  --exchange okx \
  --symbols BTC/USDT ETH/USDT SOL/USDT ADA/USDT XRP/USDT DOGE/USDT LINK/USDT AVAX/USDT \
  --timeframes 1h 4h 1d \
  --bars 2000
```

Checked-in OKX result:

| tier | selected | coverage | direction hit | MAE return | MAPE |
|---|---:|---:|---:|---:|---:|
| all_forecasts | 8640 | 1.000 | 0.562 | 367.4 bps | 3.80% |
| broad_trade_quality | 4224 | 0.489 | 0.576 | 261.3 bps | 2.64% |
| strong_trade_quality | 3231 | 0.374 | 0.578 | 246.0 bps | 2.46% |
| high_conviction | 2540 | 0.294 | 0.578 | 245.6 bps | 2.45% |
| consensus_edge | 328 | 0.038 | 0.738 | 228.9 bps | 2.25% |
| strict_consensus_edge | 216 | 0.025 | 0.750 | 213.1 bps | 2.11% |

The consensus edge is the strongest current result: all policy components agree
inside a calm-volatility regime, producing 75% historical direction hit on 216
walk-forward events. Coverage is low, so this is a research signal-quality
breakthrough, not a standalone trading system. The next task is to expand
coverage while preserving hit-rate and improving worst-slice behavior.

## Perpetual Futures Stress Check

OKX USDT perpetuals are validated separately from the spot-style OKX benchmark.
The initial spot market-field policy failed on HYPE/XRP/ZEC/SOL perps, so the
perp field now uses a conservative robust anchor and only switches components
when a fold-local candidate clears a strict improvement guard on matured
pre-test history.

Runner:

```sh
python benchmarks/crypto_price_target_benchmark.py \
  --dataset cached \
  --exchange okx \
  --symbols HYPE/USDT:USDT XRP/USDT:USDT ZEC/USDT:USDT SOL/USDT:USDT \
  --timeframes 1h 4h \
  --engines wavemind-perp-field-target wavemind-market-field-target wavemind-robust-target momentum regime-mean historical-mean naive-last \
  --bars 1200
```

Checked-in result:

| engine | queries | direction hit | MAE return | MAPE | worst slice hit |
|---|---:|---:|---:|---:|---:|
| WaveMind perp field target | 2880 | 0.591 | 392.4 bps | 4.05% | 0.411 |
| WaveMind market-field target | 2880 | 0.436 | 466.6 bps | 4.78% | 0.000 |
| WaveMind robust target | 2880 | 0.591 | 392.4 bps | 4.05% | 0.411 |
| Momentum baseline | 2880 | 0.564 | 409.2 bps | 4.21% | 0.267 |
| Historical mean baseline | 2880 | 0.511 | 406.9 bps | 4.21% | 0.078 |
| Naive last-outcome baseline | 2880 | 0.570 | 522.0 bps | 5.31% | 0.300 |

Signal-quality result:

| tier | selected | coverage | direction hit | MAE return | MAPE |
|---|---:|---:|---:|---:|---:|
| all_forecasts | 2880 | 1.000 | 0.591 | 392.4 bps | 4.05% |
| large_move_directional_edge | 39 | 0.014 | 0.872 | 771.2 bps | 10.53% |

Interpretation: the 87.2% result is a real but narrow large-move directional
edge. It does not mean the system has a universal 80-90% target-price forecast.
The 7d perpetual check remains weak: 240 daily walk-forward predictions,
direction hit `0.533`, MAPE `8.45%`.

## Confidence And Calibration

The current forecast runner reports `evidence_strength`, not true confidence.
This is deliberate. The old word "confidence" was too easy to misread as
"probability that the forecast is correct".

Current `evidence_strength` means:

- analogue agreement: do retrieved historical windows point in the same
  direction?
- regime agreement: do current features match regimes that previously worked?
- filter result: did the timeframe policy allow the signal or return `flat`?

It does not mean:

- probability of profit;
- probability that price reaches the target;
- calibrated win rate for this specific coin tomorrow.

The current 24h policy is promising but not production-grade. Its checked
BTC/ETH/SOL 720-bar validation profile has active direction accuracy `0.586`,
signal rate `0.018`, profit factor `1.557`, max drawdown `744.5` bps, and
positive market slices `7/27`. A longer BTC/ETH/SOL 2000-bar robustness profile
is low-frequency but more risk-controlled after fees/slippage (`0.09` sized net
bps, profit factor `3.915`, max drawdown `68.6` bps), while the expanded
8-asset 2000-bar stress profile is stronger (`0.65` sized net bps, active
direction accuracy `0.750`, profit factor `6.919`, max drawdown `288.7` bps).
The policy is very selective and still not enough to claim a reliable live
forecast or calibrated probability.

Required next step:

1. Bucket historical predictions by evidence strength.
2. Measure realized direction hit rate, net return, drawdown, and false
   positives per bucket.
3. Report calibration metrics such as Brier score and expected calibration
   error.
4. Expose a real probability only for buckets that remain stable across
   symbols, folds, date ranges, and exchanges.

Current checked OKX calibration result for the timeframe policy:

| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |
|---|---:|---:|---:|---:|---:|
| 0.4-0.6 | 8 | 0.536 | 0.625 | 0.089 | 116.99 |
| 0.8-1.0 | 21 | 1.000 | 0.571 | 0.429 | 2.14 |

Summary: signal events `29`, active hit rate `0.586`, Brier score if raw
evidence is treated as probability `0.375`, raw expected calibration error
`0.335`, base-rate probability `0.586`, and base-rate expected calibration
error `0.208`. Probability remains disabled because fold, symbol, timeframe,
and symbol/timeframe stability checks are still false. The score is useful as
a research signal, but the current forecast output still reports
`probability_kind=none` unless all stability checks pass.

## First Benchmark

Runner:

```sh
python benchmarks/crypto_pattern_benchmark.py --engines wavemind static --history 250 --queries 60
```

What it measures:

- `direction_accuracy_at_1` - top match has the same next-move direction;
- `direction_accuracy_at_3` - any of top 3 matches has the same direction;
- `family_accuracy_at_1` - top match belongs to the same pattern family;
- `mean_abs_return_error_bps` - absolute error between expected and retrieved
  future return, in basis points;
- query latency.

The default dataset is deterministic synthetic OHLCV. It is intentionally not a
profit claim. It exists so every future change to the market-memory layer can be
tested before any real-data backtest is added.

Current synthetic result is checked in at
`benchmarks/crypto_pattern_results.json`. The first run is intentionally easy:
both WaveMind and the static vector baseline recover the deterministic pattern
families. Treat that as a scaffold validation, not evidence of market edge.

## OHLCV Walk-Forward Benchmark

Runner:

```sh
python benchmarks/crypto_walk_forward_benchmark.py \
  --dataset ccxt \
  --exchange okx \
  --cache-dir benchmarks/data/crypto_ohlcv \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 1h 4h 1d \
  --engines market storage-controls \
  --bars 720 \
  --train-windows 420 \
  --test-windows 120 \
  --position-sizing confidence \
  --confidence-threshold 0.65 \
  --min-analogue-agreement 0.6 \
  --min-expected-edge-bps 30
```

What it adds over the first scaffold:

- real OHLCV window representation;
- explicit numeric pattern features: return, volatility, drawdown, trend slope,
  MACD-like spread, Bollinger-like position, volume, and range compression;
- future outcome labels: return, MFE, MAE, future realized volatility, and
  future max drawdown;
- train/test walk-forward evaluation;
- explicit fees and slippage;
- fixed or confidence-weighted position sizing;
- calibrated false-positive suppression with analogue agreement, regime
  filters, and confidence thresholds;
- no look-ahead insertion: a window is added to memory only after its future
  horizon is already known;
- core ablation: WaveMind field-on vs WaveMind field-off;
- market/time-series baselines: OHLCV shape kNN, naive last-regime, and simple
  TA rules;
- storage controls: static vector kNN, Chroma, and Qdrant;
- an analogue explorer HTML report.

Outputs:

- `benchmarks/crypto_walk_forward_results.json`
- `benchmarks/crypto_analogue_explorer.html`
- `benchmarks/crypto_walk_forward_okx_real_results.json`
- `benchmarks/crypto_okx_real_analogue_explorer.html`
- `benchmarks/data/crypto_ohlcv/okx/*.csv`

Current real-data walk-forward result, generated on cached OKX BTC/USDT,
ETH/USDT, and SOL/USDT across 1h, 4h, and 1d with 1,080 test windows,
`--confidence-threshold 0.65`, `--min-analogue-agreement 0.6`, and
`--min-expected-edge-bps 30`:

| engine | direction@1 | active d1 | signal rate | avg net bps | sized net bps | large FP | filtered | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind 4h profile | 0.179 | 0.523 | 0.119 | 7.48 | 5.57 | 0.142 | 0.881 | 3.72 ms |
| WaveMind field | 0.428 | 0.428 | 1.000 | -41.93 | -33.04 | 0.990 | 0.000 | 9.65 ms |
| WaveMind calibrated | 0.273 | 0.442 | 0.421 | -21.30 | -17.66 | 0.373 | 0.579 | 9.79 ms |
| WaveMind field-off | 0.404 | 0.440 | 0.869 | -21.81 | -18.69 | 0.593 | 0.000 | 6.95 ms |
| OHLCV shape kNN | 0.392 | 0.419 | 0.873 | -23.86 | -19.47 | 0.590 | 0.000 | 0.20 ms |
| Naive last-regime | 0.426 | 0.467 | 0.854 | 2.10 | 1.84 | 0.566 | 0.000 | 0.00 ms |
| TA rules | 0.317 | 0.495 | 0.481 | -25.20 | -23.52 | 0.176 | 0.000 | 0.00 ms |
| Static kNN | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 2.29 ms |
| Chroma | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 4.23 ms |
| Qdrant | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 3.80 ms |

Interpretation: this is the first positive real-data profile in the branch.
`WaveMind 4h profile` beats all included baselines on this checked-in OKX
walk-forward run after fees and slippage (`5.57` sized net bps vs `1.84` for
naive last-regime and negative static kNN/Chroma/Qdrant). It is deliberately
selective: it only acts on 4h windows, returns flat on 1h/1d, and filters
`88.1%` of all test windows. Raw WaveMind field still over-triggers and loses
after costs, so this is evidence for a promising 4h regime-memory profile, not
a general live-trading claim.

Current multi-fold 4h robustness result:

| engine | folds | queries | active d1 | signal rate | sized net bps | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static kNN | 3 | 270 | 0.489 | 0.863 | 2.06 | 0.631 | 2.36 ms |
| WaveMind field-off | 3 | 270 | 0.473 | 0.893 | 1.46 | 0.643 | 7.90 ms |
| WaveMind 4h profile | 3 | 270 | 0.356 | 0.374 | -20.39 | 0.381 | 11.33 ms |
| WaveMind field | 3 | 270 | 0.459 | 1.000 | -14.42 | 1.000 | 11.64 ms |
| Naive last-regime | 3 | 270 | 0.345 | 0.848 | -64.94 | 0.643 | 0.00 ms |

Interpretation: this is not robust yet. The field-off retrieval ablation is
near the static vector baseline, but the current wave-field market scorer hurts
this benchmark and the selective 4h profile fails the first multi-fold check.
The useful next step is redesigning the market field dynamic and validating it
across more folds, not promoting this as a trading edge.

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

Interpretation: `WaveMind adaptive-field` is now the strongest profile in the
checked-in 4h run. It uses the relationship field as a dynamic overlay: the
last mature regime proposes a trend-aligned candidate, the field vetoes only
strong opposite train/holdout relationships, and self-feedback pauses the
profile when its own recently matured signals turn negative. This improves
fixed-size net return (`37.94` vs `25.23` bps for trend persistence), profit
factor (`2.937` vs `1.462`), max drawdown (`5305.3` vs `9318.8` bps), active
direction accuracy (`0.636` vs `0.538`), and large false positives (`0.167` vs
`0.380`). On the additional five-asset check it improves net return (`44.75`
vs `21.41` bps) and cuts worst-slice loss from `-118.79` to `-23.45` bps. It
is still not a live-trading claim: the next milestone is raising the positive
slice rate across more assets, exchanges, and timeframes.

1h microstructure check, 4 folds x 60 windows:

| dataset | engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC/ETH/SOL | WaveMind microstructure | 720 | 0.574 | 0.244 | 6.98 | 1.514 | 3250.2 | 8/12 | -51.18 | 0.086 |
| BTC/ETH/SOL | TA rules | 720 | 0.525 | 0.410 | 6.41 | 1.285 | 3780.2 | 7/12 | -51.95 | 0.098 |
| XRP/DOGE/ADA/LINK/AVAX | WaveMind microstructure | 1200 | 0.543 | 0.263 | 6.44 | 1.418 | 2740.8 | 12/20 | -25.45 | 0.125 |
| XRP/DOGE/ADA/LINK/AVAX | TA rules | 1200 | 0.490 | 0.410 | 3.11 | 1.121 | 4932.2 | 10/20 | -51.68 | 0.117 |

Interpretation: the 1h policy is not the 4h adaptive-field profile reused at a
smaller candle size. It is a separate microstructure overlay: TA rules propose
short-horizon candidates, then the WaveMind relationship field vetoes validated
opposition and requires positive expected edge after fees/slippage. On the
checked BTC/ETH/SOL run it improves profit factor (`1.514` vs `1.285`) and
drawdown (`3250.2` vs `3780.2`) versus raw TA. On the additional five-asset
check it keeps the improvement (`6.44` vs `3.11` bps) and cuts worst-slice loss
from `-51.68` to `-25.45` bps.

Timeframe-aware BTC/ETH/SOL check after TA conflict veto, local regime
reliability, event-level 1h falling-knife guards, 1h late-breakout guards, 4h
exhaustion guards, and a live drawdown circuit breaker:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind timeframe policy | 1620 | 0.586 | 0.018 | 0.61 | 1.557 | 744.5 | 7/27 | -9.60 | 0.009 | 0.41 ms |

Longer BTC/ETH/SOL 2000-bar robustness check, 1h/4h:

| engine | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| WaveMind timeframe policy | 2880 | 0.600 | 0.003 | 0.09 | 3.915 | 68.6 | 2/24 | -0.38 | 0.002 | 1.28 ms |
| Trend persistence | 2880 | 0.391 | 0.497 | -22.23 | 0.587 | 68792.6 | 5/24 | -109.18 | 0.316 | 0.00 ms |
| TA rules | 2880 | 0.440 | 0.451 | -6.49 | 0.835 | 26776.9 | 9/24 | -51.10 | 0.169 | 0.00 ms |

Expanded 8-asset stress check on BTC/ETH/SOL/ADA/AVAX/DOGE/LINK/XRP, 1h/4h:

| profile | queries | active d1 | signal rate | sized net bps | profit factor | max DD bps | +slices | worst slice | large FP | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 720 bars | 2880 | 0.590 | 0.036 | 1.82 | 1.781 | 1021.2 | 20/48 | -13.39 | 0.014 | 0.76 ms |
| 2000 bars | 7680 | 0.750 | 0.007 | 0.65 | 6.919 | 288.7 | 17/64 | -2.41 | 0.002 | 1.21 ms |

Interpretation: timeframe-aware policy is now a conservative research filter.
The current policy routes 1h through microstructure, 4h through adaptive-field,
blocks unvalidated 1d forecasts, vetoes WaveMind signals when the TA baseline
points in the opposite direction, suppresses regimes that historically behaved
like short squeezes, falling knives, late-breakout exhaustion, or 4h exhaustion
traps, and pauses a market slice after live policy drawdown exceeds the
circuit-breaker threshold.
This is intentionally
conservative: the system uses a timeframe only after that timeframe has its own
validated policy and returns `no_trade` otherwise. The longer 2000-bar checks are now
positive after fees/slippage with much lower drawdown than the broad baselines,
but the signal rate is tiny; the next research steps are higher support,
per-symbol/timeframe robustness, calibrated probability, and a separate 1d
trend-memory dynamic.

## Current Forecast Runner

Runner:

```sh
python benchmarks/crypto_current_forecast.py \
  --exchange okx \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --horizon 24h \
  --bars 720 \
  --output benchmarks/crypto_current_forecast_24h.json \
  --report benchmarks/crypto_current_forecast_24h.md
```

What it does:

- fetches recent OHLCV with CCXT pagination;
- discards incomplete candles;
- trains the same `WaveMind timeframe policy` engine used in the walk-forward
  benchmark;
- queries the latest completed market window;
- writes a forced up/down market forecast, the safety-layer trade decision,
  current price, expected return, expected price, evidence strength, filter
  reason, and the validation profile into JSON/Markdown.

The forecast has two layers:

- `market forecast` is always `up` or `down` with a target price because a
  future close is never exactly flat;
- `trade validation` is the safety layer and may remain `no_trade` when the
  policy does not find a validated trade-quality signal.

Checked-in OKX 24h snapshot generated from completed 4h candles through
`2026-07-05T08:00:00+00:00`:

| symbol | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason |
|---|---|---|---:|---:|---|---:|---:|---|
| BTC/USDT | 2026-07-05T08:00:00+00:00 | up | 0.20% | 62781.1 | no_trade | 62656.2 | 0.630 | flat_candidate |
| ETH/USDT | 2026-07-05T08:00:00+00:00 | down | -0.53% | 1751 | no_trade | 1760.32 | 0.939 | flat_candidate |
| SOL/USDT | 2026-07-05T08:00:00+00:00 | up | 1.19% | 81.5183 | no_trade | 80.56 | 1.000 | adaptive_trend_mismatch |

The 24h snapshot has a forced directional estimate, but it is still an
`no_trade` result at the trade-signal layer. The current market did not produce a
validated trade-quality signal.

The 7d runner currently produces forced directional estimates but returns
`no_trade` on BTC/ETH/SOL with `unsupported_timeframe:1d`. That is intentional.
The policy refuses to produce trade-quality daily/weekly signals until a
separate 1d profile passes walk-forward validation.

The metrics are retrieval/research metrics, not a live trading claim:

- `direction_accuracy_at_1` - top analogue predicts the same next-move bucket;
- `direction_accuracy_at_3` - any of top 3 analogues predicts the same bucket;
- `active_direction_accuracy` - direction accuracy only on non-flat predicted
  signals;
- `signal_rate` - share of windows where the engine produced a non-flat signal;
- `avg_net_return_bps` - a simple long/short/flat research payoff after
  round-trip fee and slippage;
- `avg_sized_net_return_bps` - the same payoff after the selected position
  sizing mode;
- `hit_rate_after_costs` - share of windows with positive net payoff;
- `mean_abs_mfe_error_bps` and `mean_abs_mae_error_bps` - error on retrieved
  future path excursions;
- `large_move_precision` and `large_move_false_positive_rate` - whether the
  analogue layer detects large moves without over-triggering;
- `filtered_rate` - share of windows where calibrated decision logic returned
  `flat` because evidence was too weak;
- `avg_confidence` - average confidence after analogue agreement and regime
  filtering;
- query latency.

## Relationship Mining

The branch now has a separate explainable pattern-discovery layer:

```sh
python benchmarks/crypto_relationship_miner.py \
  --dataset ccxt \
  --exchange okx \
  --cache-dir benchmarks/data/crypto_ohlcv \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 4h \
  --min-support 30 \
  --output benchmarks/crypto_relationships_okx_4h_results.json \
  --report benchmarks/crypto_relationships_okx_4h_report.md
```

It mines single-feature and pairwise relationships over historical OHLCV
windows, then reports support, lift vs global average, future return, direction
rates, and large-move rate. This is not a signal by itself; it is a way to make
the memory layer inspectable before turning any pattern into a walk-forward
strategy.

Current OKX BTC/ETH/SOL 4h examples:

| relationship | support | lift bps | avg return bps | large move |
|---|---:|---:|---:|---:|
| `rsi_bucket=neutral & trend=up` | 516 | 61.79 | 51.35 | 0.727 |
| `close_position_bucket=middle & trend=up` | 287 | 71.66 | 61.22 | 0.728 |
| `bollinger_bucket=upper_band & drawdown_bucket=deep` | 257 | -90.69 | -101.13 | 0.739 |
| `macd_bucket=up & rsi_bucket=overbought` | 365 | -75.34 | -85.78 | 0.762 |

### Relationship Validation

The validation runner mines relationships on train windows and checks whether
the same relationships preserve direction on future test windows:

```sh
python benchmarks/crypto_relationship_validation.py \
  --dataset ccxt \
  --exchange okx \
  --cache-dir benchmarks/data/crypto_ohlcv \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 4h \
  --train-windows 420 \
  --test-windows 60 \
  --folds 4 \
  --min-support 30 \
  --min-test-support 10 \
  --output benchmarks/crypto_relationship_validation_okx_4h_results.json \
  --report benchmarks/crypto_relationship_validation_okx_4h_report.md
```

Current OKX 4h validation:

| metric | value |
|---|---:|
| validated relationships | 74 |
| sign preservation rate | 0.622 |
| avg signed test lift | 18.32 bps |
| median signed test lift | 15.29 bps |

Top aggregated out-of-sample relationships:

| relationship | expected | occurrences | sign preserved | avg signed test lift |
|---|---|---:|---:|---:|
| `close_position_bucket=near_high & rsi_bucket=overbought` | negative | 3 | 1.000 | 138.81 |
| `macd_bucket=up & rsi_bucket=overbought` | negative | 3 | 1.000 | 133.12 |
| `rsi_bucket=neutral & trend=up` | positive | 2 | 1.000 | 62.31 |
| `bollinger_bucket=middle & rsi_bucket=neutral` | positive | 4 | 0.750 | 29.68 |

Interpretation: the relationship layer is useful for hypothesis discovery and
some links survive future windows, but it still needs robustness filtering.
The result is research evidence, not a deployable trading system.

### CSV import

CSV input expects these columns, case-insensitive:

```text
timestamp, open, high, low, close, volume
```

Example:

```sh
python benchmarks/crypto_walk_forward_benchmark.py \
  --dataset csv \
  --csv data/btc_1h.csv \
  --symbols BTC \
  --timeframes 1h \
  --engines market
```

`timestamp` can be ISO-8601, Unix seconds, or Unix milliseconds.

### CCXT import

Install the optional crypto extra first:

```sh
pip install -e ".[crypto]"
```

Example:

```sh
python benchmarks/crypto_walk_forward_benchmark.py \
  --dataset ccxt \
  --exchange okx \
  --cache-dir benchmarks/data/crypto_ohlcv \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 1h 4h 1d \
  --bars 500
```

The CCXT path is for reproducible research pulls, not for live execution. With
`--cache-dir`, the first run saves CSV fixtures and later runs reuse them unless
`--refresh-cache` is passed.

## Freqtrade Adapter Scaffold

Example:

```sh
python -m py_compile examples/freqtrade_wavemind_strategy.py
```

File:

```text
examples/freqtrade_wavemind_strategy.py
```

It exposes `WaveMindRegimeMemory` and `WaveMindDryRunStrategy`. The adapter is
deliberately dry-run/backtest first: WaveMind provides similar-regime features,
and Freqtrade remains responsible for risk, execution, and backtesting.

## Roadmap

1. Done: add real exchange CSV fixtures with reproducible train/test splits.
2. Done: add walk-forward runs on BTC/USDT, ETH/USDT, and SOL/USDT for 1h, 4h,
   and 1d from public OKX OHLCV.
3. Done: initial false-positive suppression with calibrated confidence, regime
   filters, and stricter analogue agreement.
4. Done: first positive single-fold checked-in real-data profile
   (`WaveMind 4h profile`) that beats the included baselines after costs on OKX
   BTC/ETH/SOL.
5. Done: first multi-fold 4h robustness check. It fails for the current
   profile, so this is not yet robust.
6. Done: larger 4h fixed-size check shows WaveMind risk-overlay beats static
   retrieval and naive last-regime, but the confidence-sized path is still not
   calibrated.
7. Done: trend-risk profile adds memory opposition to a strong trend baseline;
   it slightly improves average fixed-size return and lowers false positives,
   but remains positive on only 6/12 symbol-fold slices.
8. Done: relationship miner finds explainable regime/outcome links on real OKX
   4h data and writes JSON/Markdown reports.
9. Done: train/test relationship validator checks which mined links survive
   future windows.
10. Done: adaptive relationship-field overlay uses past train/holdout
    relationship memory as a dynamic veto; it improves the checked-in average
    4h result, profit factor, drawdown, false positives, and worst-slice loss;
    the benchmark now reports slice-robustness metrics and includes an
    additional 5-asset OKX 4h cross-check.
11. Done: timeframe-aware policy routes 1h to microstructure, 4h to
    adaptive-field, and unvalidated 1d to `no_trade`.
12. Done: current forecast runner generates 24h research snapshots from
    completed live candles and embeds the validation profile.
13. Done: evidence-strength calibration diagnostic reports raw buckets,
    cross-fold monotonic calibration, active-signal base-rate calibration, and
    fold/symbol/timeframe stability checks.
14. Done: TA conflict veto, local reliability checks, event-level diagnostic
    output, 1h squeeze/falling-knife/late-breakout guards, 4h exhaustion
    guards, and a live drawdown circuit breaker supersede the earlier strict
    downside/volume filter. The current checked BTC/ETH/SOL OKX 720-bar run has
    active direction accuracy `0.586`, signal rate `0.018`, profit factor
    `1.557`, and large false positives `0.009`; the longer BTC/ETH/SOL
    2000-bar profile is low-frequency but risk-controlled at `0.09` sized
    bps/query, profit factor `3.915`, and max drawdown `68.6`; the expanded
    8-asset 2000-bar stress profile is `0.65` sized bps/query, active
    direction accuracy `0.750`, profit factor `6.919`, and max drawdown
    `288.7`.
15. Done: market-field target benchmark on 8 OKX assets, 2000 bars, 1h/4h/1d.
    It improves aggregate target direction from `0.502` to `0.562` and MAPE
    from `3.88%` to `3.80%`, but worsens worst-slice hit rate.
16. Done: signal-quality benchmark separates always-on target forecasts from
    trade-quality research tiers. The strict calm-consensus tier reaches
    `0.750` direction hit on 216 walk-forward events at `0.025` coverage.
17. Next: expand consensus-edge coverage without dropping below 0.70 direction
    hit, and fix the weak symbol/timeframe/fold slices.
18. Next: validate the market-field target on more exchanges, date ranges,
    assets, and walk-forward folds before any live-trading claim.
19. Add richer baselines: buy-and-hold, moving-average crossovers, RSI rules,
    volatility filters, DTW on smaller samples, matrix-profile style analogues,
    and ML classifiers.
20. Add signal construction only after retrieval quality is stable.
21. Publish results separately from the main README to avoid confusing memory
    benchmarks with market-performance claims.
