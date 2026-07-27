from __future__ import annotations

import numpy as np

from benchmarks.crypto_cross_sectional_field_benchmark import (
    CorrelationFieldProjector,
    CrossSectionalObservation,
    _topological_wavefield_probability,
    build_cross_sectional_observations,
    ranking_admitted_70,
    summarize_ranking,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def test_cross_sectional_builder_uses_one_completed_daily_snapshot() -> None:
    rows = []
    timestamp = 86_399
    for index in range(6):
        rows.append(
            FeatureRow(
                symbol=f"S{index}",
                timestamp=timestamp,
                target_timestamp=timestamp + 86_400,
                fold_index=-1,
                features={"signal": float(index)},
                future_return_bps=float(index * 10),
            )
        )
    rows.append(
        FeatureRow(
            symbol="ignored",
            timestamp=timestamp + 14_400,
            target_timestamp=timestamp + 100_800,
            fold_index=-1,
            features={"signal": 0.0},
            future_return_bps=0.0,
        )
    )

    observations = build_cross_sectional_observations(
        rows,
        feature_names=("signal",),
        min_assets=6,
    )

    assert len(observations) == 6
    assert sum(row.outperform for row in observations) == 3
    assert observations[0].excess_return_bps == -25.0


def test_ranking_summary_counts_days_not_assets_as_evidence() -> None:
    rows = []
    scores = []
    for day in range(2):
        timestamp = 86_399 + day * 86_400
        for index in range(6):
            rows.append(
                CrossSectionalObservation(
                    symbol=f"S{index}",
                    timestamp=timestamp,
                    target_timestamp=timestamp + 86_400,
                    features=(float(index),),
                    future_return_bps=float(index * 20),
                    excess_return_bps=float(index * 20 - 50),
                    outperform=index >= 3,
                )
            )
            scores.append(float(index))

    summary = summarize_ranking(rows, np.asarray(scores), cost_bps=10.0)

    assert summary["episodes"] == 2
    assert summary["spread_hit_rate"] == 1.0
    assert summary["asset_accuracy"] == 1.0
    assert summary["mean_net_spread_bps"] == 70.0


def test_admission_requires_independent_support_and_stability() -> None:
    accepted = {
        "episodes": 400,
        "spread_hit_rate": 0.72,
        "spread_wilson_low_95": 0.67,
        "worst_supported_year_hit_rate": 0.66,
        "mean_net_spread_bps": 12.0,
    }

    assert ranking_admitted_70(accepted)
    assert not ranking_admitted_70(accepted | {"episodes": 200})
    assert not ranking_admitted_70(
        accepted | {"worst_supported_year_hit_rate": 0.60}
    )


def test_correlation_projector_is_deterministic_and_sign_aware() -> None:
    rng = np.random.default_rng(19)
    training = rng.normal(size=(80, 6))
    projector = CorrelationFieldProjector(training, width=16, height=8)
    positive = projector.to_pattern(np.ones(6))
    negative = projector.to_pattern(-np.ones(6))

    assert positive.shape == (8, 16)
    assert np.allclose(np.linalg.norm(positive), 1.0)
    assert np.allclose(np.linalg.norm(negative), 1.0)
    assert not np.allclose(positive, negative)


def test_topological_wavefield_separates_simple_feature_regimes() -> None:
    rng = np.random.default_rng(29)
    down = rng.normal(loc=-1.0, scale=0.15, size=(80, 8))
    up = rng.normal(loc=1.0, scale=0.15, size=(80, 8))
    training = np.vstack((down, up))
    labels = np.asarray([0] * len(down) + [1] * len(up))

    probabilities = _topological_wavefield_probability(
        training,
        labels,
        training,
        seed=2027,
    )

    assert float(np.mean(probabilities[labels == 1])) > 0.55
    assert float(np.mean(probabilities[labels == 0])) < 0.45
