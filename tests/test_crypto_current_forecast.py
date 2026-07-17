from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_completed_bars_excludes_incomplete_candle():
    from benchmarks.crypto_current_forecast import completed_bars

    rows = [
        [1_700_000_000_000, 100.0, 101.0, 99.0, 100.5, 10.0],
        [1_700_003_600_000, 101.0, 102.0, 100.0, 101.5, 11.0],
        [1_700_007_200_000, 102.0, 103.0, 101.0, 102.5, 12.0],
    ]

    bars = completed_bars(rows, timeframe="1h", now_ts=1_700_007_200)

    assert [bar.timestamp for bar in bars] == [1_700_000_000, 1_700_003_600]
    assert bars[-1].close == 101.5


def test_forecast_from_bars_computes_expected_price():
    from benchmarks.crypto_current_forecast import forecast_from_bars
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv

    bars = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="4h", bars=140, seed=23)
    result = forecast_from_bars(
        bars,
        symbol="BTC/USDT",
        exchange="synthetic",
        horizon_label="24h",
        timeframe="4h",
        horizon=6,
        engine_key="timeframe-policy",
        window=16,
        top_k=3,
        validation={"queries": 10, "active_direction_accuracy": 0.6},
        calibration_profile={
            "calibration": [
                {
                    "engine": "WaveMind timeframe policy",
                    "probability_ready": False,
                    "buckets": [
                        {
                            "range": [0.0, 1.0],
                            "count": 20,
                            "avg_evidence_strength": 0.5,
                            "direction_hit_rate": 0.65,
                            "calibration_error": 0.15,
                            "avg_net_return_bps": 12.0,
                        }
                    ],
                }
            ]
        },
    )

    expected_price = result.last_close * (1.0 + result.expected_return_bps / 10_000.0)

    assert result.engine == "WaveMind timeframe policy"
    assert result.horizon_label == "24h"
    assert result.horizon_bars == 6
    assert result.direction in {"up", "down", "flat"}
    assert result.decision in {"signal", "abstain"}
    assert result.candidate_direction in {"up", "down", "flat"}
    assert result.directional_direction in {"up", "down"}
    assert not math.isclose(result.directional_expected_return_bps, 0.0)
    assert result.directional_method
    assert result.directional_support >= 0
    assert math.isclose(result.expected_price, expected_price)
    candidate_expected_price = result.last_close * (1.0 + result.candidate_expected_return_bps / 10_000.0)
    assert math.isclose(result.candidate_expected_price, candidate_expected_price)
    directional_expected_price = result.last_close * (1.0 + result.directional_expected_return_bps / 10_000.0)
    assert math.isclose(result.directional_expected_price, directional_expected_price)
    assert math.isclose(result.evidence_strength, result.confidence)
    assert result.confidence_is_probability is False
    forecast_until = datetime.fromisoformat(result.forecast_until_utc)
    data_end = datetime.fromisoformat(result.data_end_utc)
    assert forecast_until - data_end == timedelta(hours=24)
    assert result.validation["active_direction_accuracy"] == 0.6
    assert result.calibration_bucket is not None
    assert result.calibration_bucket["direction_hit_rate"] == 0.65
    assert result.calibrated_probability is None
    assert result.probability_kind == "none"


def test_calibration_bucket_for_evidence_finds_matching_range():
    from benchmarks.crypto_current_forecast import calibration_bucket_for_evidence, calibrated_probability_for_evidence

    profile = {
        "calibration": [
            {
                "engine": "WaveMind timeframe policy",
                "probability_ready": True,
                "probability_kind": "base_rate",
                "base_rate_calibration": {"probability_ready": True, "base_rate_probability": 0.61},
                "monotonic_calibration": {
                    "blocks": [{"range": [0.5, 1.0], "calibrated_probability": 0.68}]
                },
                "buckets": [
                    {"range": [0.0, 0.5], "count": 3, "direction_hit_rate": 0.33},
                    {"range": [0.5, 1.0], "count": 7, "direction_hit_rate": 0.71},
                ],
            }
        ]
    }

    bucket = calibration_bucket_for_evidence(
        profile,
        engine_name="WaveMind timeframe policy",
        evidence_strength=0.62,
    )
    probability, kind = calibrated_probability_for_evidence(
        profile,
        engine_name="WaveMind timeframe policy",
        evidence_strength=0.62,
    )

    assert bucket is not None
    assert bucket["range"] == [0.5, 1.0]
    assert bucket["direction_hit_rate"] == 0.71
    assert bucket["base_rate_probability"] == 0.61
    assert bucket["monotonic_calibrated_probability"] == 0.68
    assert probability == 0.61
    assert kind == "base_rate"


