from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


def _zip_bvol(path: Path, rows: list[dict[str, object]]) -> Path:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=["calc_time", "symbol", "base_asset", "quote_asset", "index_value"],
    )
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fixture.csv", buffer.getvalue())
    return path


def _stamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def test_bvol_archive_close_is_available_only_next_day(tmp_path: Path) -> None:
    from benchmarks.crypto_binance_bvol import load_bvol_daily_summary

    archive = _zip_bvol(
        tmp_path / "bvol.zip",
        [
            {
                "calc_time": _stamp("2026-06-30T00:00:00") * 1000,
                "symbol": "BTCBVOLUSDT",
                "base_asset": "BTCBVOL",
                "quote_asset": "USDT",
                "index_value": 40.0,
            },
            {
                "calc_time": _stamp("2026-06-30T23:59:59") * 1000,
                "symbol": "BTCBVOLUSDT",
                "base_asset": "BTCBVOL",
                "quote_asset": "USDT",
                "index_value": 44.0,
            },
        ],
    )

    summary = load_bvol_daily_summary(
        archive,
        underlying="BTCUSDT",
        index_symbol="BTCBVOLUSDT",
        trading_date=date(2026, 6, 30),
    )

    assert summary.open == 40.0
    assert summary.close == 44.0
    assert summary.available_timestamp == _stamp("2026-07-01T00:00:00")


def test_bvol_features_use_strict_asof_join() -> None:
    from benchmarks.crypto_binance_bvol import (
        BVolDailySummary,
        BVolDataset,
        add_bvol_features,
    )
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    summaries = []
    for offset in range(31):
        day = date(2026, 5, 31).toordinal() + offset
        trading_day = date.fromordinal(day)
        available = _stamp(
            datetime.combine(
                date.fromordinal(day + 1),
                datetime.min.time(),
            ).isoformat()
        )
        for underlying, index_symbol, level in (
            ("BTCUSDT", "BTCBVOLUSDT", 40.0 + offset),
            ("ETHUSDT", "ETHBVOLUSDT", 50.0 + offset),
        ):
            summaries.append(
                BVolDailySummary(
                    underlying=underlying,
                    index_symbol=index_symbol,
                    trading_date=trading_day.isoformat(),
                    available_timestamp=available,
                    first_timestamp=available - 86_400,
                    last_timestamp=available - 1,
                    open=level - 1.0,
                    close=level,
                    observations=86_400,
                    source_file="fixture.zip",
                )
            )
    dataset = BVolDataset(
        start_date="2026-05-31",
        end_date="2026-06-30",
        summaries=tuple(summaries),
        source_files=(),
        missing_source_files=(),
    )
    before = FeatureRow(
        "BTCUSDT",
        _stamp("2026-06-30T23:59:59"),
        _stamp("2026-07-01T23:59:59"),
        4,
        {"volatility_36": 100.0, "return_36": 1.0},
        1.0,
    )
    after = FeatureRow(
        "BTCUSDT",
        _stamp("2026-07-01T00:00:00"),
        _stamp("2026-07-02T00:00:00"),
        4,
        {"volatility_36": 100.0, "return_36": 1.0},
        1.0,
    )
    stale = FeatureRow(
        "BTCUSDT",
        _stamp("2026-07-10T00:00:00"),
        _stamp("2026-07-11T00:00:00"),
        4,
        {"volatility_36": 100.0, "return_36": 1.0},
        1.0,
    )

    enriched = add_bvol_features([before, after, stale], dataset, min_history=31)

    assert len(enriched) == 1
    assert enriched[0].timestamp == after.timestamp
    assert enriched[0].features["bvol_level"] == 70.0
    assert enriched[0].features["eth_bvol_level"] == 80.0


def test_bvol_feature_history_floor_is_enforced() -> None:
    from benchmarks.crypto_binance_bvol import BVolDataset, add_bvol_features

    with pytest.raises(ValueError, match="at least 7"):
        add_bvol_features([], BVolDataset("", "", (), (), ()), min_history=6)
    with pytest.raises(ValueError, match="max_age_days"):
        add_bvol_features([], BVolDataset("", "", (), (), ()), max_age_days=0)
