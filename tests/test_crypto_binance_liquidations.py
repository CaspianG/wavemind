from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import replace
from pathlib import Path

from benchmarks.crypto_binance_liquidations import (
    LIQUIDATION_FEATURES,
    LiquidationPoint,
    add_liquidation_features,
    aggregate_liquidation_bars,
    load_liquidation_points,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def _archive(path: Path, rows: list[list[str]]) -> None:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        [
            "time",
            "side",
            "order_type",
            "time_in_force",
            "original_quantity",
            "price",
            "average_price",
            "order_status",
            "last_fill_quantity",
            "accumulated_fill_quantity",
        ]
    )
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("liquidations.csv", stream.getvalue())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".CHECKSUM").write_text(
        f"{digest}  {path.name}\n",
        encoding="utf-8",
    )


def _rows() -> list[FeatureRow]:
    return [
        FeatureRow(
            symbol="BTCUSDT",
            timestamp=(index + 1) * 14_400 - 1,
            target_timestamp=(index + 2) * 14_400 - 1,
            fold_index=0,
            features={"x": float(index)},
            future_return_bps=10.0 if index % 2 else -10.0,
        )
        for index in range(40)
    ]


def test_loader_deduplicates_exact_exchange_rows(tmp_path):
    path = tmp_path / "sample.zip"
    duplicated = [
        "1718424631025",
        "BUY",
        "LIMIT",
        "IOC",
        "2",
        "66532.6",
        "66294.6",
        "FILLED",
        "2",
        "2",
    ]
    _archive(path, [duplicated, duplicated])
    points = load_liquidation_points([path])
    assert len(points) == 1
    assert points[0].timestamp == 1_718_424_631


def test_aggregation_and_features_are_causal():
    points = [
        LiquidationPoint(14_500, "BUY", 5.0, 101.0, 100.0),
        LiquidationPoint(15_000, "SELL", 1.0, 99.0, 100.0),
    ]
    bars = aggregate_liquidation_bars(points)
    assert len(bars) == 1
    assert bars[0].timestamp == 14_400
    assert bars[0].buy_quantity == 5.0
    assert bars[0].sell_quantity == 1.0

    rows = _rows()
    first = add_liquidation_features(rows, bars)
    changed_future = [
        replace(row, future_return_bps=-row.future_return_bps) for row in rows
    ]
    second = add_liquidation_features(changed_future, bars)
    for left, right in zip(first, second, strict=True):
        for name in LIQUIDATION_FEATURES:
            assert left.features[name] == right.features[name]
    assert first[1].features["liquidation_log_count"] > 0.0


def test_missing_liquidations_are_zero_not_missing():
    enriched = add_liquidation_features(_rows(), [])
    assert all(
        all(name in row.features for name in LIQUIDATION_FEATURES)
        for row in enriched
    )
    assert enriched[-1].features["liquidation_log_quantity"] == 0.0
