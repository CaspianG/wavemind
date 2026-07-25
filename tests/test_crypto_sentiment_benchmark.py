from __future__ import annotations

import pytest


def test_sentiment_comparison_uses_identical_control_rows() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")

    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_fear_greed import FEAR_GREED_FEATURES
    from benchmarks.crypto_sentiment_benchmark import run_sentiment_comparison

    rng = np.random.default_rng(37)
    rows = []
    for timestamp in range(500):
        fold = -1 if timestamp < 200 else min((timestamp - 200) // 60, 4)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            sentiment = float(rng.normal())
            features = {
                "base": float(rng.normal()),
                "return_6": float(rng.normal()),
                "return_36": float(rng.normal()),
            }
            features.update({name: sentiment for name in FEAR_GREED_FEATURES})
            rows.append(
                FeatureRow(
                    symbol=symbol,
                    timestamp=timestamp * 10,
                    target_timestamp=timestamp * 10 + 1,
                    fold_index=fold,
                    features=features,
                    future_return_bps=float(rng.normal()),
                )
            )

    payload = run_sentiment_comparison(
        rows,
        horizon_seconds=1,
        base_feature_names=("base",),
        calibration_timestamps=120,
    )

    assert payload["methodology"]["rows"] == len(rows)
    assert payload["methodology"]["assets"] == ["BTCUSDT", "ETHUSDT"]
    assert len(payload["full_coverage_comparison"]) == 6
    assert len(payload["policy_comparison"]) == 6
    assert payload["baseline"]["methodology"]["feature_count"] == 1
    assert payload["sentiment"]["methodology"]["feature_count"] == (
        1 + len(FEAR_GREED_FEATURES)
    )
