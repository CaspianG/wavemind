from __future__ import annotations


def _row(symbol: str, timestamp: int, target_timestamp: int, **features):
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    return FeatureRow(symbol, timestamp, target_timestamp, -1, features, 1.0)


def test_calendar_folds_use_fixed_half_year_boundaries():
    from datetime import datetime, timezone

    from benchmarks.crypto_multiyear_event_benchmark import assign_calendar_folds

    def stamp(value: str) -> int:
        return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())

    rows = [
        _row("BTCUSDT", stamp("2023-12-31"), stamp("2024-01-01")),
        _row("BTCUSDT", stamp("2024-01-01"), stamp("2024-01-02")),
        _row("BTCUSDT", stamp("2024-07-01"), stamp("2024-07-02")),
        _row("BTCUSDT", stamp("2026-06-30"), stamp("2026-07-01")),
    ]

    assigned = assign_calendar_folds(rows)

    assert [row.fold_index for row in assigned] == [-1, 0, 1, 4]


def test_multiyear_market_features_add_breadth_without_future_values():
    from benchmarks.crypto_multiyear_event_benchmark import add_multiyear_market_features

    shared = {
        "return_6": 10.0,
        "return_36": 20.0,
        "return_180": 30.0,
        "volatility_36": 4.0,
        "volatility_180": 5.0,
        "volatility_6": 3.0,
        "oi_change_6": 6.0,
        "oi_change_36": 7.0,
        "global_ratio_log": 0.1,
        "funding_mean36_bps": 0.2,
        "premium_mean36_bps": 0.1,
        "taker_ratio_change6": 0.01,
    }
    rows = {
        "BTCUSDT": [_row("BTCUSDT", 1, 2, **shared)],
        "ETHUSDT": [
            _row(
                "ETHUSDT",
                1,
                2,
                **(shared | {"return_6": -10.0, "return_36": -20.0, "return_180": -30.0}),
            )
        ],
    }

    combined = add_multiyear_market_features(rows)

    assert len(combined) == 2
    assert combined[0].features["market_breadth_6"] == 0.5
    assert combined[0].features["market_return_180_mean"] == 0.0


def test_policy_threshold_requires_non_overlapping_evidence():
    from datetime import datetime, timedelta, timezone

    from benchmarks.crypto_multiyear_event_benchmark import _select_policy_threshold

    events = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(80):
        opened = start + timedelta(days=index)
        target = opened + timedelta(hours=1)
        events.append(
            {
                "engine": "field",
                "symbol": "BTCUSDT",
                "timeframe": "4h",
                "fold_index": 0,
                "data_end_utc": opened.isoformat(),
                "target_end_utc": target.isoformat(),
                "quality_probability": 0.8,
                "direction_hit": 1.0 if index < 64 else 0.0,
            }
        )

    threshold = _select_policy_threshold(events)

    assert 0.10 <= threshold <= 0.8


def test_nested_benchmark_runs_train_field_policy_and_future_test():
    import numpy as np
    import pytest

    pytest.importorskip("sklearn")

    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_multiyear_event_benchmark import BASE_FEATURES, run_multiyear_benchmark

    rng = np.random.default_rng(17)
    rows = []
    for timestamp in range(400):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            features = {name: float(rng.normal()) for name in BASE_FEATURES}
            future_return = float(rng.normal() * 100.0)
            rows.append(
                FeatureRow(
                    symbol=symbol,
                    timestamp=timestamp * 10,
                    target_timestamp=timestamp * 10 + 1,
                    fold_index=0 if timestamp >= 300 else -1,
                    features=features,
                    future_return_bps=future_return,
                )
            )

    payload = run_multiyear_benchmark(
        rows,
        horizon_seconds=1,
        calibration_timestamps=90,
    )

    assert len(payload["summaries"]) == 15
    assert len(payload["policies"]) == 15
    assert payload["admitted_70"] == []
    assert payload["admitted_80"] == []


def test_nested_benchmark_supports_optional_lightgbm_expert():
    import numpy as np
    import pytest

    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")

    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_multiyear_event_benchmark import BASE_FEATURES, run_multiyear_benchmark

    rng = np.random.default_rng(23)
    rows = []
    for timestamp in range(400):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            features = {name: float(rng.normal()) for name in BASE_FEATURES}
            rows.append(
                FeatureRow(
                    symbol=symbol,
                    timestamp=timestamp * 10,
                    target_timestamp=timestamp * 10 + 1,
                    fold_index=0 if timestamp >= 300 else -1,
                    features=features,
                    future_return_bps=float(rng.normal() * 100.0),
                )
            )

    payload = run_multiyear_benchmark(
        rows,
        horizon_seconds=1,
        calibration_timestamps=90,
        include_lightgbm=True,
    )

    assert payload["methodology"]["lightgbm_expert"] is True
    assert len(payload["summaries"]) == 16
    assert len(payload["policies"]) == 16
    assert any(row["engine"] == "LightGBM direction" for row in payload["summaries"])


def test_wavefield_outcome_direction_separates_simple_regimes():
    import numpy as np

    from benchmarks.crypto_multiyear_event_benchmark import (
        _wavefield_direction_scores,
    )

    rng = np.random.default_rng(71)
    down = rng.normal(loc=-1.0, scale=0.1, size=(60, 6))
    up = rng.normal(loc=1.0, scale=0.1, size=(60, 6))
    training = np.vstack((down, up))
    labels = np.asarray([0] * len(down) + [1] * len(up))

    scores = _wavefield_direction_scores(
        training,
        labels,
        (training,),
        feature_names=tuple(f"feature_{index}" for index in range(6)),
        seed=2027,
    )[0]

    assert np.all(np.isfinite(scores))
    assert float(np.mean(scores[labels == 1])) > float(
        np.mean(scores[labels == 0])
    )


def test_wavefield_regime_memory_separates_multimodal_outcomes():
    import numpy as np

    from benchmarks.crypto_multiyear_event_benchmark import (
        _wavefield_regime_memory_scores,
    )

    rng = np.random.default_rng(79)
    centers = np.asarray(
        [
            [-2.0, -2.0, 0.0, 0.0],
            [2.0, 2.0, 0.0, 0.0],
            [-2.0, 2.0, 0.0, 0.0],
            [2.0, -2.0, 0.0, 0.0],
        ]
    )
    labels_by_center = (0, 0, 1, 1)
    blocks = [
        rng.normal(loc=center, scale=0.12, size=(80, 4))
        for center in centers
    ]
    training = np.vstack(blocks)
    labels = np.concatenate(
        [
            np.full(len(block), label, dtype=int)
            for block, label in zip(blocks, labels_by_center, strict=True)
        ]
    )

    scores = _wavefield_regime_memory_scores(
        training,
        labels,
        (training,),
        feature_names=tuple(f"feature_{index}" for index in range(4)),
        seed=2027,
        max_regimes=8,
    )[0]

    assert np.all(np.isfinite(scores))
    assert float(np.mean(scores[labels == 1])) > 0.55
    assert float(np.mean(scores[labels == 0])) < 0.45
