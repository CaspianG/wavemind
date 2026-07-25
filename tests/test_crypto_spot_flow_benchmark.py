from __future__ import annotations

import pytest


def test_spot_flow_comparison_uses_identical_rows() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")

    from benchmarks.crypto_binance_spot import SPOT_FLOW_FEATURES
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_spot_flow_benchmark import run_spot_flow_comparison

    rng = np.random.default_rng(59)
    rows = []
    for timestamp in range(500):
        fold = -1 if timestamp < 200 else min((timestamp - 200) // 60, 4)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            signal = float(rng.normal())
            rows.append(
                FeatureRow(
                    symbol=symbol,
                    timestamp=timestamp * 10,
                    target_timestamp=timestamp * 10 + 1,
                    fold_index=fold,
                    features={
                        "base": float(rng.normal()),
                        "return_6": float(rng.normal()),
                        "return_36": float(rng.normal()),
                    }
                    | {name: signal for name in SPOT_FLOW_FEATURES},
                    future_return_bps=float(rng.normal()),
                )
            )

    payload = run_spot_flow_comparison(
        rows,
        horizon_seconds=1,
        base_feature_names=("base",),
        calibration_timestamps=120,
    )

    assert payload["methodology"]["rows"] == len(rows)
    assert payload["baseline"]["methodology"]["feature_count"] == 1
    assert payload["spot_flow"]["methodology"]["feature_count"] == 12
    assert "spot_all" in payload["full_coverage_comparison"][0]
