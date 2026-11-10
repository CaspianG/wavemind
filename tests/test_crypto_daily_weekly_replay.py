from dataclasses import replace
from datetime import datetime, timezone

import pytest

from benchmarks.crypto_ohlcv import OHLCVBar


DAY = 86400
START = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())


def bars(count=80):
    return [
        OHLCVBar(START + i * DAY, 100 + i, 102 + i, 99 + i, 101 + i, 10)
        for i in range(count)
    ]


def predictable(prefix, symbol):
    return {
        "research_return_bps": 100.0,
        "validated_return_bps": None,
        "filter_reason": "unsupported_timeframe:1d",
        "interval_lower_price": prefix[-1].close * 0.9,
        "interval_upper_price": prefix[-1].close * 1.1,
    }


def test_replay_hides_future_and_settles_exactly_seven_days_later():
    from benchmarks.crypto_daily_weekly_replay import replay_market

    seen = []

    def observer(prefix, symbol):
        seen.append(prefix)
        return predictable(prefix, symbol)

    rows = replay_market(
        bars(), symbol="BTC/USDT:USDT", start_ts=START + 40 * DAY,
        end_ts=START + 42 * DAY, as_of_ts=START + 80 * DAY,
        history_bars=32, predictor=observer,
    )
    assert len(rows) == 2
    assert seen[0][-1].timestamp + DAY == rows[0]["origin_ts"]
    assert len(seen[0]) == 32
    assert rows[0]["anchor_price"] == 140.0
    assert rows[0]["actual_price"] == 147.0
    assert rows[0]["target_ts"] - rows[0]["origin_ts"] == 7 * DAY


def test_future_price_mutation_does_not_change_forecast():
    from benchmarks.crypto_daily_weekly_replay import replay_market

    original = bars()
    changed = [
        replace(b, open=b.open * 2, high=b.high * 2, low=b.low * 2, close=b.close * 2)
        if b.timestamp >= START + 40 * DAY else b for b in original
    ]
    kwargs = dict(
        symbol="BTC/USDT:USDT", start_ts=START + 40 * DAY,
        end_ts=START + 41 * DAY, as_of_ts=START + 80 * DAY,
        history_bars=32, predictor=predictable,
    )
    first, second = replay_market(original, **kwargs)[0], replay_market(changed, **kwargs)[0]
    assert first["predictions"] == second["predictions"]
    assert first["input_snapshot_sha256"] == second["input_snapshot_sha256"]
    assert first["actual_price"] != second["actual_price"]


def test_replay_keeps_unmatured_forecasts_pending():
    from benchmarks.crypto_daily_weekly_replay import replay_market

    rows = replay_market(
        bars(), symbol="BTC/USDT:USDT", start_ts=START + 40 * DAY,
        end_ts=START + 42 * DAY, as_of_ts=START + 47 * DAY,
        history_bars=32, predictor=predictable,
    )
    assert rows[0]["outcome_status"] == "matured"
    assert rows[1]["outcome_status"] == "pending"
    assert rows[1]["actual_price"] is None


def test_replay_rejects_missing_daily_bars():
    from benchmarks.crypto_daily_weekly_replay import validate_daily_bars

    with pytest.raises(ValueError, match="gap"):
        validate_daily_bars(bars()[:40] + bars()[41:])


def test_replay_rejects_missing_already_matured_trailing_outcome():
    from benchmarks.crypto_daily_weekly_replay import replay_market

    with pytest.raises(ValueError, match="missing outcome"):
        replay_market(
            bars(46), symbol="BTC/USDT:USDT", start_ts=START + 40 * DAY,
            end_ts=START + 41 * DAY, as_of_ts=START + 50 * DAY,
            history_bars=32, predictor=predictable,
        )


def test_replay_fingerprint_changes_when_feature_dependency_changes(tmp_path):
    from benchmarks.crypto_daily_weekly_replay import replay_source_sha256

    dependency = tmp_path / "feature.py"
    dependency.write_text("version = 1\n", encoding="utf-8")
    first = replay_source_sha256([dependency])
    dependency.write_text("version = 2\n", encoding="utf-8")
    assert replay_source_sha256([dependency]) != first


def test_summary_does_not_call_last_price_a_directional_forecast():
    from benchmarks.crypto_daily_weekly_replay import replay_market, summarize

    rows = replay_market(
        bars(), symbol="BTC/USDT:USDT", start_ts=START + 40 * DAY,
        end_ts=START + 42 * DAY, as_of_ts=START + 80 * DAY,
        history_bars=32, predictor=predictable,
    )
    assert summarize(rows, "WaveMind research")["direction_accuracy"] == 1.0
    assert summarize(rows, "Last price")["direction_accuracy"] is None
    assert summarize(rows, "WaveMind validated")["forecasts"] == 0
    assert summarize(rows, "WaveMind validated")["coverage"] == 0
    assert summarize(rows, "Last price")["price_mape_pct"] > 0


def test_prediction_adapter_matches_existing_live_runner():
    from benchmarks.crypto_current_forecast import forecast_from_bars
    from benchmarks.crypto_daily_weekly_replay import predict_week
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv

    history = generate_synthetic_ohlcv(symbol="BTC/USDT:USDT", timeframe="1d", bars=100, seed=23)
    expected = forecast_from_bars(
        history, symbol="BTC/USDT:USDT", exchange="okx", horizon_label="7d",
        timeframe="1d", horizon=7, engine_key="timeframe-policy",
    )
    actual = predict_week(history, "BTC/USDT:USDT")
    assert actual["research_return_bps"] == expected.directional_expected_return_bps
    assert actual["interval_lower_price"] == expected.prediction_interval_lower_price
    assert actual["validated_return_bps"] is None
