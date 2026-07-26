from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from benchmarks.crypto_capitulation_field_benchmark import (
    FROZEN_CAPITULATION_RULE,
    aggregate_evidence_70,
    admitted_70,
    evaluate_capitulation_rule,
    summarize_with_slices,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _row(
    *,
    symbol: str,
    timestamp: int,
    fold: int,
    return_12: float,
    oi_change_1: float,
    future_return_bps: float,
) -> FeatureRow:
    return FeatureRow(
        symbol=symbol,
        timestamp=timestamp,
        target_timestamp=timestamp + 10,
        fold_index=fold,
        features={
            "return_12": return_12,
            "oi_change_1": oi_change_1,
        },
        future_return_bps=future_return_bps,
    )


def test_frozen_rule_is_explicit_and_immutable():
    assert FROZEN_CAPITULATION_RULE.direction == "up"
    assert [
        (item.feature, item.quantile, item.tail)
        for item in FROZEN_CAPITULATION_RULE.conditions
    ] == [
        ("return_12", 0.01, "low"),
        ("oi_change_1", 0.10, "low"),
    ]


def test_current_fold_labels_do_not_change_selection_or_thresholds():
    history = [
        _row(
            symbol="AAAUSDT",
            timestamp=index * 20,
            fold=-1,
            return_12=float(index),
            oi_change_1=float(index),
            future_return_bps=100.0,
        )
        for index in range(100)
    ]
    test = [
        _row(
            symbol="AAAUSDT",
            timestamp=2_100,
            fold=0,
            return_12=-10.0,
            oi_change_1=-10.0,
            future_return_bps=100.0,
        ),
        _row(
            symbol="AAAUSDT",
            timestamp=2_120,
            fold=0,
            return_12=50.0,
            oi_change_1=50.0,
            future_return_bps=-100.0,
        ),
    ]
    original = evaluate_capitulation_rule(history + test)
    flipped = evaluate_capitulation_rule(
        history
        + [
            replace(row, future_return_bps=-row.future_return_bps)
            for row in test
        ]
    )

    assert [event["timestamp"] for event in original["events"]] == [2_100]
    assert [event["timestamp"] for event in flipped["events"]] == [2_100]
    assert original["fold_audits"][0]["thresholds"] == flipped["fold_audits"][0][
        "thresholds"
    ]


def test_independent_sampling_removes_overlapping_forecasts():
    history = [
        _row(
            symbol="AAAUSDT",
            timestamp=index * 20,
            fold=-1,
            return_12=float(index),
            oi_change_1=float(index),
            future_return_bps=100.0,
        )
        for index in range(100)
    ]
    test = [
        _row(
            symbol="AAAUSDT",
            timestamp=2_100 + offset,
            fold=0,
            return_12=-10.0,
            oi_change_1=-10.0,
            future_return_bps=100.0,
        )
        for offset in (0, 5, 10)
    ]

    result = evaluate_capitulation_rule(history + test)

    assert [event["timestamp"] for event in result["events"]] == [2_100, 2_110]


def test_admission_requires_supported_folds_and_uncertainty():
    events = []
    for fold in range(2):
        for index in range(50):
            events.append(
                {
                    "fold_index": fold,
                    "symbol": f"ASSET{index % 2}",
                    "direction_hit": index < 40,
                }
            )
    summary = summarize_with_slices(events, min_slice_support=5)

    assert admitted_70(summary, expected_folds=2, min_slice_support=5)
    assert aggregate_evidence_70(summary)

    weak = summarize_with_slices(events[:50] + events[50:54], min_slice_support=5)
    assert not admitted_70(weak, expected_folds=2, min_slice_support=5)
    assert aggregate_evidence_70(weak)


def test_checked_in_asset_holdout_result_is_internally_consistent():
    result_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "results"
        / "crypto"
        / "capitulation_field_24h.json"
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    holdout = payload["asset_disjoint_holdout"]
    summary = holdout["summary"]

    assert not set(payload["development_assets"]) & set(payload["holdout_assets"])
    assert len(payload["holdout_assets"]) == 8
    assert summary["signals"] == 58
    assert summary["hits"] == 48
    assert summary["accuracy"] == 48 / 58
    assert summary["wilson_low_95"] > 0.70
    assert payload["aggregate_evidence_70"]
    assert not payload["admitted_70"]
