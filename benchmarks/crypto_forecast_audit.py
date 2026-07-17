from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVBar, fetch_ohlcv_ccxt, timeframe_to_seconds  # noqa: E402


def parse_utc(value: str) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def load_ledger(path: str | Path) -> list[dict[str, Any]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        raise FileNotFoundError(f"Forecast ledger does not exist: {ledger_path}")
    rows_by_id: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {ledger_path}:{line_number}") from exc
        result_id = str(row.get("forecast_id", "")).strip()
        if not result_id:
            raise ValueError(f"Missing forecast_id at {ledger_path}:{line_number}")
        rows_by_id[result_id] = dict(row)
    return list(rows_by_id.values())


def evaluate_forecast(
    forecast: Mapping[str, Any],
    bars: Iterable[OHLCVBar],
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    now = int(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    timeframe = str(forecast["timeframe"])
    timeframe_seconds = timeframe_to_seconds(timeframe)
    data_end_ts = parse_utc(str(forecast["data_end_utc"]))
    target_end_ts = parse_utc(str(forecast["forecast_until_utc"]))
    result = dict(forecast)
    if now < target_end_ts:
        result.update({"outcome_status": "pending", "seconds_until_maturity": target_end_ts - now})
        return result

    completed = sorted(
        [bar for bar in bars if bar.timestamp + timeframe_seconds <= now],
        key=lambda bar: bar.timestamp,
    )
    future = [
        bar
        for bar in completed
        if data_end_ts < bar.timestamp + timeframe_seconds <= target_end_ts
    ]
    if not future or future[-1].timestamp + timeframe_seconds != target_end_ts:
        result.update(
            {
                "outcome_status": "missing_market_data",
                "expected_target_end_utc": datetime.fromtimestamp(target_end_ts, tz=timezone.utc).isoformat(),
                "latest_available_close_utc": (
                    datetime.fromtimestamp(future[-1].timestamp + timeframe_seconds, tz=timezone.utc).isoformat()
                    if future
                    else None
                ),
            }
        )
        return result

    last_close = float(forecast["last_close"])
    actual_price = float(future[-1].close)
    actual_return_bps = (actual_price / last_close - 1.0) * 10_000.0
    actual_direction = "up" if actual_return_bps > 0.0 else "down" if actual_return_bps < 0.0 else "flat"
    predicted_direction = str(forecast.get("market_forecast_direction") or forecast.get("direction") or "flat")
    predicted_target = float(
        forecast.get("market_forecast_target_price")
        or forecast.get("expected_price")
        or last_close
    )
    predicted_return_bps = (predicted_target / last_close - 1.0) * 10_000.0
    direction_correct = predicted_direction == actual_direction
    target_touched = _target_touched(
        future,
        direction=predicted_direction,
        target_price=predicted_target,
    )
    trade_decision = str(forecast.get("trade_decision", "no_trade"))
    result.update(
        {
            "outcome_status": "evaluated",
            "actual_price": actual_price,
            "actual_return_bps": actual_return_bps,
            "actual_return_pct": actual_return_bps / 100.0,
            "actual_direction": actual_direction,
            "direction_correct": direction_correct,
            "target_touched": target_touched,
            "target_price_error": predicted_target - actual_price,
            "target_abs_return_error_bps": abs(predicted_return_bps - actual_return_bps),
            "trade_direction_correct": direction_correct if trade_decision == "trade" else None,
            "future_high": max(float(bar.high) for bar in future),
            "future_low": min(float(bar.low) for bar in future),
            "evaluated_at_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }
    )
    return result


def _target_touched(bars: Iterable[OHLCVBar], *, direction: str, target_price: float) -> bool:
    selected = list(bars)
    if direction == "up":
        return any(float(bar.high) >= float(target_price) for bar in selected)
    if direction == "down":
        return any(float(bar.low) <= float(target_price) for bar in selected)
    return False


def summarize_outcomes(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    evaluated = [row for row in selected if row.get("outcome_status") == "evaluated"]
    trades = [row for row in evaluated if row.get("trade_decision") == "trade"]
    pending = [row for row in selected if row.get("outcome_status") == "pending"]
    missing = [row for row in selected if row.get("outcome_status") == "missing_market_data"]
    return {
        "forecasts": len(selected),
        "evaluated": len(evaluated),
        "pending": len(pending),
        "missing_market_data": len(missing),
        "market_direction_accuracy": _ratio(sum(bool(row.get("direction_correct")) for row in evaluated), len(evaluated)),
        "trade_forecasts": len(trades),
        "trade_direction_accuracy": _ratio(sum(bool(row.get("trade_direction_correct")) for row in trades), len(trades)),
        "target_touch_rate": _ratio(sum(bool(row.get("target_touched")) for row in evaluated), len(evaluated)),
        "mean_abs_target_error_bps": (
            sum(float(row["target_abs_return_error_bps"]) for row in evaluated) / len(evaluated)
            if evaluated
            else None
        ),
    }


def model_family(row: Mapping[str, Any]) -> str:
    """Collapse decision explanations into a stable, comparable model version."""
    method = str(row.get("directional_method") or "").strip()
    if method.startswith("guarded_state_field_v1"):
        return "guarded_state_field_v1"
    if method.startswith("regime_analogue_weighted"):
        return "regime_analogue_weighted"
    return method or str(row.get("engine") or "unknown")


def summarize_by_model(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        model = model_family(row)
        grouped[model].append(row)
    return [{"model": model} | summarize_outcomes(group) for model, group in sorted(grouped.items())]


def _ratio(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = dict(payload["summary"])
    lines = [
        "# WaveMind Forecast Audit",
        "",
        "Outcomes are evaluated at the forecast horizon using completed exchange candles only.",
        "This is research evidence, not financial advice.",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| forecasts | {summary['forecasts']} |",
        f"| evaluated | {summary['evaluated']} |",
        f"| pending | {summary['pending']} |",
        f"| market direction accuracy | {_format_rate(summary['market_direction_accuracy'])} |",
        f"| trade direction accuracy | {_format_rate(summary['trade_direction_accuracy'])} |",
        f"| target touch rate | {_format_rate(summary['target_touch_rate'])} |",
        f"| mean absolute target error | {_format_bps(summary['mean_abs_target_error_bps'])} |",
        "",
        "## By Model",
        "",
        "| model | forecasts | evaluated | direction accuracy | target MAE |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload.get("by_model", []):
        lines.append(
            f"| {row['model']} | {row['forecasts']} | {row['evaluated']} | "
            f"{_format_rate(row['market_direction_accuracy'])} | {_format_bps(row['mean_abs_target_error_bps'])} |"
        )
    lines.extend(
        [
        "",
        "## Forecasts",
        "",
        "| data end UTC | symbol | horizon | forecast | target | trade | status | actual | direction correct | target touched | target error |",
        "|---|---|---:|---|---:|---|---|---:|---|---|---:|",
        ]
    )
    for row in payload["results"]:
        actual_price = row.get("actual_price")
        error_bps = row.get("target_abs_return_error_bps")
        lines.append(
            "| "
            f"{row.get('data_end_utc', '')} | {row.get('symbol', '')} | {row.get('horizon_label', '')} | "
            f"{row.get('market_forecast_direction', row.get('direction', ''))} | "
            f"{float(row.get('market_forecast_target_price', row.get('expected_price', 0.0))):.8g} | "
            f"{row.get('trade_decision', 'no_trade')} | {row.get('outcome_status', '')} | "
            f"{'' if actual_price is None else format(float(actual_price), '.8g')} | "
            f"{_format_bool(row.get('direction_correct'))} | {_format_bool(row.get('target_touched'))} | "
            f"{'' if error_bps is None else format(float(error_bps), '.1f') + ' bps'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _format_bps(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1f} bps"


def _format_bool(value: Any) -> str:
    if value is None:
        return ""
    return "yes" if bool(value) else "no"


def fetch_bars_for_forecasts(
    forecasts: Iterable[Mapping[str, Any]],
    *,
    exchange: str,
    now_ts: int,
) -> dict[tuple[str, str], list[OHLCVBar]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for forecast in forecasts:
        grouped[(str(forecast["symbol"]), str(forecast["timeframe"]))].append(forecast)
    result: dict[tuple[str, str], list[OHLCVBar]] = {}
    for key, rows in grouped.items():
        symbol, timeframe = key
        seconds = timeframe_to_seconds(timeframe)
        earliest = min(parse_utc(str(row["data_end_utc"])) for row in rows)
        latest = min(now_ts, max(parse_utc(str(row["forecast_until_utc"])) for row in rows))
        limit = max(10, int(math.ceil((latest - earliest) / seconds)) + 4)
        result[key] = fetch_ohlcv_ccxt(
            exchange_id=exchange,
            symbol=symbol,
            timeframe=timeframe,
            since=(earliest - seconds) * 1000,
            limit=limit,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate matured WaveMind forecast ledger entries.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/crypto/forecast_audit.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/results/crypto/forecast_audit.md"))
    args = parser.parse_args()

    forecasts = load_ledger(args.ledger)
    now = int(datetime.now(timezone.utc).timestamp())
    mature_forecasts = [
        forecast
        for forecast in forecasts
        if parse_utc(str(forecast["forecast_until_utc"])) <= now
    ]
    bars_by_market = fetch_bars_for_forecasts(mature_forecasts, exchange=args.exchange, now_ts=now)
    results = [
        evaluate_forecast(
            forecast,
            bars_by_market.get((str(forecast["symbol"]), str(forecast["timeframe"])), []),
            now_ts=now,
        )
        for forecast in forecasts
    ]
    payload = {
        "generated_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "exchange": args.exchange,
        "summary": summarize_outcomes(results),
        "by_model": summarize_by_model(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
