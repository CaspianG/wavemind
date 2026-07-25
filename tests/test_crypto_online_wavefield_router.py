from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.crypto_online_wavefield_router import (
    QueryPanel,
    RouterConfig,
    _admitted_70,
    load_query_panels,
    simulate_router,
)


def _event(
    *,
    engine: str,
    query_id: str,
    data_end: str,
    target_end: str,
    actual: float,
    probability: float,
) -> dict:
    return {
        "engine": engine,
        "symbol": "BTCUSDT",
        "timeframe": "4h",
        "fold_index": 0,
        "query_id": query_id,
        "data_end_utc": data_end,
        "target_end_utc": target_end,
        "actual_return_bps": actual,
        "probability_up": probability,
        "quality_probability": 0.7,
        "event_probability": 0.6,
        "predicted_return_bps": 10.0 if probability >= 0.5 else -10.0,
    }


def test_load_query_panels_rejects_inconsistent_outcome(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        _event(
            engine="a",
            query_id="q1",
            data_end="2026-01-01T00:00:00+00:00",
            target_end="2026-01-02T00:00:00+00:00",
            actual=10.0,
            probability=0.7,
        ),
        _event(
            engine="b",
            query_id="q1",
            data_end="2026-01-01T00:00:00+00:00",
            target_end="2026-01-02T00:00:00+00:00",
            actual=-10.0,
            probability=0.3,
        ),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Inconsistent outcome"):
        load_query_panels(path)


def test_router_updates_only_after_target_matures() -> None:
    panels = [
        QueryPanel(
            symbol="BTCUSDT",
            timeframe="4h",
            fold_index=0,
            query_id="q1",
            data_end_utc="2026-01-01T00:00:00+00:00",
            target_end_utc="2026-01-02T00:00:00+00:00",
            actual_return_bps=-10.0,
            predictions={"always_up": {"probability_up": 0.9}},
        ),
        QueryPanel(
            symbol="BTCUSDT",
            timeframe="4h",
            fold_index=0,
            query_id="q2",
            data_end_utc="2026-01-01T12:00:00+00:00",
            target_end_utc="2026-01-02T12:00:00+00:00",
            actual_return_bps=-10.0,
            predictions={"always_up": {"probability_up": 0.9}},
        ),
        QueryPanel(
            symbol="BTCUSDT",
            timeframe="4h",
            fold_index=0,
            query_id="q3",
            data_end_utc="2026-01-03T00:00:00+00:00",
            target_end_utc="2026-01-04T00:00:00+00:00",
            actual_return_bps=-10.0,
            predictions={"always_up": {"probability_up": 0.9}},
        ),
    ]
    config = RouterConfig("test", 365.0, 0.01, 0.01, 0.0)

    events = simulate_router(panels, config)

    assert events[0]["predicted_up"] is True
    assert events[1]["predicted_up"] is True
    assert events[2]["predicted_up"] is False


def test_strict_admission_requires_sample_and_worst_symbol() -> None:
    passing = {
        "signals": 200,
        "accuracy": 0.75,
        "wilson_low_95": 0.68,
        "worst_symbol_accuracy": 0.62,
    }
    assert _admitted_70(passing)
    assert not _admitted_70(passing | {"signals": 99})
    assert not _admitted_70(passing | {"accuracy": 0.69})
    assert not _admitted_70(passing | {"worst_symbol_accuracy": 0.59})
