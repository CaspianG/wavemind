from __future__ import annotations

import csv
import gzip
import hashlib
import io
import urllib.error
import zipfile
from datetime import date

import pytest


def _zip_csv(name: str, rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, stream.getvalue())
    return output.getvalue()


def test_archive_parsers_read_normalized_binance_headers(tmp_path):
    from benchmarks.crypto_binance_archive import (
        load_funding_points,
        load_book_depth_points,
        load_futures_bars,
        load_futures_metrics,
        load_premium_points,
    )

    fixtures = {
        "bars.zip": [
            {
                "open_time": 1_700_000_000_000,
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 10,
                "close_time": 1_700_014_399_999,
                "quote_volume": 1000,
                "count": 50,
                "taker_buy_volume": 6,
                "taker_buy_quote_volume": 600,
                "ignore": 0,
            }
        ],
        "metrics.zip": [
            {
                "create_time": "2023-11-14 22:15:00",
                "symbol": "BTCUSDT",
                "sum_open_interest": 10,
                "sum_open_interest_value": 1000,
                "count_toptrader_long_short_ratio": 1.1,
                "sum_toptrader_long_short_ratio": 1.2,
                "count_long_short_ratio": 1.3,
                "sum_taker_long_short_vol_ratio": 0.9,
            }
        ],
        "funding.zip": [
            {"calc_time": 1_700_000_000_001, "funding_interval_hours": 8, "last_funding_rate": 0.0001}
        ],
        "premium.zip": [
            {
                "open_time": 1_700_000_000_000,
                "open": -0.001,
                "high": 0.001,
                "low": -0.002,
                "close": 0.0002,
                "volume": 0,
                "close_time": 1_700_014_399_999,
                "quote_volume": 0,
                "count": 1,
                "taker_buy_volume": 0,
                "taker_buy_quote_volume": 0,
                "ignore": 0,
            }
        ],
        "book_depth.zip": [
            {"timestamp": "2023-11-14 22:15:00", "percentage": "-5.00", "depth": 5, "notional": 5000},
            {"timestamp": "2023-11-14 22:15:00", "percentage": -1, "depth": 1, "notional": 1200},
            {"timestamp": "2023-11-14 22:15:00", "percentage": 1, "depth": 1, "notional": 900},
            {"timestamp": "2023-11-14 22:15:00", "percentage": 5, "depth": 5, "notional": 4500},
            {"timestamp": "2023-11-14 22:19:30", "percentage": -5, "depth": 5, "notional": 5100},
            {"timestamp": "2023-11-14 22:19:30", "percentage": -1, "depth": 1, "notional": 1300},
            {"timestamp": "2023-11-14 22:19:30", "percentage": 1, "depth": 1, "notional": 800},
            {"timestamp": "2023-11-14 22:19:30", "percentage": 5, "depth": 5, "notional": 4400},
        ],
    }
    paths = {}
    for filename, rows in fixtures.items():
        path = tmp_path / filename
        path.write_bytes(_zip_csv(filename.replace(".zip", ".csv"), rows))
        paths[filename] = path

    assert load_futures_bars(paths["bars.zip"])[0].close == 105.0
    assert load_futures_metrics(paths["metrics.zip"])[0].global_long_short_ratio == 1.3
    assert load_funding_points(paths["funding.zip"])[0].funding_rate == 0.0001
    assert load_premium_points(paths["premium.zip"])[0].close == 0.0002
    depth = load_book_depth_points(paths["book_depth.zip"])[0]
    assert depth.bid_notional_1pct == 1300.0
    assert depth.ask_notional_5pct == 4400.0


def test_checked_download_verifies_and_reuses_cache(tmp_path, monkeypatch):
    from benchmarks import crypto_binance_archive as archive

    payload = _zip_csv("fixture.csv", [{"value": 1}])
    checksum = hashlib.sha256(payload).hexdigest()
    calls = []

    def fake_read(url):
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            return f"{checksum}  fixture.zip\n".encode()
        return payload

    monkeypatch.setattr(archive, "_read_url", fake_read)
    destination = tmp_path / "fixture.zip"

    archive._download_checked(url="https://example/fixture.zip", destination=destination)
    archive._download_checked(url="https://example/fixture.zip", destination=destination)

    assert destination.read_bytes() == payload
    assert calls == ["https://example/fixture.zip.CHECKSUM", "https://example/fixture.zip"]


