from __future__ import annotations

import argparse
import hashlib
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
    _regime_signature_from_window,
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
    decision: str
    candidate_direction: str
    expected_return_bps: float
    expected_return_pct: float
    expected_price: float
    candidate_expected_return_bps: float
    candidate_expected_return_pct: float
    candidate_expected_price: float
    directional_direction: str
    directional_expected_return_bps: float
    directional_expected_return_pct: float
    directional_expected_price: float
    directional_method: str
    directional_support: int
    directional_note: str
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
    calibrated_probability: float | None = None
    probability_kind: str = "none"


@dataclass(frozen=True)
class DirectionalForecast:
    direction: str
    expected_return_bps: float
    method: str
    support: int
    note: str


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
    max_data_age_bars: int = 2,
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
    selected = bars[-limit:]
    data_age_seconds = now - (selected[-1].timestamp + seconds)
    if data_age_seconds > seconds * int(max_data_age_bars):
        raise RuntimeError(
            f"Stale market data for {symbol} {timeframe}: latest completed candle is "
            f"{data_age_seconds} seconds old"
        )
    return selected


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


def forced_directional_forecast(
    windows: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
) -> DirectionalForecast:
    """Return an always-up/down research direction without overriding trade validation."""
    signature = set(_regime_signature_from_window(query))
    scored: list[tuple[float, OHLCVWindow]] = []
    if signature:
        for index, window in enumerate(windows):
            candidate_signature = set(_regime_signature_from_window(window))
            overlap = len(signature.intersection(candidate_signature))
            if overlap < 2:
                continue
            recency = (index + 1) / max(1, len(windows))
            score = float(overlap) + 0.35 * recency
            scored.append((score, window))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:64]
    analogue_return = _weighted_future_return(selected) if selected else 0.0
    momentum_return = _momentum_directional_return(query, horizon=horizon)
    if len(selected) >= 16:
        expected_return = 0.70 * analogue_return + 0.30 * momentum_return
        method = "regime_analogue_weighted"
    elif len(selected) >= 4:
        expected_return = 0.50 * analogue_return + 0.50 * momentum_return
        method = "regime_analogue_momentum_blend"
    else:
        expected_return = momentum_return
        method = "momentum_fallback"
    if math.isclose(expected_return, 0.0, abs_tol=1e-9):
        expected_return = _last_bar_directional_return(query)
        method = f"{method}_last_bar_tiebreak"
    direction = "up" if expected_return >= 0.0 else "down"
    note = (
        "forced up/down research estimate; trade validation may still be no_trade "
        "when the trade-quality policy does not pass validation"
    )
    return DirectionalForecast(
        direction=direction,
        expected_return_bps=float(expected_return),
        method=method,
        support=len(selected),
        note=note,
    )


def guarded_state_direction(features: Mapping[str, Any], *, fallback_direction: str) -> tuple[str, str]:
    """Choose a 4h direction from observable state without future information."""
    trend = str(features.get("trend", ""))
    recent_trend = str(features.get("recent_trend", ""))
    rsi = float(features.get("rsi", 50.0))
    if trend == "down":
        return "down", "established_downtrend"
    if rsi > 65.0:
        return "down", "overbought_reversion"
    if rsi < 35.0:
        return "up", "oversold_reversion"
    if recent_trend in {"up", "down"}:
        return recent_trend, "recent_state_direction"
    return fallback_direction, "wave_fallback"


def guarded_state_field_forecast(
    windows: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
) -> DirectionalForecast:
    base = forced_directional_forecast(windows, query, horizon=horizon)
    if query.timeframe != "4h":
        return base
    direction, reason = guarded_state_direction(query.features, fallback_direction=base.direction)
    expected_return = math.copysign(abs(base.expected_return_bps), 1.0 if direction == "up" else -1.0)
    return DirectionalForecast(
        direction=direction,
        expected_return_bps=float(expected_return),
        method=f"guarded_state_field_v1:{reason}+{base.method}",
        support=base.support,
        note=(
            "4h observable-state direction with WaveMind analogue magnitude; "
            "trade validation remains a separate safety decision"
        ),
    )


