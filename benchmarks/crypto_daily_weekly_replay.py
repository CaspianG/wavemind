from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_current_forecast import (  # noqa: E402
    fetch_latest_completed_bars,
    fetch_latest_completed_bars_with_migration,
    forecast_from_bars,
    forecast_model_sha256,
    market_snapshot_sha256,
    parse_symbol_migration,
)
from benchmarks.crypto_ohlcv import OHLCVBar  # noqa: E402

DAY = 86400
ENGINES = (
    "WaveMind research", "WaveMind validated", "Last price", "Always up",
    "Weekly momentum", "Weekly mean reversion",
)


def iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def validate_daily_bars(bars: Sequence[OHLCVBar]) -> None:
    if not bars:
        raise ValueError("empty daily snapshot")
    for index, bar in enumerate(bars):
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"non-finite daily bar at {iso(bar.timestamp)}")
        if min(values[:4]) <= 0 or bar.volume < 0:
            raise ValueError(f"invalid daily bar at {iso(bar.timestamp)}")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
            raise ValueError(f"inconsistent OHLC at {iso(bar.timestamp)}")
        if index and bar.timestamp - bars[index - 1].timestamp != DAY:
            raise ValueError(f"daily gap or duplicate at {iso(bar.timestamp)}")


def predict_week(prefix: list[OHLCVBar], symbol: str) -> dict[str, Any]:
    result = forecast_from_bars(
        prefix, symbol=symbol, exchange="okx", horizon_label="7d",
        timeframe="1d", horizon=7, engine_key="timeframe-policy",
        window=32, top_k=5, fee_bps=10.0, slippage_bps=5.0,
    )
    return {
        "research_return_bps": result.directional_expected_return_bps,
        "validated_return_bps": (
            result.expected_return_bps if result.point_target_validated else None
        ),
        "filter_reason": result.filter_reason,
        "interval_lower_price": result.prediction_interval_lower_price,
        "interval_upper_price": result.prediction_interval_upper_price,
        "interval_calibration_samples": result.prediction_interval_calibration_samples,
        "method": result.directional_method,
    }


