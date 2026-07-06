from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
from benchmarks.crypto_price_target_benchmark import (
    _cache_path,
    _default_directional_policy,
    _directional_candidate_values,
    _directional_head_feature_values,
    _perp_field_value_from_features,
    _market_field_value_from_features,
    _regime_policy_bucket_keys,
    _robust_1h_target_value,
    _robust_1d_target_value,
    load_markets,
    render_markdown,
    run_price_target_benchmark,
    sampled_event_payload,
)


def test_price_target_benchmark_scores_future_price():
    bars = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="4h", bars=180, seed=41)
    windows = make_ohlcv_windows(
        bars,
        symbol="BTC/USDT",
        timeframe="4h",
        window=16,
        horizon=6,
        direction_threshold_bps=0.0,
    )
    payload = run_price_target_benchmark(
        markets=[
            {
                "symbol": "BTC/USDT",
                "timeframe": "4h",
                "horizon": 6,
                "bars": bars,
                "windows": windows,
                "source": "synthetic",
            }
        ],
        engines=[
            "wavemind-market-field-target",
            "online-expert",
            "directional-head",
            "regime-policy",
            "wavemind-robust-target",
            "wavemind-ensemble",
            "wavemind-calibrated",
            "wavemind-target",
            "momentum",
            "naive-last",
        ],
        train_windows=60,
        test_windows=12,
        folds=2,
        fold_stride=18,
        calibration_windows=24,
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}
    assert payload["scenario"]["target"] == "predict future close price, not only up/down direction"
    assert result_by_engine["WaveMind market-field target"]["queries"] == 24
    assert result_by_engine["WaveMind online-expert target"]["queries"] == 24
    assert result_by_engine["WaveMind directional-head target"]["queries"] == 24
    assert result_by_engine["WaveMind regime-policy target"]["queries"] == 24
    assert result_by_engine["WaveMind robust target"]["queries"] == 24
    assert result_by_engine["WaveMind ensemble target"]["queries"] == 24
    assert result_by_engine["WaveMind calibrated target"]["queries"] == 24
    assert result_by_engine["WaveMind price target"]["queries"] == 24
    assert result_by_engine["WaveMind robust target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind online-expert target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind directional-head target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind regime-policy target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind market-field target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind ensemble target"]["mean_abs_return_error_bps"] >= 0.0
    assert 0.0 <= result_by_engine["WaveMind calibrated target"]["direction_hit_rate"] <= 1.0
    assert result_by_engine["WaveMind calibrated target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind calibrated target"]["mape_pct"] >= 0.0
    assert "worst_slice_mape_pct" in result_by_engine["WaveMind calibrated target"]
    assert payload["event_metrics"][0]["predicted_price"] > 0.0
    assert payload["event_metrics"][0]["actual_price"] > 0.0
    assert payload["event_metrics"][0]["predicted_direction"] in {"up", "down"}
    assert any("directional_head" in row for row in payload["by_market"])
    assert any("regime_target_policy" in row for row in payload["by_market"])

    sampled = sampled_event_payload(payload, sample_size=5)
    assert sampled["event_metrics_total"] == len(payload["event_metrics"])
    assert sampled["event_metrics_sample_size"] == 5
    assert sampled["event_metrics_truncated"] is True
    assert len(sampled["event_metrics"]) == 5


def test_price_target_loader_uses_cached_csv(tmp_path):
    cache_dir = tmp_path / "cache"
    source_dir = cache_dir / "okx"
    source_dir.mkdir(parents=True)
    bars = generate_synthetic_ohlcv(symbol="ETH/USDT", timeframe="1h", bars=90, seed=12)
    csv_path = source_dir / "ETH_USDT_1h.csv"
    from benchmarks.crypto_ohlcv import save_ohlcv_csv

    save_ohlcv_csv(csv_path, bars)

    markets = load_markets(
        dataset="cached",
        symbols=["ETH"],
        timeframes=["1h"],
        exchange="okx",
        cache_dir=cache_dir,
        bars=80,
        window=12,
    )

    assert markets[0]["symbol"] == "ETH/USDT"
    assert markets[0]["timeframe"] == "1h"
    assert markets[0]["horizon"] == 24
    assert len(markets[0]["windows"]) > 0


