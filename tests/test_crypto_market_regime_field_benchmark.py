from __future__ import annotations

import numpy as np

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
from benchmarks.crypto_market_regime_field_benchmark import (
    MarketRegimePanel,
    _roc_auc,
    build_market_regime_panels,
    calibrate_decision_threshold,
    domain_adapt_fitted,
    fit_regime_candidates,
    online_topological_probabilities,
    regime_admitted,
    summarize_binary,
)


def test_market_panel_builder_aggregates_one_independent_day() -> None:
    rows = [
        FeatureRow(
            symbol=f"S{index}",
            timestamp=86_399,
            target_timestamp=172_799,
            fold_index=-1,
            features={"signal": float(index)},
            future_return_bps=float(index * 10 - 20),
        )
        for index in range(6)
    ]

    panels = build_market_regime_panels(
        rows,
        feature_names=("signal",),
        min_assets=6,
    )

    assert len(panels) == 1
    assert panels[0].features == (2.5, np.std(np.arange(6)), 0.5, 4.5)
    assert panels[0].future_market_return_bps == 5.0


def test_market_panel_builder_can_isolate_holdout_symbols() -> None:
    rows = [
        FeatureRow(
            symbol=f"S{index}",
            timestamp=86_399,
            target_timestamp=172_799,
            fold_index=-1,
            features={"signal": float(index)},
            future_return_bps=float(index),
        )
        for index in range(7)
    ]

    panels = build_market_regime_panels(
        rows,
        feature_names=("signal",),
        min_assets=6,
        target_symbols={f"S{index}" for index in range(1, 7)},
    )

    assert len(panels) == 1
    assert panels[0].future_market_return_bps == 3.5


def test_threshold_calibration_uses_balanced_accuracy() -> None:
    labels = np.asarray([0, 0, 0, 1, 1, 1])
    probabilities = np.asarray([0.1, 0.2, 0.4, 0.6, 0.8, 0.9])

    threshold = calibrate_decision_threshold(labels, probabilities)
    summary = summarize_binary(
        labels,
        probabilities,
        timestamps=[1_700_000_000 + index for index in range(6)],
        threshold=threshold,
    )

    assert summary["balanced_accuracy"] == 1.0
    assert summary["roc_auc"] == 1.0


def test_auc_handles_ties_without_external_dependency() -> None:
    labels = np.asarray([0, 0, 1, 1])
    probabilities = np.asarray([0.1, 0.5, 0.5, 0.9])

    assert _roc_auc(labels, probabilities) == 0.875


def test_regime_admission_rejects_majority_accuracy() -> None:
    accepted = {
        "episodes": 400,
        "accuracy": 0.72,
        "wilson_low_95": 0.67,
        "balanced_accuracy": 0.68,
        "roc_auc": 0.72,
        "worst_supported_year_balanced_accuracy": 0.62,
    }

    assert regime_admitted(accepted)
    assert not regime_admitted(accepted | {"balanced_accuracy": 0.50})


def test_online_field_does_not_use_unmatured_labels() -> None:
    rng = np.random.default_rng(41)
    training = [
        MarketRegimePanel(
            timestamp=index,
            target_timestamp=index + 1,
            features=tuple(rng.normal(size=8)),
            future_market_return_bps=float(index % 2),
            future_absolute_move_bps=1.0,
            future_dispersion_bps=1.0,
        )
        for index in range(120)
    ]
    train_labels = np.asarray([index % 2 for index in range(120)])
    fitted = fit_regime_candidates(training, train_labels, seed=2027)
    evaluation = [
        MarketRegimePanel(
            timestamp=200 + index * 10,
            target_timestamp=209 + index * 10,
            features=tuple(rng.normal(size=8)),
            future_market_return_bps=0.0,
            future_absolute_move_bps=1.0,
            future_dispersion_bps=1.0,
        )
        for index in range(8)
    ]
    labels = np.asarray([0, 1, 0, 1, 0, 1, 0, 1])
    changed = labels.copy()
    changed[-1] = 1 - changed[-1]

    original = online_topological_probabilities(
        fitted,
        evaluation,
        labels,
        seed=2027,
    )
    altered = online_topological_probabilities(
        fitted,
        evaluation,
        changed,
        seed=2027,
    )

    assert np.allclose(original, altered)


def test_domain_adaptation_changes_only_input_normalization() -> None:
    rng = np.random.default_rng(43)
    training = [
        MarketRegimePanel(
            timestamp=index,
            target_timestamp=index + 1,
            features=tuple(rng.normal(size=8)),
            future_market_return_bps=float(index % 2),
            future_absolute_move_bps=1.0,
            future_dispersion_bps=1.0,
        )
        for index in range(120)
    ]
    labels = np.asarray([index % 2 for index in range(120)])
    fitted = fit_regime_candidates(training, labels, seed=2027)
    shifted = [
        MarketRegimePanel(
            timestamp=200 + index,
            target_timestamp=201 + index,
            features=tuple(20.0 + rng.normal(size=8)),
            future_market_return_bps=0.0,
            future_absolute_move_bps=1.0,
            future_dispersion_bps=1.0,
        )
        for index in range(120)
    ]

    adapted = domain_adapt_fitted(fitted, shifted)

    assert adapted["pca"] is fitted["pca"]
    assert adapted["trees"] is fitted["trees"]
    assert not np.allclose(
        adapted["scaler"].mean_,
        fitted["scaler"].mean_,
    )
