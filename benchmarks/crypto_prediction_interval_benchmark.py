from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVWindow
from benchmarks.crypto_prediction_intervals import (
    PredictionInterval,
    ScalePredictor,
    fit_prediction_interval,
    interval_score,
    mature_history,
    observable_return_scale,
    wave_risk_scale,
)
from benchmarks.crypto_price_target_benchmark import (
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    _fit_wave_calibration,
    _fold_starts,
    _market_field_target_return,
    load_markets,
)


ENGINE_ZERO = "Zero-return adaptive conformal"
ENGINE_HISTORICAL = "Historical-median adaptive conformal"
ENGINE_WAVEMIND = "WaveMind field adaptive conformal"
ENGINE_WAVEMIND_RISK = "WaveMind risk-field adaptive conformal"
DEFAULT_ENGINES = ("zero", "historical", "wavemind", "wavemind-risk")
CenterPredictor = Callable[[list[OHLCVWindow], OHLCVWindow], float]


@dataclass(frozen=True)
class IntervalEvent:
    engine: str
    symbol: str
    timeframe: str
    fold_index: int
    query_id: str
    data_end_utc: str
    target_end_utc: str
    last_close: float
    actual_return_bps: float
    center_return_bps: float
    lower_return_bps: float
    upper_return_bps: float
    lower_price: float
    center_price: float
    upper_price: float
    covered: float
    width_bps: float
    abs_center_error_bps: float
    interval_score_bps: float
    directional_signal: str
    directional_hit: float | None
    calibration_samples: int
    calibration_coverage: float


def historical_median_predictor(history: list[OHLCVWindow], query: OHLCVWindow) -> float:
    del query
    values = [float(window.future_return_bps) for window in history[-256:]]
    return float(statistics.median(values)) if values else 0.0


def zero_return_predictor(history: list[OHLCVWindow], query: OHLCVWindow) -> float:
    del history, query
    return 0.0


