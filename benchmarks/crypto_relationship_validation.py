from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVWindow  # noqa: E402
from benchmarks.crypto_relationship_miner import (  # noqa: E402
    DEFAULT_FEATURE_KEYS,
    RelationshipMarket,
    load_markets_from_args,
    mine_relationships,
)


def validate_relationships(
    markets: list[RelationshipMarket],
    *,
    train_windows: int = 420,
    test_windows: int = 60,
    folds: int = 4,
    fold_stride: int | None = None,
    min_support: int = 30,
    min_test_support: int = 10,
    top_n: int = 12,
    pairwise: bool = True,
    large_move_bps: float = 75.0,
) -> dict:
    if not markets:
        raise ValueError("no markets to validate")
    starts = _fold_starts(
        min(len(market.windows) for market in markets),
        train_windows=train_windows,
        test_windows=test_windows,
        folds=folds,
        fold_stride=fold_stride,
    )
    fold_results = []
    validated = []
    for fold_index, fold_start in enumerate(starts):
        train_markets = []
        test_by_market = []
        for market in markets:
            selected_test = _select_windows(market.windows, start=fold_start, count=test_windows)
            first_test = selected_test[0]
            train = [
                window
                for window in market.windows[:fold_start]
                if window.future_end_ts <= first_test.end_ts
            ]
            train_markets.append(
                RelationshipMarket(
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    bars=market.bars,
                    windows=train,
                    source=market.source,
                    source_path=market.source_path,
                )
            )
            test_by_market.extend(selected_test)
        mined = mine_relationships(
            train_markets,
            min_support=min_support,
            top_n=top_n,
            pairwise=pairwise,
            large_move_bps=large_move_bps,
        )
        test_global = _window_summary(test_by_market, large_move_bps=large_move_bps)
        candidates = list(mined["top_positive"]) + list(mined["top_negative"])
        fold_validations = [
            _validate_candidate(
                candidate,
                test_by_market,
                test_global_avg=float(test_global["avg_future_return_bps"]),
                min_test_support=min_test_support,
                large_move_bps=large_move_bps,
            )
            for candidate in candidates
        ]
        fold_validations = [item for item in fold_validations if item["test_support"] >= min_test_support]
        validated.extend(fold_validations)
        fold_results.append(
            {
                "fold_index": fold_index,
                "fold_start": fold_start,
                "train_windows": sum(len(market.windows) for market in train_markets),
                "test_windows": len(test_by_market),
                "test_global": test_global,
                "validated": fold_validations,
            }
        )

    preserved = [item for item in validated if item["sign_preserved"]]
    signed_lifts = [float(item["signed_test_lift_bps"]) for item in validated]
    top_validated = sorted(
        validated,
        key=lambda item: float(item["signed_test_lift_bps"]) * math.sqrt(max(1, int(item["test_support"]))),
        reverse=True,
    )[:top_n]
    top_relationships = _aggregate_validations(validated)[:top_n]
    failed = sorted(validated, key=lambda item: float(item["signed_test_lift_bps"]))[:top_n]
    return {
        "scenario": {
            "name": "crypto_relationship_validation",
            "markets": [
                {
                    "symbol": market.symbol,
                    "timeframe": market.timeframe,
                    "bars": len(market.bars),
                    "windows": len(market.windows),
                    "source": market.source,
                    "source_path": market.source_path,
                }
                for market in markets
            ],
            "train_windows": int(train_windows),
            "test_windows": int(test_windows),
            "folds": len(starts),
            "fold_stride": int(fold_stride) if fold_stride is not None else None,
            "min_support": int(min_support),
            "min_test_support": int(min_test_support),
            "top_n": int(top_n),
            "pairwise": bool(pairwise),
            "large_move_bps": float(large_move_bps),
            "note": "Relationships are mined on train windows and tested on future windows. This is research validation, not a trading claim.",
        },
        "summary": {
            "validated_relationships": len(validated),
            "sign_preservation_rate": len(preserved) / len(validated) if validated else 0.0,
            "avg_signed_test_lift_bps": statistics.mean(signed_lifts) if signed_lifts else 0.0,
            "median_signed_test_lift_bps": statistics.median(signed_lifts) if signed_lifts else 0.0,
            "positive_oos_relationships": sum(1 for item in validated if float(item["signed_test_lift_bps"]) > 0),
            "negative_oos_relationships": sum(1 for item in validated if float(item["signed_test_lift_bps"]) <= 0),
        },
        "top_validated": top_validated,
        "top_relationships": top_relationships,
        "failed_examples": failed,
        "folds": fold_results,
    }