def test_optional_archive_only_tolerates_explicit_404(tmp_path, monkeypatch):
    from benchmarks import crypto_binance_archive as archive

    def missing(_url):
        raise RuntimeError("Archive request failed (404): fixture")

    monkeypatch.setattr(archive, "_read_url", missing)

    assert archive._download_optional_checked(
        url="https://example/missing.zip", destination=tmp_path / "missing.zip"
    ) is None

    monkeypatch.setattr(
        archive,
        "_read_url",
        lambda _url: (_ for _ in ()).throw(RuntimeError("Archive request failed (500): fixture")),
    )
    with pytest.raises(RuntimeError, match="500"):
        archive._download_optional_checked(
            url="https://example/broken.zip", destination=tmp_path / "broken.zip"
        )


def test_read_url_retries_transient_network_failure(monkeypatch):
    from benchmarks import crypto_binance_archive as archive

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"verified"

    def flaky_open(_request, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise urllib.error.URLError("temporary TLS failure")
        return Response()

    monkeypatch.setattr(archive.urllib.request, "urlopen", flaky_open)
    monkeypatch.setattr(archive.time, "sleep", lambda _seconds: None)

    assert archive._read_url("https://example/archive.zip") == b"verified"
    assert calls == [45, 45, 45]


def test_archive_spec_has_monthly_and_daily_sources():
    from benchmarks.crypto_binance_archive import _archive_specs

    specs = _archive_specs(
        symbol="BTCUSDT",
        timeframe="4h",
        start=date(2026, 1, 31),
        end=date(2026, 2, 2),
        base_url="https://data.example",
    )

    kinds = [kind for kind, _, _ in specs]
    assert kinds.count("klines") == 2
    assert kinds.count("intraday") == 2
    assert kinds.count("premium") == 2
    assert kinds.count("funding") == 2
    assert kinds.count("metrics") == 3
    assert kinds.count("book_depth") == 3
    assert any(
        kind == "intraday" and "/klines/BTCUSDT/5m/" in url
        for kind, _, url in specs
    )


def test_archive_spec_can_explicitly_exclude_book_depth():
    from benchmarks.crypto_binance_archive import _archive_specs

    specs = _archive_specs(
        symbol="BTCUSDT",
        timeframe="4h",
        start=date(2022, 1, 1),
        end=date(2022, 1, 2),
        base_url="https://data.example",
        sources=("klines", "premium", "funding", "metrics"),
    )

    assert {kind for kind, _, _ in specs} == {"klines", "premium", "funding", "metrics"}


def test_bundle_gzip_round_trip(tmp_path):
    from benchmarks.crypto_binance_archive import ArchiveBundle, FuturesBar, load_bundle, save_bundle

    bar = FuturesBar(1, 2, 1.0, 2.0, 0.5, 1.5, 10.0, 15.0, 3, 6.0, 9.0)
    bundle = ArchiveBundle(
        symbol="BTCUSDT",
        timeframe="4h",
        start_date="2022-01-01",
        end_date="2022-01-02",
        bars=(bar,),
        intraday_bars=(bar,),
        metrics=(),
        funding=(),
        premium=(),
        book_depth=(),
        source_files=("fixture.zip",),
        missing_source_files=(),
    )
    path = tmp_path / "bundle.json.gz"

    save_bundle(path, bundle)

    assert gzip.open(path, "rt", encoding="utf-8").read().startswith('{"symbol":"BTCUSDT"')
    assert load_bundle(path) == bundle


def test_metrics_parser_preserves_missing_values(tmp_path):
    from benchmarks.crypto_binance_archive import load_futures_metrics

    path = tmp_path / "metrics.zip"
    path.write_bytes(
        _zip_csv(
            "metrics.csv",
            [
                {
                    "create_time": "2026-01-01 00:05:00",
                    "symbol": "BTCUSDT",
                    "sum_open_interest": 10,
                    "sum_open_interest_value": 1000,
                    "count_toptrader_long_short_ratio": "",
                    "sum_toptrader_long_short_ratio": 1.2,
                    "count_long_short_ratio": 1.3,
                    "sum_taker_long_short_vol_ratio": "",
                }
            ],
        )
    )

    row = load_futures_metrics(path)[0]
    assert row.top_trader_account_ratio is None
    assert row.taker_long_short_ratio is None


def test_premium_parser_supports_legacy_headerless_archives(tmp_path):
    from benchmarks.crypto_binance_archive import load_premium_points

    path = tmp_path / "legacy-premium.zip"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "legacy.csv",
            "1640995200000,-0.0001,0.0007,-0.0008,-0.0004,0,1641009599999,0,2880,0,0,0\n",
        )
    path.write_bytes(output.getvalue())

    point = load_premium_points(path)[0]

    assert point.timestamp == 1_640_995_200
    assert point.close == -0.0004
