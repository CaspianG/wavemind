from __future__ import annotations

import pytest


def test_bvol_comparison_runs_control_and_treatment_on_identical_rows() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")

    from benchmarks.crypto_bvol_benchmark import run_bvol_comparison
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    rng = np.random.default_rng(31)
    names = ("base",)
    rows = []
    for timestamp in range(500):
        fold = -1 if timestamp < 200 else min((timestamp - 200) // 60, 4)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            bvol = float(rng.normal())
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
                        "bvol_level": bvol,
                        "bvol_change_1d": bvol,
                        "bvol_change_7d": bvol,
                        "bvol_z_30d": bvol,
                        "bvol_ma_ratio_30d": bvol,
                        "btc_bvol_level": bvol,
                        "btc_bvol_change_1d": bvol,
                        "eth_bvol_level": bvol,
                        "eth_bvol_change_1d": bvol,
                        "bvol_eth_btc_spread": bvol,
                        "bvol_realized_gap": bvol,
                        "bvol_trend_interaction": bvol,
                        "bvol_age_days": 0.0,
                    },
                    future_return_bps=float(rng.normal()),
                )
            )

    payload = run_bvol_comparison(
        rows,
        horizon_seconds=1,
        base_feature_names=names,
        calibration_timestamps=120,
    )

    assert payload["methodology"]["rows"] == len(rows)
    assert payload["methodology"]["assets"] == ["BTCUSDT", "ETHUSDT"]
    assert len(payload["full_coverage_comparison"]) == 6
    assert len(payload["policy_comparison"]) == 6
    assert payload["baseline"]["methodology"]["feature_count"] == 1
    assert payload["bvol"]["methodology"]["feature_count"] == 14