def run_prediction_interval_benchmark(
    *,
    markets: list[dict],
    engines: Iterable[str] = DEFAULT_ENGINES,
    train_windows: int = 360,
    test_windows: int = 90,
    folds: int = 4,
    fold_stride: int | None = None,
    calibration_windows: int = 120,
    nominal_coverage: float = 0.80,
) -> dict:
    engine_keys = [_normalize_engine(engine) for engine in engines]
    events: list[IntervalEvent] = []
    by_market: list[dict] = []
    calibration_rows: list[dict] = []

    for market in markets:
        windows = list(market["windows"])
        horizon = int(market["horizon"])
        starts = _fold_starts(
            windows,
            train_windows=train_windows,
            test_windows=test_windows,
            folds=folds,
            fold_stride=fold_stride,
        )
        for fold_index, fold_start in enumerate(starts):
            queries = windows[fold_start : fold_start + test_windows]
            if not queries:
                continue
            fold_history = mature_history(windows[:fold_start], current=queries[0])
            fit_prefix = fold_history[: max(40, len(fold_history) - calibration_windows)]
            wave_calibration = _fit_wave_calibration(
                fit_prefix,
                horizon=horizon,
                calibration_windows=min(calibration_windows, max(24, len(fit_prefix) // 2)),
            )

            predictors: dict[str, CenterPredictor] = {
                "zero": zero_return_predictor,
                "historical": historical_median_predictor,
                "wavemind": _wave_predictor(horizon=horizon, calibration=wave_calibration),
                "wavemind-risk": zero_return_predictor,
            }
            scale_predictors: dict[str, ScalePredictor | None] = {
                "zero": None,
                "historical": None,
                "wavemind": None,
                "wavemind-risk": wave_risk_scale,
            }
            fold_intervals: dict[str, PredictionInterval] = {}
            for engine_key in engine_keys:
                interval = fit_prediction_interval(
                    fold_history,
                    queries[0],
                    predictor=predictors[engine_key],
                    scale_predictor=scale_predictors[engine_key],
                    horizon=horizon,
                    nominal_coverage=nominal_coverage,
                    calibration_windows=calibration_windows,
                )
                if interval.status != "calibrated":
                    raise ValueError(
                        f"{market['symbol']} {market['timeframe']} fold {fold_index} "
                        f"has insufficient interval calibration"
                    )
                fold_intervals[engine_key] = interval
                calibration_rows.append(
                    {
                        "engine": _engine_name(engine_key),
                        "symbol": str(market["symbol"]),
                        "timeframe": str(market["timeframe"]),
                        "fold_index": int(fold_index),
                        **asdict(interval),
                    }
                )

            fold_events: list[IntervalEvent] = []
            for query in queries:
                history = mature_history(windows, current=query)
                for engine_key in engine_keys:
                    calibration = fold_intervals[engine_key]
                    center = float(predictors[engine_key](history, query))
                    scale_model = scale_predictors[engine_key]
                    scale = (
                        observable_return_scale(query, horizon=horizon)
                        if scale_model is None
                        else max(10.0, float(scale_model(history, query, horizon)))
                    )
                    half_width = float(calibration.conformal_quantile) * scale
                    event = _interval_event(
                        engine=_engine_name(engine_key),
                        window=query,
                        fold_index=fold_index,
                        center_return_bps=center,
                        lower_return_bps=center - half_width,
                        upper_return_bps=center + half_width,
                        nominal_coverage=nominal_coverage,
                        calibration=calibration,
                    )
                    events.append(event)
                    fold_events.append(event)

            for engine_key in engine_keys:
                engine_name = _engine_name(engine_key)
                by_market.append(
                    _summarize_events(
                        [event for event in fold_events if event.engine == engine_name],
                        engine=engine_name,
                        symbol=str(market["symbol"]),
                        timeframe=str(market["timeframe"]),
                        fold_index=fold_index,
                        nominal_coverage=nominal_coverage,
                    )
                )

    results = [
        _summarize_events(
            [event for event in events if event.engine == _engine_name(engine_key)],
            engine=_engine_name(engine_key),
            nominal_coverage=nominal_coverage,
        )
        for engine_key in engine_keys
    ]
    _attach_robustness(results, by_market)
    _attach_comparisons(results)
    by_timeframe: list[dict] = []
    for timeframe in sorted({str(market["timeframe"]) for market in markets}):
        timeframe_results = [
            _summarize_events(
                [
                    event
                    for event in events
                    if event.engine == _engine_name(engine_key) and event.timeframe == timeframe
                ],
                engine=_engine_name(engine_key),
                timeframe=timeframe,
                nominal_coverage=nominal_coverage,
            )
            for engine_key in engine_keys
        ]
        _attach_comparisons(timeframe_results)
        by_timeframe.extend(timeframe_results)
    return {
        "scenario": {
            "name": "crypto_adaptive_conformal_intervals",
            "dataset_requirement": "real exchange OHLCV only for published results",
            "protocol": (
                "walk-forward folds; each fold freezes its conformal quantile before the test block; "
                "only matured outcomes are visible"
            ),
            "nominal_coverage": float(nominal_coverage),
            "train_windows": int(train_windows),
            "test_windows": int(test_windows),
            "folds": int(folds),
            "fold_stride": int(fold_stride) if fold_stride is not None else None,
            "calibration_windows": int(calibration_windows),
            "markets": [
                {
                    "symbol": str(market["symbol"]),
                    "timeframe": str(market["timeframe"]),
                    "horizon_bars": int(market["horizon"]),
                    "bars": len(market["bars"]),
                    "windows": len(market["windows"]),
                    "source": str(market["source"]),
                }
                for market in markets
            ],
            "note": "Research evidence only. Prediction intervals and center estimates are not financial advice.",
        },
        "results": results,
        "by_timeframe": by_timeframe,
        "by_market": by_market,
        "calibration": calibration_rows,
        "event_metrics": [asdict(event) for event in events],
    }


def _wave_predictor(*, horizon: int, calibration: object) -> CenterPredictor:
    def predict(history: list[OHLCVWindow], query: OHLCVWindow) -> float:
        value, _, _ = _market_field_target_return(
            history,
            query,
            horizon=horizon,
            calibration=calibration,
        )
        return float(value)

    return predict


def _interval_event(
    *,
    engine: str,
    window: OHLCVWindow,
    fold_index: int,
    center_return_bps: float,
    lower_return_bps: float,
    upper_return_bps: float,
    nominal_coverage: float,
    calibration: PredictionInterval,
) -> IntervalEvent:
    actual = float(window.future_return_bps)
    covered = float(lower_return_bps <= actual <= upper_return_bps)
    if lower_return_bps > 0.0:
        directional_signal = "up"
        directional_hit = float(actual > 0.0)
    elif upper_return_bps < 0.0:
        directional_signal = "down"
        directional_hit = float(actual < 0.0)
    else:
        directional_signal = "none"
        directional_hit = None
    last_close = float(window.bars[-1].close)
    return IntervalEvent(
        engine=engine,
        symbol=window.symbol,
        timeframe=window.timeframe,
        fold_index=int(fold_index),
        query_id=window.id,
        data_end_utc=window.observed_until_time,
        target_end_utc=window.target_until_time,
        last_close=last_close,
        actual_return_bps=actual,
        center_return_bps=float(center_return_bps),
        lower_return_bps=float(lower_return_bps),
        upper_return_bps=float(upper_return_bps),
        lower_price=last_close * (1.0 + lower_return_bps / 10_000.0),
        center_price=last_close * (1.0 + center_return_bps / 10_000.0),
        upper_price=last_close * (1.0 + upper_return_bps / 10_000.0),
        covered=covered,
        width_bps=float(upper_return_bps - lower_return_bps),
        abs_center_error_bps=abs(center_return_bps - actual),
        interval_score_bps=interval_score(
            actual,
            lower_return_bps,
            upper_return_bps,
            nominal_coverage=nominal_coverage,
        ),
        directional_signal=directional_signal,
        directional_hit=directional_hit,
        calibration_samples=int(calibration.calibration_samples),
        calibration_coverage=float(calibration.calibration_coverage),
    )


def _summarize_events(
    events: list[IntervalEvent],
    *,
    engine: str,
    nominal_coverage: float,
    symbol: str = "all",
    timeframe: str = "all",
    fold_index: int = -1,
) -> dict:
    directional = [event for event in events if event.directional_hit is not None]
    if not events:
        return {
            "engine": engine,
            "symbol": symbol,
            "timeframe": timeframe,
            "fold_index": int(fold_index),
            "queries": 0,
        }
    coverage = statistics.mean(event.covered for event in events)
    return {
        "engine": engine,
        "symbol": symbol,
        "timeframe": timeframe,
        "fold_index": int(fold_index),
        "queries": len(events),
        "nominal_coverage": float(nominal_coverage),
        "empirical_coverage": float(coverage),
        "coverage_error": abs(float(coverage) - float(nominal_coverage)),
        "mean_width_bps": statistics.mean(event.width_bps for event in events),
        "median_width_bps": statistics.median(event.width_bps for event in events),
        "mean_interval_score_bps": statistics.mean(event.interval_score_bps for event in events),
        "mean_abs_center_error_bps": statistics.mean(event.abs_center_error_bps for event in events),
        "directional_signals": len(directional),
        "directional_signal_rate": len(directional) / len(events),
        "directional_accuracy": (
            statistics.mean(float(event.directional_hit) for event in directional) if directional else None
        ),
    }


def _attach_robustness(results: list[dict], by_market: list[dict]) -> None:
    for result in results:
        slices = [
            row
            for row in by_market
            if row.get("engine") == result["engine"] and int(row.get("queries", 0)) > 0
        ]
        result["market_slices"] = len(slices)
        result["worst_slice_coverage"] = min(float(row["empirical_coverage"]) for row in slices)
        result["best_slice_coverage"] = max(float(row["empirical_coverage"]) for row in slices)
        result["worst_slice_interval_score_bps"] = max(
            float(row["mean_interval_score_bps"]) for row in slices
        )
        signal_slices = [row for row in slices if int(row["directional_signals"]) > 0]
        result["directional_signal_slices"] = len(signal_slices)
        result["worst_signal_slice_accuracy"] = (
            min(float(row["directional_accuracy"]) for row in signal_slices)
            if signal_slices
            else None
        )


def _attach_comparisons(results: list[dict]) -> None:
    by_name = {str(result["engine"]): result for result in results}
    baseline = by_name.get(ENGINE_ZERO)
    if baseline is None:
        return
    baseline_score = float(baseline["mean_interval_score_bps"])
    baseline_width = float(baseline["mean_width_bps"])
    for result in results:
        score = float(result["mean_interval_score_bps"])
        width = float(result["mean_width_bps"])
        result["interval_score_improvement_vs_zero"] = (
            (baseline_score - score) / baseline_score if baseline_score > 0.0 else 0.0
        )
        result["width_reduction_vs_zero"] = (
            (baseline_width - width) / baseline_width if baseline_width > 0.0 else 0.0
        )


def sampled_payload(payload: dict, *, sample_size: int = 240) -> dict:
    copied = dict(payload)
    events = list(payload.get("event_metrics", []))
    copied["event_metrics_total"] = len(events)
    copied["event_metrics_sample_size"] = min(len(events), int(sample_size))
    copied["event_metrics_truncated"] = len(events) > int(sample_size)
    copied["event_metrics"] = events[: int(sample_size)]
    return copied


def render_markdown(payload: dict) -> str:
    nominal = float(payload["scenario"]["nominal_coverage"])
    lines = [
        "# WaveMind Crypto Prediction Interval Benchmark",
        "",
        "Real-OHLCV walk-forward evaluation of adaptive conformal price ranges. "
        "Lower interval score is better. This is research evidence, not financial advice.",
        "",
        f"Nominal coverage: `{nominal:.0%}`.",
        "",
        "| engine | queries | coverage | mean width | interval score | center MAE | directional signals | signal accuracy | score vs zero |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in payload["results"]:
        accuracy = (
            "n/a"
            if result["directional_accuracy"] is None
            else f"{float(result['directional_accuracy']):.3f}"
        )
        lines.append(
            "| "
            f"{result['engine']} | {result['queries']} | {result['empirical_coverage']:.3f} | "
            f"{result['mean_width_bps']:.1f} bps | {result['mean_interval_score_bps']:.1f} bps | "
            f"{result['mean_abs_center_error_bps']:.1f} bps | {result['directional_signals']} "
            f"({result['directional_signal_rate']:.1%}) | {accuracy} | "
            f"{result['interval_score_improvement_vs_zero']:+.1%} |"
        )
    lines.extend(
        [
            "",
            "## By Timeframe",
            "",
            "| engine | timeframe | queries | coverage | mean width | interval score | score vs zero |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for result in payload["by_timeframe"]:
        lines.append(
            "| "
            f"{result['engine']} | {result['timeframe']} | {result['queries']} | "
            f"{result['empirical_coverage']:.3f} | {result['mean_width_bps']:.1f} bps | "
            f"{result['mean_interval_score_bps']:.1f} bps | "
            f"{result['interval_score_improvement_vs_zero']:+.1%} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The center estimate is not presented as a precise future price.",
            "- The range is calibrated on matured errors before each test fold.",
            "- A directional signal exists only when the entire interval is above or below zero.",
            "- Wide ranges are an honest result when the market state does not support precision.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_engine(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    aliases = {
        "zero": "zero",
        "zero-return": "zero",
        "historical": "historical",
        "historical-median": "historical",
        "wavemind": "wavemind",
        "wave": "wavemind",
        "field": "wavemind",
        "wavemind-risk": "wavemind-risk",
        "risk-field": "wavemind-risk",
    }
    if key not in aliases:
        raise ValueError(f"Unknown interval engine {value!r}")
    return aliases[key]


def _engine_name(key: str) -> str:
    return {
        "zero": ENGINE_ZERO,
        "historical": ENGINE_HISTORICAL,
        "wavemind": ENGINE_WAVEMIND,
        "wavemind-risk": ENGINE_WAVEMIND_RISK,
    }[key]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward adaptive conformal interval benchmark for WaveMind crypto research."
    )
    parser.add_argument("--dataset", choices=["cached", "ccxt"], default="cached")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--cache-dir", type=Path, default=Path("benchmarks/data/crypto_ohlcv"))
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--engines", nargs="+", default=list(DEFAULT_ENGINES))
    parser.add_argument("--bars", type=int, default=1200)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--train-windows", type=int, default=360)
    parser.add_argument("--test-windows", type=int, default=90)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--calibration-windows", type=int, default=120)
    parser.add_argument("--nominal-coverage", type=float, default=0.80)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/crypto_prediction_interval_results.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("benchmarks/crypto_prediction_interval_report.md"),
    )
    parser.add_argument("--events-output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = load_markets(
        dataset=args.dataset,
        symbols=args.symbols,
        timeframes=args.timeframes,
        exchange=args.exchange,
        cache_dir=args.cache_dir,
        bars=args.bars,
        window=args.window,
    )
    payload = run_prediction_interval_benchmark(
        markets=markets,
        engines=args.engines,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        calibration_windows=args.calibration_windows,
        nominal_coverage=args.nominal_coverage,
    )
    if args.events_output is not None:
        args.events_output.parent.mkdir(parents=True, exist_ok=True)
        with args.events_output.open("w", encoding="utf-8") as handle:
            for event in payload["event_metrics"]:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    output = sampled_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = render_markdown(output)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
