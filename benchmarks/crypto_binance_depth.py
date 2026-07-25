from __future__ import annotations

import argparse
import gzip
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_binance_archive import (  # noqa: E402
    BINANCE_ARCHIVE,
    ArchiveBundle,
    BookDepthPoint,
    _download_optional_checked,
    load_book_depth_points,
    load_bundle,
    save_bundle,
)


@dataclass(frozen=True)
class SymbolBookDepthPoint:
    symbol: str
    timestamp: int
    bid_notional_1pct: float
    ask_notional_1pct: float
    bid_notional_5pct: float
    ask_notional_5pct: float


@dataclass(frozen=True)
class BookDepthDataset:
    start_date: str
    end_date: str
    points: tuple[SymbolBookDepthPoint, ...]
    source_files: tuple[str, ...]
    missing_source_files: tuple[str, ...]


def download_book_depth_dataset(
    *,
    symbols: Sequence[str],
    start: date,
    end: date,
    cache_dir: str | Path,
    workers: int = 16,
    base_url: str = BINANCE_ARCHIVE,
) -> BookDepthDataset:
    if start > end:
        raise ValueError("start must be on or before end")
    if workers <= 0:
        raise ValueError("workers must be positive")
    normalized = tuple(
        dict.fromkeys(
            symbol.upper().replace("/", "").replace(":USDT", "")
            for symbol in symbols
        )
    )
    if not normalized:
        raise ValueError("at least one symbol is required")

    specifications = [
        _archive_spec(
            symbol=symbol,
            day=day,
            root=Path(cache_dir),
            base_url=base_url.rstrip("/"),
        )
        for symbol in normalized
        for day in _days(start, end)
    ]
    downloaded: list[tuple[str, date, Path]] = []
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_optional_checked,
                url=url,
                destination=destination,
            ): (symbol, day, destination, url)
            for symbol, day, destination, url in specifications
        }
        for future in as_completed(futures):
            symbol, day, destination, url = futures[future]
            path = future.result()
            if path is None:
                missing.append(url)
                continue
            downloaded.append((symbol, day, destination))

    points = []
    for symbol, _, path in sorted(downloaded, key=lambda row: (row[0], row[1])):
        points.extend(
            SymbolBookDepthPoint(symbol=symbol, **asdict(point))
            for point in load_book_depth_points(path)
        )
    return BookDepthDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        points=tuple(points),
        source_files=tuple(str(row[2]) for row in sorted(downloaded)),
        missing_source_files=tuple(sorted(missing)),
    )


def save_book_depth_dataset(path: str | Path, dataset: BookDepthDataset) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "points": [asdict(row) for row in dataset.points],
        "source_files": list(dataset.source_files),
        "missing_source_files": list(dataset.missing_source_files),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_book_depth_dataset(path: str | Path) -> BookDepthDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return BookDepthDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        points=tuple(SymbolBookDepthPoint(**row) for row in payload["points"]),
        source_files=tuple(str(item) for item in payload.get("source_files", [])),
        missing_source_files=tuple(
            str(item) for item in payload.get("missing_source_files", [])
        ),
    )


def enrich_bundle_with_book_depth(
    bundle: ArchiveBundle,
    dataset: BookDepthDataset,
) -> ArchiveBundle:
    selected = [
        BookDepthPoint(
            timestamp=row.timestamp,
            bid_notional_1pct=row.bid_notional_1pct,
            ask_notional_1pct=row.ask_notional_1pct,
            bid_notional_5pct=row.bid_notional_5pct,
            ask_notional_5pct=row.ask_notional_5pct,
        )
        for row in dataset.points
        if row.symbol == bundle.symbol
    ]
    if not selected:
        raise ValueError(f"No book-depth points for {bundle.symbol}")
    merged = {
        row.timestamp: row
        for row in (*bundle.book_depth, *selected)
    }
    source_files = tuple(
        sorted(
            set(bundle.source_files)
            | {
                item
                for item in dataset.source_files
                if _path_contains_symbol(item, bundle.symbol)
            }
        )
    )
    missing_source_files = tuple(
        sorted(
            set(bundle.missing_source_files)
            | {
                item
                for item in dataset.missing_source_files
                if f"/{bundle.symbol}/" in item.replace("\\", "/")
            }
        )
    )
    return replace(
        bundle,
        book_depth=tuple(merged[key] for key in sorted(merged)),
        source_files=source_files,
        missing_source_files=missing_source_files,
    )


def _archive_spec(
    *,
    symbol: str,
    day: date,
    root: Path,
    base_url: str,
) -> tuple[str, date, Path, str]:
    filename = f"{symbol}-bookDepth-{day.isoformat()}.zip"
    relative = Path("daily") / "bookDepth" / symbol / filename
    return symbol, day, root / relative, f"{base_url}/daily/bookDepth/{symbol}/{filename}"


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _path_contains_symbol(path: str, symbol: str) -> bool:
    return f"/{symbol}/" in path.replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download verified Binance book-depth data and enrich futures bundles."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/binance-book-depth"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    bundles = [load_bundle(path) for path in args.bundles]
    dataset = download_book_depth_dataset(
        symbols=[bundle.symbol for bundle in bundles],
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        workers=args.workers,
    )
    save_book_depth_dataset(args.dataset, dataset)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for source, bundle in zip(args.bundles, bundles, strict=True):
        output = args.output_dir / source.name
        enriched = enrich_bundle_with_book_depth(bundle, dataset)
        save_bundle(output, enriched)
        print(
            f"Wrote {output}: book_depth={len(enriched.book_depth)}, "
            f"missing={len(enriched.missing_source_files)}"
        )
    print(
        f"Verified {len(dataset.source_files)} depth archives, "
        f"missing={len(dataset.missing_source_files)}, points={len(dataset.points)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
