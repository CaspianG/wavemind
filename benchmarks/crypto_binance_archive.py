from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVBar  # noqa: E402


BINANCE_ARCHIVE = "https://data.binance.vision/data/futures/um"
ARCHIVE_SOURCES = (
    "klines",
    "intraday",
    "premium",
    "funding",
    "metrics",
    "book_depth",
)
INTRADAY_TIMEFRAME = "5m"
KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)


@dataclass(frozen=True)
class FuturesBar:
    timestamp: int
    close_timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int
    taker_buy_volume: float
    taker_buy_quote_volume: float

    def as_ohlcv(self) -> OHLCVBar:
        return OHLCVBar(
            timestamp=self.timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


@dataclass(frozen=True)
class FuturesMetric:
    timestamp: int
    open_interest: float | None
    open_interest_value: float | None
    top_trader_account_ratio: float | None
    top_trader_position_ratio: float | None
    global_long_short_ratio: float | None
    taker_long_short_ratio: float | None


@dataclass(frozen=True)
class FundingPoint:
    timestamp: int
    interval_hours: int
    funding_rate: float


@dataclass(frozen=True)
class PremiumPoint:
    timestamp: int
    close_timestamp: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BookDepthPoint:
    timestamp: int
    bid_notional_1pct: float
    ask_notional_1pct: float
    bid_notional_5pct: float
    ask_notional_5pct: float


@dataclass(frozen=True)
class ArchiveBundle:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    bars: tuple[FuturesBar, ...]
    intraday_bars: tuple[FuturesBar, ...]
    metrics: tuple[FuturesMetric, ...]
    funding: tuple[FundingPoint, ...]
    premium: tuple[PremiumPoint, ...]
    book_depth: tuple[BookDepthPoint, ...]
    source_files: tuple[str, ...]
    missing_source_files: tuple[str, ...]


def download_archive_bundle(
    *,
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    cache_dir: str | Path,
    workers: int = 12,
    base_url: str = BINANCE_ARCHIVE,
    sources: Sequence[str] = ARCHIVE_SOURCES,
) -> ArchiveBundle:
    if start > end:
        raise ValueError("start must be on or before end")
    if workers <= 0:
        raise ValueError("workers must be positive")
    normalized_symbol = symbol.upper().replace("/", "").replace(":USDT", "")
    requested_sources = tuple(dict.fromkeys(str(source) for source in sources))
    unknown_sources = sorted(set(requested_sources) - set(ARCHIVE_SOURCES))
    if unknown_sources:
        raise ValueError("Unknown archive sources: " + ", ".join(unknown_sources))
    if "klines" not in requested_sources:
        raise ValueError("klines source is required")
    root = Path(cache_dir)
    specifications = _archive_specs(
        symbol=normalized_symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        base_url=base_url.rstrip("/"),
        sources=requested_sources,
    )
    downloaded: dict[str, Path] = {}
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_optional_checked if kind == "book_depth" else _download_checked,
                url=url,
                destination=root / relative,
            ): (kind, url)
            for kind, relative, url in specifications
        }
        for future in as_completed(futures):
            _, url = futures[future]
            path = future.result()
            if path is None:
                missing.append(url)
                continue
            downloaded[str(path)] = path

    bars: list[FuturesBar] = []
    intraday_bars: list[FuturesBar] = []
    metrics: list[FuturesMetric] = []
    funding: list[FundingPoint] = []
    premium: list[PremiumPoint] = []
    book_depth: list[BookDepthPoint] = []
    for kind, relative, _ in specifications:
        path = root / relative
        if not path.exists():
            continue
        if kind == "klines":
            bars.extend(load_futures_bars(path))
        elif kind == "intraday":
            intraday_bars.extend(load_futures_bars(path))
        elif kind == "metrics":
            metrics.extend(load_futures_metrics(path))
        elif kind == "funding":
            funding.extend(load_funding_points(path))
        elif kind == "premium":
            premium.extend(load_premium_points(path))
        elif kind == "book_depth":
            book_depth.extend(load_book_depth_points(path))
    return ArchiveBundle(
        symbol=normalized_symbol,
        timeframe=timeframe,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        bars=tuple(_dedupe(bars, key=lambda row: row.timestamp)),
        intraday_bars=tuple(_dedupe(intraday_bars, key=lambda row: row.timestamp)),
        metrics=tuple(_dedupe(metrics, key=lambda row: row.timestamp)),
        funding=tuple(_dedupe(funding, key=lambda row: row.timestamp)),
        premium=tuple(_dedupe(premium, key=lambda row: row.timestamp)),
        book_depth=tuple(_dedupe(book_depth, key=lambda row: row.timestamp)),
        source_files=tuple(sorted(downloaded)),
        missing_source_files=tuple(sorted(missing)),
    )


