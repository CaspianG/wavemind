from __future__ import annotations

import json
from datetime import datetime, timezone


def _forecast(**overrides):
    payload = {
        "forecast_id": "forecast-1",
        "symbol": "BTC/USDT",
        "exchange": "okx",
        "timeframe": "1h",
        "horizon_label": "24h",
        "data_end_utc": "2026-07-01T00:00:00+00:00",
        "forecast_until_utc": "2026-07-01T02:00:00+00:00",
        "last_close": 100.0,
        "market_forecast_direction": "up",
        "market_forecast_target_price": 105.0,
        "trade_decision": "trade",
    }
    payload.update(overrides)
    return payload


def test_evaluate_forecast_uses_target_candle_close_and_intrahorizon_touch():
    from benchmarks.crypto_forecast_audit import evaluate_forecast
    from benchmarks.crypto_ohlcv import OHLCVBar

    start = int(datetime(2026, 7, 1, 0, tzinfo=timezone.utc).timestamp())
    bars = [
        OHLCVBar(timestamp=start, open=100.0, high=106.0, low=99.0, close=103.0, volume=1.0),
        OHLCVBar(timestamp=start + 3600, open=103.0, high=104.0, low=101.0, close=102.0, volume=1.0),
    ]
    target = int(datetime(2026, 7, 1, 2, tzinfo=timezone.utc).timestamp())
    result = evaluate_forecast(_forecast(), bars, now_ts=target)

    assert result["outcome_status"] == "evaluated"
    assert result["actual_price"] == 102.0
    assert result["actual_direction"] == "up"
    assert result["direction_correct"] is True
    assert result["target_touched"] is True
    assert result["trade_direction_correct"] is True


def test_evaluate_forecast_keeps_unmatured_row_pending():
    from benchmarks.crypto_forecast_audit import evaluate_forecast

    result = evaluate_forecast(
        _forecast(),
        [],
        now_ts=int(datetime(2026, 7, 1, 1, tzinfo=timezone.utc).timestamp()),
    )

    assert result["outcome_status"] == "pending"
    assert result["seconds_until_maturity"] == 3600


def test_load_ledger_rejects_duplicate_forecast_ids(tmp_path):
    import pytest

    from benchmarks.crypto_forecast_audit import load_ledger

    path = tmp_path / "ledger.jsonl"
    first = _forecast(market_forecast_target_price=101.0)
    second = _forecast(market_forecast_target_price=102.0)
    path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate forecast_id"):
        load_ledger(path)


def test_append_forecast_ledger_is_idempotent(tmp_path):
    from benchmarks.crypto_current_forecast import append_forecast_ledger
    from benchmarks.crypto_forecast_ledger import read_ledger

    path = tmp_path / "ledger.jsonl"
    payload = {"generated_utc": "2026-07-01T00:01:00+00:00", "results": [_forecast()]}

    assert append_forecast_ledger(path, payload) == 1
    assert append_forecast_ledger(path, payload) == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    rows, integrity = read_ledger(path)
    assert rows[0]["ledger_schema_version"] == 2
    assert integrity.status == "verified"
    assert integrity.hashed_records == 1


def test_hash_chain_detects_legacy_prefix_tampering(tmp_path):
    import pytest

    from benchmarks.crypto_current_forecast import append_forecast_ledger
    from benchmarks.crypto_forecast_ledger import read_ledger

    path = tmp_path / "ledger.jsonl"
    legacy = _forecast()
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    new_forecast = _forecast(
        forecast_id="forecast-2",
        data_end_utc="2026-07-02T00:00:00+00:00",
        forecast_until_utc="2026-07-02T02:00:00+00:00",
    )

    assert append_forecast_ledger(
        path,
        {
            "generated_utc": "2026-07-02T00:01:00+00:00",
            "results": [new_forecast],
        },
    ) == 1
    _, integrity = read_ledger(path)
    assert integrity.anchored_legacy_records == 1

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["market_forecast_target_price"] = 999.0
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="previous_record_hash is invalid"):
        read_ledger(path)


def test_live_admission_requires_sample_size_wilson_and_symbol_robustness():
    from benchmarks.crypto_forecast_audit import live_admission_70

    rows = []
    for symbol_index in range(5):
        for sample_index in range(20):
            rows.append(
                {
                    "symbol": f"COIN{symbol_index}",
                    "direction_correct": sample_index < 16,
                }
            )

    assert live_admission_70(rows) is True
    assert live_admission_70(rows[:50]) is False


def test_summarize_by_model_keeps_model_versions_separate():
    from benchmarks.crypto_forecast_audit import summarize_by_model

    rows = [
        _forecast(directional_method="old", outcome_status="evaluated", direction_correct=False, target_touched=False, target_abs_return_error_bps=40.0),
        _forecast(forecast_id="forecast-2", directional_method="new", outcome_status="evaluated", direction_correct=True, target_touched=True, target_abs_return_error_bps=20.0),
    ]

    summaries = {row["model"]: row for row in summarize_by_model(rows)}

    assert summaries["old"]["market_direction_accuracy"] == 0.0
    assert summaries["new"]["market_direction_accuracy"] == 1.0


def test_summarize_by_model_groups_guard_reasons_under_one_version():
    from benchmarks.crypto_forecast_audit import summarize_by_model

    rows = [
        _forecast(directional_method="guarded_state_field_v1:established_downtrend+regime_analogue_weighted"),
        _forecast(
            forecast_id="forecast-2",
            directional_method="guarded_state_field_v1:recent_state_direction+regime_analogue_weighted",
        ),
    ]

    summaries = summarize_by_model(rows)

    assert len(summaries) == 1
    assert summaries[0]["model"] == "guarded_state_field_v1"
    assert summaries[0]["forecasts"] == 2
