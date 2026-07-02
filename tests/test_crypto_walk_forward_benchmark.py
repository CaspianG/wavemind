import json
import os
import subprocess
import sys
from pathlib import Path


def test_crypto_walk_forward_runs_core_engines(tmp_path):
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_walk_forward_benchmark import MarketDataset, run_walk_forward, write_analogue_html

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="1h", bars=140, seed=4)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="1h", window=16, horizon=3)
    payload = run_walk_forward(
        markets=[MarketDataset(symbol="BTC", timeframe="1h", bars=bars, windows=windows)],
        engines=["wavemind", "4h-profile", "risk-overlay", "regime-gated", "calibrated", "field-off", "shape", "naive", "ta"],
        train_windows=40,
        test_windows=12,
        top_k=3,
        fee_bps=8,
        slippage_bps=3,
        position_sizing="confidence",
        confidence_threshold=0.6,
        min_analogue_agreement=0.5,
        min_expected_edge_bps=12.0,
        gate_min_support=0.55,
        gate_min_regime_agreement=0.45,
        gate_performance_lookback=24,
        gate_min_historical_edge_bps=-5.0,
        risk_max_opposition=0.8,
        risk_min_regime_agreement=0.2,
        risk_min_historical_edge_bps=-50.0,
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}

    assert set(result_by_engine) == {
        "WaveMind field",
        "WaveMind 4h profile",
        "WaveMind risk-overlay",
        "WaveMind regime-gated",
        "WaveMind calibrated",
        "WaveMind field-off",
        "OHLCV shape kNN",
        "Naive last-regime",
        "TA rules",
    }
    assert result_by_engine["WaveMind field"]["queries"] == 12
    assert 0.0 <= result_by_engine["WaveMind field"]["direction_accuracy_at_1"] <= 1.0
    assert "mean_abs_mfe_error_bps" in result_by_engine["WaveMind field"]
    assert "mean_abs_mae_error_bps" in result_by_engine["WaveMind field"]
    assert "large_move_precision" in result_by_engine["WaveMind field"]
    assert "large_move_false_positive_rate" in result_by_engine["WaveMind field"]
    assert "avg_position_size" in result_by_engine["WaveMind field"]
    assert "avg_confidence" in result_by_engine["WaveMind calibrated"]
    assert "filtered_rate" in result_by_engine["WaveMind calibrated"]
    assert "filtered_rate" in result_by_engine["WaveMind regime-gated"]
    assert "filtered_rate" in result_by_engine["WaveMind risk-overlay"]
    assert "filtered_rate" in result_by_engine["WaveMind 4h profile"]
    assert 0.0 <= result_by_engine["WaveMind calibrated"]["filtered_rate"] <= 1.0
    assert "avg_sized_net_return_bps" in result_by_engine["WaveMind field"]
    assert 0.0 <= result_by_engine["WaveMind field"]["avg_position_size"] <= 1.0
    assert "avg_net_return_bps" in result_by_engine["OHLCV shape kNN"]
    assert payload["scenario"]["round_trip_cost_bps"] == 22.0
    assert payload["scenario"]["large_move_bps"] == 75.0
    assert payload["scenario"]["position_sizing"] == "confidence"
    assert payload["scenario"]["confidence_threshold"] == 0.6
    assert payload["scenario"]["min_analogue_agreement"] == 0.5
    assert payload["scenario"]["min_expected_edge_bps"] == 12.0
    assert payload["scenario"]["gate_min_support"] == 0.55
    assert payload["scenario"]["gate_min_regime_agreement"] == 0.45
    assert payload["scenario"]["gate_performance_lookback"] == 24
    assert payload["scenario"]["gate_min_historical_edge_bps"] == -5.0
    assert payload["scenario"]["risk_max_opposition"] == 0.8
    assert payload["scenario"]["risk_min_regime_agreement"] == 0.2
    assert payload["scenario"]["risk_min_historical_edge_bps"] == -50.0
    assert payload["scenario"]["regime_filter"] is True
    assert payload["analogue_samples"]
    assert "max_favorable_excursion_bps" in payload["analogue_samples"][0]["query"]
    assert "max_adverse_excursion_bps" in payload["analogue_samples"][0]["analogues"][0]
    assert "future_return_bps" not in payload["analogue_samples"][0]["analogues"][0]["text"]

    html_path = tmp_path / "analogues.html"
    write_analogue_html(payload, html_path)

    assert "WaveMind Crypto Analogue Explorer" in html_path.read_text(encoding="utf-8")
    assert "MFE bps" in html_path.read_text(encoding="utf-8")


def test_wavemind_engine_metrics_are_isolated_from_profile_engine(tmp_path):
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_walk_forward_benchmark import MarketDataset, run_walk_forward

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="4h", bars=150, seed=8)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="4h", window=16, horizon=3)
    market = MarketDataset(symbol="BTC", timeframe="4h", bars=bars, windows=windows)

    solo = run_walk_forward(
        markets=[market],
        engines=["wavemind"],
        train_windows=45,
        test_windows=12,
        top_k=3,
    )
    mixed = run_walk_forward(
        markets=[market],
        engines=["4h-profile", "wavemind"],
        train_windows=45,
        test_windows=12,
        top_k=3,
    )

    solo_field = next(result for result in solo["results"] if result["engine"] == "WaveMind field")
    mixed_field = next(result for result in mixed["results"] if result["engine"] == "WaveMind field")
    stable_keys = [
        "queries",
        "direction_accuracy_at_1",
        "direction_accuracy_at_3",
        "signal_rate",
        "avg_net_return_bps",
        "avg_sized_net_return_bps",
        "large_move_false_positive_rate",
    ]

    for key in stable_keys:
        assert mixed_field[key] == solo_field[key]


