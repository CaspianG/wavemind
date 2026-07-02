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
- `benchmarks/crypto_pattern_benchmark.py` - deterministic OHLCV-pattern
  retrieval benchmark scaffold.
- `benchmarks/crypto_pattern_results.json` - first checked-in synthetic result.
- `tests/test_crypto_pattern_benchmark.py` - regression tests for the benchmark.

The current benchmark is synthetic and intentionally easy. It validates the
research harness, not market edge.

## Quick Run

```sh
pip install -e ".[dev]"
python benchmarks/crypto_pattern_benchmark.py --engines wavemind static --history 250 --queries 60
```

Current checked-in synthetic result:

| engine | direction@1 | direction@3 | family@1 | avg latency |
|---|---:|---:|---:|---:|
| WaveMind | 1.000 | 1.000 | 1.000 | 6.69 ms |
| Static vector | 1.000 | 1.000 | 1.000 | 0.03 ms |

Interpretation: both systems recover the deterministic synthetic pattern
families. This is a scaffold validation only.

## Research Plan

1. Add real OHLCV CSV import.
2. Add explicit train/test and walk-forward splits.
3. Add fees, slippage, and position sizing.
4. Compare WaveMind against static vector retrieval, Chroma, Qdrant, and simple
   technical-analysis baselines.
5. Only after retrieval quality is stable, test signal construction and
   backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>
