from __future__ import annotations

import math

from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
from benchmarks.crypto_prediction_interval_benchmark import (
    render_markdown,
    run_prediction_interval_benchmark,
    sampled_payload,
)
from benchmarks.crypto_prediction_intervals import (
    conformal_quantile,
    fit_prediction_interval,
    interval_score,
    mature_history,
    observable_return_scale,
)


def _windows(*, bars: int = 220):
    source = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="4h", bars=bars, seed=181)
    windows = make_ohlcv_windows(
        source,
        symbol="BTC/USDT",
        timeframe="4h",
        window=16,
        horizon=6,
        direction_threshold_bps=0.0,
    )
    return source, windows


def test_conformal_quantile_uses_finite_sample_correction():
    assert conformal_quantile([1.0, 2.0, 3.0, 4.0], nominal_coverage=0.80) == 4.0


def test_interval_score_penalizes_misses():
    covered = interval_score(0.0, -10.0, 10.0, nominal_coverage=0.80)
    missed = interval_score(20.0, -10.0, 10.0, nominal_coverage=0.80)

    assert covered == 20.0
    assert missed > covered


def test_prediction_interval_uses_only_mature_history():
    _, windows = _windows()
    query = windows[-1]
    observed_history = mature_history(windows, current=query)

    result = fit_prediction_interval(
        windows,
        query,
        predictor=lambda history, current: (
            sum(window.future_return_bps for window in history[-32:]) / max(1, len(history[-32:]))
        ),
        horizon=6,
        nominal_coverage=0.80,
        calibration_windows=80,
        min_prior_windows=16,
        min_calibration_samples=20,
    )

    assert observed_history
    assert all(window.future_end_ts <= query.end_ts for window in observed_history)
    assert result.status == "calibrated"
    assert result.calibration_samples >= 20
    assert result.lower_return_bps < result.upper_return_bps
    assert result.observable_scale_bps == observable_return_scale(query, horizon=6)
    assert 0.80 <= result.calibration_coverage <= 1.0


def test_prediction_interval_refuses_under_calibrated_output():
    _, windows = _windows(bars=80)
    query = windows[-1]

    result = fit_prediction_interval(
        windows,
        query,
        predictor=lambda history, current: 0.0,
        horizon=6,
        calibration_windows=20,
        min_prior_windows=24,
        min_calibration_samples=30,
    )

    assert result.status == "insufficient_calibration"
    assert math.isnan(result.lower_return_bps)
    assert math.isnan(result.upper_return_bps)


def test_interval_benchmark_scores_wave_and_baselines():
    bars, windows = _windows(bars=240)
    payload = run_prediction_interval_benchmark(
        markets=[
            {
                "symbol": "BTC/USDT",
                "timeframe": "4h",
                "horizon": 6,
                "bars": bars,
                "windows": windows,
                "source": "unit-test-fixture",
            }
        ],
        engines=["zero", "historical", "wavemind", "wavemind-risk"],
        train_windows=100,
        test_windows=12,
        folds=2,
        fold_stride=24,
        calibration_windows=48,
        nominal_coverage=0.80,
    )

    results = {row["engine"]: row for row in payload["results"]}
    assert payload["scenario"]["protocol"].startswith("walk-forward")
    assert results["Zero-return adaptive conformal"]["queries"] == 24
    assert results["Historical-median adaptive conformal"]["queries"] == 24
    assert results["WaveMind field adaptive conformal"]["queries"] == 24
    assert results["WaveMind risk-field adaptive conformal"]["queries"] == 24
    for row in results.values():
        assert 0.0 <= row["empirical_coverage"] <= 1.0
        assert row["mean_width_bps"] > 0.0
        assert row["mean_interval_score_bps"] > 0.0
        assert row["market_slices"] == 2
    assert len(payload["calibration"]) == 8
    assert len(payload["by_timeframe"]) == 4
    assert {row["timeframe"] for row in payload["by_timeframe"]} == {"4h"}
    assert payload["event_metrics"][0]["lower_price"] > 0.0
    assert payload["event_metrics"][0]["upper_price"] > payload["event_metrics"][0]["lower_price"]

    sampled = sampled_payload(payload, sample_size=5)
    assert sampled["event_metrics_total"] == 96
    assert sampled["event_metrics_sample_size"] == 5
    assert sampled["event_metrics_truncated"] is True
    assert "Lower interval score is better" in render_markdown(sampled)