def test_crypto_walk_forward_supports_multiple_isolated_folds(tmp_path):
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks.crypto_walk_forward_benchmark import MarketDataset, run_walk_forward

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="4h", bars=160, seed=12)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="4h", window=16, horizon=3)
    payload = run_walk_forward(
        markets=[MarketDataset(symbol="BTC", timeframe="4h", bars=bars, windows=windows)],
        engines=["4h-profile", "wavemind", "naive"],
        train_windows=45,
        test_windows=8,
        folds=2,
        fold_stride=12,
        top_k=3,
        memory_store="memory",
    )

    result_by_engine = {result["engine"]: result for result in payload["results"]}

    assert payload["scenario"]["folds"] == 2
    assert payload["scenario"]["fold_stride"] == 12
    assert payload["scenario"]["memory_store"] == "memory"
    assert result_by_engine["WaveMind 4h profile"]["queries"] == 16
    assert result_by_engine["WaveMind field"]["queries"] == 16
    assert result_by_engine["Naive last-regime"]["queries"] == 16
    assert len(payload["by_market"]) == 6
    assert {item["fold_index"] for item in payload["by_market"]} == {0, 1}
    assert {item["fold_start"] for item in payload["by_market"]} == {45, 57}


def test_crypto_walk_forward_cli_writes_json_and_html(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "walk-forward.json"
    html_output = tmp_path / "analogues.html"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/crypto_walk_forward_benchmark.py",
            "--dataset",
            "synthetic",
            "--symbols",
            "BTC",
            "--timeframes",
            "1h",
            "--engines",
            "wavemind",
            "4h-profile",
            "risk-overlay",
            "regime-gated",
            "calibrated",
            "field-off",
            "shape",
            "naive",
            "ta",
            "--bars",
            "140",
            "--window",
            "16",
            "--horizon",
            "3",
            "--train-windows",
            "40",
            "--test-windows",
            "8",
            "--output",
            str(output),
            "--analogue-html",
            str(html_output),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["scenario"]["name"] == "crypto_walk_forward"
    assert payload["scenario"]["note"].startswith("Research walk-forward")
    assert payload["results"][0]["engine"] == "WaveMind field"
    assert payload["results"][1]["engine"] == "WaveMind 4h profile"
    assert payload["results"][2]["engine"] == "WaveMind risk-overlay"
    assert payload["results"][3]["engine"] == "WaveMind regime-gated"
    assert payload["results"][4]["engine"] == "WaveMind calibrated"
    assert payload["results"][5]["engine"] == "WaveMind field-off"
    assert html_output.exists()


def test_walk_forward_skips_optional_vector_dbs_when_missing(monkeypatch):
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows
    from benchmarks import crypto_walk_forward_benchmark as bench

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="1h", bars=90, seed=4)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="1h", window=12, horizon=3)
    original_create_engine = bench._create_engine

    def fail_create(engine_key, encoder, *, market, temp_root, **kwargs):
        if engine_key == "chroma":
            raise RuntimeError("chromadb is not installed; install the bench extra")
        return original_create_engine(engine_key, encoder, market=market, temp_root=temp_root, **kwargs)

    monkeypatch.setattr(bench, "_create_engine", fail_create)

    payload = bench.run_walk_forward(
        markets=[bench.MarketDataset(symbol="BTC", timeframe="1h", bars=bars, windows=windows)],
        engines=["chroma"],
        train_windows=25,
        test_windows=5,
    )

    assert payload["results"][0]["skipped"] is True
    assert "chromadb is not installed" in payload["results"][0]["skip_reason"]


def test_load_markets_from_ccxt_cache_without_network(tmp_path, monkeypatch):
    from argparse import Namespace
    from benchmarks.crypto_ohlcv import OHLCVBar, save_ohlcv_csv
    from benchmarks import crypto_walk_forward_benchmark as bench

    cache_dir = tmp_path / "ccxt-cache"
    cache_path = cache_dir / "okx" / "BTC_USDT_1h.csv"
    bars = [
        OHLCVBar(timestamp=1_700_000_000 + index * 3600, open=100 + index, high=101 + index, low=99 + index, close=100.5 + index, volume=10 + index)
        for index in range(70)
    ]
    save_ohlcv_csv(cache_path, bars)

    def fail_fetch(**kwargs):
        raise AssertionError("network fetch should not be called when cache exists")

    monkeypatch.setattr(bench, "fetch_ohlcv_ccxt", fail_fetch)

    markets = bench.load_markets_from_args(
        Namespace(
            dataset="ccxt",
            csv=None,
            exchange="okx",
            cache_dir=cache_dir,
            refresh_cache=False,
            symbols=["BTC/USDT"],
            timeframes=["1h"],
            bars=70,
            window=16,
            horizon=3,
            fee_bps=5,
            slippage_bps=2,
        )
    )

    assert len(markets) == 1
    assert markets[0].source == "ccxt_cache:okx"
    assert markets[0].source_path.endswith("BTC_USDT_1h.csv")
    assert len(markets[0].windows) > 0
