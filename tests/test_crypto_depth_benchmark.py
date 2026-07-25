from __future__ import annotations

import pytest


def test_depth_comparison_runs_control_and_treatment_on_identical_rows() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")

    from benchmarks.crypto_depth_benchmark import run_depth_comparison
    from benchmarks.crypto_derivatives_field_benchmark import (
        MICROSTRUCTURE_FEATURES,
        FeatureRow,
    )

    rng = np.random.default_rng(47)
    rows = []
    for timestamp in range(500):
        fold = -1 if timestamp < 200 else min((timestamp - 200) // 60, 4)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            depth = float(rng.normal())
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
                    | {name: depth for name in MICROSTRUCTURE_FEATURES},
                    future_return_bps=float(rng.normal()),
                )
            )

    payload = run_depth_comparison(
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
    assert payload["depth"]["methodology"]["feature_count"] == 11
    assert "depth_all" in payload["full_coverage_comparison"][0]
    assert "bvol_all" not in payload["full_coverage_comparison"][0]