def replay_market(
    bars: Sequence[OHLCVBar], *, symbol: str, start_ts: int, end_ts: int,
    as_of_ts: int, history_bars: int = 800,
    predictor: Callable = predict_week, progress: bool = False,
) -> list[dict[str, Any]]:
    validate_daily_bars(bars)
    if history_bars < 32:
        raise ValueError("history_bars must be at least 32")
    by_close = {bar.timestamp + DAY: bar for bar in bars}
    rows = []
    for index, bar in enumerate(bars):
        origin = bar.timestamp + DAY
        if not start_ts <= origin < end_ts or origin > as_of_ts:
            continue
        prefix = list(bars[max(0, index + 1 - history_bars):index + 1])
        if len(prefix) != history_bars:
            raise ValueError(f"insufficient training history for {symbol} at {iso(origin)}")
        # This is the only input handed to the live model: a closed-candle prefix.
        predicted = predictor(prefix, symbol)
        target_ts = origin + 7 * DAY
        target_bar = by_close.get(target_ts) if target_ts <= as_of_ts else None
        if target_ts <= as_of_ts and target_bar is None:
            raise ValueError(f"missing outcome candle for {symbol} at {iso(target_ts)}")
        anchor = bar.close
        trailing_week = (anchor / prefix[-8].close - 1.0) * 10_000.0
        trailing_month = (anchor / prefix[-31].close - 1.0) * 100.0
        predictions = {
            "WaveMind research": predicted["research_return_bps"],
            "WaveMind validated": predicted["validated_return_bps"],
            "Last price": 0.0,
            "Always up": 1.0,
            "Weekly momentum": trailing_week,
            "Weekly mean reversion": -trailing_week,
        }
        row = {
            "symbol": symbol, "origin_ts": origin, "origin_utc": iso(origin),
            "target_ts": target_ts, "target_utc": iso(target_ts),
            "anchor_price": anchor,
            "actual_price": target_bar.close if target_bar else None,
            "actual_return_bps": (
                (target_bar.close / anchor - 1.0) * 10_000.0 if target_bar else None
            ),
            "outcome_status": "matured" if target_bar else "pending",
            "month": iso(origin)[:7],
            "phase": ((origin - start_ts) // DAY) % 7,
            "regime": (
                "rising" if trailing_month > 5 else
                "falling" if trailing_month < -5 else "sideways"
            ),
            "past_30d_return_pct": trailing_month,
            "input_bars": len(prefix),
            "input_snapshot_sha256": market_snapshot_sha256(prefix, symbol=symbol, timeframe="1d"),
            "predictions": predictions,
            **{key: value for key, value in predicted.items() if key not in {"research_return_bps", "validated_return_bps"}},
        }
        rows.append(row)
        if progress and len(rows) % 10 == 0:
            print(f"{symbol}: {len(rows)} daily origins through {iso(origin)}", flush=True)
    return rows


def summarize(rows: Sequence[dict[str, Any]], engine: str) -> dict[str, Any]:
    matured = [r for r in rows if r["outcome_status"] == "matured"]
    chosen = [r for r in matured if r["predictions"][engine] is not None]
    hits, mape, errors, directions, covered = [], [], [], [], []
    for row in chosen:
        predicted = float(row["predictions"][engine])
        actual = float(row["actual_return_bps"])
        target = row["anchor_price"] * (1 + predicted / 10_000)
        mape.append(abs(target / row["actual_price"] - 1) * 100)
        errors.append(abs(predicted - actual))
        if abs(predicted) > 1e-12:
            hits.append((predicted > 0 and actual > 0) or (predicted < 0 and actual < 0))
            directions.append("up" if predicted > 0 else "down")
        if engine.startswith("WaveMind"):
            lo, hi = row.get("interval_lower_price"), row.get("interval_upper_price")
            if lo is not None and hi is not None:
                covered.append(lo <= row["actual_price"] <= hi)
    return {
        "engine": engine, "matured_origins": len(matured), "forecasts": len(chosen),
        "directional_forecasts": len(hits), "correct_directions": sum(hits),
        "direction_accuracy": statistics.mean(hits) if hits else None,
        "coverage": len(chosen) / len(matured) if matured else 0.0,
        "price_mape_pct": statistics.mean(mape) if mape else None,
        "mae_return_bps": statistics.mean(errors) if errors else None,
        "up_forecasts": directions.count("up"), "down_forecasts": directions.count("down"),
        "interval_samples": len(covered),
        "interval_coverage": statistics.mean(covered) if covered else None,
    }


def summarize_groups(rows: list[dict], key: str) -> list[dict]:
    return [
        {key: value, "results": [summarize([r for r in rows if r[key] == value], e) for e in ENGINES]}
        for value in sorted({r[key] for r in rows})
    ]


def rate(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def render_report(payload: dict) -> str:
    lines = [
        "# Three-month daily seven-day forecast replay", "",
        f"Frozen model: `{payload['model_source_sha256']}`. Protocol: `{payload['protocol_sha256']}`.",
        f"Daily origins: {payload['protocol']['start_utc']} to {payload['protocol']['end_utc_exclusive']} (exclusive).",
        f"As of {payload['as_of_utc']}: {payload['matured']} matured and {payload['pending']} pending asset forecasts.",
        "", "Every forecast reuses the unchanged live runner with only the preceding 800 completed daily candles.",
        "The weekly entry policy is unsupported; research estimates are scored separately from admitted trades.",
        "This replay reconstructs historical predictions. It is not a record of predictions published on those dates.",
        "", "## Overall", "",
        "| model | forecasts | direction accuracy | target-price MAPE | interval coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["results"]:
        error = f"{row['price_mape_pct']:.2f}%" if row['price_mape_pct'] is not None else "n/a"
        lines.append(f"| {row['engine']} | {row['forecasts']} | {rate(row['direction_accuracy'])} | {error} | {rate(row['interval_coverage'])} |")
    for key, title in (("symbol", "By asset"), ("month", "By origin month"), ("regime", "By observable market regime"), ("phase", "Non-overlapping weekly phases")):
        lines.extend(["", f"## {title}", "", f"| {key} | forecasts | WaveMind accuracy | always up | momentum | mean reversion | WaveMind MAPE |", "|---|---:|---:|---:|---:|---:|---:|"])
        for group in payload[f"by_{key}"]:
            models = {r["engine"]: r for r in group["results"]}
            wave = models["WaveMind research"]
            error = f"{wave['price_mape_pct']:.2f}%" if wave['price_mape_pct'] is not None else "n/a"
            lines.append(f"| {group[key]} | {wave['forecasts']} | {rate(wave['direction_accuracy'])} | {rate(models['Always up']['direction_accuracy'])} | {rate(models['Weekly momentum']['direction_accuracy'])} | {rate(models['Weekly mean reversion']['direction_accuracy'])} | {error} |")
    lines.extend([
        "", "Daily seven-day forecasts overlap. Each phase has disjoint horizons within each asset,",
        "but assets still share market exposure. Asset rows and phases are not independent replications.",
        "Regimes use only the preceding 30-day return: rising above +5%, falling below -5%, otherwise sideways.",
        "Always-up is a direction control with a fixed +1 bp target. Last price is the zero-return price control.",
        "No thresholds, coins, months, or best phase were selected after observing the outcomes.",
        "Price errors and direction accuracy do not include execution costs and are not trading returns.", "",
    ])
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def replay_source_sha256(paths: Sequence[Path] | None = None) -> str:
    dependencies = paths if paths is not None else [
        Path(__file__),
        PROJECT_ROOT / "benchmarks/crypto_current_forecast.py",
        PROJECT_ROOT / "benchmarks/crypto_ohlcv.py",
        PROJECT_ROOT / "benchmarks/crypto_prediction_intervals.py",
        PROJECT_ROOT / "benchmarks/crypto_walk_forward_benchmark.py",
        PROJECT_ROOT / "wavemind/core.py",
        PROJECT_ROOT / "wavemind/encoders.py",
        PROJECT_ROOT / "wavemind/field_graph.py",
        PROJECT_ROOT / "wavemind/indexes.py",
    ]
    digest = hashlib.sha256()
    for path in dependencies:
        try:
            label = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            label = path.name
        digest.update(label.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _run_market(job: dict) -> list[dict]:
    cache_path = Path(job["output_dir"]) / f"{job['asset']}_replay.json"
    snapshot = json.loads(Path(job["snapshot_path"]).read_text(encoding="utf-8"))
    metadata = {"protocol_sha256": job["protocol_sha256"], "model_source_sha256": job["model_source_sha256"], "replay_source_sha256": job["replay_source_sha256"], "snapshot_sha256": snapshot["sha256"]}
    if cache_path.exists() and not job.get("recompute", False):
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["metadata"] != metadata:
            raise ValueError("cached replay does not match frozen inputs")
        return cached["rows"]
    rows = replay_market(
        [OHLCVBar(**r) for r in snapshot["bars"]], symbol=job["symbol"],
        start_ts=job["start_ts"], end_ts=job["end_ts"], as_of_ts=job["as_of_ts"],
        history_bars=job["history_bars"], progress=True,
    )
    _write_json(cache_path, {"metadata": metadata, "rows": rows})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Causal daily replay of the unchanged weekly live forecast")
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT / "benchmarks/protocols/daily_weekly_replay_2026-11-11.json")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmarks/results/crypto/replay_2026-11-11")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--recompute", action="store_true", help="Recalculate predictions from the same frozen input snapshots")
    args = parser.parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    protocol_sha = hashlib.sha256(protocol_bytes).hexdigest()
    model_sha = forecast_model_sha256()
    replay_sha = replay_source_sha256()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["protocol_sha256"] != protocol_sha or manifest["model_source_sha256"] != model_sha:
            raise ValueError("existing run uses different protocol or model")
        if manifest.get("replay_source_sha256") != replay_sha:
            if not args.recompute:
                raise ValueError("replay code changed; use --recompute on the frozen snapshots")
            manifest["replay_source_sha256"] = replay_sha
            _write_json(manifest_path, manifest)
    else:
        manifest = {"protocol": protocol, "protocol_sha256": protocol_sha, "model_source_sha256": model_sha, "replay_source_sha256": replay_sha, "as_of_utc": datetime.now(timezone.utc).isoformat(), "source_commit": "1c36d9d"}
        _write_json(manifest_path, manifest)
    as_of_ts = timestamp(manifest["as_of_utc"])
    migration = parse_symbol_migration(protocol["gram_migration"])
    jobs = []
    for symbol in protocol["symbols"]:
        asset = symbol.split("/", 1)[0]
        path = args.output_dir / "inputs" / f"{asset}.json"
        if not path.exists():
            print(f"Downloading {symbol} daily candles", flush=True)
            params = dict(exchange_id=protocol["exchange"], symbol=symbol, timeframe="1d", limit=protocol["download_bars"])
            bars = (fetch_latest_completed_bars_with_migration(**params, migration=migration) if symbol == migration.target_symbol else fetch_latest_completed_bars(**params))
            bars = [b for b in bars if b.timestamp + DAY <= as_of_ts]
            validate_daily_bars(bars)
            _write_json(path, {"symbol": symbol, "sha256": market_snapshot_sha256(bars, symbol=symbol, timeframe="1d"), "bars": [asdict(b) for b in bars]})
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        bars = [OHLCVBar(**r) for r in snapshot["bars"]]
        validate_daily_bars(bars)
        if market_snapshot_sha256(bars, symbol=symbol, timeframe="1d") != snapshot["sha256"]:
            raise ValueError(f"snapshot hash mismatch: {symbol}")
        jobs.append(dict(symbol=symbol, asset=asset, snapshot_path=str(path), output_dir=str(args.output_dir), protocol_sha256=protocol_sha, model_source_sha256=model_sha, replay_source_sha256=replay_sha, recompute=args.recompute, start_ts=timestamp(protocol["start_utc"]), end_ts=timestamp(protocol["end_utc_exclusive"]), as_of_ts=as_of_ts, history_bars=protocol["history_bars"]))
    rows = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_run_market, job): job["symbol"] for job in jobs}
        for future in as_completed(futures):
            result = future.result()
            rows.extend(result)
            print(f"Completed {futures[future]}: {len(result)} daily origins", flush=True)
    rows.sort(key=lambda r: (r["origin_ts"], r["symbol"]))
    payload = {
        **manifest, "matured": sum(r["outcome_status"] == "matured" for r in rows),
        "pending": sum(r["outcome_status"] == "pending" for r in rows),
        "results": [summarize(rows, e) for e in ENGINES],
        **{f"by_{key}": summarize_groups(rows, key) for key in ("symbol", "month", "regime", "phase")},
    }
    _write_json(args.output_dir / "summary.json", payload)
    (args.output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(render_report(payload), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
