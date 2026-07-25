from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import sys
import zipfile
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_binance_archive import _download_optional_checked  # noqa: E402
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


BINANCE_BVOL_ARCHIVE = "https://data.binance.vision/data/option/daily/BVOLIndex"
BVOL_INDEX_SYMBOLS = {
    "BTCUSDT": "BTCBVOLUSDT",
    "ETHUSDT": "ETHBVOLUSDT",
}
BVOL_FEATURES = (
    "bvol_level",
    "bvol_change_1d",
    "bvol_change_7d",
    "bvol_z_30d",
    "bvol_ma_ratio_30d",
    "btc_bvol_level",
    "btc_bvol_change_1d",
    "eth_bvol_level",
    "eth_bvol_change_1d",
    "bvol_eth_btc_spread",
    "bvol_realized_gap",
    "bvol_trend_interaction",
    "bvol_age_days",
)


@dataclass(frozen=True)
class BVolDailySummary:
    underlying: str
    index_symbol: str
    trading_date: str
    available_timestamp: int
    first_timestamp: int
    last_timestamp: int
    open: float
    close: float
    observations: int
    source_file: str


@dataclass(frozen=True)
class BVolDataset:
    start_date: str
    end_date: str
    summaries: tuple[BVolDailySummary, ...]
    source_files: tuple[str, ...]
    missing_source_files: tuple[str, ...]


def download_bvol_dataset(
    *,
    symbols: Sequence[str],
    start: date,
    end: date,
    cache_dir: str | Path,
    workers: int = 16,
    base_url: str = BINANCE_BVOL_ARCHIVE,
) -> BVolDataset:
    if start > end:
        raise ValueError("start must be on or before end")
    if workers <= 0:
        raise ValueError("workers must be positive")
    normalized = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
    unknown = sorted(set(normalized) - set(BVOL_INDEX_SYMBOLS))
    if unknown:
        raise ValueError("Unsupported BVOL underlyings: " + ", ".join(unknown))

    root = Path(cache_dir)
    specifications = [
        _archive_spec(
            underlying=underlying,
            index_symbol=BVOL_INDEX_SYMBOLS[underlying],
            day=day,
            root=root,
            base_url=base_url.rstrip("/"),
        )
        for underlying in normalized
        for day in _days(start, end)
    ]
    downloaded: list[tuple[str, str, date, Path]] = []
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_optional_checked,
                url=url,
                destination=destination,
            ): (underlying, index_symbol, day, destination, url)
            for underlying, index_symbol, day, destination, url in specifications
        }
        for future in as_completed(futures):
            underlying, index_symbol, day, destination, url = futures[future]
            path = future.result()
            if path is None:
                missing.append(url)
                continue
            downloaded.append((underlying, index_symbol, day, destination))

    summaries = [
        load_bvol_daily_summary(
            path,
            underlying=underlying,
            index_symbol=index_symbol,
            trading_date=day,
        )
        for underlying, index_symbol, day, path in sorted(
            downloaded,
            key=lambda row: (row[0], row[2]),
        )
    ]
    return BVolDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        summaries=tuple(summaries),
        source_files=tuple(str(row[3]) for row in sorted(downloaded)),
        missing_source_files=tuple(sorted(missing)),
    )


