from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.crypto_dynamic_field_transfer_benchmark import (
    DEFAULT_PROTOCOL,
    _validate_asset_sets,
)
from benchmarks.crypto_asset_normalized_field_transfer_benchmark import (
    load_protocol,
)


def test_dynamic_transfer_requires_asset_disjoint_sets() -> None:
    with pytest.raises(ValueError, match="overlap"):
        _validate_asset_sets(
            ["AAAUSDT", "BBBUSDT"],
            ["BBBUSDT", "CCCUSDT"],
            expected_training=None,
            expected_holdout=None,
        )


def test_dynamic_transfer_enforces_frozen_asset_lists() -> None:
    with pytest.raises(ValueError, match="training symbols"):
        _validate_asset_sets(
            ["AAAUSDT"],
            ["BBBUSDT"],
            expected_training=["OTHERUSDT"],
            expected_holdout=["BBBUSDT"],
        )
    with pytest.raises(ValueError, match="holdout symbols"):
        _validate_asset_sets(
            ["AAAUSDT"],
            ["BBBUSDT"],
            expected_training=["AAAUSDT"],
            expected_holdout=["OTHERUSDT"],
        )


def test_default_dynamic_protocol_freezes_support_and_transfer() -> None:
    protocol, digest = load_protocol(Path(DEFAULT_PROTOCOL))

    assert len(protocol["training_symbols"]) == 13
    assert len(protocol["holdout_symbols"]) == 20
    assert protocol["candidate_event"]["return_quantile"] == 0.01
    assert protocol["candidate_event"]["open_interest_quantile"] == 0.5
    assert protocol["joint_veto"]["minimum_up_probability"] == 0.55
    assert protocol["strict_gate"]["minimum_signals"] == 150
    assert protocol["strict_gate"]["minimum_supported_folds"] == 5
    assert len(digest) == 64