def write_markdown_report(payload: Mapping[str, object], path: str | Path) -> None:
    summary = payload["summary"]  # type: ignore[index]
    lines = [
        "# WaveMind Crypto Relationship Validation",
        "",
        "Train/test validation for mined OHLCV relationships. This is not financial advice.",
        "",
        "## Summary",
        "",
        f"- validated relationships: {summary['validated_relationships']}",  # type: ignore[index]
        f"- sign preservation rate: {float(summary['sign_preservation_rate']):.3f}",  # type: ignore[index]
        f"- avg signed test lift: {float(summary['avg_signed_test_lift_bps']):.2f} bps",  # type: ignore[index]
        f"- median signed test lift: {float(summary['median_signed_test_lift_bps']):.2f} bps",  # type: ignore[index]
        "",
        "## Top Aggregated Relationships",
        "",
        _aggregate_table(payload.get("top_relationships", [])),  # type: ignore[arg-type]
        "",
        "## Top Out-Of-Sample Relationship Events",
        "",
        _validation_table(payload.get("top_validated", [])),  # type: ignore[arg-type]
        "",
        "## Failed / Unstable Examples",
        "",
        _validation_table(payload.get("failed_examples", [])),  # type: ignore[arg-type]
        "",
    ]
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mined OHLCV relationships out-of-sample.")
    parser.add_argument("--dataset", choices=["synthetic", "csv", "ccxt"], default="synthetic")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument("--bars", type=int, default=720)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--direction-threshold-bps", type=float, default=30.0)
    parser.add_argument("--large-move-bps", type=float, default=75.0)
    parser.add_argument("--train-windows", type=int, default=420)
    parser.add_argument("--test-windows", type=int, default=60)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--min-support", type=int, default=30)
    parser.add_argument("--min-test-support", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--single-only", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_relationship_validation_results.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_relationship_validation_report.md"))
    args = parser.parse_args()

    markets = load_markets_from_args(args)
    payload = validate_relationships(
        markets,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        min_support=args.min_support,
        min_test_support=args.min_test_support,
        top_n=args.top_n,
        pairwise=not args.single_only,
        large_move_bps=args.large_move_bps,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(payload, args.report)
    print_table(payload)
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


def print_table(payload: Mapping[str, object]) -> None:
    print("| relationship | train lift | test lift | signed test lift | support |")
    print("|---|---:|---:|---:|---:|")
    for item in payload.get("top_validated", [])[:8]:  # type: ignore[index]
        print(
            f"| {item['relationship']} | "
            f"{float(item['train_lift_bps']):.2f} | "
            f"{float(item['test_lift_bps']):.2f} | "
            f"{float(item['signed_test_lift_bps']):.2f} | "
            f"{item['test_support']} |"
        )


def _validate_candidate(
    candidate: Mapping[str, object],
    test_windows: list[OHLCVWindow],
    *,
    test_global_avg: float,
    min_test_support: int,
    large_move_bps: float,
) -> dict:
    features = tuple(str(item) for item in candidate["features"])  # type: ignore[index]
    matched = [window for window in test_windows if _matches(window, features)]
    summary = _window_summary(matched, large_move_bps=large_move_bps)
    train_lift = float(candidate["lift_vs_global_bps"])  # type: ignore[index]
    test_lift = float(summary["avg_future_return_bps"]) - float(test_global_avg) if matched else 0.0
    expected_sign = 1.0 if train_lift >= 0.0 else -1.0
    signed_test_lift = test_lift * expected_sign
    return {
        "relationship": candidate["relationship"],
        "features": list(features),
        "expected_direction": "positive" if expected_sign > 0 else "negative",
        "train_support": int(candidate["support"]),  # type: ignore[index]
        "train_lift_bps": train_lift,
        "train_avg_future_return_bps": float(candidate["avg_future_return_bps"]),  # type: ignore[index]
        "test_support": len(matched),
        "test_support_rate": len(matched) / max(len(test_windows), 1),
        "test_avg_future_return_bps": float(summary["avg_future_return_bps"]),
        "test_lift_bps": test_lift,
        "signed_test_lift_bps": signed_test_lift,
        "sign_preserved": bool(signed_test_lift > 0.0 and len(matched) >= min_test_support),
        "test_up_rate": float(summary["up_rate"]),
        "test_down_rate": float(summary["down_rate"]),
        "test_large_move_rate": float(summary["large_move_rate"]),
    }


def _window_summary(windows: list[OHLCVWindow], *, large_move_bps: float) -> dict[str, float | int]:
    if not windows:
        return {
            "windows": 0,
            "avg_future_return_bps": 0.0,
            "median_future_return_bps": 0.0,
            "up_rate": 0.0,
            "down_rate": 0.0,
            "flat_rate": 0.0,
            "large_move_rate": 0.0,
        }
    returns = [float(window.future_return_bps) for window in windows]
    return {
        "windows": len(windows),
        "avg_future_return_bps": statistics.mean(returns),
        "median_future_return_bps": statistics.median(returns),
        "up_rate": _rate(window.direction == "up" for window in windows),
        "down_rate": _rate(window.direction == "down" for window in windows),
        "flat_rate": _rate(window.direction == "flat" for window in windows),
        "large_move_rate": _rate(abs(window.future_return_bps) >= large_move_bps for window in windows),
    }


def _validation_table(items: Iterable[Mapping[str, object]]) -> str:
    rows = [
        "| relationship | expected | train lift | test lift | signed test lift | test support |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in items:
        rows.append(
            f"| {item['relationship']} | {item['expected_direction']} | "
            f"{float(item['train_lift_bps']):.2f} | "
            f"{float(item['test_lift_bps']):.2f} | "
            f"{float(item['signed_test_lift_bps']):.2f} | "
            f"{item['test_support']} |"
        )
    return "\n".join(rows)


def _aggregate_validations(items: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        key = (str(item["relationship"]), str(item["expected_direction"]))
        grouped.setdefault(key, []).append(item)
    result = []
    for (relationship, expected_direction), group in grouped.items():
        signed = [float(item["signed_test_lift_bps"]) for item in group]
        test_lifts = [float(item["test_lift_bps"]) for item in group]
        train_lifts = [float(item["train_lift_bps"]) for item in group]
        test_support = sum(int(item["test_support"]) for item in group)
        preserved = sum(1 for item in group if item["sign_preserved"])
        result.append(
            {
                "relationship": relationship,
                "expected_direction": expected_direction,
                "occurrences": len(group),
                "sign_preservation_rate": preserved / len(group),
                "avg_signed_test_lift_bps": statistics.mean(signed),
                "median_signed_test_lift_bps": statistics.median(signed),
                "avg_test_lift_bps": statistics.mean(test_lifts),
                "avg_train_lift_bps": statistics.mean(train_lifts),
                "total_test_support": test_support,
            }
        )
    result.sort(
        key=lambda item: float(item["avg_signed_test_lift_bps"]) * math.sqrt(max(1, int(item["total_test_support"]))),
        reverse=True,
    )
    return result


def _aggregate_table(items: Iterable[Mapping[str, object]]) -> str:
    rows = [
        "| relationship | expected | occurrences | sign preserved | avg signed test lift | test support |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in items:
        rows.append(
            f"| {item['relationship']} | {item['expected_direction']} | "
            f"{item['occurrences']} | "
            f"{float(item['sign_preservation_rate']):.3f} | "
            f"{float(item['avg_signed_test_lift_bps']):.2f} | "
            f"{item['total_test_support']} |"
        )
    return "\n".join(rows)


def _matches(window: OHLCVWindow, features: tuple[str, ...]) -> bool:
    tokens = {
        f"{key}={window.features[key]}"
        for key in DEFAULT_FEATURE_KEYS
        if key in window.features and window.features[key] is not None
    }
    return all(feature in tokens for feature in features)


def _fold_starts(
    total_windows: int,
    *,
    train_windows: int,
    test_windows: int,
    folds: int,
    fold_stride: int | None,
) -> list[int]:
    if folds <= 0:
        raise ValueError("folds must be positive")
    if fold_stride is not None and fold_stride <= 0:
        raise ValueError("fold_stride must be positive")
    first = int(train_windows)
    max_start = int(total_windows) - int(test_windows)
    if max_start < first:
        raise ValueError(
            f"not enough windows: need at least {first + test_windows}, got {total_windows}. "
            "Increase --bars or reduce train/test windows."
        )
    if folds == 1:
        return [first]
    if fold_stride is not None:
        starts = [first + index * int(fold_stride) for index in range(int(folds))]
        return [start for start in starts if start <= max_start] or [first]
    span = max_start - first
    if span <= 0:
        return [first]
    return sorted(
        {
            min(max_start, max(first, int(round(first + (span * index / max(1, int(folds) - 1))))))
            for index in range(int(folds))
        }
    )


def _select_windows(windows: list[OHLCVWindow], *, start: int, count: int) -> list[OHLCVWindow]:
    end = int(start) + int(count)
    if len(windows) < end:
        raise ValueError(f"not enough windows: need at least {end}, got {len(windows)}")
    return windows[int(start) : end]


def _rate(values: Iterable[bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1.0 for item in items if item) / len(items)


if __name__ == "__main__":
    raise SystemExit(main())