def load_bvol_daily_summary(
    path: str | Path,
    *,
    underlying: str,
    index_symbol: str,
    trading_date: date,
) -> BVolDailySummary:
    archive = Path(path)
    with zipfile.ZipFile(archive) as bundle:
        csv_names = [
            name for name in bundle.namelist() if name.lower().endswith(".csv")
        ]
        if len(csv_names) != 1:
            raise ValueError(
                f"Expected one BVOL CSV in {archive}, found {len(csv_names)}"
            )
        content = bundle.read(csv_names[0])
    first_break = content.find(b"\n")
    if first_break < 0:
        raise ValueError(f"BVOL archive has no data rows: {archive}")
    second_break = content.find(b"\n", first_break + 1)
    if second_break < 0:
        second_break = len(content)
    stripped = content.rstrip(b"\r\n")
    last_break = stripped.rfind(b"\n")
    if last_break < first_break:
        raise ValueError(f"BVOL archive has no data rows: {archive}")

    header = next(csv.reader(io.StringIO(content[:first_break].decode("utf-8-sig"))))
    expected = ["calc_time", "symbol", "base_asset", "quote_asset", "index_value"]
    if header != expected:
        raise ValueError(f"Unexpected BVOL columns in {archive}: {header}")
    first = _row_dict(header, content[first_break + 1 : second_break])
    last = _row_dict(header, stripped[last_break + 1 :])
    if first["symbol"] != index_symbol or last["symbol"] != index_symbol:
        raise ValueError(f"Unexpected BVOL symbol in {archive}")

    first_timestamp = _milliseconds(first["calc_time"])
    last_timestamp = _milliseconds(last["calc_time"])
    start_timestamp = _midnight(trading_date)
    end_timestamp = _midnight(trading_date + timedelta(days=1))
    if not (start_timestamp <= first_timestamp <= last_timestamp < end_timestamp):
        raise ValueError(f"BVOL timestamps escape trading date in {archive}")
    open_value = float(first["index_value"])
    close_value = float(last["index_value"])
    if not all(
        math.isfinite(value) and value > 0.0 for value in (open_value, close_value)
    ):
        raise ValueError(f"Invalid BVOL values in {archive}")

    observations = max(content.count(b"\n") - 1, 1)
    return BVolDailySummary(
        underlying=underlying,
        index_symbol=index_symbol,
        trading_date=trading_date.isoformat(),
        available_timestamp=end_timestamp,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        open=open_value,
        close=close_value,
        observations=observations,
        source_file=str(archive),
    )


def save_bvol_dataset(path: str | Path, dataset: BVolDataset) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "summaries": [asdict(row) for row in dataset.summaries],
        "source_files": list(dataset.source_files),
        "missing_source_files": list(dataset.missing_source_files),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_bvol_dataset(path: str | Path) -> BVolDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return BVolDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        summaries=tuple(BVolDailySummary(**row) for row in payload["summaries"]),
        source_files=tuple(str(item) for item in payload.get("source_files", [])),
        missing_source_files=tuple(
            str(item) for item in payload.get("missing_source_files", [])
        ),
    )


def add_bvol_features(
    rows: Sequence[FeatureRow],
    dataset: BVolDataset,
    *,
    min_history: int = 30,
    max_age_days: float = 3.0,
) -> list[FeatureRow]:
    if min_history < 7:
        raise ValueError("min_history must be at least 7 days")
    if max_age_days <= 0.0:
        raise ValueError("max_age_days must be positive")
    series = _feature_series(dataset)
    output = []
    for row in rows:
        own = series.get(row.symbol)
        btc = series.get("BTCUSDT")
        eth = series.get("ETHUSDT")
        if own is None or btc is None or eth is None:
            continue
        own_point = _asof(own, row.timestamp)
        btc_point = _asof(btc, row.timestamp)
        eth_point = _asof(eth, row.timestamp)
        if (
            own_point is None
            or btc_point is None
            or eth_point is None
            or int(own_point["history"]) < min_history
            or int(btc_point["history"]) < min_history
            or int(eth_point["history"]) < min_history
        ):
            continue
        ages = [
            (row.timestamp - int(point["available_timestamp"])) / 86_400.0
            for point in (own_point, btc_point, eth_point)
        ]
        if any(age < 0.0 or age > max_age_days for age in ages):
            continue
        realized_annualized = (
            float(row.features["volatility_36"]) * math.sqrt(6.0 * 365.0) / 100.0
        )
        additions = {
            "bvol_level": float(own_point["level"]),
            "bvol_change_1d": float(own_point["change_1d"]),
            "bvol_change_7d": float(own_point["change_7d"]),
            "bvol_z_30d": float(own_point["z_30d"]),
            "bvol_ma_ratio_30d": float(own_point["ma_ratio_30d"]),
            "btc_bvol_level": float(btc_point["level"]),
            "btc_bvol_change_1d": float(btc_point["change_1d"]),
            "eth_bvol_level": float(eth_point["level"]),
            "eth_bvol_change_1d": float(eth_point["change_1d"]),
            "bvol_eth_btc_spread": float(eth_point["level"] - btc_point["level"]),
            "bvol_realized_gap": float(own_point["level"] - realized_annualized),
            "bvol_trend_interaction": float(
                own_point["change_1d"] * row.features["return_36"] / 100.0
            ),
            "bvol_age_days": float(max(ages)),
        }
        output.append(
            FeatureRow(
                symbol=row.symbol,
                timestamp=row.timestamp,
                target_timestamp=row.target_timestamp,
                fold_index=row.fold_index,
                features=dict(row.features) | additions,
                future_return_bps=row.future_return_bps,
            )
        )
    return output


