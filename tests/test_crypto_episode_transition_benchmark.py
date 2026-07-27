from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pytest

from benchmarks.crypto_bybit_capitulation_benchmark import ANALOGUE_FEATURES
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
from benchmarks.crypto_episode_transition_benchmark import (
    EXTRA_TREES_CONFIG,
    OI_QUANTILE,
    PCA_COMPONENTS,
    RETURN_QUANTILE,
    EpisodePanel,
    build_episode_panels,
    candidate_probabilities,
    evaluate_transition_models,
    summarize_probabilities,
    transition_admitted_70,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _timestamp(year: int, month: int, day: int) -> int:
    return int(
        datetime(year, month, day, tzinfo=timezone.utc).timestamp()
    )


def _row(
    *,
    symbol: str,
    timestamp: int,
    return_12: float,
    oi_change_1: float,
    future: float,
) -> FeatureRow:
    features = {
        name: float(index + 1)
        for index, name in enumerate(ANALOGUE_FEATURES)
    }
    features.update(
        {
            "return_1": return_12 / 12.0,
            "return_3": return_12 / 4.0,
            "return_12": return_12,
            "oi_change_1": oi_change_1,
        }
    )
    return FeatureRow(
        symbol=symbol,
        timestamp=timestamp,
        target_timestamp=timestamp + 86_400,
        fold_index=-1,
        features=features,
        future_return_bps=future,
    )


def test_episode_panels_are_aligned_and_do_not_embed_targets() -> None:
    rows = []
    for day in range(1, 7):
        timestamp = day * 86_400
        rows.extend(
            [
                _row(
                    symbol="A",
                    timestamp=timestamp,
                    return_12=-1_000.0 - day,
                    oi_change_1=-100.0 - day,
                    future=100.0 if day % 2 else -100.0,
                ),
                _row(
                    symbol="B",
                    timestamp=timestamp,
                    return_12=100.0,
                    oi_change_1=100.0,
                    future=-100.0,
                ),
            ]
        )
    panels, thresholds = build_episode_panels(
        rows,
        horizon_bars=6,
        calibration_end=5 * 86_400,
        return_quantile=0.49,
        oi_quantile=0.49,
    )
    changed_rows = [
        FeatureRow(
            symbol=row.symbol,
            timestamp=row.timestamp,
            target_timestamp=row.target_timestamp,
            fold_index=row.fold_index,
            features=row.features,
            future_return_bps=-row.future_return_bps,
        )
        for row in rows
    ]
    changed, _ = build_episode_panels(
        changed_rows,
        horizon_bars=6,
        calibration_end=5 * 86_400,
        return_quantile=0.49,
        oi_quantile=0.49,
    )

    assert panels
    assert len(panels) == len(changed)
    assert [panel.features for panel in panels] == [
        panel.features for panel in changed
    ]
    assert [panel.outcome_up for panel in panels] != [
        panel.outcome_up for panel in changed
    ]
    assert thresholds["return_threshold_bps"] < 0.0
    assert all(panel.timestamp % 86_400 == 0 for panel in panels)


def test_probability_summary_and_admission_are_strict() -> None:
    timestamps = [
        _timestamp(2025, 1, 1) + index * 86_400
        for index in range(50)
    ]
    summary = summarize_probabilities(
        np.ones(50, dtype=int),
        np.ones(50, dtype=float),
        timestamps=timestamps,
    )

    assert summary["accuracy"] == 1.0
    assert summary["wilson_low_95"] > 0.90
    assert transition_admitted_70(summary, uplift_vs_majority=0.10)
    assert not transition_admitted_70(summary, uplift_vs_majority=0.01)


def test_candidate_probabilities_are_bounded() -> None:
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(27)
    train_x = rng.normal(size=(80, 12))
    train_y = (train_x[:, 0] > 0.0).astype(int)
    evaluation_x = rng.normal(size=(15, 12))

    output = candidate_probabilities(
        train_x,
        train_y,
        evaluation_x,
        seed=27,
    )

    assert set(output) == {
        "majority",
        "logistic",
        "extra_trees",
        "knn",
        "wavefield",
        "field_tree_hybrid",
    }
    assert all(values.shape == (15,) for values in output.values())
    assert all(
        np.all((0.0 <= values) & (values <= 1.0))
        for values in output.values()
    )


def test_transition_evaluation_keeps_final_split_separate() -> None:
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(12)
    panels = []
    starts = (
        (_timestamp(2023, 1, 1), 80),
        (_timestamp(2024, 1, 1), 45),
        (_timestamp(2025, 1, 1), 50),
    )
    for start, count in starts:
        for index in range(count):
            features = rng.normal(size=10)
            outcome = bool(features[0] > 0.0)
            panels.append(
                EpisodePanel(
                    timestamp=start + index * 86_400,
                    target_timestamp=start + (index + 1) * 86_400,
                    features=tuple(float(value) for value in features),
                    future_return_bps=100.0 if outcome else -100.0,
                    outcome_up=outcome,
                    selected_assets=("TEST",),
                    available_assets=1,
                )
            )

    result = evaluate_transition_models(
        panels,
        train_end=_timestamp(2024, 1, 1),
        validation_end=_timestamp(2025, 1, 1),
        seed=12,
    )

    assert result["episodes"] == {
        "train": 80,
        "validation": 45,
        "final": 50,
    }
    assert result["selected_model"] in result["validation"]
    assert result["selected_final"] == result["final"][
        result["selected_model"]
    ]


def test_forward_protocol_matches_frozen_implementation() -> None:
    protocol = json.loads(
        (
            PROJECT_ROOT
            / "benchmarks/protocols/bybit_episode_transition_forward_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert protocol["horizon"] == "48h"
    assert protocol["event_policy"]["return_quantile"] == RETURN_QUANTILE
    assert protocol["event_policy"]["oi_quantile"] == OI_QUANTILE
    assert protocol["model"]["pca_components"] == PCA_COMPONENTS
    assert protocol["model"]["parameters"] == EXTRA_TREES_CONFIG
