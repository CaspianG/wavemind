from __future__ import annotations

import json
from pathlib import Path


def _event(
    *,
    fold: int,
    index: int,
    hit: float,
    agreement: float,
    symbol: str = "BTCUSDT",
) -> dict:
    start = fold * 10_000 + index * 100
    return {
        "engine": "test",
        "symbol": symbol,
        "timeframe": "1h",
        "fold_index": fold,
        "query_id": f"{symbol}-{fold}-{index}",
        "data_end_utc": f"2026-01-{fold + 1:02d}T00:{index:02d}:00+00:00",
        "target_end_utc": f"2026-01-{fold + 1:02d}T00:{index + 1:02d}:00+00:00",
        "direction_hit": hit,
        "agreement": agreement,
        "strength": agreement,
        "magnitude_bps": agreement * 500.0,
        "volatility_bps": 100.0,
        "_order": start,
    }


def test_json_array_loader_supports_utf16(tmp_path: Path) -> None:
    from benchmarks.crypto_signal_transfer_benchmark import load_signal_events

    path = tmp_path / "events.json"
    path.write_text(
        json.dumps([_event(fold=0, index=0, hit=1.0, agreement=1.0)]),
        encoding="utf-16",
    )

    assert load_signal_events(path)[0]["query_id"] == "BTCUSDT-0-0"


def test_policy_is_selected_without_test_labels() -> None:
    from benchmarks.crypto_signal_transfer_benchmark import (
        run_signal_transfer_benchmark,
    )

    training = [
        _event(
            fold=0,
            index=index,
            hit=1.0 if index >= 10 else 0.0,
            agreement=1.0 if index >= 10 else 0.0,
        )
        for index in range(30)
    ]
    test = [
        _event(
            fold=1,
            index=index,
            hit=1.0,
            agreement=1.0 if index >= 10 else 0.0,
        )
        for index in range(30)
    ]
    first = run_signal_transfer_benchmark(
        training + test,
        min_training_signals=10,
        min_test_signals=5,
        min_fold_accuracy=0.0,
        min_slice_accuracy=0.0,
        min_wilson_low_95=0.0,
    )
    changed_test = [
        dict(row, direction_hit=1.0 - float(row["direction_hit"]))
        for row in test
    ]
    second = run_signal_transfer_benchmark(
        training + changed_test,
        min_training_signals=10,
        min_test_signals=5,
        min_fold_accuracy=0.0,
        min_slice_accuracy=0.0,
        min_wilson_low_95=0.0,
    )

    assert (
        first["by_timeframe"][0]["folds"][0]["policy"]
        == second["by_timeframe"][0]["folds"][0]["policy"]
    )
    assert (
        first["transferred_summary"]["accuracy"]
        != second["transferred_summary"]["accuracy"]
    )


def test_overlapping_events_are_collapsed_before_transfer() -> None:
    from benchmarks.crypto_signal_transfer_benchmark import (
        run_signal_transfer_benchmark,
    )

    events = []
    for fold in (0, 1):
        for index in range(10):
            row = _event(
                fold=fold,
                index=index,
                hit=1.0,
                agreement=1.0,
            )
            row["target_end_utc"] = f"2026-01-{fold + 1:02d}T01:00:00+00:00"
            events.append(row)
    payload = run_signal_transfer_benchmark(
        events,
        min_training_signals=1,
        min_test_signals=1,
        min_fold_accuracy=0.0,
        min_slice_accuracy=0.0,
        min_wilson_low_95=0.0,
    )

    assert payload["methodology"]["raw_events"] == 20
    assert payload["methodology"]["independent_events"] < 20


def test_markdown_discloses_transfer_verdict() -> None:
    from benchmarks.crypto_signal_transfer_benchmark import (
        render_markdown,
        run_signal_transfer_benchmark,
    )

    events = [
        _event(fold=fold, index=index, hit=1.0, agreement=1.0)
        for fold in (0, 1)
        for index in range(10)
    ]
    payload = run_signal_transfer_benchmark(
        events,
        min_training_signals=1,
        min_test_signals=1,
        min_fold_accuracy=0.0,
        min_slice_accuracy=0.0,
        min_wilson_low_95=0.0,
    )
    markdown = render_markdown(payload)

    assert "earlier folds only" in markdown
    assert "admitted at 70%" in markdown
