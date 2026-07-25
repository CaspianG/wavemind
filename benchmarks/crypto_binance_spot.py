from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
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

from benchmarks.crypto_binance_archive import (  # noqa: E402
    FuturesBar,
    _download_checked,
    load_futures_bars,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


BINANCE_SPOT_ARCHIVE = "https://data.binance.vision/data/spot"
SPOT_TIMEFRAME = "5m"
SPOT_FLOW_FEATURES = (
    "spot_return_4h_bps",
    "spot_realized_volatility_bps",
    "spot_taker_imbalance_mean",
    "spot_taker_imbalance_last_hour",
    "spot_taker_imbalance_shift",
    "spot_quote_volume_log",
    "spot_trades_log",
    "spot_futures_return_spread_bps",
    "spot_futures_flow_spread",
    "spot_flow_return_interaction",
    "spot_age_seconds",
)


@dataclass(frozen=True)
class SymbolSpotBar:
    symbol: str
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

    def as_bar(self) -> FuturesBar:
        return FuturesBar(
            timestamp=self.timestamp,
            close_timestamp=self.close_timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            quote_volume=self.quote_volume,
            trades=self.trades,
            taker_buy_volume=self.taker_buy_volume,
            taker_buy_quote_volume=self.taker_buy_quote_volume,
        )


@dataclass(frozen=True)
class SpotDataset:
    start_date: str
    end_date: str
    timeframe: str
    bars: tuple[SymbolSpotBar, ...]
    source_files: tuple[str, ...]


def download_spot_dataset(
    *,
    symbols: Sequence[str],
    start: date,
    end: date,
    cache_dir: str | Path,
    workers: int = 8,
    timeframe: str = SPOT_TIMEFRAME,
    base_url: str = BINANCE_SPOT_ARCHIVE,
) -> SpotDataset:
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
            month=month,
            timeframe=timeframe,
            root=Path(cache_dir),
            base_url=base_url.rstrip("/"),
        )
        for symbol in normalized
        for month in _months(start, end)
    ]
    downloaded: list[tuple[str, date, Path]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_checked,
                url=url,
                destination=destination,
            ): (symbol, month, destination)
            for symbol, month, destination, url in specifications
        }
        for future in as_completed(futures):
            symbol, month, destination = futures[future]
            future.result()
            downloaded.append((symbol, month, destination))

    first_timestamp = _midnight(start)
    last_timestamp = _midnight(end + timedelta(days=1)) - 1
    bars = []
    for symbol, _, path in sorted(downloaded, key=lambda row: (row[0], row[1])):
        bars.extend(
            SymbolSpotBar(symbol=symbol, **asdict(bar))
            for bar in load_futures_bars(path)
            if first_timestamp <= bar.close_timestamp <= last_timestamp
        )
    return SpotDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        timeframe=timeframe,
        bars=tuple(bars),
        source_files=tuple(str(row[2]) for row in sorted(downloaded)),
    )


def save_spot_dataset(path: str | Path, dataset: SpotDataset) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "timeframe": dataset.timeframe,
        "bars": [asdict(row) for row in dataset.bars],
        "source_files": list(dataset.source_files),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_spot_dataset(path: str | Path) -> SpotDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return SpotDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        timeframe=str(payload["timeframe"]),
        bars=tuple(SymbolSpotBar(**row) for row in payload["bars"]),
        source_files=tuple(str(item) for item in payload.get("source_files", [])),
    )


def add_spot_flow_features(
    rows: Sequence[FeatureRow],
    dataset: SpotDataset,
    *,
    min_bars: int = 40,
    window_seconds: int = 4 * 60 * 60,
    max_age_seconds: int = 15 * 60,
) -> list[FeatureRow]:
    if min_bars <= 1:
        raise ValueError("min_bars must be greater than one")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    grouped: dict[str, list[SymbolSpotBar]] = {}
    for bar in dataset.bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    series = {
        symbol: tuple(sorted(bars, key=lambda row: row.close_timestamp))
        for symbol, bars in grouped.items()
    }
    timestamps = {
        symbol: tuple(row.close_timestamp for row in bars)
        for symbol, bars in series.items()
    }

    output = []
    for row in rows:
        bars = series.get(row.symbol)
        closes = timestamps.get(row.symbol)
        if bars is None or closes is None:
            continue
        end = bisect_right(closes, row.timestamp)
        start = bisect_right(closes, row.timestamp - window_seconds)
        window = bars[start:end]
        if len(window) < min_bars:
            continue
        age = row.timestamp - window[-1].close_timestamp
        if age < 0 or age > max_age_seconds:
            continue
        additions = _spot_window_features(window, row.features, age=age)
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


def _spot_window_features(
    bars: Sequence[SymbolSpotBar],
    futures_features: Mapping[str, float],
    *,
    age: int,
) -> dict[str, float]:
    feature_map = dict(futures_features)
    close = np.asarray([row.close for row in bars], dtype=float)
    volume = np.asarray([row.volume for row in bars], dtype=float)
    quote_volume = np.asarray([row.quote_volume for row in bars], dtype=float)
    trades = np.asarray([row.trades for row in bars], dtype=float)
    taker_buy = np.asarray([row.taker_buy_volume for row in bars], dtype=float)
    imbalance = np.divide(
        2.0 * taker_buy,
        np.maximum(volume, 1e-12),
    ) - 1.0
    path = np.concatenate(([float(bars[0].open)], close))
    returns = np.diff(np.log(np.maximum(path, 1e-12))) * 10_000.0
    spot_return = float(np.sum(returns))
    first_hour = min(12, len(imbalance))
    last_hour = max(0, len(imbalance) - 12)
    spot_flow = float(np.mean(imbalance))
    futures_flow = float(
        feature_map.get(
            "intraday_taker_imbalance_mean",
            feature_map.get("taker_imbalance", 0.0),
        )
    )
    return {
        "spot_return_4h_bps": spot_return,
        "spot_realized_volatility_bps": float(np.sqrt(np.sum(returns**2))),
        "spot_taker_imbalance_mean": spot_flow,
        "spot_taker_imbalance_last_hour": float(np.mean(imbalance[last_hour:])),
        "spot_taker_imbalance_shift": float(
            np.mean(imbalance[last_hour:]) - np.mean(imbalance[:first_hour])
        ),
        "spot_quote_volume_log": float(math.log1p(np.sum(quote_volume))),
        "spot_trades_log": float(math.log1p(np.sum(trades))),
        "spot_futures_return_spread_bps": float(
            spot_return - float(feature_map.get("return_1", 0.0))
        ),
        "spot_futures_flow_spread": spot_flow - futures_flow,
        "spot_flow_return_interaction": float(spot_flow * spot_return),
        "spot_age_seconds": float(age),
    }


def _archive_spec(
    *,
    symbol: str,
    month: date,
    timeframe: str,
    root: Path,
    base_url: str,
) -> tuple[str, date, Path, str]:
    suffix = month.strftime("%Y-%m")
    filename = f"{symbol}-{timeframe}-{suffix}.zip"
    relative = Path("monthly") / "klines" / symbol / timeframe / filename
    return symbol, month, root / relative, f"{base_url}/{relative.as_posix()}"


def _months(start: date, end: date) -> Iterable[date]:
    current = start.replace(day=1)
    final = end.replace(day=1)
    while current <= final:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def _midnight(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download checksum-verified Binance spot 5m archives."
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/binance-spot"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = download_spot_dataset(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        workers=args.workers,
    )
    save_spot_dataset(args.output, dataset)
    print(
        f"Wrote {args.output}: bars={len(dataset.bars)}, "
        f"verified_sources={len(dataset.source_files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
