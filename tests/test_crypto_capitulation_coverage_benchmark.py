from __future__ import annotations

from dataclasses import replace

from benchmarks.crypto_binance_liquidations import (
    LiquidationPoint,
    add_liquidation_features,
    aggregate_liquidation_bars,
)
from benchmarks.crypto_capitulation_coverage_benchmark import (
    CoverageConfig,
    _admitted_70,
    _collapse_signals,
    _liquidation_matches,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _row(index: int) -> FeatureRow:
    return FeatureRow(
        symbol="BTCUSDT",
        timestamp=(index + 1) * 14_400 - 1,
        target_timestamp=(index + 7) * 14_400 - 1,
        fold_index=0,
        features={"return_12": -100.0, "oi_change_1": -10.0},
        future_return_bps=25.0,
    )


def test_config_rejects_unknown_liquidation_policy():
    assert CoverageConfig(0.01, 0.50, "none").oi_quantile == 0.50
    try:
        CoverageConfig(0.01, 0.10, "future_leak")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unknown policy was accepted")


def test_rolling_liquidation_features_only_use_current_and_past_bars():
    rows = [_row(index) for index in range(8)]
    points = [
        LiquidationPoint(14_500, "SELL", 5.0, 99.0, 100.0),
        LiquidationPoint(28_900, "BUY", 1.0, 101.0, 100.0),
    ]
    bars = aggregate_liquidation_bars(points)
    enriched = add_liquidation_features(rows, bars)
    future_changed = add_liquidation_features(
        [replace(row, future_return_bps=-row.future_return_bps) for row in rows],
        bars,
    )
    for left, right in zip(enriched, future_changed, strict=True):
        assert left.features == right.features
    assert enriched[1].features["liquidation_log_count_sum6"] > 0.0
    assert enriched[1].features["liquidation_weighted_imbalance6"] < 0.0


def test_rolling_sell_policy_uses_causal_24h_pressure():
    rows = [_row(index) for index in range(8)]
    points = [
        LiquidationPoint(14_500, "SELL", 5.0, 99.0, 100.0),
        LiquidationPoint(14_600, "SELL", 3.0, 99.0, 100.0),
        LiquidationPoint(14_700, "BUY", 1.0, 101.0, 100.0),
    ]
    enriched = add_liquidation_features(
        rows,
        aggregate_liquidation_bars(points),
    )
    assert _liquidation_matches(enriched[1], "rolling_sell")
    assert not _liquidation_matches(enriched[-1], "current_sell")


def test_signal_collapse_happens_after_event_detection():
    rows = [_row(index) for index in range(14)]
    selected = _collapse_signals([rows[1], rows[2], rows[8]])
    assert selected == [rows[1], rows[8]]


def test_admission_requires_support_and_robust_slices():
    passing = {
        "signals": 100,
        "accuracy": 0.75,
        "wilson_low_95": 0.66,
        "worst_supported_fold_accuracy": 0.70,
        "worst_supported_symbol_accuracy": 0.68,
    }
    assert _admitted_70(passing)
    assert not _admitted_70(passing | {"wilson_low_95": 0.64})
    assert not _admitted_70(passing | {"signals": 39})
