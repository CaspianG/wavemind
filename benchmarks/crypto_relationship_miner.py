from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    OHLCVWindow,
    fetch_ohlcv_ccxt,
    generate_synthetic_ohlcv,
    load_ohlcv_csv,
    make_ohlcv_windows,
    save_ohlcv_csv,
)


DEFAULT_FEATURE_KEYS = (
    "trend",
    "recent_trend",
    "rsi_bucket",
    "volatility_bucket",
    "volume_bucket",
    "close_position_bucket",
    "drawdown_bucket",
    "macd_bucket",
    "bollinger_bucket",
)


@dataclass(frozen=True)
class RelationshipMarket:
    symbol: str
    timeframe: str
    bars: list[OHLCVBar]
    windows: list[OHLCVWindow]
    source: str = ""
    source_path: str = ""


@dataclass(frozen=True)
class RelationshipFinding:
    relationship: str
    features: tuple[str, ...]
    support: int
    support_rate: float
    avg_future_return_bps: float
    median_future_return_bps: float
    lift_vs_global_bps: float
    abs_lift_score: float
    up_rate: float
    down_rate: float
    flat_rate: float
    large_move_rate: float
    avg_mfe_bps: float
    avg_mae_bps: float


def mine_relationships(
    markets: list[RelationshipMarket],
    *,
    feature_keys: Iterable[str] = DEFAULT_FEATURE_KEYS,
    min_support: int = 20,
    top_n: int = 15,
    pairwise: bool = True,
    large_move_bps: float = 75.0,
) -> dict:
    windows = [window for market in markets for window in market.windows]
    if not windows:
        raise ValueError("no windows to mine")
    keys = tuple(feature_keys)
    global_summary = _summarize_windows(windows, large_move_bps=large_move_bps)
    global_avg = float(global_summary["avg_future_return_bps"])
    candidates: dict[tuple[str, ...], list[OHLCVWindow]] = {}
    for window in windows:
        tokens = [
            f"{key}={window.features[key]}"
            for key in keys
            if key in window.features and window.features[key] is not None
        ]
        for token in tokens:
            candidates.setdefault((token,), []).append(window)
        if pairwise:
            for left, right in itertools.combinations(tokens, 2):
                candidates.setdefault(tuple(sorted((left, right))), []).append(window)

    findings = [
        _finding_from_group(
            relationship=relationship,
            group=group,
            total=len(windows),
            global_avg=global_avg,
            large_move_bps=large_move_bps,
        )
        for relationship, group in candidates.items()
        if len(group) >= int(min_support)
    ]
    findings.sort(key=lambda item: item.abs_lift_score, reverse=True)
    positive = sorted(
        (item for item in findings if item.lift_vs_global_bps > 0),
        key=lambda item: item.abs_lift_score,
        reverse=True,
    )[:top_n]
    negative = sorted(
        (item for item in findings if item.lift_vs_global_bps < 0),
        key=lambda item: item.abs_lift_score,
        reverse=True,
    )[:top_n]
    large_moves = sorted(
        findings,
        key=lambda item: (item.large_move_rate, item.support),
        reverse=True,
    )[:top_n]
    return {
        "scenario": {
            "name": "crypto_relationship_miner",
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
            "feature_keys": list(keys),
            "min_support": int(min_support),
            "pairwise": bool(pairwise),
            "large_move_bps": float(large_move_bps),
            "note": "Relationship mining over historical OHLCV windows. This is research evidence, not a trading claim.",
        },
        "global": global_summary,
        "top_positive": [asdict(item) for item in positive],
        "top_negative": [asdict(item) for item in negative],
        "top_large_move": [asdict(item) for item in large_moves],
    }


