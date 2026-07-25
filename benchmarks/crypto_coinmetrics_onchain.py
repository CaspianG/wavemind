from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


COINMETRICS_URL = (
    "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
)
ASSET_MAP = {"BTCUSDT": "btc", "ETHUSDT": "eth"}
COINMETRICS_METRICS = (
    "AdrActCnt",
    "AdrBalCnt",
    "CapMVRVCur",
    "FeeTotNtv",
    "FlowInExUSD",
    "FlowOutExUSD",
    "SplyExNtv",
    "SplyExUSD",
    "TxCnt",
    "TxTfrCnt",
)
COMPLETION_METRIC = "AssetEODCompletionTime"
ONCHAIN_FEATURES = tuple(
    feature
    for metric in COINMETRICS_METRICS
    for feature in (
        f"cm_{metric.lower()}_z60",
        f"cm_{metric.lower()}_change1_bps",
        f"cm_{metric.lower()}_change7_bps",
    )
) + (
    "cm_net_exchange_flow_usd_z60",
    "cm_exchange_flow_ratio",
    "cm_max_age_days",
)


@dataclass(frozen=True)
class OnChainObservation:
    asset: str
    observation_date: str
    available_timestamp: int
    values: Mapping[str, float]


@dataclass(frozen=True)
class OnChainDataset:
    start_date: str
    end_date: str
    publication_lag_days: int
    observations: tuple[OnChainObservation, ...]
    source_urls: tuple[str, ...]
    source_sha256: tuple[str, ...]


def download_onchain_dataset(
    *,
    assets: Sequence[str] = ("btc", "eth"),
    metrics: Sequence[str] = COINMETRICS_METRICS,
    start: date,
    end: date,
    publication_lag_days: int = 2,
    base_url: str = COINMETRICS_URL,
) -> OnChainDataset:
    if start > end:
        raise ValueError("start must be on or before end")
    if publication_lag_days < 1:
        raise ValueError("publication_lag_days must be at least one")
    requested_assets = tuple(dict.fromkeys(item.lower() for item in assets))
    requested_metrics = tuple(dict.fromkeys(metrics))
    if not requested_assets or not requested_metrics:
        raise ValueError("assets and metrics must not be empty")

    url = _series_url(
        base_url,
        requested_assets,
        requested_metrics + (COMPLETION_METRIC,),
        start,
        end,
    )
    observations = []
    source_urls = []
    source_sha256 = []
    while url:
        content = _read_url(url)
        payload = json.loads(content)
        observations.extend(
            parse_onchain_payload(
                payload,
                metrics=requested_metrics,
                publication_lag_days=publication_lag_days,
            )
        )
        source_urls.append(url)
        source_sha256.append(hashlib.sha256(content).hexdigest())
        url = str(payload.get("next_page_url") or "")
    return OnChainDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        publication_lag_days=publication_lag_days,
        observations=tuple(
            sorted(
                observations,
                key=lambda row: (row.asset, row.available_timestamp),
            )
        ),
        source_urls=tuple(source_urls),
        source_sha256=tuple(source_sha256),
    )


def parse_onchain_payload(
    payload: Mapping[str, Any],
    *,
    metrics: Sequence[str],
    publication_lag_days: int,
) -> list[OnChainObservation]:
    if publication_lag_days < 1:
        raise ValueError("publication_lag_days must be at least one")
    output = []
    for row in payload.get("data", []):
        asset = str(row["asset"]).lower()
        observed = date.fromisoformat(str(row["time"])[:10])
        values = {}
        for metric in metrics:
            raw = row.get(metric)
            if raw is None:
                break
            value = float(raw)
            if not math.isfinite(value):
                break
            values[metric] = value
        if len(values) != len(metrics):
            continue
        fallback_timestamp = _midnight(
            observed + timedelta(days=publication_lag_days)
        )
        latest_initial_timestamp = _midnight(
            observed + timedelta(days=7)
        )
        completion = row.get(COMPLETION_METRIC)
        completion_timestamp = (
            int(float(completion)) if completion is not None else 0
        )
        status_timestamps = [
            _iso_timestamp(str(value))
            for key, value in row.items()
            if key.endswith("-status-time") and value
        ]
        initial_timestamps = [
            timestamp
            for timestamp in [completion_timestamp, *status_timestamps]
            if _midnight(observed) < timestamp <= latest_initial_timestamp
        ]
        if initial_timestamps:
            available_timestamp = max(initial_timestamps)
        else:
            available_timestamp = fallback_timestamp
        output.append(
            OnChainObservation(
                asset=asset,
                observation_date=observed.isoformat(),
                available_timestamp=available_timestamp,
                values=values,
            )
        )
    return output