def test_learned_price_target_alias_runs_with_safe_fallback():
    bars = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="1h", bars=180, seed=52)
    windows = make_ohlcv_windows(
        bars,
        symbol="BTC/USDT",
        timeframe="1h",
        window=16,
        horizon=24,
        direction_threshold_bps=0.0,
    )

    payload = run_price_target_benchmark(
        markets=[
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "horizon": 24,
                "bars": bars,
                "windows": windows,
                "source": "synthetic",
            }
        ],
        engines=["learned-target", "wavemind-robust-target"],
        train_windows=95,
        test_windows=8,
        folds=1,
        calibration_windows=48,
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}
    assert result_by_engine["WaveMind learned target"]["queries"] == 8
    assert result_by_engine["WaveMind robust target"]["queries"] == 8
    assert result_by_engine["WaveMind learned target"]["mean_abs_return_error_bps"] >= 0.0
    assert payload["by_market"][0]["target_model"]["note"]


def test_regime_policy_falls_back_on_daily_horizon():
    bars = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="1d", bars=180, seed=71)
    windows = make_ohlcv_windows(
        bars,
        symbol="BTC/USDT",
        timeframe="1d",
        window=16,
        horizon=7,
        direction_threshold_bps=0.0,
    )

    payload = run_price_target_benchmark(
        markets=[
            {
                "symbol": "BTC/USDT",
                "timeframe": "1d",
                "horizon": 7,
                "bars": bars,
                "windows": windows,
                "source": "synthetic",
            }
        ],
        engines=["regime-policy", "wavemind-robust-target"],
        train_windows=95,
        test_windows=8,
        folds=1,
        calibration_windows=48,
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}
    assert result_by_engine["WaveMind regime-policy target"]["queries"] == 8
    assert result_by_engine["WaveMind robust target"]["queries"] == 8
    assert payload["by_market"][0]["regime_target_policy"]["enabled"] is False
    assert payload["by_market"][0]["regime_target_policy"]["note"] == "daily_horizon_requires_separate_policy"


def test_robust_1d_target_reduces_magnitude_in_high_risk_windows():
    calm = _robust_1d_target_value(
        calibrated_wave=300.0,
        momentum=180.0,
        regime=220.0,
        features={"volatility_bps": 20.0, "trend_slope_bps": 5.0},
    )
    volatile = _robust_1d_target_value(
        calibrated_wave=300.0,
        momentum=180.0,
        regime=220.0,
        features={"volatility_bps": 450.0, "trend_slope_bps": 180.0},
    )

    assert calm > 0.0
    assert volatile > 0.0
    assert abs(volatile) < abs(calm)


def test_robust_1h_target_uses_combo_sign_only_on_rsi_extremes():
    calm = _robust_1h_target_value(
        calibrated_wave=200.0,
        momentum=-80.0,
        naive=120.0,
        features={"rsi": 50.0},
    )
    extreme = _robust_1h_target_value(
        calibrated_wave=200.0,
        momentum=-80.0,
        naive=120.0,
        features={"rsi": 72.0},
    )

    assert calm < 0.0
    assert extreme > 0.0
    assert abs(calm) == abs(extreme)


def test_market_field_value_uses_timeframe_specific_reversion():
    features = {
        "raw_wave": 80.0,
        "calibrated_wave": 60.0,
        "momentum": 50.0,
        "regime": 40.0,
        "historical": 30.0,
    }

    one_hour, one_hour_note = _market_field_value_from_features(features, "1h")
    four_hour, four_hour_note = _market_field_value_from_features(features, "4h")
    one_day, one_day_note = _market_field_value_from_features(features, "1d")

    assert one_hour == -40.0
    assert four_hour == -50.0
    assert one_day == -30.0
    assert "intraday_regime_reversion" in one_hour_note
    assert "swing_momentum_reversion" in four_hour_note
    assert "daily_historical_reversion" in one_day_note


