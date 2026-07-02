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
  --dataset synthetic \
  --symbols BTC ETH SOL \
  --timeframes 1h 4h 1d \
  --engines market storage-controls \
  --position-sizing confidence \
  --confidence-threshold 0.65 \
  --min-analogue-agreement 0.6
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

Current synthetic walk-forward result, generated on BTC/ETH/SOL across 1h, 4h,
and 1d with 540 test windows, `--confidence-threshold 0.65`, and
`--min-analogue-agreement 0.6`:

| engine | direction@1 | direction@3 | avg net bps | sized net bps | large FP | filtered | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| WaveMind field | 0.522 | 0.670 | -4.82 | -1.44 | 0.987 | 0.000 | 9.09 ms |
| WaveMind calibrated | 0.426 | 0.670 | 7.96 | 7.39 | 0.545 | 0.433 | 9.58 ms |
| WaveMind field-off | 0.472 | 0.743 | -1.32 | 1.45 | 0.584 | 0.000 | 6.36 ms |
| OHLCV shape kNN | 0.302 | 0.689 | -32.74 | -22.53 | 0.524 | 0.000 | 0.19 ms |
| Naive last-regime | 0.589 | 0.589 | 27.37 | 26.89 | 0.489 | 0.000 | 0.00 ms |
| TA rules | 0.191 | 0.191 | -64.06 | -56.38 | 0.082 | 0.000 | 0.00 ms |
| Static kNN | 0.481 | 0.741 | -2.13 | 0.81 | 0.606 | 0.000 | 2.59 ms |
| Chroma | 0.481 | 0.741 | -2.13 | 0.81 | 0.606 | 0.000 | 4.76 ms |
| Qdrant | 0.481 | 0.741 | -2.13 | 0.81 | 0.606 | 0.000 | 3.73 ms |

Interpretation: the relevant signal is the ablation and calibration tradeoff.
The raw wave-field version beats the field-off version on top-1 direction
retrieval (`0.522` vs `0.472`), which means the dynamic memory layer is adding
measurable retrieval information in this synthetic walk-forward setup. It also
over-triggers large moves. The calibrated variant intentionally returns `flat`
when analogue agreement, regime agreement, or confidence is weak. That reduces
large-move false positives from `0.987` to `0.545` and moves sized net bps from
`-1.44` to `7.39`, but final direction@1 drops to `0.426` because 43.3% of
queries are filtered. It still does not beat the naive last-regime baseline on
net payoff, so this remains a research harness, not evidence of a deployable
market edge.

The metrics are retrieval/research metrics, not a live trading claim:

- `direction_accuracy_at_1` - top analogue predicts the same next-move bucket;
- `direction_accuracy_at_3` - any of top 3 analogues predicts the same bucket;
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
  --exchange binance \
  --symbols BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 1h 4h 1d \
  --bars 500
```

The CCXT path is for reproducible research pulls, not for live execution.

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

1. Add real exchange CSV fixtures with reproducible train/test splits.
2. Add walk-forward runs on BTC/ETH/SOL for 1h, 4h, and 1d from public OHLCV.
3. Done: initial false-positive suppression with calibrated confidence, regime
   filters, and stricter analogue agreement.
4. Validate calibration on real OHLCV data and tune thresholds by
   market/timeframe.
5. Add richer baselines: buy-and-hold, moving-average crossovers, RSI rules,
   volatility filters, DTW on smaller samples, matrix-profile style analogues,
   and ML classifiers.
6. Add signal construction only after retrieval quality is stable.
7. Publish results separately from the main README to avoid confusing memory
   benchmarks with market-performance claims.
