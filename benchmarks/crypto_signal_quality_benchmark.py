from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVWindow, timeframe_to_seconds  # noqa: E402
from benchmarks.crypto_price_target_benchmark import (  # noqa: E402
    DEFAULT_EVENT_SAMPLE_SIZE,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    PriceTargetEvent,
    _default_directional_policy,
    _directional_candidate_values,
    _fit_directional_policy,
    _fit_wave_calibration,
    _fold_starts,
    _force_nonzero,
    _market_field_value_from_features,
    _mature_history,
    _perp_field_value_from_features,
    _price_target_event,
    _robust_value_from_features,
    _signed_direction,
    _summarize_events,
    _target_model_features,
    load_markets,
)


COMPONENT_NAMES = ("raw_wave", "calibrated_wave", "momentum", "regime", "historical", "naive")


@dataclass(frozen=True)
class SignalTier:
    name: str
    min_agreement: float = 0.0
    min_strength: float = 0.0
    min_magnitude_bps: float = 0.0
    max_volatility_bps: float | None = None
    description: str = ""


@dataclass(frozen=True)
class SignalQualityEvent:
    engine: str
    symbol: str
    timeframe: str
    fold_index: int
    query_id: str
    data_end_utc: str
    target_end_utc: str
    last_close: float
    actual_return_bps: float
    predicted_return_bps: float
    actual_price: float
    predicted_price: float
    abs_return_error_bps: float
    abs_pct_error: float
    direction_hit: float
    predicted_direction: str
    actual_direction: str
    support: int
    method: str
    agreement: float
    strength: float
    magnitude_bps: float
    volatility_bps: float
    component_signs: dict[str, str]
    confidence_is_probability: bool
    confidence_note: str


DEFAULT_SIGNAL_TIERS: tuple[SignalTier, ...] = (
    SignalTier(
        name="all_forecasts",
        description="Every forced price forecast. This is the full research baseline, not a trade-quality filter.",
    ),
    SignalTier(
        name="broad_trade_quality",
        min_agreement=0.50,
        min_strength=0.25,
        max_volatility_bps=250.0,
        description="Broad evidence filter: component agreement plus moderate volatility guard.",
    ),
    SignalTier(
        name="strong_trade_quality",
        min_agreement=0.50,
        min_strength=0.50,
        max_volatility_bps=250.0,
        description="Stronger evidence filter with better historical direction hit at lower coverage.",
    ),
    SignalTier(
        name="high_conviction",
        min_agreement=0.50,
        min_strength=0.75,
        max_volatility_bps=250.0,
        description="High-conviction subset: fewer forecasts promoted to trade-quality.",
    ),
    SignalTier(
        name="large_move_directional_edge",
        min_agreement=0.125,
        min_magnitude_bps=300.0,
        max_volatility_bps=250.0,
        description="Large predicted move diagnostic tier. Measures directional edge, not precise target-price quality.",
    ),
    SignalTier(
        name="consensus_edge",
        min_agreement=1.00,
        min_strength=0.50,
        min_magnitude_bps=25.0,
        max_volatility_bps=100.0,
        description="All policy components agree in a calm regime; low coverage, high historical direction hit.",
    ),
    SignalTier(
        name="strict_consensus_edge",
        min_agreement=1.00,
        min_strength=0.75,
        min_magnitude_bps=50.0,
        max_volatility_bps=100.0,
        description="Strictest calm-consensus edge tier. Useful as a signal-quality smoke test, not as coverage.",
    ),
)


