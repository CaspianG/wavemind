from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
from benchmarks.crypto_signal_quality_benchmark import (
    DEFAULT_SIGNAL_TIERS,
    render_markdown,
    run_signal_quality_benchmark,
    sampled_signal_quality_payload,
)


def test_signal_quality_benchmark_builds_fixed_tiers():
    bars = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="4h", bars=180, seed=91)
    windows = make_ohlcv_windows(
        bars,
        symbol="BTC/USDT",
        timeframe="4h",
        window=16,
        horizon=6,
        direction_threshold_bps=0.0,
    )

    payload = run_signal_quality_benchmark(
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
        train_windows=60,
        test_windows=12,
        folds=2,
        fold_stride=18,
        calibration_windows=24,
    )

    results = {result["tier"]: result for result in payload["results"]}
    assert set(results) == {tier.name for tier in DEFAULT_SIGNAL_TIERS}
    assert payload["scenario"]["name"] == "crypto_signal_quality_walk_forward"
    assert payload["scenario"]["confidence_is_probability"] is False
    assert results["all_forecasts"]["selected_queries"] == 24
    assert results["all_forecasts"]["coverage"] == 1.0
    assert 0.0 <= results["strong_trade_quality"]["coverage"] <= 1.0
    assert 0.0 <= results["strong_trade_quality"]["direction_hit_rate"] <= 1.0
    assert results["strong_trade_quality"]["confidence_is_probability"] is False
    assert payload["event_metrics"][0]["confidence_is_probability"] is False
    assert payload["event_metrics"][0]["predicted_direction"] in {"up", "down"}
    assert payload["event_metrics"][0]["agreement"] >= 0.0
    assert payload["event_metrics"][0]["strength"] >= 0.0

    sampled = sampled_signal_quality_payload(payload, sample_size=3)
    assert sampled["event_metrics_total"] == len(payload["event_metrics"])
    assert sampled["event_metrics_sample_size"] == 3
    assert sampled["event_metrics_truncated"] is True
    assert len(sampled["event_metrics"]) == 3


def test_signal_quality_markdown_and_cli(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "signal-quality.json"
    report = tmp_path / "signal-quality.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_signal_quality_benchmark.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "4h",
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
    assert payload["results"][0]["tier"] == "all_forecasts"
    assert payload["event_metrics_total"] >= len(payload["event_metrics"])
    assert "event_metrics_truncated" in payload
    assert "WaveMind Crypto Signal Quality Benchmark" in markdown
    assert "not financial advice" in markdown.lower()
    assert "not a calibrated probability" in markdown
    assert render_markdown(payload).startswith("# WaveMind Crypto Signal Quality Benchmark")