def _feature_series(
    dataset: BVolDataset,
) -> dict[str, tuple[tuple[int, Mapping[str, float]], ...]]:
    grouped: dict[str, list[BVolDailySummary]] = {}
    for summary in dataset.summaries:
        grouped.setdefault(summary.underlying, []).append(summary)
    output = {}
    for underlying, summaries in grouped.items():
        ordered = sorted(summaries, key=lambda row: row.available_timestamp)
        closes: list[float] = []
        points = []
        for summary in ordered:
            closes.append(float(summary.close))
            current = closes[-1]
            previous = closes[-2] if len(closes) >= 2 else current
            previous_7d = closes[-8] if len(closes) >= 8 else closes[0]
            window = np.asarray(closes[-30:], dtype=float)
            mean = float(np.mean(window))
            std = float(np.std(window))
            points.append(
                (
                    summary.available_timestamp,
                    {
                        "history": float(len(closes)),
                        "available_timestamp": float(summary.available_timestamp),
                        "level": current,
                        "change_1d": _log_change(current, previous),
                        "change_7d": _log_change(current, previous_7d),
                        "z_30d": (current - mean) / max(std, 1e-9),
                        "ma_ratio_30d": current / max(mean, 1e-9) - 1.0,
                    },
                )
            )
        output[underlying] = tuple(points)
    return output


def _asof(
    series: Sequence[tuple[int, Mapping[str, float]]],
    timestamp: int,
) -> Mapping[str, float] | None:
    position = bisect_right([row[0] for row in series], timestamp) - 1
    return None if position < 0 else series[position][1]


def _archive_spec(
    *,
    underlying: str,
    index_symbol: str,
    day: date,
    root: Path,
    base_url: str,
) -> tuple[str, str, date, Path, str]:
    filename = f"{index_symbol}-BVOLIndex-{day.isoformat()}.zip"
    destination = root / index_symbol / filename
    url = f"{base_url}/{index_symbol}/{filename}"
    return underlying, index_symbol, day, destination, url


def _row_dict(header: Sequence[str], content: bytes) -> dict[str, str]:
    values = next(csv.reader(io.StringIO(content.decode("utf-8").strip())))
    return dict(zip(header, values, strict=True))


def _log_change(current: float, previous: float) -> float:
    return math.log(max(current, 1e-9) / max(previous, 1e-9)) * 100.0


def _milliseconds(value: str) -> int:
    number = int(float(value))
    return number // 1000 if number >= 10_000_000_000 else number


def _midnight(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download checksum-verified Binance Options BVOL daily archives."
    )
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = download_bvol_dataset(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        workers=args.workers,
    )
    save_bvol_dataset(args.output, dataset)
    print(
        json.dumps(
            {
                "summaries": len(dataset.summaries),
                "source_files": len(dataset.source_files),
                "missing_source_files": len(dataset.missing_source_files),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
