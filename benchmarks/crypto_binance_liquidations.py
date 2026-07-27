from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import (  # noqa: E402
    _wilson_low,
    collapse_overlapping_events,
)
from benchmarks.crypto_binance_archive import (  # noqa: E402
    _download_checked,
    _zip_csv_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


S3_LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BINANCE_DATA_URL = "https://data.binance.vision"
COIN_M_PREFIX = "data/futures/cm/daily/liquidationSnapshot"
LIQUIDATION_FEATURES = (
    "liquidation_log_quantity",
    "liquidation_log_count",
    "liquidation_imbalance",
    "liquidation_quantity_z36",
    "liquidation_count_z36",
    "liquidation_imbalance_mean6",
    "liquidation_imbalance_shift6",
    "liquidation_persistence6",
    "liquidation_slippage_bps",
    "liquidation_log_quantity_sum6",
    "liquidation_log_count_sum6",
    "liquidation_quantity_z36_max6",
    "liquidation_count_z36_max6",
    "liquidation_weighted_imbalance6",
)


@dataclass(frozen=True)
class LiquidationPoint:
    timestamp: int
    side: str
    quantity: float
    price: float
    average_price: float


@dataclass(frozen=True)
class LiquidationBar:
    timestamp: int
    buy_quantity: float
    sell_quantity: float
    buy_count: int
    sell_count: int
    slippage_bps: float


def list_liquidation_archives(
    coin_m_symbol: str,
    *,
    start: date,
    end: date,
    list_url: str = S3_LIST_URL,
) -> list[str]:
    symbol = coin_m_symbol.upper()
    prefix = f"{COIN_M_PREFIX}/{symbol}/"
    continuation: str | None = None
    keys: list[str] = []
    while True:
        query = {
            "list-type": "2",
            "prefix": prefix,
            "max-keys": "1000",
        }
        if continuation:
            query["continuation-token"] = continuation
        url = f"{list_url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "WaveMind-Research/1.0"},
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            root = ET.fromstring(response.read())
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        keys.extend(
            element.text or ""
            for element in root.findall(".//s3:Contents/s3:Key", namespace)
        )
        truncated = (
            root.findtext("s3:IsTruncated", default="false", namespaces=namespace)
            == "true"
        )
        if not truncated:
            break
        continuation = root.findtext(
            "s3:NextContinuationToken",
            default="",
            namespaces=namespace,
        )
        if not continuation:
            raise RuntimeError("Binance S3 listing was truncated without a continuation token")
    output = []
    for key in keys:
        if not key.endswith(".zip"):
            continue
        archive_date = _date_from_key(key)
        if start <= archive_date <= end:
            output.append(key)
    return sorted(output)


def download_liquidation_archives(
    coin_m_symbol: str,
    *,
    start: date,
    end: date,
    cache_dir: str | Path,
    workers: int = 20,
    list_url: str = S3_LIST_URL,
    data_url: str = BINANCE_DATA_URL,
) -> list[Path]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    keys = list_liquidation_archives(
        coin_m_symbol,
        start=start,
        end=end,
        list_url=list_url,
    )
    root = Path(cache_dir)
    downloaded: list[Path] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_checked,
                url=f"{data_url}/{key}",
                destination=root / Path(key).relative_to("data"),
            ): key
            for key in keys
        }
        for future in as_completed(futures):
            downloaded.append(future.result())
    return sorted(downloaded)


def load_liquidation_points(paths: Iterable[str | Path]) -> list[LiquidationPoint]:
    unique: dict[tuple[Any, ...], LiquidationPoint] = {}
    for path in paths:
        for row in _zip_csv_rows(path):
            point = LiquidationPoint(
                timestamp=_milliseconds(row["time"]),
                side=str(row["side"]).upper(),
                quantity=float(row["original_quantity"]),
                price=float(row["price"]),
                average_price=float(row["average_price"]),
            )
            key = (
                point.timestamp,
                point.side,
                point.quantity,
                point.price,
                point.average_price,
            )
            unique[key] = point
    return sorted(unique.values(), key=lambda row: row.timestamp)


