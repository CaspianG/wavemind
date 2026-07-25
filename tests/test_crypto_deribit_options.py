from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest


def _stamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def _trade(
    trade_id: str,
    *,
    kind: str,
    strike: float,
    iv: float,
    direction: str,
    amount: float,
    timestamp: int,
    currency: str = "BTC",
    expiry: str = "30JUN26",
):
    return {
        "trade_id": trade_id,
        "timestamp": timestamp * 1000,
        "instrument_name": f"{currency}-{expiry}-{strike:g}-{kind}",
        "index_price": 100.0,
        "iv": iv,
        "direction": direction,
        "amount": amount,
    }


def _summary(day: date, symbol: str, offset: int):
    from benchmarks.crypto_deribit_options import OptionsDailySummary

    available = int(
        datetime.combine(
            day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        ).timestamp()
    )
    return OptionsDailySummary(
        symbol=symbol,
        currency=symbol[:3],
        trading_date=day.isoformat(),
        available_timestamp=available,
        sampled_trades=100,
        sample_truncated=True,
        total_contracts=1000.0 + offset,
        atm_iv=50.0 + offset,
        otm_put_iv=60.0 + offset,
        otm_call_iv=45.0 + offset,
        skew_iv=15.0 + offset,
        term_spread_iv=2.0,
        put_call_log_ratio=0.2,
        directional_flow=0.01 * offset,
        source_sha256="a" * 64,
    )


def test_option_summary_extracts_skew_and_directional_flow():
    from benchmarks.crypto_deribit_options import summarize_option_trades

    observed = _stamp("2026-06-01T12:00:00")
    trades = [
        _trade(
            "p-buy",
            kind="P",
            strike=95,
            iv=70,
            direction="buy",
            amount=2,
            timestamp=observed,
            expiry="10JUN26",
        ),
        _trade(
            "c-buy",
            kind="C",
            strike=105,
            iv=50,
            direction="buy",
            amount=1,
            timestamp=observed,
            expiry="31JUL26",
        ),
        _trade(
            "atm",
            kind="C",
            strike=100,
            iv=55,
            direction="sell",
            amount=1,
            timestamp=observed,
            expiry="10JUN26",
        ),
        _trade(
            "back",
            kind="P",
            strike=90,
            iv=60,
            direction="sell",
            amount=1,
            timestamp=observed,
            expiry="31JUL26",
        ),
    ]

    summary = summarize_option_trades(
        trades,
        symbol="BTCUSDT",
        currency="BTC",
        trading_date=date(2026, 6, 1),
        source_sha256="b" * 64,
        sample_truncated=True,
    )

    assert summary is not None
    assert summary.available_timestamp == _stamp("2026-06-02T00:00:00")
    assert summary.skew_iv > 0.0
    assert summary.directional_flow < 0.0
    assert summary.sampled_trades == 4


def test_options_features_use_previous_day_only():
    from benchmarks.crypto_deribit_options import (
        OptionsDataset,
        add_options_features,
    )
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    start = date(2026, 4, 1)
    summaries = tuple(
        _summary(start + timedelta(days=offset), symbol, offset)
        for offset in range(31)
        for symbol in ("BTCUSDT", "ETHUSDT")
    )
    dataset = OptionsDataset(
        start_date=start.isoformat(),
        end_date=(start + timedelta(days=30)).isoformat(),
        sample_count=250,
        sample_windows=("open", "midday", "close"),
        summaries=summaries,
        source_endpoint="https://example.test",
        missing_days=(),
    )
    before = FeatureRow(
        "BTCUSDT",
        _stamp("2026-05-01T23:59:59"),
        _stamp("2026-05-02T23:59:59"),
        4,
        {},
        1.0,
    )
    after = FeatureRow(
        "BTCUSDT",
        _stamp("2026-05-02T00:00:00"),
        _stamp("2026-05-03T00:00:00"),
        4,
        {},
        1.0,
    )

    enriched = add_options_features([before, after], dataset, min_history=31)

    assert [row.timestamp for row in enriched] == [after.timestamp]
    assert enriched[0].features["options_skew_iv"] == pytest.approx(45.0)
    assert enriched[0].features["btc_options_skew_iv"] == pytest.approx(45.0)


