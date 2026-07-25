from __future__ import annotations

import numpy as np

from benchmarks.crypto_online_wavefield_router import QueryPanel
from benchmarks.crypto_oos_stacking_benchmark import (
    _admitted_70,
    confidence_frontier,
    feature_matrix,
    prediction_summary,
)


def _panel(index: int, *, symbol: str = "BTCUSDT", actual: float = 1.0) -> QueryPanel:
    return QueryPanel(
        symbol=symbol,
        timeframe="4h",
        fold_index=3,
        query_id=f"q{index}",
        data_end_utc=f"2025-08-{index + 1:02d}T00:00:00+00:00",
        target_end_utc=f"2025-08-{index + 2:02d}T00:00:00+00:00",
        actual_return_bps=actual,
        predictions={
            "a": {
                "probability_up": 0.8,
                "quality_probability": 0.7,
                "event_probability": 0.6,
            },
            "b": {
                "probability_up": 0.4,
                "quality_probability": 0.5,
                "event_probability": 0.4,
            },
        },
    )


def test_feature_matrix_contains_experts_consensus_calendar_and_symbol() -> None:
    panels = [_panel(0), _panel(1, symbol="ETHUSDT")]

    matrix = feature_matrix(
        panels,
        experts=("a", "b"),
        symbols=("BTCUSDT", "ETHUSDT"),
    )

    assert matrix.shape == (2, 17)
    assert np.all(np.isfinite(matrix))
    assert matrix[0, -2:].tolist() == [1.0, 0.0]
    assert matrix[1, -2:].tolist() == [0.0, 1.0]


def test_confidence_frontier_uses_only_requested_validation_rows() -> None:
    panels = [_panel(index) for index in range(10)]
    probabilities = np.asarray([0.9] * 8 + [0.51, 0.49], dtype=float)

    frontier = confidence_frontier(
        panels,
        probabilities,
        min_signals=5,
        min_coverage=0.5,
    )

    assert frontier[0]["summary"]["signals"] == 10
    assert any(row["summary"]["signals"] == 8 for row in frontier)


def test_prediction_summary_and_admission_are_strict() -> None:
    panels = [_panel(index % 20, symbol=f"S{index % 5}", actual=1.0) for index in range(100)]
    summary = prediction_summary(panels, np.full(100, 0.9))

    assert summary["accuracy"] == 1.0
    assert _admitted_70(summary)
    assert not _admitted_70(summary | {"signals": 99})
