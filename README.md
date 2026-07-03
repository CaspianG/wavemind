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

The scaffold benchmark is synthetic. The current walk-forward benchmark uses
real cached OKX OHLCV. It does not show a deployable market edge yet.

## Quick Run

```sh
pip install -e ".[dev,crypto,bench]"
python benchmarks/crypto_pattern_benchmark.py --engines wavemind static --history 250 --queries 60
```

Real walk-forward run, using checked-in OKX CSV cache:

```sh
python benchmarks/crypto_walk_forward_benchmark.py --dataset ccxt --exchange okx --cache-dir benchmarks/data/crypto_ohlcv --symbols BTC/USDT ETH/USDT SOL/USDT --timeframes 1h 4h 1d --engines market storage-controls --bars 720 --train-windows 420 --test-windows 120 --position-sizing confidence --confidence-threshold 0.65 --min-analogue-agreement 0.6 --min-expected-edge-bps 30
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

Current checked-in real OKX walk-forward result:

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

Interpretation: the first positive real-data profile is now checked in.
`WaveMind 4h profile` beats every included baseline on this OKX walk-forward
run after fees and slippage (`5.57` sized net bps vs `1.84` for naive
last-regime and negative static kNN/Chroma/Qdrant). The caveat is important:
this is a selective 4h profile, not a universal predictor. It stays flat on
1h/1d, filters `88.1%` of all windows, and only acts when the wave-memory
evidence agrees with the current 4h regime. Raw WaveMind field still
over-triggers and loses heavily after costs, so the research direction is
profile discovery, stronger regime modeling, and out-of-sample robustness.

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

Expanded 4h check, 4 folds x 60 windows:

| engine | queries | active d1 | signal rate | sized net bps | large FP |
|---|---:|---:|---:|---:|---:|
| WaveMind trend-risk | 720 | 0.541 | 0.554 | 25.30 | 0.365 |
| Trend persistence | 720 | 0.538 | 0.568 | 25.23 | 0.380 |
| WaveMind risk-overlay | 720 | 0.501 | 0.843 | 17.40 | 0.651 |
| Naive last-regime | 720 | 0.497 | 0.869 | 15.36 | 0.688 |
| Static kNN | 720 | 0.470 | 0.833 | -9.75 | 0.651 |

Interpretation: the strongest current result is `WaveMind trend-risk`, which
adds WaveMind memory opposition on top of a strong trend-persistence market
baseline. It slightly improves average fixed-size net return (`25.30` vs
`25.23` bps) and reduces large false positives (`0.365` vs `0.380`). This is
real signal-shaping evidence, but not a robust market edge yet: it is positive
on 6/12 symbol-fold slices, and the worst slice is still `-77.66` bps.

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
15. Next: improve downside robustness across bad folds, add drawdown/profit
    factor metrics, and validate on more date ranges, exchanges, assets, and
    walk-forward folds.
16. Only after robustness holds, test signal construction and backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>

For migration from Chroma to the core memory layer, see
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).
