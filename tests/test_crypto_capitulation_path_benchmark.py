from __future__ import annotations

from benchmarks.crypto_binance_archive import FuturesBar
from benchmarks.crypto_capitulation_path_benchmark import (
    MODEL_FEATURES,
    PathConfig,
    PathEvent,
    collapse_overlapping_rows,
    path_admitted_70,
    resolve_path,
    summarize_events,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _bar(index: int, close: float) -> FuturesBar:
    return FuturesBar(
        timestamp=index * 14_400,
        close_timestamp=(index + 1) * 14_400 - 1,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        quote_volume=1.0,
        trades=1,
        taker_buy_volume=0.5,
        taker_buy_quote_volume=0.5,
    )


def _row(timestamp: int, *, symbol: str = "BTCUSDT") -> FeatureRow:
    return FeatureRow(
        symbol=symbol,
        timestamp=timestamp,
        target_timestamp=timestamp + 86_400,
        fold_index=-1,
        features={name: 0.0 for name in MODEL_FEATURES},
        future_return_bps=0.0,
    )


def test_path_uses_future_closes_in_order() -> None:
    bars = [
        _bar(0, 100.0),
        _bar(1, 99.0),
        _bar(2, 101.1),
        _bar(3, 97.0),
    ]
    event = resolve_path(
        _row(bars[0].close_timestamp),
        bars,
        config=PathConfig(horizon_bars=3, barrier_bps=100.0),
    )

    assert event is not None
    assert event.outcome == "down"
    assert event.bars_to_resolution == 1
    assert not event.hit


def test_unresolved_path_is_a_conservative_miss() -> None:
    bars = [_bar(index, 100.0) for index in range(4)]
    event = resolve_path(
        _row(bars[0].close_timestamp),
        bars,
        config=PathConfig(horizon_bars=3, barrier_bps=100.0),
    )

    assert event is not None
    assert event.outcome == "unresolved"
    assert not event.resolved
    assert not event.hit


def test_overlap_control_is_per_asset() -> None:
    rows = [
        _row(100, symbol="BTCUSDT"),
        _row(200, symbol="BTCUSDT"),
        _row(200, symbol="ETHUSDT"),
        _row(100_000, symbol="BTCUSDT"),
    ]

    collapsed = collapse_overlapping_rows(rows, horizon_bars=6)

    assert [(row.symbol, row.timestamp) for row in collapsed] == [
        ("BTCUSDT", 100),
        ("ETHUSDT", 200),
        ("BTCUSDT", 100_000),
    ]


def test_admission_uses_conservative_accuracy_and_stability() -> None:
    events = [
        PathEvent(
            symbol="BTCUSDT" if index % 2 else "ETHUSDT",
            timestamp=index,
            target_timestamp=index + 1,
            year=2025 if index < 50 else 2026,
            outcome="up" if index % 5 != 4 else "down",
            hit=index % 5 != 4,
            resolved=True,
            bars_to_resolution=1,
            terminal_return_bps=100.0,
            max_return_bps=100.0,
            min_return_bps=-10.0,
            features=tuple(0.0 for _ in MODEL_FEATURES),
        )
        for index in range(100)
    ]
    summary = summarize_events(events, unconditional_up_rate=0.50)

    assert summary["conservative_accuracy"] == 0.80
    assert summary["wilson_low_95"] > 0.70
    assert path_admitted_70(summary)
    assert not path_admitted_70(
        summary | {"resolution_rate": 0.70}
    )
