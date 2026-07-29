from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from benchmarks.crypto_asset_normalized_field_transfer_benchmark import (
    candidate_indices,
    prepare_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _row(
    symbol: str,
    timestamp: int,
    *,
    return_12: float,
    oi_change_1: float,
    future_return_bps: float = 100.0,
) -> FeatureRow:
    return FeatureRow(
        symbol=symbol,
        timestamp=timestamp,
        target_timestamp=timestamp + 86_400,
        fold_index=-1,
        features={
            "return_12": return_12,
            "oi_change_1": oi_change_1,
            "return_1": 0.0,
            "return_3": 0.0,
            "hour_sin": 0.0,
            "hour_cos": 1.0,
            "weekday_sin": 0.0,
            "weekday_cos": 1.0,
        },
        future_return_bps=future_return_bps,
    )


def test_prepare_rows_normalizes_each_asset_without_labels() -> None:
    start = _timestamp("2023-01-01")
    rows = [
        _row(
            symbol,
            start + index * 86_400,
            return_12=float(index + offset),
            oi_change_1=float(index),
            future_return_bps=100.0 if index % 2 else -100.0,
        )
        for symbol, offset in (("AAAUSDT", 0), ("BBBUSDT", 1000))
        for index in range(120)
    ]

    prepared = prepare_rows(rows, normalization_end="2024-01-01")
    return_column = prepared.feature_names.index("return_12")
    medians = [
        np.median(
            prepared.normalized[
                prepared.symbols == symbol,
                return_column,
            ]
        )
        for symbol in ("AAAUSDT", "BBBUSDT")
    ]

    assert np.allclose(medians, [0.0, 0.0])


def test_candidate_indices_use_per_asset_history_and_collapse_overlap() -> None:
    start = _timestamp("2023-01-01")
    test_start = _timestamp("2024-01-01")
    rows = [
        _row(
            symbol,
            start + index * 86_400,
            return_12=float(index),
            oi_change_1=float(index),
        )
        for symbol in ("AAAUSDT", "BBBUSDT")
        for index in range(365)
    ]
    rows.extend(
        [
            _row(
                symbol,
                test_start + offset,
                return_12=-100.0,
                oi_change_1=-100.0,
            )
            for symbol in ("AAAUSDT", "BBBUSDT")
            for offset in (0, 3_600, 90_000)
        ]
    )
    prepared = prepare_rows(rows, normalization_end="2024-01-01")

    selected = candidate_indices(
        prepared,
        start="2024-01-01",
        end="2024-01-03",
        return_quantile=0.01,
        oi_quantile=0.10,
    )

    assert len(selected) == 4
    assert {
        (prepared.symbols[index], prepared.timestamps[index])
        for index in selected
    } == {
        ("AAAUSDT", test_start),
        ("AAAUSDT", test_start + 90_000),
        ("BBBUSDT", test_start),
        ("BBBUSDT", test_start + 90_000),
    }