def test_calibrated_probability_prefers_ready_monotonic_blocks():
    from benchmarks.crypto_current_forecast import calibrated_probability_for_evidence

    probability, kind = calibrated_probability_for_evidence(
        {
            "calibration": [
                {
                    "engine": "WaveMind timeframe policy",
                    "probability_ready": True,
                    "probability_kind": "monotonic",
                    "monotonic_calibration": {
                        "blocks": [
                            {"range": [0.0, 0.5], "calibrated_probability": 0.54},
                            {"range": [0.5, 1.0], "calibrated_probability": 0.67},
                        ]
                    },
                }
            ]
        },
        engine_name="WaveMind timeframe policy",
        evidence_strength=0.72,
    )

    assert probability == 0.67
    assert kind == "monotonic"


def test_guarded_state_direction_uses_downtrend_and_rsi_extremes():
    from benchmarks.crypto_current_forecast import guarded_state_direction

    assert guarded_state_direction({"trend": "down", "rsi": 20.0}, fallback_direction="up") == (
        "down",
        "established_downtrend",
    )
    assert guarded_state_direction({"trend": "up", "rsi": 72.0}, fallback_direction="up") == (
        "down",
        "overbought_reversion",
    )
    assert guarded_state_direction(
        {"trend": "up", "recent_trend": "up", "rsi": 50.0},
        fallback_direction="down",
    ) == ("up", "recent_state_direction")


def test_fetch_latest_completed_bars_uses_since_slack(monkeypatch):
    from benchmarks import crypto_current_forecast as forecast
    from benchmarks.crypto_ohlcv import OHLCVBar

    calls = []

    def fake_fetch_ohlcv_ccxt(**kwargs):
        calls.append(kwargs)
        now = int(datetime.now(timezone.utc).timestamp())
        return [
            OHLCVBar(
                timestamp=now - (8 - index) * 3600,
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=10.0 + index,
            )
            for index in range(8)
        ]

    monkeypatch.setattr(forecast, "fetch_ohlcv_ccxt", fake_fetch_ohlcv_ccxt)

    bars = forecast.fetch_latest_completed_bars(exchange_id="okx", symbol="BTC/USDT", timeframe="1h", limit=5)

    assert len(bars) == 5
    assert calls[0]["since"] is not None
    assert calls[0]["limit"] > 5
    assert bars[-1].timestamp > bars[0].timestamp


def test_fetch_latest_completed_bars_rejects_stale_exchange_data(monkeypatch):
    from benchmarks import crypto_current_forecast as forecast
    from benchmarks.crypto_ohlcv import OHLCVBar

    now = int(datetime.now(timezone.utc).timestamp())

    def fake_fetch_ohlcv_ccxt(**kwargs):
        return [
            OHLCVBar(
                timestamp=now - (20 - index) * 3600,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=10.0,
            )
            for index in range(8)
        ]

    monkeypatch.setattr(forecast, "fetch_ohlcv_ccxt", fake_fetch_ohlcv_ccxt)

    with pytest.raises(RuntimeError, match="Stale market data"):
        forecast.fetch_latest_completed_bars(
            exchange_id="okx",
            symbol="BTC/USDT",
            timeframe="1h",
            limit=5,
        )


