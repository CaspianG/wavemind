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
- `benchmarks/data/crypto_ohlcv/okx/*.csv` - checked-in real OKX OHLCV fixtures.
- `benchmarks/crypto_walk_forward_okx_real_results.json` - checked-in real
  OKX walk-forward result.
- `benchmarks/crypto_okx_real_analogue_explorer.html` - local visual analogue
  explorer for the real OKX run.
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
| WaveMind field | 0.428 | 0.428 | 1.000 | -41.93 | -33.04 | 0.990 | 0.000 | 11.17 ms |
| WaveMind calibrated | 0.273 | 0.442 | 0.421 | -21.30 | -17.66 | 0.373 | 0.579 | 11.23 ms |
| WaveMind field-off | 0.404 | 0.440 | 0.869 | -21.81 | -18.69 | 0.593 | 0.000 | 8.32 ms |
| OHLCV shape kNN | 0.392 | 0.419 | 0.873 | -23.86 | -19.47 | 0.590 | 0.000 | 0.22 ms |
| Naive last-regime | 0.426 | 0.467 | 0.854 | 2.10 | 1.84 | 0.566 | 0.000 | 0.00 ms |
| TA rules | 0.317 | 0.495 | 0.481 | -25.20 | -23.52 | 0.176 | 0.000 | 0.00 ms |
| Static kNN | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 2.65 ms |
| Chroma | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 4.79 ms |
| Qdrant | 0.409 | 0.447 | 0.863 | -14.07 | -13.40 | 0.607 | 0.000 | 4.48 ms |

Interpretation: this is not good enough for a trading claim. Raw WaveMind field
slightly improves direction@1 over naive last-regime (`0.428` vs `0.426`) but
over-triggers and loses heavily after fees/slippage. Calibration reduces
large-move false positives from `0.990` to `0.373`, but it still loses
(`-17.66` sized net bps). Static vector retrieval, Chroma, and Qdrant are also
negative. The strongest result in this run is the naive last-regime baseline,
which is only slightly positive (`1.84` sized net bps). This branch is therefore
a real-data research harness, not evidence of market edge.

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
9. Next: improve feature/regime modeling because current real-data results do
   not beat naive last-regime after costs.
10. Only after retrieval quality is stable, test signal construction and
   backtesting.

## Core Project

For normal WaveMind usage, installation, APIs, agent memory, LangChain,
FastAPI, Studio, and public memory benchmarks, use the main branch:

<https://github.com/CaspianG/wavemind/tree/main>

For migration from Chroma to the core memory layer, see
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).
