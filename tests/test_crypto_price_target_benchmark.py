from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
from benchmarks.crypto_price_target_benchmark import (
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
        engines=["wavemind-ensemble", "wavemind-calibrated", "wavemind-target", "momentum", "naive-last"],
        train_windows=60,
        test_windows=12,
        folds=2,
        fold_stride=18,
        calibration_windows=24,
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}
    assert payload["scenario"]["target"] == "predict future close price, not only up/down direction"
    assert result_by_engine["WaveMind ensemble target"]["queries"] == 24
    assert result_by_engine["WaveMind calibrated target"]["queries"] == 24
    assert result_by_engine["WaveMind price target"]["queries"] == 24
    assert result_by_engine["WaveMind ensemble target"]["mean_abs_return_error_bps"] >= 0.0
    assert 0.0 <= result_by_engine["WaveMind calibrated target"]["direction_hit_rate"] <= 1.0
    assert result_by_engine["WaveMind calibrated target"]["mean_abs_return_error_bps"] >= 0.0
    assert result_by_engine["WaveMind calibrated target"]["mape_pct"] >= 0.0
    assert "worst_slice_mape_pct" in result_by_engine["WaveMind calibrated target"]
    assert payload["event_metrics"][0]["predicted_price"] > 0.0
    assert payload["event_metrics"][0]["actual_price"] > 0.0
    assert payload["event_metrics"][0]["predicted_direction"] in {"up", "down"}

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
    assert payload["results"][0]["engine"] == "WaveMind ensemble target"
    assert payload["event_metrics_total"] >= len(payload["event_metrics"])
    assert "event_metrics_truncated" in payload
    assert "WaveMind Crypto Price Target Benchmark" in markdown
    assert "MAPE" in markdown
    assert render_markdown(payload).startswith("# WaveMind Crypto Price Target Benchmark")