def _weighted_future_return(scored_windows: list[tuple[float, OHLCVWindow]]) -> float:
    if not scored_windows:
        return 0.0
    weights = [math.exp(-float(index) / max(6.0, len(scored_windows) / 3.0)) for index, _ in enumerate(scored_windows)]
    denominator = max(sum(weights), 1e-12)
    return float(
        sum(float(window.future_return_bps) * weight for (_, window), weight in zip(scored_windows, weights, strict=False))
        / denominator
    )


def _momentum_directional_return(query: OHLCVWindow, *, horizon: int) -> float:
    features = query.features
    recent = float(features.get("recent_return_bps", 0.0))
    trend_slope = float(features.get("trend_slope_bps", 0.0))
    macd = float(features.get("macd_bps", 0.0))
    rsi = float(features.get("rsi", 50.0))
    bollinger_position = float(features.get("bollinger_position", 0.0))
    horizon_scale = max(1.0, math.sqrt(float(horizon)))
    reversion = 0.0
    if rsi < 35.0:
        reversion += (35.0 - rsi) * 1.8
    elif rsi > 65.0:
        reversion -= (rsi - 65.0) * 1.8
    if bollinger_position < -1.0:
        reversion += abs(bollinger_position + 1.0) * 18.0
    elif bollinger_position > 1.0:
        reversion -= abs(bollinger_position - 1.0) * 18.0
    return float(0.30 * recent + 0.45 * trend_slope * horizon_scale + 0.35 * macd + reversion)


def _last_bar_directional_return(query: OHLCVWindow) -> float:
    if len(query.bars) < 2:
        return 1.0
    previous = float(query.bars[-2].close)
    current = float(query.bars[-1].close)
    if previous <= 0.0:
        return 1.0
    change_bps = (current / previous - 1.0) * 10_000.0
    if math.isclose(change_bps, 0.0, abs_tol=1e-9):
        return 1.0
    return float(change_bps)


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
    last_close = float(query.bars[-1].close)
    directional = guarded_state_field_forecast(windows, query, horizon=horizon)
    decision = "abstain" if prediction.filtered or prediction.direction == "flat" else "signal"
    candidate_direction = prediction.candidate_direction or prediction.raw_direction or prediction.direction
    candidate_expected_return_bps = (
        float(prediction.candidate_expected_return_bps)
        if prediction.candidate_expected_return_bps
        else float(prediction.expected_return_bps)
    )
    expected_price = last_close * (1.0 + float(prediction.expected_return_bps) / 10_000.0)
    candidate_expected_price = last_close * (1.0 + candidate_expected_return_bps / 10_000.0)
    directional_expected_price = last_close * (1.0 + directional.expected_return_bps / 10_000.0)
    if decision == "signal":
        calibrated_probability, probability_kind = calibrated_probability_for_evidence(
            calibration_profile,
            engine_name=engine.name,
            evidence_strength=float(prediction.confidence),
        )
    else:
        calibrated_probability, probability_kind = None, "none"
    return ForecastResult(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        horizon_label=horizon_label,
        horizon_bars=int(horizon),
        engine=engine.name,
        data_end_utc=query.observed_until_time,
        forecast_until_utc=query.target_until_time,
        last_close=last_close,
        direction=prediction.direction,
        decision=decision,
        candidate_direction=candidate_direction,
        expected_return_bps=float(prediction.expected_return_bps),
        expected_return_pct=float(prediction.expected_return_bps) / 100.0,
        expected_price=float(expected_price),
        candidate_expected_return_bps=candidate_expected_return_bps,
        candidate_expected_return_pct=candidate_expected_return_bps / 100.0,
        candidate_expected_price=float(candidate_expected_price),
        directional_direction=directional.direction,
        directional_expected_return_bps=directional.expected_return_bps,
        directional_expected_return_pct=directional.expected_return_bps / 100.0,
        directional_expected_price=float(directional_expected_price),
        directional_method=directional.method,
        directional_support=int(directional.support),
        directional_note=directional.note,
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
        calibrated_probability=calibrated_probability,
        probability_kind=probability_kind,
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
        base_rate = engine.get("base_rate_calibration", {})
        monotonic = engine.get("monotonic_calibration", {})
        monotonic_block = _monotonic_block_for_evidence(monotonic, evidence_strength=evidence_strength)
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
                    "probability_kind": str(engine.get("probability_kind", "none")),
                    "base_rate_probability": float(base_rate.get("base_rate_probability", 0.0)) if base_rate else 0.0,
                    "base_rate_probability_ready": bool(base_rate.get("probability_ready", False)) if base_rate else False,
                    "monotonic_calibrated_probability": (
                        float(monotonic_block.get("calibrated_probability", 0.0)) if monotonic_block else 0.0
                    ),
                }
        return None
    return None


