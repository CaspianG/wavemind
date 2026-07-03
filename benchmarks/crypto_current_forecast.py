from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    OHLCVWindow,
    fetch_ohlcv_ccxt,
    make_ohlcv_windows,
    timeframe_to_seconds,
)
from benchmarks.crypto_ohlcv import _window_features  # noqa: E402
from benchmarks.crypto_walk_forward_benchmark import (  # noqa: E402
    MarketDataset,
    _create_engine,
)
from wavemind.encoders import create_text_encoder  # noqa: E402


HORIZON_PRESETS = {
    "24h": {"timeframe": "4h", "horizon": 6, "engine": "timeframe-policy"},
    "7d": {"timeframe": "1d", "horizon": 7, "engine": "timeframe-policy"},
}

CONFIDENCE_NOTE = "evidence strength from analogue/regime agreement; not a calibrated probability"


@dataclass(frozen=True)
class ForecastResult:
    symbol: str
    exchange: str
    timeframe: str
    horizon_label: str
    horizon_bars: int
    engine: str
    data_end_utc: str
    forecast_until_utc: str
    last_close: float
    direction: str
    expected_return_bps: float
    expected_return_pct: float
    expected_price: float
    confidence: float
    filtered: bool
    filter_reason: str
    analogue_agreement: float
    regime_agreement: float
    latency_ms: float
    validation: Mapping[str, Any]
    evidence_strength: float = 0.0
    confidence_is_probability: bool = False
    confidence_note: str = CONFIDENCE_NOTE
    calibration_bucket: Mapping[str, Any] | None = None


