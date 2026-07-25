from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
import urllib.parse
import urllib.request
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = (
    "VIXCLS",
    "DTWEXBGS",
    "DGS10",
    "DGS2",
    "SP500",
    "NASDAQCOM",
)
MACRO_FEATURES = tuple(
    feature
    for series in FRED_SERIES
    for feature in (
        f"fred_{series.lower()}_z60",
        f"fred_{series.lower()}_change1_bps",
        f"fred_{series.lower()}_change5_bps",
        f"fred_{series.lower()}_change20_bps",
    )
) + ("fred_max_age_days",)


@dataclass(frozen=True)
class FredObservation:
    series: str
    observation_date: str
    available_timestamp: int
    value: float


@dataclass(frozen=True)
class FredDataset:
    start_date: str
    end_date: str
    publication_lag_days: int
    observations: tuple[FredObservation, ...]
    source_urls: tuple[str, ...]
    source_sha256: tuple[str, ...]


def download_fred_dataset(
    *,
    series: Sequence[str] = FRED_SERIES,
    start: date,
    end: date,
    publication_lag_days: int = 2,
    workers: int = 6,
    base_url: str = FRED_CSV_URL,
) -> FredDataset:
    if start > end:
        raise ValueError("start must be on or before end")
    if publication_lag_days < 1:
        raise ValueError("publication_lag_days must be at least one")
    if workers <= 0:
        raise ValueError("workers must be positive")
    requested = tuple(dict.fromkeys(item.upper() for item in series))
    if not requested:
        raise ValueError("at least one FRED series is required")

    downloads = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(requested))) as executor:
        futures = {
            executor.submit(
                _read_fred_url,
                _series_url(base_url, item, start, end),
            ): item
            for item in requested
        }
        for future in as_completed(futures):
            item = futures[future]
            downloads[item] = future.result()

    observations = []
    urls = []
    fingerprints = []
    for item in requested:
        content = downloads[item]
        url = _series_url(base_url, item, start, end)
        observations.extend(
            parse_fred_csv(
                content,
                series=item,
                publication_lag_days=publication_lag_days,
            )
        )
        urls.append(url)
        fingerprints.append(hashlib.sha256(content).hexdigest())
    return FredDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        publication_lag_days=publication_lag_days,
        observations=tuple(observations),
        source_urls=tuple(urls),
        source_sha256=tuple(fingerprints),
    )


def parse_fred_csv(
    content: bytes,
    *,
    series: str,
    publication_lag_days: int,
) -> list[FredObservation]:
    if publication_lag_days < 1:
        raise ValueError("publication_lag_days must be at least one")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    expected = {"observation_date", series}
    if set(reader.fieldnames or ()) != expected:
        raise ValueError(
            f"Unexpected FRED columns for {series}: {reader.fieldnames}"
        )
    observations = []
    for row in reader:
        raw = str(row[series]).strip()
        if not raw or raw == ".":
            continue
        value = float(raw)
        if not math.isfinite(value):
            continue
        observed = date.fromisoformat(str(row["observation_date"]))
        available = _midnight(observed + timedelta(days=publication_lag_days))
        observations.append(
            FredObservation(
                series=series,
                observation_date=observed.isoformat(),
                available_timestamp=available,
                value=value,
            )
        )
    return observations


def save_fred_dataset(path: str | Path, dataset: FredDataset) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "publication_lag_days": dataset.publication_lag_days,
        "observations": [asdict(row) for row in dataset.observations],
        "source_urls": list(dataset.source_urls),
        "source_sha256": list(dataset.source_sha256),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_fred_dataset(path: str | Path) -> FredDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return FredDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        publication_lag_days=int(payload["publication_lag_days"]),
        observations=tuple(
            FredObservation(**row) for row in payload["observations"]
        ),
        source_urls=tuple(str(item) for item in payload.get("source_urls", [])),
        source_sha256=tuple(
            str(item) for item in payload.get("source_sha256", [])
        ),
    )