def _monotonic_block_for_evidence(
    monotonic_profile: Mapping[str, Any] | None,
    *,
    evidence_strength: float,
) -> dict[str, Any] | None:
    if not monotonic_profile:
        return None
    blocks = list(monotonic_profile.get("blocks", []))
    if not blocks:
        return None
    evidence = float(evidence_strength)
    for block in blocks:
        low, high = block.get("range", [0.0, 1.0])
        if float(low) <= evidence < float(high) or (math.isclose(evidence, 1.0) and float(high) >= 1.0):
            return dict(block)
    if evidence < float(blocks[0].get("range", [0.0, 1.0])[0]):
        return dict(blocks[0])
    return dict(blocks[-1])


def calibrated_probability_for_evidence(
    profile: Mapping[str, Any] | None,
    *,
    engine_name: str,
    evidence_strength: float,
) -> tuple[float | None, str]:
    if not profile:
        return None, "none"
    for engine in profile.get("calibration", []):
        if engine.get("engine") != engine_name:
            continue
        if not bool(engine.get("probability_ready", False)):
            return None, "none"
        probability_kind = str(engine.get("probability_kind", "none"))
        if probability_kind == "monotonic":
            block = _monotonic_block_for_evidence(
                engine.get("monotonic_calibration", {}),
                evidence_strength=evidence_strength,
            )
            if block:
                return float(block.get("calibrated_probability", 0.0)), "monotonic"
        if probability_kind == "base_rate":
            base_rate = engine.get("base_rate_calibration", {})
            if base_rate.get("probability_ready"):
                return float(base_rate.get("base_rate_probability", 0.0)), "base_rate"
        return None, "none"
    return None, "none"


def forecast_to_dict(result: ForecastResult) -> dict[str, Any]:
    trade_decision = "trade" if result.decision == "signal" else "no_trade"
    payload = {
        "symbol": result.symbol,
        "exchange": result.exchange,
        "timeframe": result.timeframe,
        "horizon_label": result.horizon_label,
        "horizon_bars": result.horizon_bars,
        "engine": result.engine,
        "data_end_utc": result.data_end_utc,
        "forecast_until_utc": result.forecast_until_utc,
        "last_close": result.last_close,
        "market_forecast_direction": result.directional_direction,
        "market_forecast_return_bps": result.directional_expected_return_bps,
        "market_forecast_return_pct": result.directional_expected_return_pct,
        "market_forecast_target_price": result.directional_expected_price,
        "trade_decision": trade_decision,
        "direction": result.direction,
        "decision": result.decision,
        "candidate_direction": result.candidate_direction,
        "expected_return_bps": result.expected_return_bps,
        "expected_return_pct": result.expected_return_pct,
        "expected_price": result.expected_price,
        "candidate_expected_return_bps": result.candidate_expected_return_bps,
        "candidate_expected_return_pct": result.candidate_expected_return_pct,
        "candidate_expected_price": result.candidate_expected_price,
        "directional_direction": result.directional_direction,
        "directional_expected_return_bps": result.directional_expected_return_bps,
        "directional_expected_return_pct": result.directional_expected_return_pct,
        "directional_expected_price": result.directional_expected_price,
        "directional_method": result.directional_method,
        "directional_support": result.directional_support,
        "directional_note": result.directional_note,
        "evidence_strength": result.evidence_strength,
        "confidence": result.confidence,
        "confidence_is_probability": result.confidence_is_probability,
        "confidence_note": result.confidence_note,
        "calibrated_probability": result.calibrated_probability,
        "probability_kind": result.probability_kind,
        "filtered": result.filtered,
        "filter_reason": result.filter_reason,
        "analogue_agreement": result.analogue_agreement,
        "regime_agreement": result.regime_agreement,
        "latency_ms": result.latency_ms,
        "validation": dict(result.validation),
        "calibration_bucket": dict(result.calibration_bucket or {}),
    }
    payload["forecast_id"] = forecast_id(payload)
    return payload


