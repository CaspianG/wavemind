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
  richer numeric features, future outcome labels, and no-leakage pattern text.
- `benchmarks/crypto_walk_forward_benchmark.py` - BTC/ETH/SOL walk-forward
  benchmark with fees, slippage, field-on/field-off ablation,
  calibrated false-positive suppression, market/time-series baselines, optional
  storage controls, and analogue explorer output.
- `benchmarks/crypto_walk_forward_results.json` - checked-in synthetic
  walk-forward result.
- `benchmarks/crypto_analogue_explorer.html` - local visual analogue explorer.
- `examples/freqtrade_wavemind_strategy.py` - dry-run first Freqtrade scaffold.
- `tests/test_crypto_pattern_benchmark.py` - regression tests for the benchmark.
- `tests/test_crypto_ohlcv.py` - importer/windowing tests.
- `tests/test_crypto_walk_forward_benchmark.py` - walk-forward runner tests.

The current benchmarks are synthetic. They validate the research harness, not
market edge.

## Quick Run

```sh
pip install -e ".[dev]"
python benchmarks/crypto_pattern_benchmark.py --engines wavemind static --history 250 --queries 60
```

Walk-forward run:

```sh
python benchmarks/crypto_walk_forward_benchmark.py --dataset synthetic --symbols BTC ETH SOL --timeframes 1h 4h 1d --engines market storage-controls --position-sizing confidence --confidence-threshold 0.65 --min-analogue-agreement 0.6
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

Current checked-in synthetic walk-forward result:

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

Interpretation: raw WaveMind field improves top-1 direction retrieval over
field-off memory (`0.522` vs `0.472`), but it over-triggers large moves. The
calibrated variant suppresses weak signals using analogue agreement, regime
matching, and a confidence threshold. It cuts large-move false positives from
`0.987` to `0.545` and moves sized net bps from `-1.44` to `7.39`, while
lowering final direction@1 because it intentionally returns `flat` on weak
evidence. The naive last-regime baseline is still strong on this synthetic
dataset, so this branch remains a research harness, not a deployable trading
edge.

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
8. Next: validate calibration on real OHLCV CSV/CCXT data and tune thresholds
   per market/timeframe.
9. Only after retrieval quality is stable, test signal construction and
   backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>

For migration from Chroma to the core memory layer, see
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).