def completed_bars(rows: Iterable[Iterable[Any]], *, timeframe: str, now_ts: int | None = None) -> list[OHLCVBar]:
    now = int(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    seconds = timeframe_to_seconds(timeframe)
    bars = [
        OHLCVBar(
            timestamp=int(row[0] // 1000),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
        if int(row[0] // 1000) + seconds <= now
    ]
    return sorted(bars, key=lambda item: item.timestamp)


def fetch_latest_completed_bars(
    *,
    exchange_id: str,
    symbol: str,
    timeframe: str,
    limit: int,
) -> list[OHLCVBar]:
    seconds = timeframe_to_seconds(timeframe)
    now = int(datetime.now(timezone.utc).timestamp())
    since_ms = int((now - seconds * (limit + 40)) * 1000)
    fetched = fetch_ohlcv_ccxt(
        exchange_id=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        since=since_ms,
        limit=limit + 80,
    )
    bars = [bar for bar in fetched if bar.timestamp + seconds <= now]
    if len(bars) < limit:
        raise ValueError(f"Only {len(bars)} completed bars fetched for {symbol} {timeframe}; need {limit}")
    return bars[-limit:]


def make_latest_query_window(
    bars: Iterable[OHLCVBar],
    *,
    symbol: str,
    timeframe: str,
    window: int,
    horizon: int,
) -> OHLCVWindow:
    ordered = sorted(list(bars), key=lambda item: item.timestamp)
    if len(ordered) < window:
        raise ValueError(f"Need at least {window} bars to build a query window")
    segment = tuple(ordered[-window:])
    return OHLCVWindow(
        id=f"{symbol.replace('/', '')}_{timeframe}_latest_completed",
        symbol=symbol,
        timeframe=timeframe,
        index=len(ordered) - window,
        start_ts=segment[0].timestamp,
        end_ts=segment[-1].timestamp,
        future_end_ts=segment[-1].timestamp + horizon * timeframe_to_seconds(timeframe),
        bars=segment,
        features=_window_features(segment),
        future_return_bps=0.0,
        max_favorable_excursion_bps=0.0,
        max_adverse_excursion_bps=0.0,
        future_realized_vol_bps=0.0,
        future_max_drawdown_bps=0.0,
        direction="flat",
    )


def forecast_from_bars(
    bars: Iterable[OHLCVBar],
    *,
    symbol: str,
    exchange: str,
    horizon_label: str,
    timeframe: str,
    horizon: int,
    engine_key: str,
    window: int = 32,
    top_k: int = 5,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    validation: Mapping[str, Any] | None = None,
    calibration_profile: Mapping[str, Any] | None = None,
) -> ForecastResult:
    ordered = sorted(list(bars), key=lambda item: item.timestamp)
    direction_threshold = max(15.0, 2.0 * (float(fee_bps) + float(slippage_bps)))
    windows = make_ohlcv_windows(
        ordered,
        symbol=symbol,
        timeframe=timeframe,
        window=window,
        horizon=horizon,
        direction_threshold_bps=direction_threshold,
    )
    market = MarketDataset(symbol=symbol, timeframe=timeframe, bars=ordered, windows=windows, source=exchange)
    encoder = create_text_encoder("hash", vector_dim=384)
    round_trip_cost_bps = 2.0 * (float(fee_bps) + float(slippage_bps))
    query = make_latest_query_window(ordered, symbol=symbol, timeframe=timeframe, window=window, horizon=horizon)
    with tempfile.TemporaryDirectory(prefix="wavemind_crypto_forecast_") as temp_dir:
        engine = _create_engine(
            engine_key,
            encoder,
            market=market,
            temp_root=Path(temp_dir),
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store="memory",
        )
        try:
            for item in windows:
                engine.add(item)
            prediction = engine.query(query, top_k=top_k)
        finally:
            engine.close()
    expected_price = float(query.bars[-1].close) * (1.0 + float(prediction.expected_return_bps) / 10_000.0)
    return ForecastResult(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        horizon_label=horizon_label,
        horizon_bars=int(horizon),
        engine=engine.name,
        data_end_utc=query.end_time,
        forecast_until_utc=datetime.fromtimestamp(query.future_end_ts, tz=timezone.utc).isoformat(),
        last_close=float(query.bars[-1].close),
        direction=prediction.direction,
        expected_return_bps=float(prediction.expected_return_bps),
        expected_return_pct=float(prediction.expected_return_bps) / 100.0,
        expected_price=float(expected_price),
        confidence=float(prediction.confidence),
        filtered=bool(prediction.filtered),
        filter_reason=prediction.filter_reason,
        analogue_agreement=float(prediction.analogue_agreement),
        regime_agreement=float(prediction.regime_agreement),
        latency_ms=float(prediction.latency_ms),
        validation=dict(validation or {}),
        evidence_strength=float(prediction.confidence),
        confidence_is_probability=False,
        confidence_note=CONFIDENCE_NOTE,
        calibration_bucket=calibration_bucket_for_evidence(
            calibration_profile,
            engine_name=engine.name,
            evidence_strength=float(prediction.confidence),
        ),
    )


def validation_by_engine(path: str | Path | None, *, engine_name: str) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for result in payload.get("results", []):
        if result.get("engine") == engine_name:
            keys = [
                "queries",
                "active_direction_accuracy",
                "signal_rate",
                "avg_sized_net_return_bps",
                "sized_profit_factor",
                "sized_max_drawdown_bps",
                "positive_market_slices",
                "market_slices",
                "worst_market_slice_sized_net_bps",
                "large_move_false_positive_rate",
            ]
            return {key: result[key] for key in keys if key in result}
    return {}


def load_calibration_profile(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    calibration_path = Path(path)
    if not calibration_path.exists():
        return {}
    return json.loads(calibration_path.read_text(encoding="utf-8"))


def calibration_bucket_for_evidence(
    profile: Mapping[str, Any] | None,
    *,
    engine_name: str,
    evidence_strength: float,
) -> dict[str, Any] | None:
    if not profile:
        return None
    for engine in profile.get("calibration", []):
        if engine.get("engine") != engine_name:
            continue
        for bucket in engine.get("buckets", []):
            low, high = bucket.get("range", [0.0, 1.0])
            evidence = float(evidence_strength)
            if float(low) <= evidence < float(high) or (math.isclose(evidence, 1.0) and float(high) >= 1.0):
                if int(bucket.get("count", 0)) <= 0:
                    return None
                return {
                    "range": [float(low), float(high)],
                    "count": int(bucket.get("count", 0)),
                    "avg_evidence_strength": float(bucket.get("avg_evidence_strength", 0.0)),
                    "direction_hit_rate": float(bucket.get("direction_hit_rate", 0.0)),
                    "calibration_error": float(bucket.get("calibration_error", 0.0)),
                    "avg_net_return_bps": float(bucket.get("avg_net_return_bps", 0.0)),
                    "probability_ready": bool(engine.get("probability_ready", False)),
                }
        return None
    return None


def forecast_to_dict(result: ForecastResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "exchange": result.exchange,
        "timeframe": result.timeframe,
        "horizon_label": result.horizon_label,
        "horizon_bars": result.horizon_bars,
        "engine": result.engine,
        "data_end_utc": result.data_end_utc,
        "forecast_until_utc": result.forecast_until_utc,
        "last_close": result.last_close,
        "direction": result.direction,
        "expected_return_bps": result.expected_return_bps,
        "expected_return_pct": result.expected_return_pct,
        "expected_price": result.expected_price,
        "evidence_strength": result.evidence_strength,
        "confidence": result.confidence,
        "confidence_is_probability": result.confidence_is_probability,
        "confidence_note": result.confidence_note,
        "filtered": result.filtered,
        "filter_reason": result.filter_reason,
        "analogue_agreement": result.analogue_agreement,
        "regime_agreement": result.regime_agreement,
        "latency_ms": result.latency_ms,
        "validation": dict(result.validation),
        "calibration_bucket": dict(result.calibration_bucket or {}),
    }


def render_markdown(results: list[ForecastResult]) -> str:
    lines = [
        "# WaveMind Crypto Current Forecast",
        "",
        "Research forecast from completed candles only. Not financial advice.",
        "Evidence strength is analogue/regime agreement, not a calibrated probability.",
        "",
        "| symbol | horizon | data end UTC | direction | last close | expected return | expected price | evidence strength | bucket hit rate | filter |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        filter_text = result.filter_reason if result.filtered else ""
        bucket_hit = ""
        if result.calibration_bucket:
            bucket_hit = f"{float(result.calibration_bucket.get('direction_hit_rate', 0.0)):.3f}"
        lines.append(
            "| "
            f"{result.symbol} | {result.horizon_label} | {result.data_end_utc} | {result.direction} | "
            f"{result.last_close:.6g} | {result.expected_return_pct:.2f}% | "
            f"{result.expected_price:.6g} | {result.evidence_strength:.3f} | {bucket_hit} | {filter_text} |"
        )
    lines.append("")
    validation = dict(results[0].validation) if results else {}
    if validation:
        active_accuracy = validation.get("active_direction_accuracy")
        signal_rate = validation.get("signal_rate")
        positive_slices = validation.get("positive_market_slices")
        market_slices = validation.get("market_slices")
        if active_accuracy is not None and signal_rate is not None:
            lines.append(
                "Validation profile: "
                f"historical active direction accuracy {float(active_accuracy):.3f}, "
                f"signal rate {float(signal_rate):.3f}"
                + (
                    f", positive market slices {positive_slices}/{market_slices}"
                    if positive_slices is not None and market_slices is not None
                    else ""
                )
                + "."
            )
            lines.append("")
    lines.append("Validation profile is embedded in the JSON output for each row.")
    lines.append("Calibration bucket hit rate is historical and not guaranteed future probability.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate current WaveMind crypto research forecasts.")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    parser.add_argument("--horizon", choices=sorted(HORIZON_PRESETS), default="24h")
    parser.add_argument("--bars", type=int, default=720)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--profile-json", type=Path, default=Path("benchmarks/crypto_walk_forward_okx_timeframe_policy_results.json"))
    parser.add_argument("--calibration-json", type=Path, default=Path("benchmarks/crypto_confidence_calibration_okx_timeframe_policy_results.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_current_forecast.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_current_forecast.md"))
    args = parser.parse_args()

    preset = HORIZON_PRESETS[args.horizon]
    validation = validation_by_engine(args.profile_json, engine_name="WaveMind timeframe policy")
    calibration_profile = load_calibration_profile(args.calibration_json)
    results = []
    for symbol in args.symbols:
        bars = fetch_latest_completed_bars(
            exchange_id=args.exchange,
            symbol=symbol,
            timeframe=str(preset["timeframe"]),
            limit=args.bars,
        )
        results.append(
            forecast_from_bars(
                bars,
                symbol=symbol,
                exchange=args.exchange,
                horizon_label=args.horizon,
                timeframe=str(preset["timeframe"]),
                horizon=int(preset["horizon"]),
                engine_key=str(preset["engine"]),
                window=args.window,
                top_k=args.top_k,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                validation=validation,
                calibration_profile=calibration_profile,
            )
        )

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "closed_candles_only": True,
        "results": [forecast_to_dict(result) for result in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(results), encoding="utf-8")
    print(render_markdown(results))
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
