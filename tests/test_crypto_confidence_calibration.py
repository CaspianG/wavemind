from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_calibration_by_engine_reports_probability_not_ready():
    from benchmarks.crypto_confidence_calibration import calibration_by_engine

    events = [
        {
            "engine": "WaveMind timeframe policy",
            "predicted_direction": "up",
            "confidence": 0.55,
            "direction_at_1": 1.0,
            "net_return_bps": 20.0,
            "sized_net_return_bps": 20.0,
        },
        {
            "engine": "WaveMind timeframe policy",
            "predicted_direction": "up",
            "confidence": 0.57,
            "direction_at_1": 0.0,
            "net_return_bps": -40.0,
            "sized_net_return_bps": -40.0,
        },
        {
            "engine": "WaveMind timeframe policy",
            "predicted_direction": "flat",
            "confidence": 0.0,
            "direction_at_1": 1.0,
            "net_return_bps": 0.0,
            "sized_net_return_bps": 0.0,
        },
    ]

    result = calibration_by_engine(events, bins=5)[0]

    assert result["engine"] == "WaveMind timeframe policy"
    assert result["signal_events"] == 2
    assert result["probability_ready"] is False
    assert result["probability_kind"] == "none"
    assert result["expected_calibration_error"] > 0.0
    assert sum(bucket["count"] for bucket in result["buckets"]) == 2
    assert "monotonic_calibration" in result
    assert "base_rate_calibration" in result
    assert "stability" in result


def test_calibration_by_engine_requires_stable_slices_for_probability():
    from benchmarks.crypto_confidence_calibration import calibration_by_engine

    events = []
    for fold_index in range(4):
        for symbol in ["BTC/USDT", "ETH/USDT"]:
            for timeframe in ["1h", "4h"]:
                for index in range(10):
                    hit = 1.0 if index < 6 else 0.0
                    events.append(
                        {
                            "engine": "WaveMind timeframe policy",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "fold_index": fold_index,
                            "predicted_direction": "up",
                            "confidence": 0.9,
                            "direction_at_1": hit,
                            "net_return_bps": 30.0 if hit else -25.0,
                            "sized_net_return_bps": 30.0 if hit else -25.0,
                        }
                    )

    result = calibration_by_engine(events, bins=5)[0]

    assert result["signal_events"] == 160
    assert result["probability_ready"] is True
    assert result["probability_kind"] in {"monotonic", "base_rate"}
    assert result["base_rate_calibration"]["probability_ready"] is True
    assert result["stability"]["fold"]["stable"] is True
    assert result["stability"]["symbol"]["stable"] is True
    assert result["stability"]["timeframe"]["stable"] is True


def test_calibration_rejects_probability_when_folds_are_unstable():
    from benchmarks.crypto_confidence_calibration import calibration_by_engine

    events = []
    fold_hits = {0: 36, 1: 4, 2: 20, 3: 20}
    for fold_index, hits in fold_hits.items():
        for index in range(40):
            hit = 1.0 if index < hits else 0.0
            events.append(
                {
                    "engine": "WaveMind timeframe policy",
                    "symbol": "BTC/USDT" if index % 2 == 0 else "ETH/USDT",
                    "timeframe": "4h",
                    "fold_index": fold_index,
                    "predicted_direction": "down",
                    "confidence": 0.5,
                    "direction_at_1": hit,
                    "net_return_bps": 40.0 if hit else -40.0,
                    "sized_net_return_bps": 40.0 if hit else -40.0,
                }
            )

    result = calibration_by_engine(events, bins=5)[0]

    assert result["signal_events"] == 160
    assert result["stability"]["fold"]["stable"] is False
    assert result["probability_ready"] is False
    assert result["probability_kind"] == "none"


def test_walk_forward_can_emit_event_metrics():
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_walk_forward_benchmark import MarketDataset, run_walk_forward

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="4h", bars=120, seed=44)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="4h", window=16, horizon=3)
    payload = run_walk_forward(
        markets=[MarketDataset(symbol="BTC", timeframe="4h", bars=bars, windows=windows)],
        engines=["timeframe-policy"],
        train_windows=40,
        test_windows=8,
        top_k=3,
        memory_store="memory",
        include_event_metrics=True,
    )

    assert len(payload["event_metrics"]) == 8
    assert payload["event_metrics"][0]["engine"] == "WaveMind timeframe policy"
    assert "confidence" in payload["event_metrics"][0]


def test_crypto_confidence_calibration_cli_writes_report(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "calibration.json"
    report = tmp_path / "calibration.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_confidence_calibration.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "4h",
            "--engines",
            "adaptive-field",
            "--bars",
            "120",
            "--window",
            "16",
            "--horizon",
            "3",
            "--train-windows",
            "40",
            "--test-windows",
            "8",
            "--bins",
            "4",
            "--adaptive-min-expected-edge-bps",
            "0",
            "--adaptive-min-recent-edge-bps",
            "-999",
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

    assert payload["calibration"][0]["engine"] == "WaveMind adaptive-field"
    assert "expected_calibration_error" in payload["calibration"][0]
    assert "stability" in payload["calibration"][0]
    assert "base_rate_calibration" in payload["calibration"][0]
    assert "WaveMind Crypto Confidence Calibration" in report.read_text(encoding="utf-8")