def save_bundle(path: str | Path, bundle: ArchiveBundle) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": bundle.symbol,
        "timeframe": bundle.timeframe,
        "start_date": bundle.start_date,
        "end_date": bundle.end_date,
        "bars": [asdict(row) for row in bundle.bars],
        "intraday_bars": [asdict(row) for row in bundle.intraday_bars],
        "metrics": [asdict(row) for row in bundle.metrics],
        "funding": [asdict(row) for row in bundle.funding],
        "premium": [asdict(row) for row in bundle.premium],
        "book_depth": [asdict(row) for row in bundle.book_depth],
        "source_files": list(bundle.source_files),
        "missing_source_files": list(bundle.missing_source_files),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_bundle(path: str | Path) -> ArchiveBundle:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return ArchiveBundle(
        symbol=str(payload["symbol"]),
        timeframe=str(payload["timeframe"]),
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        bars=tuple(FuturesBar(**row) for row in payload["bars"]),
        intraday_bars=tuple(FuturesBar(**row) for row in payload.get("intraday_bars", [])),
        metrics=tuple(FuturesMetric(**row) for row in payload["metrics"]),
        funding=tuple(FundingPoint(**row) for row in payload["funding"]),
        premium=tuple(PremiumPoint(**row) for row in payload["premium"]),
        book_depth=tuple(BookDepthPoint(**row) for row in payload.get("book_depth", [])),
        source_files=tuple(str(item) for item in payload.get("source_files", [])),
        missing_source_files=tuple(str(item) for item in payload.get("missing_source_files", [])),
    )


