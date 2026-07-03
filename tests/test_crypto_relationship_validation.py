import json
import os
import subprocess
import sys
from pathlib import Path


def test_crypto_relationship_validation_checks_future_windows():
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_relationship_miner import RelationshipMarket
    from benchmarks.crypto_relationship_validation import validate_relationships

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="4h", bars=180, seed=5)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="4h", window=16, horizon=3)
    payload = validate_relationships(
        [RelationshipMarket(symbol="BTC", timeframe="4h", bars=bars, windows=windows, source="synthetic")],
        train_windows=60,
        test_windows=16,
        folds=2,
        min_support=5,
        min_test_support=2,
        top_n=4,
        large_move_bps=40,
    )

    assert payload["scenario"]["name"] == "crypto_relationship_validation"
    assert payload["scenario"]["folds"] == 2
    assert payload["summary"]["validated_relationships"] > 0
    assert "sign_preservation_rate" in payload["summary"]
    assert payload["top_relationships"]
    assert "avg_signed_test_lift_bps" in payload["top_relationships"][0]
    assert payload["folds"][0]["train_windows"] > payload["folds"][0]["test_windows"]


def test_crypto_relationship_validation_cli_writes_json_and_report(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "validation.json"
    report = tmp_path / "validation.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_relationship_validation.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "4h",
            "--bars",
            "160",
            "--window",
            "16",
            "--horizon",
            "3",
            "--train-windows",
            "60",
            "--test-windows",
            "12",
            "--folds",
            "2",
            "--min-support",
            "4",
            "--min-test-support",
            "2",
            "--top-n",
            "4",
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

    assert payload["scenario"]["name"] == "crypto_relationship_validation"
    assert report.exists()
