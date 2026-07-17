from __future__ import annotations


def _event(*, query: int, hit: bool, fold: int = 0, magnitude: float = 200.0):
    from datetime import datetime, timedelta, timezone

    data_end = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * query)
    return {
        "engine": "engine",
        "symbol": "BTC/USDT",
        "fold_index": fold,
        "query_id": f"query-{query}",
        "data_end_utc": data_end.isoformat(),
        "target_end_utc": (data_end + timedelta(hours=24)).isoformat(),
        "predicted_return_bps": magnitude,
        "direction_hit": 1.0 if hit else 0.0,
    }


def test_overlap_collapse_keeps_one_observation_per_horizon():
    from benchmarks.crypto_accuracy_gate import collapse_overlapping_events

    selected = collapse_overlapping_events([_event(query=index, hit=True) for index in range(12)])

    assert [row["query_id"] for row in selected] == ["query-0", "query-6"]


def test_overlap_collapse_keeps_independent_timeframes():
    from benchmarks.crypto_accuracy_gate import collapse_overlapping_events

    one_hour = _event(query=0, hit=True)
    one_hour["timeframe"] = "1h"
    four_hour = _event(query=0, hit=True)
    four_hour["timeframe"] = "4h"

    selected = collapse_overlapping_events([one_hour, four_hour])

    assert {row["timeframe"] for row in selected} == {"1h", "4h"}


def test_accuracy_gate_rejects_tiny_apparent_80_percent_edge():
    from benchmarks.crypto_accuracy_gate import evaluate_accuracy_gate

    events = [_event(query=index * 6, hit=index < 8) for index in range(10)]
    payload = evaluate_accuracy_gate(
        events,
        min_effective_signals=40,
        min_fold_signals=1,
        thresholds_bps=[150.0],
    )

    row = payload["engines"][0]["frontier"][0]
    assert row["effective"]["accuracy"] == 0.8
    assert row["effective"]["signals"] == 10
    assert row["admitted"] is False


def test_accuracy_gate_requires_every_market_slice_to_hold():
    from benchmarks.crypto_accuracy_gate import evaluate_accuracy_gate

    events = []
    for symbol in ("BTC/USDT", "SOL/USDT"):
        for index in range(30):
            event = _event(query=index * 6, hit=(symbol == "BTC/USDT" or index < 15))
            event["symbol"] = symbol
            event["timeframe"] = "4h"
            events.append(event)
    payload = evaluate_accuracy_gate(
        events,
        min_effective_signals=40,
        min_fold_signals=1,
        min_slice_signals=5,
        min_wilson_low_95=0.0,
        thresholds_bps=[150.0],
    )

    row = payload["engines"][0]["frontier"][0]
    assert row["effective"]["accuracy"] == 0.75
    assert row["by_slice"][0]["accuracy"] == 1.0
    assert row["by_slice"][1]["accuracy"] == 0.5
    assert row["slice_ready"] is False
    assert row["admitted"] is False


def test_accuracy_gate_requires_every_fold_to_hold():
    from benchmarks.crypto_accuracy_gate import evaluate_accuracy_gate

    events = []
    for fold in range(2):
        for index in range(20):
            events.append(_event(query=(fold * 100) + index * 6, fold=fold, hit=(fold == 0 or index < 10)))
    payload = evaluate_accuracy_gate(
        events,
        min_effective_signals=40,
        min_fold_signals=5,
        thresholds_bps=[150.0],
    )

    row = payload["engines"][0]["frontier"][0]
    assert row["by_fold"][0]["accuracy"] == 1.0
    assert row["by_fold"][1]["accuracy"] == 0.5
    assert row["fold_ready"] is False
    assert row["admitted"] is False