def test_render_markdown_contains_price_target():
    from benchmarks.crypto_current_forecast import ForecastResult, render_markdown

    markdown = render_markdown(
        [
            ForecastResult(
                symbol="BTC/USDT",
                exchange="okx",
                timeframe="4h",
                horizon_label="24h",
                horizon_bars=6,
                engine="WaveMind timeframe policy",
                data_end_utc="2026-07-03T12:00:00+00:00",
                forecast_until_utc="2026-07-04T12:00:00+00:00",
                last_close=100_000.0,
                direction="up",
                decision="signal",
                candidate_direction="up",
                expected_return_bps=120.0,
                expected_return_pct=1.2,
                expected_price=101_200.0,
                candidate_expected_return_bps=120.0,
                candidate_expected_return_pct=1.2,
                candidate_expected_price=101_200.0,
                directional_direction="up",
                directional_expected_return_bps=140.0,
                directional_expected_return_pct=1.4,
                directional_expected_price=101_400.0,
                directional_method="regime_analogue_weighted",
                directional_support=32,
                directional_note="forced up/down research estimate",
                confidence=0.73,
                evidence_strength=0.73,
                calibration_bucket={"direction_hit_rate": 0.62},
                calibrated_probability=0.62,
                probability_kind="base_rate",
                filtered=False,
                filter_reason="",
                analogue_agreement=0.8,
                regime_agreement=0.6,
                latency_ms=2.0,
                validation={},
            )
        ]
    )

    assert "Research forecast from completed candles only" in markdown
    assert "Evidence strength is analogue/regime agreement" in markdown
    assert "market forecast" in markdown
    assert "trade validation" in markdown
    assert "policy candidate" in markdown
    assert "0.620" in markdown
    assert "base_rate" in markdown
    assert "BTC/USDT" in markdown
    assert "101400" in markdown
    assert "101200" in markdown
    assert "1.40%" in markdown


def test_crypto_current_forecast_cli_writes_json_and_markdown(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    bars_path = tmp_path / "unused.json"
    output = tmp_path / "forecast.json"
    report = tmp_path / "forecast.md"

    # The CLI fetches live data, so this test exercises the serialisation path
    # through a small in-process script with deterministic synthetic bars.
    script = tmp_path / "run_forecast.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "from benchmarks.crypto_current_forecast import forecast_from_bars, forecast_to_dict, render_markdown",
                "from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv",
                "bars = generate_synthetic_ohlcv(symbol='ETH/USDT', timeframe='4h', bars=120, seed=31)",
                "result = forecast_from_bars(bars, symbol='ETH/USDT', exchange='synthetic', horizon_label='24h', timeframe='4h', horizon=6, engine_key='timeframe-policy', window=16, top_k=3)",
                f"Path({str(output)!r}).write_text(json.dumps({{'results': [forecast_to_dict(result)]}}, indent=2) + '\\n', encoding='utf-8')",
                f"Path({str(report)!r}).write_text(render_markdown([result]), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run([sys.executable, str(script)], cwd=project_root, env=env, check=True)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["results"][0]["symbol"] == "ETH/USDT"
    assert payload["results"][0]["engine"] == "WaveMind timeframe policy"
    assert payload["results"][0]["decision"] in {"signal", "abstain"}
    assert payload["results"][0]["trade_decision"] in {"trade", "no_trade"}
    assert payload["results"][0]["market_forecast_direction"] in {"up", "down"}
    assert payload["results"][0]["market_forecast_target_price"] > 0.0
    assert payload["results"][0]["candidate_direction"] in {"up", "down", "flat"}
    assert payload["results"][0]["confidence_is_probability"] is False
    assert "not a calibrated probability" in payload["results"][0]["confidence_note"]
    assert payload["results"][0]["evidence_strength"] == payload["results"][0]["confidence"]
    assert payload["results"][0]["probability_kind"] == "none"
    assert payload["results"][0]["calibrated_probability"] is None
    assert "ETH/USDT" in report.read_text(encoding="utf-8")
    assert not bars_path.exists()
