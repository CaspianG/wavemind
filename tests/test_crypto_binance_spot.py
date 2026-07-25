from __future__ import annotations

from pathlib import Path

import pytest


def _spot_bar(index: int, *, symbol: str = "BTCUSDT", close: float | None = None):
    from benchmarks.crypto_binance_spot import SymbolSpotBar

    opened = index * 300
    price = 100.0 + index * 0.1
    return SymbolSpotBar(
        symbol=symbol,
        timestamp=opened,
        close_timestamp=opened + 299,
        open=price,
        high=price + 0.2,
        low=price - 0.2,
        close=price + 0.1 if close is None else close,
        volume=10.0,
        quote_volume=1_000.0,
        trades=100,
        taker_buy_volume=6.0,
        taker_buy_quote_volume=600.0,
    )


def test_spot_dataset_round_trip(tmp_path: Path) -> None:
    from benchmarks.crypto_binance_spot import (
        SpotDataset,
        load_spot_dataset,
        save_spot_dataset,
    )

    dataset = SpotDataset(
        start_date="2026-01-01",
        end_date="2026-01-01",
        timeframe="5m",
        bars=(_spot_bar(0),),
        source_files=("source.zip",),
    )
    path = tmp_path / "spot.json.gz"
    save_spot_dataset(path, dataset)

    assert load_spot_dataset(path) == dataset


def test_spot_features_are_strictly_causal_and_ignore_future_bar() -> None:
    from benchmarks.crypto_binance_spot import (
        SpotDataset,
        add_spot_flow_features,
    )
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    completed = tuple(_spot_bar(index) for index in range(48))
    future = _spot_bar(48, close=1_000_000.0)
    dataset = SpotDataset(
        start_date="1970-01-01",
        end_date="1970-01-02",
        timeframe="5m",
        bars=completed + (future,),
        source_files=(),
    )
    cutoff = completed[-1].close_timestamp
    row = FeatureRow(
        "BTCUSDT",
        cutoff,
        cutoff + 86_400,
        0,
        {
            "return_1": 10.0,
            "taker_imbalance": 0.1,
            "intraday_taker_imbalance_mean": 0.15,
        },
        20.0,
    )

    enriched = add_spot_flow_features([row], dataset)

    assert len(enriched) == 1
    assert enriched[0].features["spot_return_4h_bps"] < 1_000.0
    assert enriched[0].features["spot_futures_flow_spread"] == pytest.approx(0.05)
    assert enriched[0].features["spot_age_seconds"] == 0.0


def test_spot_features_reject_incomplete_or_stale_windows() -> None:
    from benchmarks.crypto_binance_spot import (
        SpotDataset,
        add_spot_flow_features,
    )
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    bars = tuple(_spot_bar(index) for index in range(10))
    dataset = SpotDataset("", "", "5m", bars, ())
    row = FeatureRow("BTCUSDT", bars[-1].close_timestamp + 901, 99_999, 0, {}, 1.0)

    assert add_spot_flow_features([row], dataset) == []
    with pytest.raises(ValueError, match="min_bars"):
        add_spot_flow_features([], dataset, min_bars=1)