def test_options_dataset_round_trip(tmp_path):
    from benchmarks.crypto_deribit_options import (
        OptionsDataset,
        load_options_dataset,
        save_options_dataset,
    )

    dataset = OptionsDataset(
        start_date="2026-01-01",
        end_date="2026-01-01",
        sample_count=250,
        sample_windows=("open", "midday", "close"),
        summaries=(_summary(date(2026, 1, 1), "BTCUSDT", 0),),
        source_endpoint="https://example.test",
        missing_days=("ETHUSDT:2026-01-01",),
    )
    path = tmp_path / "options.json.gz"
    save_options_dataset(path, dataset)

    assert load_options_dataset(path) == dataset


def test_options_dataset_merge_deduplicates_dates():
    from benchmarks.crypto_deribit_options import (
        OptionsDataset,
        merge_options_datasets,
    )

    left = OptionsDataset(
        "2026-01-01",
        "2026-01-02",
        250,
        ("open", "midday", "close"),
        (
            _summary(date(2026, 1, 1), "BTCUSDT", 0),
            _summary(date(2026, 1, 2), "BTCUSDT", 1),
        ),
        "https://example.test",
        (),
    )
    right = OptionsDataset(
        "2026-01-02",
        "2026-01-03",
        250,
        ("open", "midday", "close"),
        (
            _summary(date(2026, 1, 2), "BTCUSDT", 1),
            _summary(date(2026, 1, 3), "BTCUSDT", 2),
        ),
        "https://example.test",
        (),
    )

    merged = merge_options_datasets(left, right)

    assert merged.start_date == "2026-01-01"
    assert merged.end_date == "2026-01-03"
    assert len(merged.summaries) == 3


def test_options_downloader_fingerprints_and_caches_three_causal_windows(tmp_path):
    from benchmarks.crypto_deribit_options import download_options_dataset

    calls = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        observed = _stamp("2026-06-01T12:00:00")
        trades = [
            _trade(
                f"put-{len(calls)}",
                kind="P",
                strike=95,
                iv=60,
                direction="buy",
                amount=1,
                timestamp=observed,
                expiry="10JUN26",
            ),
            _trade(
                f"call-{len(calls)}",
                kind="C",
                strike=105,
                iv=50,
                direction="buy",
                amount=1,
                timestamp=observed,
                expiry="31JUL26",
            ),
            _trade(
                f"atm-{len(calls)}",
                kind="C",
                strike=100,
                iv=55,
                direction="sell",
                amount=1,
                timestamp=observed,
                expiry="10JUN26",
            ),
        ]
        return json.dumps(
            {"result": {"trades": trades, "has_more": True}}
        ).encode()

    dataset = download_options_dataset(
        symbols=("BTCUSDT",),
        start=date(2026, 6, 1),
        end=date(2026, 6, 1),
        workers=1,
        fetcher=fetcher,
        cache_dir=tmp_path / "cache",
    )
    repeated = download_options_dataset(
        symbols=("BTCUSDT",),
        start=date(2026, 6, 1),
        end=date(2026, 6, 1),
        workers=1,
        fetcher=lambda _: pytest.fail("cached response was not reused"),
        cache_dir=tmp_path / "cache",
    )

    assert len(calls) == 3
    assert len(dataset.summaries) == 1
    assert dataset.summaries[0].sample_truncated is True
    assert len(dataset.summaries[0].source_sha256) == 64
    assert repeated == dataset
    assert len(list((tmp_path / "cache" / "BTC").glob("*.json.gz"))) == 3


def test_options_feature_validation():
    from benchmarks.crypto_deribit_options import OptionsDataset, add_options_features

    empty = OptionsDataset("", "", 250, (), (), "", ())
    with pytest.raises(ValueError, match="at least 7"):
        add_options_features([], empty, min_history=6)
    with pytest.raises(ValueError, match="max_age_days"):
        add_options_features([], empty, max_age_days=0.0)