def test_perp_field_uses_fold_local_selected_candidate():
    features = {
        "raw_wave": 80.0,
        "calibrated_wave": 60.0,
        "momentum": 50.0,
        "regime": 40.0,
        "historical": 30.0,
        "naive": 20.0,
    }
    policy = _default_directional_policy("test")
    policy = policy.__class__(
        selected_candidate="inv_regime",
        validation_direction_hit=0.72,
        validation_mae_bps=123.0,
        samples=42,
        candidate_direction_hit={"inv_regime": 0.72},
        candidate_mae_bps={"inv_regime": 123.0},
        note="test",
    )

    value, note = _perp_field_value_from_features(features, "1h", policy)

    assert value == -40.0
    assert "inv_regime" in note
    assert "validation_hit=0.720" in note
    assert _directional_candidate_values(features, "1h")["inv_historical"] == -30.0


def test_directional_head_features_include_signals_and_agreements():
    features = {
        "raw_wave": 80.0,
        "calibrated_wave": 60.0,
        "momentum": -50.0,
        "regime": 40.0,
        "historical": 30.0,
        "naive": 20.0,
        "support_log": 2.0,
        "rsi": 72.0,
        "range_bps": 200.0,
        "volatility_bps": 50.0,
    }

    values = _directional_head_feature_values(features, "1h")

    assert values["robust_sign"] in {-1.0, 1.0}
    assert values["momentum_sign"] == -1.0
    assert values["rsi_signed_distance"] == 22.0
    assert values["volatility_range_ratio"] == 0.25
    assert values["support_signed_wave"] == 2.0


def test_regime_policy_bucket_keys_are_specific_then_broad():
    features = {
        "trend_code": 1.0,
        "recent_trend_code": -1.0,
        "rsi": 72.0,
        "volatility_bps": 250.0,
        "drawdown_bps": -320.0,
        "close_position": 0.9,
        "range_compression": 0.6,
    }

    keys = _regime_policy_bucket_keys(features, "4h")

    assert keys[0] == "tf=4h|trend=up|recent=down|rsi=overbought|vol=high|dd=pullback|close=high"
    assert keys[-1] == "tf=4h|vol=high"
    assert len(keys) == len(set(keys))


def test_cache_path_sanitizes_perpetual_symbols(tmp_path):
    path = _cache_path(tmp_path, "okx", "HYPE/USDT:USDT", "1h")

    assert path.name == "HYPE_USDT_USDT_1h.csv"
    assert ":" not in path.name


def test_price_target_markdown_and_cli(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "price-target.json"
    report = tmp_path / "price-target.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_price_target_benchmark.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "4h",
            "--engines",
            "wavemind-market-field-target",
            "online-expert",
            "directional-head",
            "regime-policy",
            "perp-field",
            "wavemind-robust-target",
            "wavemind-ensemble",
            "wavemind-calibrated",
            "wavemind-target",
            "momentum",
            "--bars",
            "150",
            "--window",
            "16",
            "--train-windows",
            "50",
            "--test-windows",
            "8",
            "--folds",
            "2",
            "--fold-stride",
            "12",
            "--calibration-windows",
            "20",
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    markdown = report.read_text(encoding="utf-8")
    assert payload["results"][0]["engine"] == "WaveMind market-field target"
    assert any(result["engine"] == "WaveMind online-expert target" for result in payload["results"])
    assert any(result["engine"] == "WaveMind directional-head target" for result in payload["results"])
    assert any(result["engine"] == "WaveMind regime-policy target" for result in payload["results"])
    assert any(result["engine"] == "WaveMind perp field target" for result in payload["results"])
    assert payload["event_metrics_total"] >= len(payload["event_metrics"])
    assert "event_metrics_truncated" in payload
    assert "WaveMind Crypto Price Target Benchmark" in markdown
    assert "MAPE" in markdown
    assert render_markdown(payload).startswith("# WaveMind Crypto Price Target Benchmark")
