from __future__ import annotations

from dataclasses import replace

import pytest


def _bundle(symbol: str = "BTCUSDT"):
    from benchmarks.crypto_binance_archive import ArchiveBundle

    return ArchiveBundle(
        symbol=symbol,
        timeframe="4h",
        start_date="2025-01-01",
        end_date="2025-01-02",
        bars=(),
        intraday_bars=(),
        metrics=(),
        funding=(),
        premium=(),
        book_depth=(),
        source_files=("base.zip",),
        missing_source_files=(),
    )


def _dataset():
    from benchmarks.crypto_binance_depth import (
        BookDepthDataset,
        SymbolBookDepthPoint,
    )

    return BookDepthDataset(
        start_date="2025-01-01",
        end_date="2025-01-02",
        points=(
            SymbolBookDepthPoint("BTCUSDT", 200, 10.0, 8.0, 20.0, 18.0),
            SymbolBookDepthPoint("BTCUSDT", 100, 9.0, 8.0, 19.0, 18.0),
            SymbolBookDepthPoint("ETHUSDT", 100, 4.0, 5.0, 8.0, 9.0),
        ),
        source_files=(
            "cache/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2025-01-01.zip",
            "cache/daily/bookDepth/ETHUSDT/ETHUSDT-bookDepth-2025-01-01.zip",
        ),
        missing_source_files=(
            "https://host/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2025-01-02.zip",
            "https://host/daily/bookDepth/ETHUSDT/ETHUSDT-bookDepth-2025-01-02.zip",
        ),
    )


def test_book_depth_dataset_round_trip_and_bundle_enrichment(tmp_path):
    from benchmarks.crypto_binance_depth import (
        enrich_bundle_with_book_depth,
        load_book_depth_dataset,
        save_book_depth_dataset,
    )

    path = tmp_path / "depth.json.gz"
    save_book_depth_dataset(path, _dataset())
    restored = load_book_depth_dataset(path)
    enriched = enrich_bundle_with_book_depth(_bundle(), restored)

    assert restored == _dataset()
    assert [row.timestamp for row in enriched.book_depth] == [100, 200]
    assert any("BTCUSDT-bookDepth" in item for item in enriched.source_files)
    assert len(enriched.missing_source_files) == 1
    assert "BTCUSDT" in enriched.missing_source_files[0]


def test_book_depth_enrichment_merges_existing_timestamps():
    from benchmarks.crypto_binance_archive import BookDepthPoint
    from benchmarks.crypto_binance_depth import enrich_bundle_with_book_depth

    existing = BookDepthPoint(100, 1.0, 1.0, 1.0, 1.0)
    enriched = enrich_bundle_with_book_depth(
        replace(_bundle(), book_depth=(existing,)),
        _dataset(),
    )

    assert len(enriched.book_depth) == 2
    assert enriched.book_depth[0].bid_notional_1pct == 9.0


def test_book_depth_enrichment_rejects_missing_symbol():
    from benchmarks.crypto_binance_depth import enrich_bundle_with_book_depth

    with pytest.raises(ValueError, match="No book-depth points"):
        enrich_bundle_with_book_depth(_bundle("SOLUSDT"), _dataset())
