from __future__ import annotations

from benchmarks.crypto_capitulation_confirmation_benchmark import (
    ConfirmationConfig,
    _confirmation_matches,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _row(**features: float) -> FeatureRow:
    return FeatureRow(
        symbol="BTCUSDT",
        timestamp=1,
        target_timestamp=2,
        fold_index=0,
        features={
            "return_1": 10.0,
            "return_3": -30.0,
            "taker_imbalance": -0.2,
        }
        | features,
        future_return_bps=10.0,
    )


def test_config_rejects_unknown_confirmation():
    try:
        ConfirmationConfig(0.01, 0.10, "future_price")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unknown confirmation was accepted")


def test_green_and_absorption_confirmations_are_causal_feature_rules():
    row = _row()
    assert _confirmation_matches(row, "green_4h")
    assert _confirmation_matches(row, "green_absorption")
    assert not _confirmation_matches(row, "green_flow")


def test_deceleration_detects_a_selloff_losing_speed():
    assert _confirmation_matches(_row(return_1=-5.0), "decelerating_selloff")
    assert not _confirmation_matches(
        _row(return_1=-20.0),
        "decelerating_selloff",
    )
