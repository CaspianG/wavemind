import json
import os
import subprocess
import sys
from pathlib import Path


def test_crypto_relationship_miner_finds_explainable_regimes(tmp_path):
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_relationship_miner import (
        RelationshipMarket,
        mine_relationships,
        write_markdown_report,
    )

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="4h", bars=150, seed=3)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="4h", window=16, horizon=3)
    payload = mine_relationships(
        [RelationshipMarket(symbol="BTC", timeframe="4h", bars=bars, windows=windows, source="synthetic")],
        min_support=5,
        top_n=5,
        large_move_bps=40,
    )

    assert payload["scenario"]["name"] == "crypto_relationship_miner"
    assert payload["global"]["windows"] == len(windows)
    assert payload["top_positive"]
    assert payload["top_negative"]
    assert payload["top_large_move"]
    assert "relationship" in payload["top_positive"][0]
    assert "lift_vs_global_bps" in payload["top_positive"][0]

    report_path = tmp_path / "relationships.md"
    write_markdown_report(payload, report_path)

    report = report_path.read_text(encoding="utf-8")
    assert "WaveMind Crypto Relationship Report" in report
    assert "Top Positive Relationships" in report


def test_crypto_relationship_miner_cli_writes_json_and_report(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "relationships.json"
    report = tmp_path / "relationships.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_relationship_miner.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "4h",
            "--bars",
            "120",
            "--window",
            "16",
            "--horizon",
            "3",
            "--min-support",
            "4",
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

    assert payload["scenario"]["name"] == "crypto_relationship_miner"
    assert report.exists()