def load_futures_bars(path: str | Path) -> list[FuturesBar]:
    return [
        FuturesBar(
            timestamp=_milliseconds(row["open_time"]),
            close_timestamp=_milliseconds(row["close_time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            quote_volume=float(row["quote_volume"]),
            trades=int(row["count"]),
            taker_buy_volume=float(row["taker_buy_volume"]),
            taker_buy_quote_volume=float(row["taker_buy_quote_volume"]),
        )
        for row in _zip_csv_rows(path, fieldnames=KLINE_COLUMNS)
    ]


def load_futures_metrics(path: str | Path) -> list[FuturesMetric]:
    return [
        FuturesMetric(
            timestamp=_utc_seconds(row["create_time"]),
            open_interest=_optional_float(row["sum_open_interest"]),
            open_interest_value=_optional_float(row["sum_open_interest_value"]),
            top_trader_account_ratio=_optional_float(row["count_toptrader_long_short_ratio"]),
            top_trader_position_ratio=_optional_float(row["sum_toptrader_long_short_ratio"]),
            global_long_short_ratio=_optional_float(row["count_long_short_ratio"]),
            taker_long_short_ratio=_optional_float(row["sum_taker_long_short_vol_ratio"]),
        )
        for row in _zip_csv_rows(
            path,
            fieldnames=(
                "create_time",
                "symbol",
                "sum_open_interest",
                "sum_open_interest_value",
                "count_toptrader_long_short_ratio",
                "sum_toptrader_long_short_ratio",
                "count_long_short_ratio",
                "sum_taker_long_short_vol_ratio",
            ),
        )
    ]


def load_funding_points(path: str | Path) -> list[FundingPoint]:
    return [
        FundingPoint(
            timestamp=_milliseconds(row["calc_time"]),
            interval_hours=int(row["funding_interval_hours"]),
            funding_rate=float(row["last_funding_rate"]),
        )
        for row in _zip_csv_rows(
            path,
            fieldnames=("calc_time", "funding_interval_hours", "last_funding_rate"),
        )
    ]


def load_premium_points(path: str | Path) -> list[PremiumPoint]:
    return [
        PremiumPoint(
            timestamp=_milliseconds(row["open_time"]),
            close_timestamp=_milliseconds(row["close_time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in _zip_csv_rows(path, fieldnames=KLINE_COLUMNS)
    ]


def load_book_depth_points(path: str | Path) -> list[BookDepthPoint]:
    snapshots: dict[int, dict[int, float]] = {}
    for row in _zip_csv_rows(path):
        timestamp = _utc_seconds(row["timestamp"])
        percentage = int(float(row["percentage"]))
        if percentage not in {-5, -1, 1, 5}:
            continue
        snapshots.setdefault(timestamp, {})[percentage] = float(row["notional"])
    buckets: dict[int, BookDepthPoint] = {}
    for timestamp, levels in sorted(snapshots.items()):
        if not all(level in levels for level in (-5, -1, 1, 5)):
            continue
        point = BookDepthPoint(
            timestamp=timestamp,
            bid_notional_1pct=levels[-1],
            ask_notional_1pct=levels[1],
            bid_notional_5pct=levels[-5],
            ask_notional_5pct=levels[5],
        )
        buckets[timestamp // (5 * 60)] = point
    return [buckets[key] for key in sorted(buckets)]


def _archive_specs(
    *,
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    base_url: str,
    sources: Sequence[str] = ARCHIVE_SOURCES,
) -> list[tuple[str, Path, str]]:
    requested = set(sources)
    specs: list[tuple[str, Path, str]] = []
    for month in _months(start, end):
        suffix = month.strftime("%Y-%m")
        for kind, archive_name in (
            ("klines", "klines"),
            ("premium", "premiumIndexKlines"),
        ):
            if kind not in requested:
                continue
            filename = f"{symbol}-{timeframe}-{suffix}.zip"
            relative = Path("monthly") / archive_name / symbol / timeframe / filename
            specs.append((kind, relative, f"{base_url}/{relative.as_posix()}"))
        if "intraday" in requested:
            filename = f"{symbol}-{INTRADAY_TIMEFRAME}-{suffix}.zip"
            relative = (
                Path("monthly")
                / "klines"
                / symbol
                / INTRADAY_TIMEFRAME
                / filename
            )
            specs.append(("intraday", relative, f"{base_url}/{relative.as_posix()}"))
        if "funding" in requested:
            funding_name = f"{symbol}-fundingRate-{suffix}.zip"
            funding_relative = Path("monthly") / "fundingRate" / symbol / funding_name
            specs.append(("funding", funding_relative, f"{base_url}/{funding_relative.as_posix()}"))
    for day in _days(start, end):
        suffix = day.isoformat()
        for kind, archive_name in (("metrics", "metrics"), ("book_depth", "bookDepth")):
            if kind not in requested:
                continue
            filename = f"{symbol}-{archive_name}-{suffix}.zip"
            relative = Path("daily") / archive_name / symbol / filename
            specs.append((kind, relative, f"{base_url}/{relative.as_posix()}"))
    return specs


def _download_checked(*, url: str, destination: Path) -> Path:
    checksum_path = destination.with_name(destination.name + ".CHECKSUM")
    if destination.exists() and checksum_path.exists():
        expected = _checksum_value(checksum_path.read_text(encoding="utf-8"))
        if _sha256(destination) == expected:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    checksum_text = _read_url(url + ".CHECKSUM").decode("utf-8")
    expected = _checksum_value(checksum_text)
    content = _read_url(url)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ValueError(f"Checksum mismatch for {url}: expected {expected}, got {actual}")
    destination.write_bytes(content)
    checksum_path.write_text(checksum_text, encoding="utf-8")
    return destination


def _download_optional_checked(*, url: str, destination: Path) -> Path | None:
    try:
        return _download_checked(url=url, destination=destination)
    except RuntimeError as exc:
        if "Archive request failed (404)" in str(exc):
            return None
        raise


def _read_url(url: str, *, attempts: int = 8) -> bytes:
    if attempts <= 0:
        raise ValueError("attempts must be positive")
    request = urllib.request.Request(url, headers={"User-Agent": "WaveMind-Research/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise RuntimeError(f"Archive request failed ({exc.code}): {url}") from exc
            error: Exception = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            error = exc
        if attempt + 1 < attempts:
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError(f"Archive request failed after {attempts} attempts: {url}") from error


def _zip_csv_rows(
    path: str | Path, *, fieldnames: Sequence[str] | None = None
) -> list[dict[str, str]]:
    archive = Path(path)
    with zipfile.ZipFile(archive) as bundle:
        csv_names = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"Expected one CSV in {archive}, found {len(csv_names)}")
        with bundle.open(csv_names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.reader(text)
            try:
                first = next(reader)
            except StopIteration:
                return []
            if fieldnames is None:
                names = first
                data = reader
            elif first and first[0].strip() == fieldnames[0]:
                names = first
                data = reader
            else:
                names = list(fieldnames)
                data = chain((first,), reader)
            if len(names) != len(set(names)):
                raise ValueError(f"Duplicate CSV columns in {archive}")
            return [dict(zip(names, row, strict=True)) for row in data]


def _checksum_value(text: str) -> str:
    parts = text.strip().split()
    if not parts or len(parts[0]) != 64:
        raise ValueError("Invalid Binance checksum file")
    return parts[0].lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _milliseconds(value: Any) -> int:
    number = int(float(value))
    return number // 1000 if number >= 10_000_000_000 else number


def _utc_seconds(value: str) -> int:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _optional_float(value: Any) -> float | None:
    raw = "" if value is None else str(value).strip()
    return None if not raw else float(raw)


def _months(start: date, end: date) -> Iterable[date]:
    current = start.replace(day=1)
    final = end.replace(day=1)
    while current <= final:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _dedupe(rows: Sequence[Any], *, key: Callable[[Any], int]) -> list[Any]:
    unique = {key(row): row for row in rows}
    return [unique[item] for item in sorted(unique)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Download verified Binance USD-M futures research data.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/binance-archive"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--source",
        action="append",
        choices=ARCHIVE_SOURCES,
        dest="sources",
        help="Explicit source to include; repeat as needed (default: all sources).",
    )
    args = parser.parse_args()

    bundle = download_archive_bundle(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        workers=args.workers,
        sources=tuple(args.sources) if args.sources else ARCHIVE_SOURCES,
    )
    save_bundle(args.output, bundle)
    print(
        f"Wrote {args.output}: bars={len(bundle.bars)}, "
        f"intraday_bars={len(bundle.intraday_bars)}, metrics={len(bundle.metrics)}, "
        f"funding={len(bundle.funding)}, premium={len(bundle.premium)}, "
        f"book_depth={len(bundle.book_depth)}, missing={len(bundle.missing_source_files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
