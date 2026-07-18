from __future__ import annotations


def test_cross_asset_features_require_btc_and_add_market_context():
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow, add_cross_asset_features

    base = {
        "return_6": 10.0,
        "oi_change_6": 20.0,
        "global_ratio_log": 0.1,
    }
    rows = {
        "BTCUSDT": [FeatureRow("BTCUSDT", 1, 2, -1, base, 5.0)],
        "ETHUSDT": [FeatureRow("ETHUSDT", 1, 2, -1, base | {"return_6": -10.0}, -5.0)],
    }

    combined = add_cross_asset_features(rows)

    assert len(combined) == 2
    assert combined[0].features["btc_return_6"] == 10.0
    assert combined[0].features["market_return_6_mean"] == 0.0


def test_walk_forward_folds_leave_training_history_unassigned():
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow, assign_walk_forward_folds

    rows = [
        FeatureRow("BTCUSDT", timestamp=index, target_timestamp=index + 1, fold_index=-1, features={}, future_return_bps=1.0)
        for index in range(20)
    ]

    assigned = assign_walk_forward_folds(rows, folds=2, test_timestamps=5)

    assert [row.fold_index for row in assigned[:10]] == [-1] * 10
    assert [row.fold_index for row in assigned[10:15]] == [0] * 5
    assert [row.fold_index for row in assigned[15:]] == [1] * 5


def test_matrix_adds_explicit_symbol_indicators():
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow, _matrix

    rows = [FeatureRow("ETHUSDT", 1, 2, 0, {"feature": 3.0}, 1.0)]

    matrix = _matrix(rows, ("feature", "symbol_ETHUSDT", "symbol_SOLUSDT"))

    assert matrix.tolist() == [[3.0, 1.0, 0.0]]


def test_metric_freshness_is_checked_per_field():
    from benchmarks.crypto_derivatives_field_benchmark import _metric_fields_are_fresh

    cutoff = 10_000
    timestamps = {"open_interest": 9_950, "ratio": 9_000}

    assert not _metric_fields_are_fresh(
        cutoff, timestamps, ("open_interest", "ratio"), max_age_seconds=300
    )
    assert _metric_fields_are_fresh(
        cutoff, {"open_interest": 9_950, "ratio": 9_900}, ("open_interest", "ratio"), max_age_seconds=300
    )


def test_horizon_label_is_explicit():
    from benchmarks.crypto_derivatives_field_benchmark import _horizon_label

    assert _horizon_label(24 * 60 * 60) == "24h"
    assert _horizon_label(7 * 24 * 60 * 60) == "7d"


def test_extended_features_do_not_require_microstructure_fields():
    from benchmarks.crypto_derivatives_field_benchmark import _features_from_history

    history = []
    for index in range(181):
        history.append(
            {
                "close": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "quote_volume": 1_000.0 + index,
                "trades": 100.0 + index,
                "taker_imbalance": 0.01 * ((index % 5) - 2),
                "open_interest_value": 10_000.0 + index * 3,
                "top_trader_account_ratio": 1.1 + index / 10_000,
                "top_trader_position_ratio": 1.2 + index / 10_000,
                "global_long_short_ratio": 1.0 + index / 10_000,
                "taker_long_short_ratio": 0.9 + index / 10_000,
                "funding_rate": 0.0001,
                "premium": 0.0002,
                "oi_intrabar_change_bps": 1.0,
                "oi_intrabar_range_bps": 2.0,
                "global_ratio_intrabar_mean_log": 0.1,
                "global_ratio_intrabar_std": 0.01,
                "taker_ratio_intrabar_mean_log": 0.1,
                "taker_ratio_intrabar_std": 0.01,
                "top_account_intrabar_mean_log": 0.1,
                "top_position_intrabar_mean_log": 0.1,
                "premium_range_bps": 1.0,
                "hour_sin": 0.0,
                "hour_cos": 1.0,
                "weekday_sin": 0.0,
                "weekday_cos": 1.0,
            }
        )

    features = _features_from_history(
        history,
        include_microstructure=False,
        extended_features=True,
    )

    assert "return_180" in features
    assert "oi_change_180" in features
    assert "depth_imbalance_1pct" not in features


def test_intraday_path_features_preserve_completed_bar_order_flow():
    import math

    import numpy as np
    import pytest

    from benchmarks.crypto_binance_archive import FuturesBar
    from benchmarks.crypto_derivatives_field_benchmark import _intraday_path_features

    bars = tuple(
        FuturesBar(
            timestamp=index * 300,
            close_timestamp=index * 300 + 299,
            open=100.0 + index,
            high=101.5 + index,
            low=99.5 + index,
            close=101.0 + index,
            volume=10.0,
            quote_volume=1_000.0 + index,
            trades=100 + index,
            taker_buy_volume=6.0,
            taker_buy_quote_volume=600.0,
        )
        for index in range(48)
    )

    features = _intraday_path_features(bars)

    assert set(features) == {
        "intraday_return_first_hour_bps",
        "intraday_return_last_hour_bps",
        "intraday_realized_volatility_bps",
        "intraday_path_efficiency",
        "intraday_return_autocorrelation",
        "intraday_max_drawdown_bps",
        "intraday_close_position",
        "intraday_last_hour_volume_share",
        "intraday_last_hour_trade_share",
        "intraday_taker_imbalance_mean",
        "intraday_taker_imbalance_std",
        "intraday_taker_imbalance_first_hour",
        "intraday_taker_imbalance_last_hour",
        "intraday_taker_imbalance_shift",
        "intraday_taker_buy_persistence",
        "intraday_flow_return_interaction",
    }
    assert features["intraday_taker_buy_persistence"] == 1.0
    assert features["intraday_taker_imbalance_shift"] == 0.0
    assert features["intraday_return_last_hour_bps"] == pytest.approx(
        math.log(148.0 / 136.0) * 10_000.0
    )
    assert 0.0 < features["intraday_path_efficiency"] <= 1.0
    assert np.isfinite(list(features.values())).all()


def test_intraday_path_rejects_incomplete_observation():
    import pytest

    from benchmarks.crypto_derivatives_field_benchmark import _intraday_path_features

    with pytest.raises(ValueError, match="at least 40"):
        _intraday_path_features(())