def add_fred_macro_features(
    rows: Sequence[FeatureRow],
    dataset: FredDataset,
    *,
    min_history: int = 60,
    max_age_days: float = 10.0,
) -> list[FeatureRow]:
    if min_history < 20:
        raise ValueError("min_history must be at least 20 observations")
    if max_age_days <= 0.0:
        raise ValueError("max_age_days must be positive")
    feature_series = _feature_series(dataset)
    if set(feature_series) != set(FRED_SERIES):
        missing = sorted(set(FRED_SERIES) - set(feature_series))
        raise ValueError("Missing required FRED series: " + ", ".join(missing))
    timestamps = {
        series: tuple(point[0] for point in values)
        for series, values in feature_series.items()
    }

    output = []
    for row in rows:
        selected = {}
        ages = []
        valid = True
        for series in FRED_SERIES:
            values = feature_series[series]
            index = bisect_right(timestamps[series], row.timestamp) - 1
            if index < 0:
                valid = False
                break
            point = values[index][1]
            if int(point["history"]) < min_history:
                valid = False
                break
            age = (
                row.timestamp - int(point["available_timestamp"])
            ) / 86_400.0
            if age < 0.0 or age > max_age_days:
                valid = False
                break
            selected[series] = point
            ages.append(age)
        if not valid:
            continue
        additions = {}
        for series, point in selected.items():
            prefix = f"fred_{series.lower()}"
            additions.update(
                {
                    f"{prefix}_z60": float(point["z60"]),
                    f"{prefix}_change1_bps": float(point["change1_bps"]),
                    f"{prefix}_change5_bps": float(point["change5_bps"]),
                    f"{prefix}_change20_bps": float(point["change20_bps"]),
                }
            )
        additions["fred_max_age_days"] = float(max(ages))
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
    dataset: FredDataset,
) -> dict[str, tuple[tuple[int, Mapping[str, float]], ...]]:
    grouped: dict[str, list[FredObservation]] = {}
    for observation in dataset.observations:
        grouped.setdefault(observation.series, []).append(observation)
    output = {}
    for series, observations in grouped.items():
        ordered = sorted(observations, key=lambda row: row.available_timestamp)
        values = []
        points = []
        for observation in ordered:
            values.append(float(observation.value))
            window = np.asarray(values[-60:], dtype=float)
            mean = float(np.mean(window))
            std = float(np.std(window))
            current = values[-1]
            points.append(
                (
                    observation.available_timestamp,
                    {
                        "history": float(len(values)),
                        "available_timestamp": float(
                            observation.available_timestamp
                        ),
                        "z60": (current - mean) / max(std, 1e-9),
                        "change1_bps": _log_change(values, 1),
                        "change5_bps": _log_change(values, 5),
                        "change20_bps": _log_change(values, 20),
                    },
                )
            )
        output[series] = tuple(points)
    return output


def _log_change(values: Sequence[float], period: int) -> float:
    if len(values) <= period:
        return 0.0
    current = max(float(values[-1]), 1e-12)
    previous = max(float(values[-period - 1]), 1e-12)
    return math.log(current / previous) * 10_000.0


def _series_url(base_url: str, series: str, start: date, end: date) -> str:
    query = urllib.parse.urlencode(
        {
            "id": series,
            "cosd": start.isoformat(),
            "coed": end.isoformat(),
        }
    )
    return f"{base_url}?{query}"


def _read_fred_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _midnight(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download causal, fingerprinted FRED market series."
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--publication-lag-days", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = download_fred_dataset(
        start=args.start,
        end=args.end,
        publication_lag_days=args.publication_lag_days,
        workers=args.workers,
    )
    save_fred_dataset(args.output, dataset)
    print(
        f"Wrote {args.output}: observations={len(dataset.observations)}, "
        f"series={len(dataset.source_urls)}, lag_days={dataset.publication_lag_days}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
