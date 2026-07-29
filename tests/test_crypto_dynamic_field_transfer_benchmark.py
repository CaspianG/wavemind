from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.crypto_dynamic_field_transfer_benchmark import (
    DEFAULT_PROTOCOL,
    _validate_asset_sets,
    summarize_diagnostic_ablations,
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


def test_diagnostic_ablations_use_the_frozen_probability_floor() -> None:
    events = [
        {
            "fold_index": 0,
            "symbol": "AAAUSDT",
            "timestamp": index * 86_400,
            "future_return_bps": future_return,
            "direction_hit": future_return > 0.0,
            "tree_probability_up": tree,
            "field_probability_up": field,
        }
        for index, (future_return, tree, field) in enumerate(
            [
                (100.0, 0.60, 0.70),
                (-100.0, 0.60, 0.40),
                (100.0, 0.40, 0.70),
                (-100.0, 0.40, 0.40),
            ]
        )
    ]

    result = summarize_diagnostic_ablations(events, threshold=0.55)

    assert result["all_candidates"]["summary"]["signals"] == 4
    assert result["extra_trees_only"]["summary"]["signals"] == 2
    assert result["wavefield_only"]["summary"]["signals"] == 2
    assert result["joint_veto"]["summary"]["signals"] == 1
