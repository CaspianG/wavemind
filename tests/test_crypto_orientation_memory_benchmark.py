from __future__ import annotations

import json
from pathlib import Path

from benchmarks.crypto_orientation_memory_benchmark import (
    DirectionEvent,
    OrientationMemory,
    run_benchmark,
)


def _event(
    index: int,
    *,
    actual_up: bool,
    guard_up: bool = True,
    fold: int = -1,
) -> DirectionEvent:
    return DirectionEvent(
        symbol="AAAUSDT",
        observed_at=index * 20,
        target_at=index * 20 + 10,
        fold_index=fold,
        actual_up=actual_up,
        guard_up=guard_up,
        momentum_up=True,
        regime=("up", "up", "neutral", "normal"),
    )


def test_orientation_memory_can_invert_a_persistently_wrong_guard() -> None:
    memory = OrientationMemory(prior_strength=2.0)
    for index in range(10):
        memory.observe(_event(index, actual_up=False))

    predicted_up, reliability = memory.predict(
        _event(11, actual_up=False)
    )

    assert not predicted_up
    assert reliability < 0.5


def test_run_benchmark_updates_memory_only_after_target_matures() -> None:
    events = [
        _event(index, actual_up=False, fold=-1)
        for index in range(10)
    ]
    events.extend(
        [
            _event(20, actual_up=False, fold=0),
            _event(21, actual_up=False, fold=0),
        ]
    )

    result = run_benchmark(events)
    summaries = {
        row["engine"]: row for row in result["summaries"]
    }

    assert summaries["guarded_state"]["hits"] == 0
    assert summaries["inverse_guarded_state"]["hits"] == 2
    assert summaries["orientation_memory"]["hits"] == 2


def test_checked_in_orientation_result_is_consistent() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "results"
        / "crypto"
        / "orientation_memory_24h.json"
    )
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["assets"]) == 32
    for row in payload["summaries"]:
        assert row["hits"] <= row["signals"]
        assert row["accuracy"] == row["hits"] / row["signals"]
        assert row["signals"] == 29_152
    by_engine = {
        row["engine"]: row for row in payload["summaries"]
    }
    assert by_engine["mean_reversion"]["accuracy"] > 0.52
    assert by_engine["mean_reversion"]["accuracy"] < 0.53
    assert by_engine["orientation_memory"]["accuracy"] < 0.50
    assert not payload["admitted_engines"]