def run_signal_quality_benchmark(
    *,
    markets: list[dict],
    train_windows: int = 360,
    test_windows: int = 90,
    folds: int = 4,
    fold_stride: int | None = None,
    calibration_windows: int = 120,
    tiers: Iterable[SignalTier] = DEFAULT_SIGNAL_TIERS,
    target_engine: str = "market-field",
) -> dict:
    target_engine_key = _normalize_target_engine(target_engine)
    events: list[SignalQualityEvent] = []
    for market in markets:
        windows = list(market["windows"])
        starts = _fold_starts(
            windows,
            train_windows=train_windows,
            test_windows=test_windows,
            folds=folds,
            fold_stride=fold_stride,
        )
        for fold_index, fold_start in enumerate(starts):
            calibration = _fit_wave_calibration(
                windows[:fold_start],
                horizon=int(market["horizon"]),
                calibration_windows=calibration_windows,
            )
            directional_policy = (
                _fit_directional_policy(
                    windows[:fold_start],
                    horizon=int(market["horizon"]),
                    calibration=calibration,
                    calibration_windows=calibration_windows,
                )
                if target_engine_key == "perp-field"
                else _default_directional_policy("not_requested")
            )
            for query in windows[fold_start : fold_start + test_windows]:
                history = _mature_history(windows, current=query)
                if len(history) < 4:
                    continue
                events.append(
                    _signal_quality_event(
                        history=history,
                        query=query,
                        horizon=int(market["horizon"]),
                        fold_index=fold_index,
                        calibration=calibration,
                        target_engine=target_engine_key,
                        directional_policy=directional_policy,
                    )
                )

    tier_results = [
        _summarize_tier(events, tier=tier)
        for tier in tiers
    ]
    by_tier_timeframe = [
        _summarize_tier_timeframe(events, tier=tier, timeframe=timeframe)
        for tier in tiers
        for timeframe in sorted({event.timeframe for event in events})
    ]
    return {
        "scenario": {
            "name": "crypto_signal_quality_walk_forward",
            "target": "separate always-on market-field target-price forecasts from historically stronger trade-quality subsets",
            "train_windows": int(train_windows),
            "test_windows": int(test_windows),
            "folds": int(folds),
            "fold_stride": int(fold_stride) if fold_stride is not None else None,
            "calibration_windows": int(calibration_windows),
            "target_engine": target_engine_key,
            "markets": [
                {
                    "symbol": str(market["symbol"]),
                    "timeframe": str(market["timeframe"]),
                    "horizon_bars": int(market["horizon"]),
                    "horizon_seconds": int(market["horizon"]) * timeframe_to_seconds(str(market["timeframe"])),
                    "bars": len(market["bars"]),
                    "windows": len(market["windows"]),
                    "source": str(market["source"]),
                }
                for market in markets
            ],
            "confidence_is_probability": False,
            "note": (
                "Research benchmark only. The forecast always has an up/down target price; "
                "signal tiers decide whether historical evidence is strong enough to call it trade-quality. "
                "This is not financial advice."
            ),
        },
        "tiers": [asdict(tier) for tier in tiers],
        "results": tier_results,
        "by_tier_timeframe": by_tier_timeframe,
        "event_metrics": [asdict(event) for event in events],
    }


def sampled_signal_quality_payload(payload: dict, *, sample_size: int = DEFAULT_EVENT_SAMPLE_SIZE) -> dict:
    events = list(payload.get("event_metrics", []))
    copied = dict(payload)
    copied["event_metrics_total"] = len(events)
    copied["event_metrics_sample_size"] = min(int(sample_size), len(events))
    copied["event_metrics_truncated"] = len(events) > int(sample_size)
    copied["event_metrics"] = events[: int(sample_size)]
    return copied


