from __future__ import annotations

import pytest

from benchmarks.crypto_capitulation_asset_transfer_benchmark import (
    FROZEN_TRANSFER_CONFIG,
    _aggregate_evidence_70,
    run_asset_transfer_benchmark,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _row(symbol: str) -> FeatureRow:
    return FeatureRow(
        symbol=symbol,
        timestamp=1,
        target_timestamp=2,
        fold_index=-1,
        features={},
        future_return_bps=1.0,
    )


def test_frozen_rule_is_the_predeclared_sparse_candidate():
    assert FROZEN_TRANSFER_CONFIG.return_quantile == 0.01
    assert FROZEN_TRANSFER_CONFIG.oi_quantile == 0.10
    assert FROZEN_TRANSFER_CONFIG.confirmation == "decelerating_selloff"


def test_asset_overlap_is_rejected_before_evaluation():
    with pytest.raises(ValueError, match="overlap"):
        run_asset_transfer_benchmark(
            [_row("BTCUSDT")],
            [_row("BTCUSDT")],
        )


def test_aggregate_gate_requires_wilson_support():
    summary = {
        "signals": 100,
        "accuracy": 0.75,
        "wilson_low_95": 0.66,
    }
    assert _aggregate_evidence_70(summary)
    assert not _aggregate_evidence_70(summary | {"wilson_low_95": 0.64})