def save_onchain_dataset(path: str | Path, dataset: OnChainDataset) -> None:
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
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_onchain_dataset(path: str | Path) -> OnChainDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return OnChainDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        publication_lag_days=int(payload["publication_lag_days"]),
        observations=tuple(
            OnChainObservation(
                asset=str(row["asset"]),
                observation_date=str(row["observation_date"]),
                available_timestamp=int(row["available_timestamp"]),
                values={
                    str(key): float(value)
                    for key, value in row["values"].items()
                },
            )
            for row in payload["observations"]
        ),
        source_urls=tuple(str(item) for item in payload.get("source_urls", [])),
        source_sha256=tuple(
            str(item) for item in payload.get("source_sha256", [])
        ),
    )


def add_onchain_features(
    rows: Sequence[FeatureRow],
    dataset: OnChainDataset,
    *,
    min_history: int = 60,
    max_age_days: float = 4.0,
) -> list[FeatureRow]:
    if min_history < 7:
        raise ValueError("min_history must be at least seven observations")
    if max_age_days <= 0.0:
        raise ValueError("max_age_days must be positive")
    series = _feature_series(dataset)
    timestamp_series = {
        asset: tuple(point[0] for point in points)
        for asset, points in series.items()
    }
    reverse_assets = {symbol: asset for symbol, asset in ASSET_MAP.items()}

    output = []
    for row in rows:
        asset = reverse_assets.get(row.symbol)
        points = series.get(asset or "")
        timestamps = timestamp_series.get(asset or "")
        if points is None or timestamps is None:
            continue
        index = bisect_right(timestamps, row.timestamp) - 1
        if index < 0:
            continue
        point = points[index][1]
        age = (
            row.timestamp - int(point["available_timestamp"])
        ) / 86_400.0
        if (
            int(point["history"]) < min_history
            or age < 0.0
            or age > max_age_days
        ):
            continue
        additions = {
            feature: float(point[feature])
            for feature in ONCHAIN_FEATURES
            if feature != "cm_max_age_days"
        }
        additions["cm_max_age_days"] = age
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
    dataset: OnChainDataset,
) -> dict[str, tuple[tuple[int, Mapping[str, float]], ...]]:
    grouped: dict[str, list[OnChainObservation]] = {}
    for observation in dataset.observations:
        grouped.setdefault(observation.asset, []).append(observation)
    output = {}
    for asset, observations in grouped.items():
        history = {metric: [] for metric in COINMETRICS_METRICS}
        net_flow_history = []
        points = []
        for observation in sorted(
            observations, key=lambda row: row.available_timestamp
        ):
            for metric in COINMETRICS_METRICS:
                history[metric].append(float(observation.values[metric]))
            net_flow_history.append(
                float(observation.values["FlowOutExUSD"])
                - float(observation.values["FlowInExUSD"])
            )
            point: dict[str, float] = {
                "history": float(len(net_flow_history)),
                "available_timestamp": float(observation.available_timestamp),
            }
            for metric, values in history.items():
                prefix = f"cm_{metric.lower()}"
                point[f"{prefix}_z60"] = _zscore(values, 60)
                point[f"{prefix}_change1_bps"] = _log_change(values, 1)
                point[f"{prefix}_change7_bps"] = _log_change(values, 7)
            point["cm_net_exchange_flow_usd_z60"] = _zscore(
                net_flow_history, 60
            )
            flow_in = max(float(observation.values["FlowInExUSD"]), 1e-12)
            flow_out = max(float(observation.values["FlowOutExUSD"]), 1e-12)
            point["cm_exchange_flow_ratio"] = math.log(flow_out / flow_in)
            points.append((observation.available_timestamp, point))
        output[asset] = tuple(points)
    return output


def _zscore(values: Sequence[float], window: int) -> float:
    selected = np.asarray(values[-window:], dtype=float)
    std = float(np.std(selected))
    return (float(selected[-1]) - float(np.mean(selected))) / max(std, 1e-9)


def _log_change(values: Sequence[float], period: int) -> float:
    if len(values) <= period:
        return 0.0
    current = max(float(values[-1]), 1e-12)
    previous = max(float(values[-period - 1]), 1e-12)
    return math.log(current / previous) * 10_000.0


def _series_url(
    base_url: str,
    assets: Sequence[str],
    metrics: Sequence[str],
    start: date,
    end: date,
) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": ",".join(assets),
            "metrics": ",".join(metrics),
            "frequency": "1d",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "page_size": 10000,
        }
    )
    return f"{base_url}?{query}"


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "WaveMind-Crypto-Research/0.2"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _midnight(day: date) -> int:
    return int(
        datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ).timestamp()
    )


def _iso_timestamp(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download causal Coin Metrics Community on-chain data."
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--publication-lag-days", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = download_onchain_dataset(
        start=args.start,
        end=args.end,
        publication_lag_days=args.publication_lag_days,
    )
    save_onchain_dataset(args.output, dataset)
    print(
        f"Wrote {args.output}: observations={len(dataset.observations)}, "
        f"sources={len(dataset.source_urls)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
