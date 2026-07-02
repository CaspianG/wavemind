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
4. Done: first positive checked-in real-data profile (`WaveMind 4h profile`)
   that beats the included baselines after costs on OKX BTC/ETH/SOL.
5. Next: validate the 4h profile across more date ranges, exchanges, assets,
   and walk-forward folds.
6. Add richer baselines: buy-and-hold, moving-average crossovers, RSI rules,
   volatility filters, DTW on smaller samples, matrix-profile style analogues,
   and ML classifiers.
7. Add signal construction only after retrieval quality is stable.
8. Publish results separately from the main README to avoid confusing memory
   benchmarks with market-performance claims.