def render_markdown(payload: dict) -> str:
    lines = [
        "# WaveMind Crypto Signal Quality Benchmark",
        "",
        "Walk-forward benchmark for separating always-on price forecasts from trade-quality subsets. This is not financial advice.",
        "",
        "The price forecast always exists. The signal tier is a historical evidence filter, not a calibrated probability.",
        "",
        "## Summary",
        "",
        "| tier | selected | coverage | direction hit | MAE return | MAPE | within 50 bps | worst slice hit | mean agreement | mean strength |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in payload["results"]:
        lines.append(
            "| "
            f"{result['tier']} | {result['selected_queries']} | {result['coverage']:.3f} | "
            f"{result['direction_hit_rate']:.3f} | {result['mean_abs_return_error_bps']:.1f} bps | "
            f"{result['mape_pct']:.2f}% | {result['within_50bps_rate']:.3f} | "
            f"{result.get('worst_slice_direction_hit_rate', 0.0):.3f} | "
            f"{result['mean_agreement']:.3f} | {result['mean_strength']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## By Timeframe",
            "",
            "| tier | timeframe | selected | coverage | direction hit | MAE return | MAPE |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["by_tier_timeframe"]:
        lines.append(
            "| "
            f"{row['tier']} | {row['timeframe']} | {row['selected_queries']} | {row['coverage']:.3f} | "
            f"{row['direction_hit_rate']:.3f} | {row['mean_abs_return_error_bps']:.1f} bps | {row['mape_pct']:.2f}% |"
        )
    lines.extend(
        [
            "",
            "Interpretation: higher tiers are diagnostics, not guarantees. Some tiers optimize direction hit, "
            "others should also improve target error. A high tier with tiny coverage is evidence of selective edge, "
            "not a standalone trading system.",
            "",
        ]
    )
    return "\n".join(lines)


def _signal_quality_event(
    *,
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    horizon: int,
    fold_index: int,
    calibration,
    target_engine: str,
    directional_policy,
) -> SignalQualityEvent:
    features = _target_model_features(history, query, horizon=horizon, calibration=calibration)
    if target_engine == "robust":
        predicted_return_bps, suffix = _robust_value_from_features(features, query.timeframe)
        engine_name = "WaveMind robust target"
        method_prefix = "signal_quality_robust"
    elif target_engine == "perp-field":
        predicted_return_bps, suffix = _perp_field_value_from_features(features, query.timeframe, directional_policy)
        engine_name = "WaveMind perp field target"
        method_prefix = "signal_quality_perp"
    else:
        predicted_return_bps, suffix = _market_field_value_from_features(features, query.timeframe)
        engine_name = "WaveMind market-field target"
        method_prefix = "signal_quality"
    support = int(max(0.0, round(features.get("support_count", 0.0))))
    price_event = _price_target_event(
        engine=engine_name,
        window=query,
        predicted_return_bps=predicted_return_bps,
        support=support,
        method=f"{method_prefix}+{suffix}",
        fold_index=fold_index,
    )
    component_values = _policy_component_values(
        features,
        query.timeframe,
        predicted_return_bps,
        target_engine=target_engine,
    )
    predicted_direction = _signed_direction(predicted_return_bps)
    agreement = sum(1 for value in component_values.values() if _signed_direction(value) == predicted_direction) / len(component_values)
    volatility = abs(float(features.get("volatility_bps", 0.0)))
    strength = abs(float(predicted_return_bps)) / max(volatility, 1.0)
    return _quality_from_price_event(
        price_event,
        agreement=agreement,
        strength=strength,
        volatility_bps=volatility,
        component_signs={name: _signed_direction(value) for name, value in component_values.items()},
    )


def _policy_component_values(
    features: dict[str, float],
    timeframe: str,
    predicted_return_bps: float,
    *,
    target_engine: str = "market-field",
) -> dict[str, float]:
    if target_engine == "perp-field":
        candidates = _directional_candidate_values(features, timeframe)
        return {
            "selected_policy": predicted_return_bps,
            "raw_wave": candidates["raw_wave"],
            "calibrated_wave": candidates["calibrated_wave"],
            "momentum": candidates["momentum"],
            "regime": candidates["regime"],
            "historical": candidates["historical"],
            "robust": candidates["robust"],
            "market_field": candidates["market_field"],
        }
    raw_wave = _force_nonzero(float(features.get("raw_wave", 0.0)), fallback=predicted_return_bps)
    calibrated_wave = _force_nonzero(float(features.get("calibrated_wave", raw_wave)), fallback=predicted_return_bps)
    momentum = _force_nonzero(float(features.get("momentum", calibrated_wave)), fallback=predicted_return_bps)
    regime = _force_nonzero(float(features.get("regime", calibrated_wave)), fallback=predicted_return_bps)
    historical = _force_nonzero(float(features.get("historical", calibrated_wave)), fallback=predicted_return_bps)
    naive = _force_nonzero(float(features.get("naive", momentum)), fallback=predicted_return_bps)
    if timeframe == "1h":
        return {
            "intraday_regime_reversion": -regime,
            "intraday_momentum_reversion": -momentum,
            "intraday_historical_reversion": -historical,
            "naive_reversion": -naive,
        }
    if timeframe == "4h":
        return {
            "swing_momentum_reversion": -momentum,
            "swing_raw_wave_reversion": -raw_wave,
            "swing_historical_reversion": -historical,
            "swing_regime_reversion": -regime,
        }
    if timeframe == "1d":
        return {
            "daily_historical_reversion": -historical,
            "daily_raw_wave_reversion": -raw_wave,
            "daily_regime": regime,
            "daily_calibrated_wave": calibrated_wave,
        }
    return {
        name: _force_nonzero(float(features.get(name, 0.0)), fallback=predicted_return_bps)
        for name in COMPONENT_NAMES
    }


def _normalize_target_engine(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    aliases = {
        "robust": "robust",
        "robust-target": "robust",
        "wavemind-robust": "robust",
        "wavemind-robust-target": "robust",
        "market": "market-field",
        "market-field": "market-field",
        "wavemind-market-field": "market-field",
        "perp": "perp-field",
        "perp-field": "perp-field",
        "perp-field-target": "perp-field",
        "wavemind-perp-field": "perp-field",
        "wavemind-perp-field-target": "perp-field",
    }
    if key not in aliases:
        raise ValueError(f"Unknown signal-quality target engine {value!r}")
    return aliases[key]


def _quality_from_price_event(
    event: PriceTargetEvent,
    *,
    agreement: float,
    strength: float,
    volatility_bps: float,
    component_signs: dict[str, str],
) -> SignalQualityEvent:
    return SignalQualityEvent(
        engine=event.engine,
        symbol=event.symbol,
        timeframe=event.timeframe,
        fold_index=event.fold_index,
        query_id=event.query_id,
        data_end_utc=event.data_end_utc,
        target_end_utc=window_target_end_time_from_event(event),
        last_close=event.last_close,
        actual_return_bps=event.actual_return_bps,
        predicted_return_bps=event.predicted_return_bps,
        actual_price=event.actual_price,
        predicted_price=event.predicted_price,
        abs_return_error_bps=event.abs_return_error_bps,
        abs_pct_error=event.abs_pct_error,
        direction_hit=event.direction_hit,
        predicted_direction=event.predicted_direction,
        actual_direction=event.actual_direction,
        support=event.support,
        method=event.method,
        agreement=float(agreement),
        strength=float(strength),
        magnitude_bps=abs(float(event.predicted_return_bps)),
        volatility_bps=float(volatility_bps),
        component_signs=component_signs,
        confidence_is_probability=False,
        confidence_note="agreement and strength are evidence filters, not calibrated probabilities",
    )


def window_target_end_time_from_event(event: PriceTargetEvent) -> str:
    return event.target_end_utc


def _summarize_tier(events: list[SignalQualityEvent], *, tier: SignalTier) -> dict:
    selected = _select_tier(events, tier)
    summary = _summarize_signal_events(selected, tier=tier, total_queries=len(events), timeframe="")
    _attach_quality_robustness(summary, selected)
    return summary


def _summarize_tier_timeframe(events: list[SignalQualityEvent], *, tier: SignalTier, timeframe: str) -> dict:
    timeframe_events = [event for event in events if event.timeframe == timeframe]
    selected = _select_tier(timeframe_events, tier)
    return _summarize_signal_events(selected, tier=tier, total_queries=len(timeframe_events), timeframe=timeframe)


def _summarize_signal_events(
    events: list[SignalQualityEvent],
    *,
    tier: SignalTier,
    total_queries: int,
    timeframe: str,
) -> dict:
    price_events = [_price_event_from_quality(event) for event in events]
    engine = events[0].engine if events else "WaveMind market-field target"
    summary = _summarize_events(price_events, engine=engine, timeframe=timeframe)
    return summary | {
        "tier": tier.name,
        "description": tier.description,
        "selected_queries": len(events),
        "total_queries": int(total_queries),
        "coverage": len(events) / max(1, int(total_queries)),
        "min_agreement": tier.min_agreement,
        "min_strength": tier.min_strength,
        "min_magnitude_bps": tier.min_magnitude_bps,
        "max_volatility_bps": tier.max_volatility_bps,
        "mean_agreement": statistics.mean(event.agreement for event in events) if events else 0.0,
        "mean_strength": statistics.mean(event.strength for event in events) if events else 0.0,
        "mean_magnitude_bps": statistics.mean(event.magnitude_bps for event in events) if events else 0.0,
        "mean_volatility_bps": statistics.mean(event.volatility_bps for event in events) if events else 0.0,
        "confidence_is_probability": False,
    }


def _attach_quality_robustness(summary: dict, events: list[SignalQualityEvent]) -> None:
    groups: dict[tuple[str, str, int], list[SignalQualityEvent]] = {}
    for event in events:
        groups.setdefault((event.symbol, event.timeframe, event.fold_index), []).append(event)
    slices = [
        _summarize_signal_events(group, tier=SignalTier(name=summary["tier"]), total_queries=len(group), timeframe=key[1])
        for key, group in groups.items()
        if group
    ]
    if not slices:
        summary["market_slices"] = 0
        summary["positive_direction_slices"] = 0
        summary["slice_positive_rate"] = 0.0
        summary["worst_slice_direction_hit_rate"] = 0.0
        summary["worst_slice_mape_pct"] = math.inf
        return
    summary["market_slices"] = len(slices)
    summary["positive_direction_slices"] = sum(1 for row in slices if row["direction_hit_rate"] >= 0.5)
    summary["slice_positive_rate"] = summary["positive_direction_slices"] / max(1, len(slices))
    summary["worst_slice_direction_hit_rate"] = min(row["direction_hit_rate"] for row in slices)
    summary["worst_slice_mape_pct"] = max(row["mape_pct"] for row in slices)


def _select_tier(events: list[SignalQualityEvent], tier: SignalTier) -> list[SignalQualityEvent]:
    if tier.name == "all_forecasts":
        return list(events)
    selected = []
    for event in events:
        if event.agreement < tier.min_agreement:
            continue
        if event.strength < tier.min_strength:
            continue
        if event.magnitude_bps < tier.min_magnitude_bps:
            continue
        if tier.max_volatility_bps is not None and event.volatility_bps > tier.max_volatility_bps:
            continue
        selected.append(event)
    return selected


def _price_event_from_quality(event: SignalQualityEvent) -> PriceTargetEvent:
    error = float(event.predicted_return_bps) - float(event.actual_return_bps)
    return PriceTargetEvent(
        engine=event.engine,
        symbol=event.symbol,
        timeframe=event.timeframe,
        fold_index=event.fold_index,
        query_id=event.query_id,
        data_end_utc=event.data_end_utc,
        target_end_utc=event.target_end_utc,
        last_close=event.last_close,
        actual_return_bps=event.actual_return_bps,
        predicted_return_bps=event.predicted_return_bps,
        actual_price=event.actual_price,
        predicted_price=event.predicted_price,
        abs_return_error_bps=event.abs_return_error_bps,
        abs_price_error=abs(float(event.predicted_price) - float(event.actual_price)),
        abs_pct_error=event.abs_pct_error,
        squared_return_error_bps=error * error,
        direction_hit=event.direction_hit,
        predicted_direction=event.predicted_direction,
        actual_direction=event.actual_direction,
        support=event.support,
        method=event.method,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward signal-quality benchmark for WaveMind crypto research.")
    parser.add_argument("--dataset", choices=["cached", "ccxt", "synthetic"], default="cached")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--cache-dir", type=Path, default=Path("benchmarks/data/crypto_ohlcv"))
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--train-windows", type=int, default=360)
    parser.add_argument("--test-windows", type=int, default=90)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--calibration-windows", type=int, default=120)
    parser.add_argument(
        "--target-engine",
        choices=["market-field", "perp-field", "robust"],
        default="market-field",
        help="Forecast engine used before signal-quality tiering.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_signal_quality_results.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_signal_quality_report.md"))
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
        seed=args.seed,
    )
    payload = run_signal_quality_benchmark(
        markets=markets,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        calibration_windows=args.calibration_windows,
        target_engine=args.target_engine,
    )
    output_payload = sampled_signal_quality_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = render_markdown(output_payload)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