def forecast_id(result: Mapping[str, Any]) -> str:
    """Return a stable ID for one symbol, horizon, and information cutoff."""
    identity = "|".join(
        [
            str(result.get("exchange", "")),
            str(result.get("symbol", "")),
            str(result.get("timeframe", "")),
            str(result.get("horizon_label", "")),
            str(result.get("data_end_utc", "")),
            str(result.get("engine", "")),
            str(result.get("directional_method", "")),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def append_forecast_ledger(path: str | Path, payload: Mapping[str, Any]) -> int:
    """Append unseen forecast rows to JSONL and return the number added."""
    ledger_path = Path(path)
    existing_ids: set[str] = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("forecast_id"):
                existing_ids.add(str(row["forecast_id"]))

    generated_utc = str(payload.get("generated_utc", ""))
    rows = []
    for raw_result in payload.get("results", []):
        result = dict(raw_result)
        result_id = str(result.get("forecast_id") or forecast_id(result))
        if result_id in existing_ids:
            continue
        result["forecast_id"] = result_id
        result["generated_utc"] = generated_utc
        rows.append(result)
        existing_ids.add(result_id)

    if not rows:
        return 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(rows)


def render_markdown(results: list[ForecastResult]) -> str:
    lines = [
        "# WaveMind Crypto Current Forecast",
        "",
        "Research forecast from completed candles only. Not financial advice.",
        "Evidence strength is analogue/regime agreement, not a calibrated probability.",
        "The market forecast is always up/down with a target price because a future close is never exactly flat.",
        "`trade validation` is separate: `trade` means the policy found a validated signal; `no_trade` means a forecast exists but the signal did not pass the trade-quality gate.",
        "",
        "| symbol | horizon | data end UTC | market forecast | expected move | target price | trade validation | last close | evidence strength | validation reason | policy signal | policy candidate | policy target | calibrated probability | probability kind |",
        "|---|---:|---|---|---:|---:|---|---:|---:|---|---|---|---:|---:|---|",
    ]
    for result in results:
        filter_text = result.filter_reason if result.filtered else ""
        probability_text = "" if result.calibrated_probability is None else f"{result.calibrated_probability:.3f}"
        trade_decision = "trade" if result.decision == "signal" else "no_trade"
        lines.append(
            "| "
            f"{result.symbol} | {result.horizon_label} | {result.data_end_utc} | "
            f"{result.directional_direction} | {result.directional_expected_return_pct:.2f}% | "
            f"{result.directional_expected_price:.6g} | {trade_decision} | "
            f"{result.last_close:.6g} | {result.evidence_strength:.3f} | {filter_text} | "
            f"{result.direction} | {result.candidate_direction} | {result.expected_price:.6g} | "
            f"{probability_text} | {result.probability_kind} |"
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
    lines.append("Calibrated probability is profile-level and still not financial advice.")
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
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Optional JSONL ledger. Unseen forecasts are appended for later outcome auditing.",
    )
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
    ledger_rows = append_forecast_ledger(args.ledger, payload) if args.ledger is not None else 0
    print(render_markdown(results))
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    if args.ledger is not None:
        print(f"Appended {ledger_rows} new forecast(s) to {args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