def write_markdown_report(payload: Mapping[str, object], path: str | Path) -> None:
    scenario = payload["scenario"]  # type: ignore[index]
    global_summary = payload["global"]  # type: ignore[index]
    lines = [
        "# WaveMind Crypto Relationship Report",
        "",
        "Research-only relationship mining over historical OHLCV windows. This is not financial advice.",
        "",
        "## Scenario",
        "",
        f"- windows: {global_summary['windows']}",  # type: ignore[index]
        f"- global avg future return: {float(global_summary['avg_future_return_bps']):.2f} bps",  # type: ignore[index]
        f"- global large-move rate: {float(global_summary['large_move_rate']):.3f}",  # type: ignore[index]
        f"- min support: {scenario['min_support']}",  # type: ignore[index]
        f"- pairwise: {scenario['pairwise']}",  # type: ignore[index]
        "",
        "## Top Positive Relationships",
        "",
        _finding_table(payload.get("top_positive", [])),  # type: ignore[arg-type]
        "",
        "## Top Negative Relationships",
        "",
        _finding_table(payload.get("top_negative", [])),  # type: ignore[arg-type]
        "",
        "## Top Large-Move Relationships",
        "",
        _finding_table(payload.get("top_large_move", [])),  # type: ignore[arg-type]
        "",
    ]
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def load_markets_from_args(args: argparse.Namespace) -> list[RelationshipMarket]:
    markets: list[RelationshipMarket] = []
    if args.dataset == "synthetic":
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                bars = generate_synthetic_ohlcv(symbol=symbol, timeframe=timeframe, bars=args.bars, seed=args.seed)
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=args.direction_threshold_bps,
                )
                markets.append(RelationshipMarket(symbol, timeframe, bars, windows, source="synthetic"))
        return markets
    if args.dataset == "csv":
        if args.csv is None:
            raise ValueError("--csv is required for --dataset csv")
        if len(args.symbols) != 1 or len(args.timeframes) != 1:
            raise ValueError("--dataset csv expects one symbol and one timeframe")
        bars = load_ohlcv_csv(args.csv)
        windows = make_ohlcv_windows(
            bars,
            symbol=args.symbols[0],
            timeframe=args.timeframes[0],
            window=args.window,
            horizon=args.horizon,
            direction_threshold_bps=args.direction_threshold_bps,
        )
        return [RelationshipMarket(args.symbols[0], args.timeframes[0], bars, windows, source="csv", source_path=str(args.csv))]
    if args.dataset == "ccxt":
        if args.exchange is None:
            raise ValueError("--exchange is required for --dataset ccxt")
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                cache_path = _ccxt_cache_path(args.cache_dir, args.exchange, symbol, timeframe)
                if cache_path is not None and cache_path.exists() and not args.refresh_cache:
                    bars = load_ohlcv_csv(cache_path)
                    source = f"ccxt_cache:{args.exchange}"
                    source_path = str(cache_path)
                else:
                    bars = fetch_ohlcv_ccxt(
                        exchange_id=args.exchange,
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=args.bars,
                    )
                    source = f"ccxt:{args.exchange}"
                    source_path = ""
                    if cache_path is not None:
                        save_ohlcv_csv(cache_path, bars)
                        source_path = str(cache_path)
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=args.direction_threshold_bps,
                )
                markets.append(RelationshipMarket(symbol, timeframe, bars, windows, source=source, source_path=source_path))
        return markets
    raise ValueError(f"Unknown dataset: {args.dataset}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine explainable OHLCV regime relationships.")
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
    parser.add_argument("--min-support", type=int, default=30)
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--single-only", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_relationship_results.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_relationship_report.md"))
    args = parser.parse_args()

    markets = load_markets_from_args(args)
    payload = mine_relationships(
        markets,
        min_support=args.min_support,
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
    print("| relationship | support | lift bps | avg return bps | large move |")
    print("|---|---:|---:|---:|---:|")
    for item in payload.get("top_positive", [])[:8]:  # type: ignore[index]
        print(
            f"| {item['relationship']} | {item['support']} | "
            f"{float(item['lift_vs_global_bps']):.2f} | "
            f"{float(item['avg_future_return_bps']):.2f} | "
            f"{float(item['large_move_rate']):.3f} |"
        )


def _summarize_windows(windows: list[OHLCVWindow], *, large_move_bps: float) -> dict[str, float | int]:
    returns = [float(window.future_return_bps) for window in windows]
    return {
        "windows": len(windows),
        "avg_future_return_bps": statistics.mean(returns),
        "median_future_return_bps": statistics.median(returns),
        "up_rate": _rate(window.direction == "up" for window in windows),
        "down_rate": _rate(window.direction == "down" for window in windows),
        "flat_rate": _rate(window.direction == "flat" for window in windows),
        "large_move_rate": _rate(abs(window.future_return_bps) >= large_move_bps for window in windows),
        "avg_mfe_bps": statistics.mean(float(window.max_favorable_excursion_bps) for window in windows),
        "avg_mae_bps": statistics.mean(float(window.max_adverse_excursion_bps) for window in windows),
    }


def _finding_from_group(
    *,
    relationship: tuple[str, ...],
    group: list[OHLCVWindow],
    total: int,
    global_avg: float,
    large_move_bps: float,
) -> RelationshipFinding:
    returns = [float(window.future_return_bps) for window in group]
    avg_return = statistics.mean(returns)
    lift = avg_return - global_avg
    support = len(group)
    return RelationshipFinding(
        relationship=" & ".join(relationship),
        features=relationship,
        support=support,
        support_rate=support / max(total, 1),
        avg_future_return_bps=avg_return,
        median_future_return_bps=statistics.median(returns),
        lift_vs_global_bps=lift,
        abs_lift_score=abs(lift) * math.sqrt(support),
        up_rate=_rate(window.direction == "up" for window in group),
        down_rate=_rate(window.direction == "down" for window in group),
        flat_rate=_rate(window.direction == "flat" for window in group),
        large_move_rate=_rate(abs(window.future_return_bps) >= large_move_bps for window in group),
        avg_mfe_bps=statistics.mean(float(window.max_favorable_excursion_bps) for window in group),
        avg_mae_bps=statistics.mean(float(window.max_adverse_excursion_bps) for window in group),
    )


def _finding_table(items: Iterable[Mapping[str, object]]) -> str:
    rows = [
        "| relationship | support | lift bps | avg return bps | up | down | large move |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in items:
        rows.append(
            f"| {item['relationship']} | {item['support']} | "
            f"{float(item['lift_vs_global_bps']):.2f} | "
            f"{float(item['avg_future_return_bps']):.2f} | "
            f"{float(item['up_rate']):.3f} | "
            f"{float(item['down_rate']):.3f} | "
            f"{float(item['large_move_rate']):.3f} |"
        )
    return "\n".join(rows)


def _rate(values: Iterable[bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1.0 for item in items if item) / len(items)


def _ccxt_cache_path(cache_dir: Path | None, exchange: str, symbol: str, timeframe: str) -> Path | None:
    if cache_dir is None:
        return None
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    return cache_dir / exchange / f"{safe_symbol}_{timeframe}.csv"


if __name__ == "__main__":
    raise SystemExit(main())
