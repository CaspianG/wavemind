from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
from benchmarks.crypto_temporal_field_benchmark import (
    TemporalFieldScale,
    _admitted,
    _events,
    _select_quality_threshold,
    encode_lagged_state_features,
    encode_temporal_field_features,
    render_markdown,
)


FEATURES = ("x", "y")
SCALES = (TemporalFieldScale("test", decay=0.95, speed=0.1, nonlin=0.01),)


def _rows(count: int = 24) -> list[FeatureRow]:
    return [
        FeatureRow(
            symbol="BTCUSDT",
            timestamp=index * 100,
            target_timestamp=index * 100 + 100,
            fold_index=0,
            features={"x": float(index % 5), "y": float((index * 3) % 7)},
            future_return_bps=10.0 if index % 2 else -10.0,
        )
        for index in range(count)
    ]


def test_temporal_features_are_deterministic_and_ignore_targets():
    rows = _rows()
    changed_targets = [
        replace(row, future_return_bps=-row.future_return_bps) for row in rows
    ]
    first, names = encode_temporal_field_features(
        rows,
        fit_rows=rows[:12],
        feature_names=FEATURES,
        scales=SCALES,
        seed=11,
        width=8,
        height=8,
        layers=2,
        pool_size=4,
    )
    second, second_names = encode_temporal_field_features(
        changed_targets,
        fit_rows=changed_targets[:12],
        feature_names=FEATURES,
        scales=SCALES,
        seed=11,
        width=8,
        height=8,
        layers=2,
        pool_size=4,
    )
    assert names == second_names
    assert set(first) == set(second)
    for key in first:
        np.testing.assert_allclose(first[key], second[key])


def test_future_features_do_not_change_prefix_state():
    rows = _rows()
    changed = list(rows)
    changed[-1] = replace(changed[-1], features={"x": 999.0, "y": -999.0})
    first, _ = encode_temporal_field_features(
        rows,
        fit_rows=rows[:12],
        feature_names=FEATURES,
        scales=SCALES,
        seed=17,
        width=8,
        height=8,
        layers=2,
        pool_size=4,
    )
    second, _ = encode_temporal_field_features(
        changed,
        fit_rows=rows[:12],
        feature_names=FEATURES,
        scales=SCALES,
        seed=17,
        width=8,
        height=8,
        layers=2,
        pool_size=4,
    )
    for row in rows[:-1]:
        np.testing.assert_allclose(
            first[(row.symbol, row.timestamp)],
            second[(row.symbol, row.timestamp)],
        )


def test_lagged_state_is_causal_and_does_not_use_current_row():
    rows = _rows()
    changed = list(rows)
    changed[-1] = replace(changed[-1], features={"x": 999.0, "y": -999.0})
    first, names = encode_lagged_state_features(
        rows,
        feature_names=FEATURES,
        lags=(1, 3),
    )
    second, second_names = encode_lagged_state_features(
        changed,
        feature_names=FEATURES,
        lags=(1, 3),
    )

    assert names == second_names
    assert len(names) == 4
    np.testing.assert_allclose(
        first[("BTCUSDT", rows[-1].timestamp)],
        second[("BTCUSDT", rows[-1].timestamp)],
        equal_nan=True,
    )


def test_lagged_state_validation_is_strict():
    rows = _rows()
    with pytest.raises(ValueError, match="feature_names"):
        encode_lagged_state_features(rows, feature_names=(), lags=(1,))
    with pytest.raises(ValueError, match="positive"):
        encode_lagged_state_features(rows, feature_names=FEATURES, lags=(0,))


def test_quality_threshold_uses_independent_policy_events():
    rows = _rows(80)
    probabilities = [0.9 if row.future_return_bps > 0 else 0.1 for row in rows]
    events = _events(
        "fixture",
        0,
        rows,
        probabilities,
        horizon_seconds=100,
    )
    assert _select_quality_threshold(events) <= 0.8


def test_admission_requires_every_slice_and_wilson():
    passing = {
        "selected": {
            "accuracy": 0.8,
            "signals": 100,
            "wilson_low_95": 0.71,
            "worst_fold_accuracy": 0.7,
            "worst_symbol_accuracy": 0.68,
        }
    }
    assert _admitted(passing, 0.7)
    failing = {
        "selected": passing["selected"] | {"worst_symbol_accuracy": 0.64}
    }
    assert not _admitted(failing, 0.7)


def test_report_discloses_nested_selection_and_admission():
    summary = {
        "engine": "Temporal WaveField Logistic",
        "all": {
            "signals": 100,
            "accuracy": 0.55,
        },
        "selected": {
            "signals": 40,
            "accuracy": 0.6,
            "wilson_low_95": 0.45,
            "worst_fold_accuracy": 0.5,
            "worst_symbol_accuracy": 0.5,
        },
    }
    report = render_markdown(
        {
            "methodology": {
                "horizon": "24h",
                "assets": ["BTCUSDT"],
            },
            "admitted_70": [],
            "summaries": [summary],
            "final_holdout_2026_h1": [
                summary | {"selected": summary["selected"] | {"accuracy": 0.575}}
            ],
        }
    )
    assert "admitted at 70%: none" in report
    assert "Test labels select nothing" not in report
    assert "Thresholds are chosen only from pre-test policy data" in report
