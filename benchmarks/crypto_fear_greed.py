from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import urllib.request
from bisect import bisect_right
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=0&format=json"
FEAR_GREED_FEATURES = (
    "fng_value",
    "fng_z_30d",
    "fng_z_90d",
    "fng_change_1d",
    "fng_change_7d",
    "fng_change_30d",
    "fng_mean_7d",
    "fng_mean_30d",
    "fng_volatility_30d",
    "fng_extreme_fear",
    "fng_extreme_greed",
    "fng_return_6_interaction",
    "fng_return_36_interaction",
    "fng_age_hours",
)


@dataclass(frozen=True)
class FearGreedObservation:
    observation_timestamp: int
    available_timestamp: int
    value: float
    classification: str


@dataclass(frozen=True)
class FearGreedDataset:
    publication_lag_hours: int
    observations: tuple[FearGreedObservation, ...]
    source_url: str
    source_sha256: str


def download_fear_greed_dataset(
    *,
    publication_lag_hours: int = 24,
    url: str = FEAR_GREED_URL,
) -> FearGreedDataset:
    if publication_lag_hours < 1:
        raise ValueError("publication_lag_hours must be at least one")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "WaveMindResearch/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    observations = parse_fear_greed_json(
        content,
        publication_lag_hours=publication_lag_hours,
    )
    return FearGreedDataset(
        publication_lag_hours=publication_lag_hours,
        observations=tuple(observations),
        source_url=url,
        source_sha256=hashlib.sha256(content).hexdigest(),
    )


def parse_fear_greed_json(
    content: bytes,
    *,
    publication_lag_hours: int,
) -> list[FearGreedObservation]:
    if publication_lag_hours < 1:
        raise ValueError("publication_lag_hours must be at least one")
    payload = json.loads(content.decode("utf-8-sig"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected Fear & Greed response shape")
    error = payload.get("metadata", {}).get("error")
    if error:
        raise ValueError(f"Fear & Greed API error: {error}")
    lag_seconds = publication_lag_hours * 60 * 60
    observations = {}
    for item in payload["data"]:
        if not isinstance(item, Mapping):
            continue
        try:
            timestamp = int(str(item["timestamp"]))
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp <= 0 or not math.isfinite(value) or not 0.0 <= value <= 100.0:
            continue
        observations[timestamp] = FearGreedObservation(
            observation_timestamp=timestamp,
            available_timestamp=timestamp + lag_seconds,
            value=value,
            classification=str(item.get("value_classification", "")),
        )
    return [observations[key] for key in sorted(observations)]


def save_fear_greed_dataset(
    path: str | Path,
    dataset: FearGreedDataset,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "publication_lag_hours": dataset.publication_lag_hours,
        "observations": [asdict(row) for row in dataset.observations],
        "source_url": dataset.source_url,
        "source_sha256": dataset.source_sha256,
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_fear_greed_dataset(path: str | Path) -> FearGreedDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return FearGreedDataset(
        publication_lag_hours=int(payload["publication_lag_hours"]),
        observations=tuple(
            FearGreedObservation(**row) for row in payload["observations"]
        ),
        source_url=str(payload["source_url"]),
        source_sha256=str(payload["source_sha256"]),
    )


def add_fear_greed_features(
    rows: Sequence[FeatureRow],
    dataset: FearGreedDataset,
    *,
    min_history: int = 90,
    max_age_hours: float = 72.0,
) -> list[FeatureRow]:
    if min_history < 30:
        raise ValueError("min_history must be at least 30 observations")
    if max_age_hours <= 0.0:
        raise ValueError("max_age_hours must be positive")
    series = _feature_series(dataset)
    timestamps = tuple(point[0] for point in series)
    output = []
    for row in rows:
        index = bisect_right(timestamps, row.timestamp) - 1
        if index < 0:
            continue
        point = series[index][1]
        if int(point["history"]) < min_history:
            continue
        age_hours = (
            row.timestamp - int(point["available_timestamp"])
        ) / 3600.0
        if age_hours < 0.0 or age_hours > max_age_hours:
            continue
        centered = float(point["value"]) / 50.0 - 1.0
        additions = {
            "fng_value": centered,
            "fng_z_30d": float(point["z30"]),
            "fng_z_90d": float(point["z90"]),
            "fng_change_1d": float(point["change1"]) / 100.0,
            "fng_change_7d": float(point["change7"]) / 100.0,
            "fng_change_30d": float(point["change30"]) / 100.0,
            "fng_mean_7d": float(point["mean7"]) / 50.0 - 1.0,
            "fng_mean_30d": float(point["mean30"]) / 50.0 - 1.0,
            "fng_volatility_30d": float(point["std30"]) / 100.0,
            "fng_extreme_fear": float(point["value"] <= 25.0),
            "fng_extreme_greed": float(point["value"] >= 75.0),
            "fng_return_6_interaction": centered
            * float(row.features.get("return_6", 0.0)),
            "fng_return_36_interaction": centered
            * float(row.features.get("return_36", 0.0)),
            "fng_age_hours": age_hours,
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
    dataset: FearGreedDataset,
) -> tuple[tuple[int, Mapping[str, float]], ...]:
    ordered = sorted(
        dataset.observations,
        key=lambda row: (row.available_timestamp, row.observation_timestamp),
    )
    values = []
    output = []
    for observation in ordered:
        values.append(float(observation.value))
        window30 = np.asarray(values[-30:], dtype=float)
        window90 = np.asarray(values[-90:], dtype=float)
        output.append(
            (
                observation.available_timestamp,
                {
                    "history": float(len(values)),
                    "available_timestamp": float(observation.available_timestamp),
                    "value": float(observation.value),
                    "z30": _zscore(window30),
                    "z90": _zscore(window90),
                    "change1": _change(values, 1),
                    "change7": _change(values, 7),
                    "change30": _change(values, 30),
                    "mean7": float(np.mean(values[-7:])),
                    "mean30": float(np.mean(window30)),
                    "std30": float(np.std(window30)),
                },
            )
        )
    return tuple(output)


def _zscore(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values))
    return (
        (float(values[-1]) - float(np.mean(values)))
        / max(standard_deviation, 1e-9)
    )


def _change(values: Sequence[float], period: int) -> float:
    if len(values) <= period:
        return 0.0
    return float(values[-1]) - float(values[-period - 1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download causal, fingerprinted Crypto Fear & Greed history."
    )
    parser.add_argument("--publication-lag-hours", type=int, default=24)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = download_fear_greed_dataset(
        publication_lag_hours=args.publication_lag_hours,
    )
    save_fear_greed_dataset(args.output, dataset)
    print(
        f"Wrote {args.output}: observations={len(dataset.observations)}, "
        f"lag_hours={dataset.publication_lag_hours}, "
        f"sha256={dataset.source_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
