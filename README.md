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
  and no-leakage pattern text.
- `benchmarks/crypto_walk_forward_benchmark.py` - BTC/ETH/SOL walk-forward
  benchmark with fees, slippage, Chroma/Qdrant/static/TA/naive baselines, and
  analogue explorer output.
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
python benchmarks/crypto_walk_forward_benchmark.py --dataset synthetic --symbols BTC ETH SOL --timeframes 1h 4h 1d --engines wavemind static chroma qdrant naive ta
```

Current checked-in synthetic result:

| engine | direction@1 | direction@3 | family@1 | avg latency |
|---|---:|---:|---:|---:|
| WaveMind | 1.000 | 1.000 | 1.000 | 6.69 ms |
| Static vector | 1.000 | 1.000 | 1.000 | 0.03 ms |

Interpretation: both systems recover the deterministic synthetic pattern
families. This is a scaffold validation only.

Current checked-in synthetic walk-forward result:

| engine | direction@1 | direction@3 | avg net bps | hit rate | avg latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 0.509 | 0.670 | -9.36 | 0.507 | 5.40 ms |
| Static kNN | 0.454 | 0.707 | -8.51 | 0.428 | 1.77 ms |
| Chroma | 0.454 | 0.707 | -8.51 | 0.428 | 3.63 ms |
| Qdrant | 0.454 | 0.707 | -8.51 | 0.428 | 3.09 ms |
| Naive last-regime | 0.589 | 0.589 | 27.37 | 0.567 | 0.00 ms |
| TA rules | 0.191 | 0.191 | -64.06 | 0.143 | 0.00 ms |

Interpretation: WaveMind beats static vector retrieval, Chroma, and Qdrant on
top-1 direction retrieval in this synthetic walk-forward run, but it does not
beat the naive last-regime baseline on net payoff. This branch is a research
harness, not a deployable trading edge.

## Research Plan

The product direction is documented here:

[`docs/CRYPTO_MARKET_DIRECTION_2026_2027.md`](docs/CRYPTO_MARKET_DIRECTION_2026_2027.md)

Near-term execution plan:

1. Add real OHLCV CSV and CCXT import.
2. Add explicit train/test and walk-forward splits.
3. Add fees, slippage, and position sizing.
4. Compare WaveMind against static vector retrieval, Chroma, Qdrant, and simple
   technical-analysis baselines.
5. Build a Freqtrade research adapter before any live-trading integration.
6. Only after retrieval quality is stable, test signal construction and
   backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>

For migration from Chroma to the core memory layer, see
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).