def aggregate_liquidation_bars(
    points: Sequence[LiquidationPoint],
    *,
    interval_seconds: int = 4 * 60 * 60,
) -> list[LiquidationBar]:
    buckets: defaultdict[int, list[LiquidationPoint]] = defaultdict(list)
    for point in points:
        buckets[(point.timestamp // interval_seconds) * interval_seconds].append(
            point
        )
    output = []
    for timestamp, rows in sorted(buckets.items()):
        buy = [row for row in rows if row.side == "BUY"]
        sell = [row for row in rows if row.side == "SELL"]
        weighted_slippage = []
        weights = []
        for row in rows:
            if row.average_price <= 0.0:
                continue
            weighted_slippage.append(
                abs(row.price - row.average_price) / row.average_price * 10_000.0
            )
            weights.append(max(row.quantity, 1e-9))
        output.append(
            LiquidationBar(
                timestamp=timestamp,
                buy_quantity=sum(row.quantity for row in buy),
                sell_quantity=sum(row.quantity for row in sell),
                buy_count=len(buy),
                sell_count=len(sell),
                slippage_bps=(
                    float(np.average(weighted_slippage, weights=weights))
                    if weights
                    else 0.0
                ),
            )
        )
    return output


def add_liquidation_features(
    rows: Sequence[FeatureRow],
    liquidation_bars: Sequence[LiquidationBar],
    *,
    interval_seconds: int = 4 * 60 * 60,
) -> list[FeatureRow]:
    by_timestamp = {row.timestamp: row for row in liquidation_bars}
    ordered = sorted(rows, key=lambda row: row.timestamp)
    quantities: list[float] = []
    counts: list[float] = []
    imbalances: list[float] = []
    signed_quantities: list[float] = []
    quantity_z_scores: list[float] = []
    count_z_scores: list[float] = []
    output = []
    for row in ordered:
        bucket_timestamp = (row.timestamp // interval_seconds) * interval_seconds
        current = by_timestamp.get(
            bucket_timestamp,
            LiquidationBar(bucket_timestamp, 0.0, 0.0, 0, 0, 0.0),
        )
        total_quantity = current.buy_quantity + current.sell_quantity
        total_count = current.buy_count + current.sell_count
        imbalance = (
            (current.buy_quantity - current.sell_quantity) / total_quantity
            if total_quantity > 0.0
            else 0.0
        )
        quantities.append(total_quantity)
        counts.append(float(total_count))
        imbalances.append(imbalance)
        signed_quantities.append(current.buy_quantity - current.sell_quantity)
        quantity_history = np.asarray(quantities[-36:], dtype=float)
        count_history = np.asarray(counts[-36:], dtype=float)
        imbalance_history = np.asarray(imbalances[-6:], dtype=float)
        quantity_z = _robust_z(quantity_history)
        count_z = _robust_z(count_history)
        quantity_z_scores.append(quantity_z)
        count_z_scores.append(count_z)
        quantity_sum6 = float(sum(quantities[-6:]))
        count_sum6 = float(sum(counts[-6:]))
        weighted_imbalance6 = (
            float(sum(signed_quantities[-6:])) / quantity_sum6
            if quantity_sum6 > 0.0
            else 0.0
        )
        nonzero = imbalance_history[np.abs(imbalance_history) > 1e-12]
        persistence = (
            float(np.mean(np.sign(nonzero) == np.sign(imbalance)))
            if len(nonzero) and abs(imbalance) > 1e-12
            else 0.0
        )
        additions = {
            "liquidation_log_quantity": math.log1p(total_quantity),
            "liquidation_log_count": math.log1p(total_count),
            "liquidation_imbalance": imbalance,
            "liquidation_quantity_z36": quantity_z,
            "liquidation_count_z36": count_z,
            "liquidation_imbalance_mean6": float(np.mean(imbalance_history)),
            "liquidation_imbalance_shift6": float(
                imbalance - np.mean(imbalance_history[:-1])
                if len(imbalance_history) > 1
                else 0.0
            ),
            "liquidation_persistence6": persistence,
            "liquidation_slippage_bps": current.slippage_bps,
            "liquidation_log_quantity_sum6": math.log1p(quantity_sum6),
            "liquidation_log_count_sum6": math.log1p(count_sum6),
            "liquidation_quantity_z36_max6": float(max(quantity_z_scores[-6:])),
            "liquidation_count_z36_max6": float(max(count_z_scores[-6:])),
            "liquidation_weighted_imbalance6": weighted_imbalance6,
        }
        output.append(
            FeatureRow(
                **(asdict(row) | {"features": dict(row.features) | additions})
            )
        )
    return output


def run_liquidation_cascade_benchmark(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    min_training_signals: int = 40,
) -> dict[str, Any]:
    policies = []
    events = []
    folds = sorted({row.fold_index for row in rows if row.fold_index >= 0})
    for fold in folds:
        test_rows = [row for row in rows if row.fold_index == fold]
        test_start = min(row.timestamp for row in test_rows)
        history = [row for row in rows if row.target_timestamp < test_start]
        candidates = []
        for orientation in ("reversal", "continuation"):
            for imbalance in (0.2, 0.4, 0.6, 0.8):
                for quantity_z in (0.0, 1.0, 2.0, 3.0):
                    for count in (1.0, 3.0, 6.0):
                        policy = {
                            "orientation": orientation,
                            "min_abs_imbalance": imbalance,
                            "min_quantity_z": quantity_z,
                            "min_count": count,
                        }
                        selected = _independent(
                            _cascade_events(
                                history,
                                fold=-1,
                                policy=policy,
                                horizon_seconds=horizon_seconds,
                            )
                        )
                        if len(selected) < min_training_signals:
                            continue
                        candidates.append((policy, summarize(selected)))
        if not candidates:
            chosen = {
                "orientation": "reversal",
                "min_abs_imbalance": 0.0,
                "min_quantity_z": 0.0,
                "min_count": 1.0,
            }
            training_summary = summarize([])
        else:
            chosen, training_summary = max(
                candidates,
                key=lambda item: (
                    float(item[1]["wilson_low_95"] or 0.0),
                    float(item[1]["accuracy"] or 0.0),
                    int(item[1]["signals"]),
                ),
            )
        test_events = _cascade_events(
            test_rows,
            fold=fold,
            policy=chosen,
            horizon_seconds=horizon_seconds,
        )
        events.extend(test_events)
        policies.append(
            {
                "fold_index": fold,
                "policy": chosen,
                "training": training_summary,
                "test": summarize(_independent(test_events)),
            }
        )
    summary = summarize(_independent(events))
    by_fold = _group(events, "fold_index")
    by_symbol = _group(events, "symbol")
    admitted = bool(
        summary["signals"] >= 40
        and summary["accuracy"] is not None
        and summary["accuracy"] >= 0.70
        and summary["wilson_low_95"] is not None
        and summary["wilson_low_95"] >= 0.65
        and by_fold
        and min(row["accuracy"] for row in by_fold if row["signals"] >= 5) >= 0.65
        and by_symbol
        and min(row["accuracy"] for row in by_symbol if row["signals"] >= 5)
        >= 0.65
    )
    return {
        "methodology": {
            "source": "Binance COIN-M daily liquidationSnapshot with SHA-256 checksums",
            "selection": "orientation and thresholds selected from prior matured events only",
            "overlap": "one event per asset and forecast horizon",
            "horizon": _horizon_label(horizon_seconds),
        },
        "summary": summary,
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "policies": policies,
        "admitted_70": admitted,
        "events": events,
    }


def _cascade_events(
    rows: Sequence[FeatureRow],
    *,
    fold: int,
    policy: Mapping[str, Any],
    horizon_seconds: int,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        features = row.features
        imbalance = float(features["liquidation_imbalance"])
        quantity_z = float(features["liquidation_quantity_z36"])
        count = math.expm1(float(features["liquidation_log_count"]))
        if abs(imbalance) < float(policy["min_abs_imbalance"]):
            continue
        if quantity_z < float(policy["min_quantity_z"]):
            continue
        if count < float(policy["min_count"]):
            continue
        dominant_buy = imbalance > 0.0
        predicted_up = (
            not dominant_buy
            if str(policy["orientation"]) == "reversal"
            else dominant_buy
        )
        actual_up = row.future_return_bps > 0.0
        output.append(
            {
                "engine": "Liquidation cascade field",
                "symbol": row.symbol,
                "timeframe": "4h",
                "fold_index": fold,
                "query_id": f"{row.symbol}-{row.timestamp}",
                "data_end_utc": _iso(row.timestamp),
                "target_end_utc": _iso(
                    min(row.target_timestamp, row.timestamp + horizon_seconds)
                ),
                "liquidation_imbalance": imbalance,
                "liquidation_quantity_z36": quantity_z,
                "predicted_return_bps": (
                    1000.0 * abs(imbalance) * (1.0 if predicted_up else -1.0)
                ),
                "actual_return_bps": row.future_return_bps,
                "direction_hit": float(predicted_up == actual_up),
            }
        )
    return output


def summarize(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(event) for event in events]
    hits = sum(int(row["direction_hit"]) for row in rows)
    return {
        "signals": len(rows),
        "hits": hits,
        "accuracy": hits / len(rows) if rows else None,
        "wilson_low_95": _wilson_low(hits, len(rows)) if rows else None,
    }


def _group(
    events: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    independent = _independent(events)
    output = []
    for value in sorted({str(event[field]) for event in independent}):
        subset = [event for event in independent if str(event[field]) == value]
        output.append({field: value} | summarize(subset))
    return output


def _independent(
    events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return collapse_overlapping_events(dict(event) for event in events)


def _robust_z(values: np.ndarray) -> float:
    if len(values) < 4:
        return 0.0
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return float((values[-1] - median) / max(1.4826 * mad, 1.0))


def _date_from_key(key: str) -> date:
    stem = Path(key).name.removesuffix(".zip")
    return date.fromisoformat(stem[-10:])


def _milliseconds(value: Any) -> int:
    number = int(float(value))
    while number >= 10_000_000_000:
        number //= 1000
    return number


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _horizon_label(horizon_seconds: int) -> str:
    hours = horizon_seconds / 3600.0
    return f"{int(hours // 24)}d" if hours % 24 == 0 and hours > 24 else f"{hours:g}h"


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Official Binance Liquidation Cascade Benchmark",
        "",
        "Every liquidation snapshot is timestamped and checksum-verified. Fold policies are frozen from earlier matured events.",
        "",
        f"- horizon: {payload['methodology']['horizon']};",
        f"- independent signals: {summary['signals']};",
        f"- accuracy: {_percent(summary['accuracy'])};",
        f"- Wilson low: {_percent(summary['wilson_low_95'])};",
        f"- admitted at 70%: {'yes' if payload['admitted_70'] else 'no'}.",
        "",
        "| fold | orientation | imbalance | quantity z | count | train accuracy | test signals | test accuracy |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["policies"]:
        policy = row["policy"]
        lines.append(
            f"| {row['fold_index']} | {policy['orientation']} | "
            f"{policy['min_abs_imbalance']:.1f} | {policy['min_quantity_z']:.1f} | "
            f"{policy['min_count']:.0f} | {_percent(row['training']['accuracy'])} | "
            f"{row['test']['signals']} | {_percent(row['test']['accuracy'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download or inspect verified Binance COIN-M liquidation snapshots."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/binance-liquidations"))
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archives = download_liquidation_archives(
        args.symbol,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        workers=args.workers,
    )
    points = load_liquidation_points(archives)
    bars = aggregate_liquidation_bars(points)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "symbol": args.symbol,
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "archives": [str(path) for path in archives],
                "points": [asdict(point) for point in points],
                "bars": [asdict(bar) for bar in bars],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output}: archives={len(archives)}, "
        f"deduplicated_points={len(points)}, bars={len(bars)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
