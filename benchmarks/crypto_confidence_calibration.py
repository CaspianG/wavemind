from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_walk_forward_benchmark import load_markets_from_args, run_walk_forward  # noqa: E402


def _safe_mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return float(statistics.mean(materialized)) if materialized else 0.0


def calibration_by_engine(events: Iterable[Mapping[str, Any]], *, bins: int = 5) -> list[dict[str, Any]]:
    if bins <= 0:
        raise ValueError("bins must be positive")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        if str(event.get("predicted_direction", "flat")) == "flat":
            continue
        grouped.setdefault(str(event["engine"]), []).append(event)

    results: list[dict[str, Any]] = []
    for engine, engine_events in sorted(grouped.items()):
        buckets: list[dict[str, Any]] = []
        brier_values = []
        total = len(engine_events)
        ece = 0.0
        for index in range(bins):
            low = index / bins
            high = (index + 1) / bins
            bucket_events = [
                event
                for event in engine_events
                if low <= float(event.get("confidence", 0.0)) < high
                or (index == bins - 1 and math.isclose(float(event.get("confidence", 0.0)), 1.0))
            ]
            count = len(bucket_events)
            avg_evidence = _safe_mean(float(event.get("confidence", 0.0)) for event in bucket_events)
            hit_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in bucket_events)
            avg_net = _safe_mean(float(event.get("net_return_bps", 0.0)) for event in bucket_events)
            avg_sized_net = _safe_mean(float(event.get("sized_net_return_bps", 0.0)) for event in bucket_events)
            if count:
                ece += (count / total) * abs(avg_evidence - hit_rate)
                brier_values.extend(
                    (float(event.get("confidence", 0.0)) - float(event.get("direction_at_1", 0.0))) ** 2
                    for event in bucket_events
                )
            buckets.append(
                {
                    "bin": index,
                    "range": [low, high],
                    "count": count,
                    "avg_evidence_strength": avg_evidence,
                    "direction_hit_rate": hit_rate,
                    "calibration_error": abs(avg_evidence - hit_rate) if count else 0.0,
                    "avg_net_return_bps": avg_net,
                    "avg_sized_net_return_bps": avg_sized_net,
                }
            )
        enough_samples = total >= 100 and any(bucket["count"] >= 30 for bucket in buckets)
        results.append(
            {
                "engine": engine,
                "signal_events": total,
                "brier_score_if_treated_as_probability": _safe_mean(brier_values),
                "expected_calibration_error": ece,
                "probability_ready": bool(enough_samples and ece <= 0.08),
                "note": "Evidence strength is tested here as if it were a probability; probability_ready=false means do not use it as probability.",
                "buckets": buckets,
            }
        )
    return results


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# WaveMind Crypto Confidence Calibration",
        "",
        "This report checks whether evidence strength behaves like a calibrated probability.",
        "It is a research diagnostic, not a trading signal.",
        "",
    ]
    for engine in payload.get("calibration", []):
        lines.extend(
            [
                f"## {engine['engine']}",
                "",
                f"- signal events: {engine['signal_events']}",
                f"- Brier if treated as probability: {engine['brier_score_if_treated_as_probability']:.3f}",
                f"- expected calibration error: {engine['expected_calibration_error']:.3f}",
                f"- probability ready: {str(engine['probability_ready']).lower()}",
                "",
                "| evidence range | count | avg evidence | hit rate | calibration error | avg net bps |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for bucket in engine["buckets"]:
            low, high = bucket["range"]
            lines.append(
                f"| {low:.1f}-{high:.1f} | {bucket['count']} | "
                f"{bucket['avg_evidence_strength']:.3f} | {bucket['direction_hit_rate']:.3f} | "
                f"{bucket['calibration_error']:.3f} | {bucket['avg_net_return_bps']:.2f} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate WaveMind crypto evidence strength.")
    parser.add_argument("--dataset", choices=["synthetic", "csv", "ccxt"], default="synthetic")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument("--engines", nargs="+", default=["timeframe-policy"])
    parser.add_argument("--bars", type=int, default=420)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--train-windows", type=int, default=180)
    parser.add_argument("--test-windows", type=int, default=60)
    parser.add_argument("--folds", type=int, default=1)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--position-sizing", choices=["fixed", "confidence"], default="fixed")
    parser.add_argument("--bins", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--memory-store", choices=["disk", "memory"], default="memory")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_confidence_calibration_results.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_confidence_calibration_report.md"))
    args = parser.parse_args()

    markets = load_markets_from_args(args)
    walk_forward = run_walk_forward(
        markets=markets,
        engines=args.engines,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        top_k=args.top_k,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        position_sizing=args.position_sizing,
        memory_store=args.memory_store,
        include_event_metrics=True,
    )
    payload = {
        "scenario": walk_forward["scenario"],
        "calibration": calibration_by_engine(walk_forward.get("event_metrics", []), bins=args.bins),
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
