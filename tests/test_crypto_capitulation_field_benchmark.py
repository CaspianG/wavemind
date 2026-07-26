from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from benchmarks.crypto_capitulation_field_benchmark import (
    DEFAULT_FOLD_BOUNDARIES,
    EARLY_REPLICATION_BOUNDARIES,
    FROZEN_CAPITULATION_RULE,
    _validate_disjoint_asset_sets,
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


def test_replication_periods_are_explicit_and_non_overlapping():
    assert DEFAULT_FOLD_BOUNDARIES == (
        ("2024-01-01", "2024-07-01"),
        ("2024-07-01", "2025-01-01"),
        ("2025-01-01", "2025-07-01"),
        ("2025-07-01", "2026-01-01"),
        ("2026-01-01", "2026-07-01"),
    )
    assert EARLY_REPLICATION_BOUNDARIES == (
        ("2023-07-01", "2023-10-01"),
        ("2023-10-01", "2024-01-01"),
    )
    assert EARLY_REPLICATION_BOUNDARIES[-1][1] <= DEFAULT_FOLD_BOUNDARIES[0][0]


def test_replication_assets_must_be_disjoint():
    _validate_disjoint_asset_sets(
        development=["AAAUSDT"],
        holdout=["BBBUSDT"],
        replication=["CCCUSDT"],
    )

    try:
        _validate_disjoint_asset_sets(
            development=["AAAUSDT"],
            holdout=["BBBUSDT"],
            replication=["AAAUSDT"],
        )
    except ValueError as exc:
        assert "development and replication assets overlap" in str(exc)
    else:
        raise AssertionError("Expected overlapping replication assets to fail")


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


def test_checked_in_replication_result_is_internally_consistent():
    result_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "results"
        / "crypto"
        / "capitulation_field_replication_24h.json"
    )
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    asset_sets = (
        set(payload["development_assets"]),
        set(payload["holdout_assets"]),
        set(payload["replication_assets"]),
    )

    pairs = (
        (asset_sets[0], asset_sets[1]),
        (asset_sets[0], asset_sets[2]),
        (asset_sets[1], asset_sets[2]),
    )
    assert all(not left & right for left, right in pairs)
    assert len(payload["replication_assets"]) == 8
    assert payload["replication_protocol"]["current_period_folds"] == [
        list(item) for item in DEFAULT_FOLD_BOUNDARIES
    ]
    assert payload["replication_protocol"]["early_period_folds"] == [
        list(item) for item in EARLY_REPLICATION_BOUNDARIES
    ]
    for key in ("asset_disjoint_replication", "early_period_replication"):
        summary = payload[key]["summary"]
        assert summary["hits"] <= summary["signals"]
        assert summary["accuracy"] == summary["hits"] / summary["signals"]

    replication = payload["asset_disjoint_replication"]
    assert replication["summary"]["signals"] == 60
    assert replication["summary"]["hits"] == 50
    assert replication["summary"]["accuracy"] == 50 / 60
    assert replication["summary"]["wilson_low_95"] > 0.70
    assert replication["aggregate_evidence_70"]
    assert not replication["admitted_70"]

    combined = payload["combined_asset_replications"]
    assert len(payload["combined_replication_assets"]) == 16
    assert combined["summary"]["signals"] == 118
    assert combined["summary"]["hits"] == 98
    assert combined["summary"]["accuracy"] == 98 / 118
    assert combined["summary"]["wilson_low_95"] > 0.75
    assert combined["aggregate_evidence_70"]
    assert not combined["admitted_70"]

    early = payload["early_period_replication"]
    assert early["summary"]["signals"] == 3
    assert early["summary"]["hits"] == 1
    assert not early["aggregate_evidence_70"]
    assert not early["admitted_70"]
