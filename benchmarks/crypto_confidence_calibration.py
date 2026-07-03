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


def _signal_events(events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [event for event in events if str(event.get("predicted_direction", "flat")) != "flat"]


def _bucket_events(
    events: Iterable[Mapping[str, Any]],
    *,
    field: str,
    bins: int,
) -> list[dict[str, Any]]:
    materialized = list(events)
    buckets: list[dict[str, Any]] = []
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket_events = [
            event
            for event in materialized
            if low <= float(event.get(field, 0.0)) < high
            or (index == bins - 1 and math.isclose(float(event.get(field, 0.0)), 1.0))
        ]
        count = len(bucket_events)
        avg_score = _safe_mean(float(event.get(field, 0.0)) for event in bucket_events)
        hit_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in bucket_events)
        avg_net = _safe_mean(float(event.get("net_return_bps", 0.0)) for event in bucket_events)
        avg_sized_net = _safe_mean(float(event.get("sized_net_return_bps", 0.0)) for event in bucket_events)
        buckets.append(
            {
                "bin": index,
                "range": [low, high],
                "count": count,
                "avg_score": avg_score,
                "direction_hit_rate": hit_rate,
                "calibration_error": abs(avg_score - hit_rate) if count else 0.0,
                "avg_net_return_bps": avg_net,
                "avg_sized_net_return_bps": avg_sized_net,
            }
        )
    return buckets


def _probability_metrics(
    events: Iterable[Mapping[str, Any]],
    *,
    probability_field: str,
    bins: int,
) -> dict[str, Any]:
    materialized = list(events)
    total = len(materialized)
    buckets = _bucket_events(materialized, field=probability_field, bins=bins)
    ece = 0.0
    brier_values = []
    for bucket in buckets:
        count = int(bucket["count"])
        if count:
            ece += (count / max(total, 1)) * float(bucket["calibration_error"])
    for event in materialized:
        brier_values.append(
            (float(event.get(probability_field, 0.0)) - float(event.get("direction_at_1", 0.0))) ** 2
        )
    return {
        "events": total,
        "brier_score": _safe_mean(brier_values),
        "expected_calibration_error": ece,
        "buckets": buckets,
    }


def _fit_isotonic_blocks(
    events: Iterable[Mapping[str, Any]],
    *,
    bins: int,
) -> list[dict[str, Any]]:
    raw_buckets = _bucket_events(events, field="confidence", bins=bins)
    blocks: list[dict[str, Any]] = []
    for bucket in raw_buckets:
        count = int(bucket["count"])
        if count <= 0:
            continue
        low, high = bucket["range"]
        blocks.append(
            {
                "range": [float(low), float(high)],
                "count": count,
                "sum_hits": float(bucket["direction_hit_rate"]) * count,
                "avg_evidence_numerator": float(bucket["avg_score"]) * count,
            }
        )
    index = 0
    while index < len(blocks) - 1:
        left = blocks[index]
        right = blocks[index + 1]
        left_rate = left["sum_hits"] / max(float(left["count"]), 1.0)
        right_rate = right["sum_hits"] / max(float(right["count"]), 1.0)
        if left_rate <= right_rate:
            index += 1
            continue
        merged = {
            "range": [left["range"][0], right["range"][1]],
            "count": int(left["count"]) + int(right["count"]),
            "sum_hits": float(left["sum_hits"]) + float(right["sum_hits"]),
            "avg_evidence_numerator": float(left["avg_evidence_numerator"]) + float(right["avg_evidence_numerator"]),
        }
        blocks[index : index + 2] = [merged]
        index = max(0, index - 1)
    return [
        {
            "range": block["range"],
            "count": int(block["count"]),
            "avg_evidence_strength": float(block["avg_evidence_numerator"]) / max(float(block["count"]), 1.0),
            "calibrated_probability": float(block["sum_hits"]) / max(float(block["count"]), 1.0),
        }
        for block in blocks
    ]


def _apply_isotonic_blocks(evidence_strength: float, blocks: list[Mapping[str, Any]]) -> float:
    if not blocks:
        return 0.0
    evidence = float(evidence_strength)
    for block in blocks:
        low, high = block.get("range", [0.0, 1.0])
        if float(low) <= evidence < float(high) or (math.isclose(evidence, 1.0) and float(high) >= 1.0):
            return float(block.get("calibrated_probability", 0.0))
    if evidence < float(blocks[0].get("range", [0.0, 1.0])[0]):
        return float(blocks[0].get("calibrated_probability", 0.0))
    return float(blocks[-1].get("calibrated_probability", 0.0))


def _crossfold_isotonic_calibration(
    events: list[Mapping[str, Any]],
    *,
    bins: int,
) -> dict[str, Any]:
    folds = sorted({int(event.get("fold_index", -1)) for event in events if "fold_index" in event})
    evaluated: list[dict[str, Any]] = []
    fold_reports: list[dict[str, Any]] = []
    out_of_sample = len(folds) >= 2
    if out_of_sample:
        for fold in folds:
            train_events = [event for event in events if int(event.get("fold_index", -1)) != fold]
            test_events = [event for event in events if int(event.get("fold_index", -1)) == fold]
            blocks = _fit_isotonic_blocks(train_events, bins=bins)
            fold_evaluated = []
            for event in test_events:
                calibrated = _apply_isotonic_blocks(float(event.get("confidence", 0.0)), blocks)
                payload = dict(event)
                payload["calibrated_probability"] = calibrated
                fold_evaluated.append(payload)
            evaluated.extend(fold_evaluated)
            fold_reports.append(
                {
                    "fold_index": fold,
                    "train_events": len(train_events),
                    "test_events": len(test_events),
                    "blocks": blocks,
                    "metrics": _probability_metrics(fold_evaluated, probability_field="calibrated_probability", bins=bins),
                }
            )
    else:
        blocks = _fit_isotonic_blocks(events, bins=bins)
        for event in events:
            payload = dict(event)
            payload["calibrated_probability"] = _apply_isotonic_blocks(float(event.get("confidence", 0.0)), blocks)
            evaluated.append(payload)
        fold_reports.append(
            {
                "fold_index": None,
                "train_events": len(events),
                "test_events": len(events),
                "blocks": blocks,
                "metrics": _probability_metrics(evaluated, probability_field="calibrated_probability", bins=bins),
            }
        )
    final_blocks = _fit_isotonic_blocks(events, bins=bins)
    metrics = _probability_metrics(evaluated, probability_field="calibrated_probability", bins=bins)
    min_block_count = min((int(block["count"]) for block in final_blocks), default=0)
    return {
        "method": "bucketed_isotonic_pav",
        "out_of_sample": out_of_sample,
        "events": len(evaluated),
        "brier_score": metrics["brier_score"],
        "expected_calibration_error": metrics["expected_calibration_error"],
        "min_block_count": min_block_count,
        "blocks": final_blocks,
        "folds": fold_reports,
        "buckets": metrics["buckets"],
    }


def _crossfold_base_rate_calibration(events: list[Mapping[str, Any]], *, bins: int) -> dict[str, Any]:
    folds = sorted({int(event.get("fold_index", -1)) for event in events if "fold_index" in event})
    evaluated: list[dict[str, Any]] = []
    out_of_sample = len(folds) >= 2
    fold_reports = []
    if out_of_sample:
        for fold in folds:
            train_events = [event for event in events if int(event.get("fold_index", -1)) != fold]
            test_events = [event for event in events if int(event.get("fold_index", -1)) == fold]
            base_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in train_events)
            fold_hit_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in test_events)
            for event in test_events:
                payload = dict(event)
                payload["base_rate_probability"] = base_rate
                evaluated.append(payload)
            fold_reports.append(
                {
                    "fold_index": fold,
                    "train_events": len(train_events),
                    "test_events": len(test_events),
                    "base_rate_probability": base_rate,
                    "test_hit_rate": fold_hit_rate,
                    "abs_error": abs(base_rate - fold_hit_rate),
                }
            )
    else:
        base_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in events)
        for event in events:
            payload = dict(event)
            payload["base_rate_probability"] = base_rate
            evaluated.append(payload)
        fold_reports.append(
            {
                "fold_index": None,
                "train_events": len(events),
                "test_events": len(events),
                "base_rate_probability": base_rate,
            }
        )
    metrics = _probability_metrics(evaluated, probability_field="base_rate_probability", bins=bins)
    final_probability = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in events)
    return {
        "method": "crossfold_signal_base_rate",
        "out_of_sample": out_of_sample,
        "events": len(evaluated),
        "base_rate_probability": final_probability,
        "brier_score": metrics["brier_score"],
        "expected_calibration_error": metrics["expected_calibration_error"],
        "folds": fold_reports,
        "buckets": metrics["buckets"],
        "note": "Base-rate probability is calibrated for active signals as a group; it is not individualized by evidence strength.",
    }


def _slice_key(event: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(event.get(field, "")) for field in fields)


def _slice_stability(
    events: list[Mapping[str, Any]],
    *,
    fields: tuple[str, ...],
    reference_probability: float,
    min_events: int = 20,
) -> dict[str, Any]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for event in events:
        key = _slice_key(event, fields)
        if all(key):
            grouped.setdefault(key, []).append(event)

    slices = []
    for key, group in sorted(grouped.items()):
        count = len(group)
        hit_rate = _safe_mean(float(event.get("direction_at_1", 0.0)) for event in group)
        avg_net = _safe_mean(float(event.get("net_return_bps", 0.0)) for event in group)
        slices.append(
            {
                "key": list(key),
                "count": count,
                "eligible": count >= min_events,
                "hit_rate": hit_rate,
                "abs_error_from_reference": abs(hit_rate - reference_probability),
                "avg_net_return_bps": avg_net,
            }
        )

    eligible = [item for item in slices if item["eligible"]]
    max_abs_error = max((float(item["abs_error_from_reference"]) for item in eligible), default=0.0)
    min_hit_rate = min((float(item["hit_rate"]) for item in eligible), default=0.0)
    max_hit_rate = max((float(item["hit_rate"]) for item in eligible), default=0.0)
    positive_net_slices = sum(1 for item in eligible if float(item["avg_net_return_bps"]) > 0.0)
    stable = bool(
        slices
        and len(eligible) == len(slices)
        and max_abs_error <= 0.16
        and min_hit_rate >= 0.45
    )
    return {
        "fields": list(fields),
        "min_events": min_events,
        "total_slices": len(slices),
        "eligible_slices": len(eligible),
        "positive_net_slices": positive_net_slices,
        "min_hit_rate": min_hit_rate,
        "max_hit_rate": max_hit_rate,
        "max_abs_error_from_reference": max_abs_error,
        "stable": stable,
        "slices": slices,
    }


def _overall_probability_ready(
    *,
    events: list[Mapping[str, Any]],
    base_rate: Mapping[str, Any],
    stability: Mapping[str, Any],
) -> bool:
    fold_stability = stability.get("fold", {})
    symbol_stability = stability.get("symbol", {})
    timeframe_stability = stability.get("timeframe", {})
    symbol_timeframe_stability = stability.get("symbol_timeframe", {})
    return bool(
        len(events) >= 100
        and bool(base_rate.get("out_of_sample", False))
        and float(base_rate.get("expected_calibration_error", 1.0)) <= 0.08
        and 0.45 <= float(base_rate.get("base_rate_probability", 0.0)) <= 0.75
        and bool(fold_stability.get("stable", False))
        and bool(symbol_stability.get("stable", False))
        and bool(timeframe_stability.get("stable", False))
        and bool(symbol_timeframe_stability.get("stable", False))
    )


def calibration_by_engine(events: Iterable[Mapping[str, Any]], *, bins: int = 5) -> list[dict[str, Any]]:
    if bins <= 0:
        raise ValueError("bins must be positive")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in _signal_events(events):
        grouped.setdefault(str(event["engine"]), []).append(event)

    results: list[dict[str, Any]] = []
    for engine, engine_events in sorted(grouped.items()):
        raw_metrics = _probability_metrics(engine_events, probability_field="confidence", bins=bins)
        raw_buckets = [
            {
                **bucket,
                "avg_evidence_strength": bucket.pop("avg_score"),
            }
            for bucket in raw_metrics["buckets"]
        ]
        monotonic = _crossfold_isotonic_calibration(engine_events, bins=bins)
        base_rate = _crossfold_base_rate_calibration(engine_events, bins=bins)
        reference_probability = float(base_rate.get("base_rate_probability", 0.0))
        stability = {
            "fold": _slice_stability(
                engine_events,
                fields=("fold_index",),
                reference_probability=reference_probability,
                min_events=8,
            ),
            "symbol": _slice_stability(
                engine_events,
                fields=("symbol",),
                reference_probability=reference_probability,
                min_events=20,
            ),
            "timeframe": _slice_stability(
                engine_events,
                fields=("timeframe",),
                reference_probability=reference_probability,
                min_events=20,
            ),
            "symbol_timeframe": _slice_stability(
                engine_events,
                fields=("symbol", "timeframe"),
                reference_probability=reference_probability,
                min_events=12,
            ),
        }
        base_rate_ready = _overall_probability_ready(
            events=engine_events,
            base_rate=base_rate,
            stability=stability,
        )
        base_rate["probability_ready"] = base_rate_ready
        enough_samples = len(engine_events) >= 100 and monotonic["min_block_count"] >= 30
        stable_slices = all(bool(item.get("stable", False)) for item in stability.values())
        monotonic_ready = bool(
            enough_samples
            and monotonic["out_of_sample"]
            and monotonic["expected_calibration_error"] <= 0.08
            and monotonic["brier_score"] <= raw_metrics["brier_score"]
            and stable_slices
        )
        probability_ready = bool(monotonic_ready or base_rate_ready)
        results.append(
            {
                "engine": engine,
                "signal_events": len(engine_events),
                "brier_score_if_treated_as_probability": raw_metrics["brier_score"],
                "expected_calibration_error": raw_metrics["expected_calibration_error"],
                "probability_ready": probability_ready,
                "probability_kind": "monotonic" if monotonic_ready else ("base_rate" if base_rate_ready else "none"),
                "note": "Raw evidence strength is not probability. Base-rate probability is allowed only as a group-level active-signal probability.",
                "buckets": raw_buckets,
                "monotonic_calibration": monotonic,
                "base_rate_calibration": base_rate,
                "stability": stability,
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
                f"- raw Brier if treated as probability: {engine['brier_score_if_treated_as_probability']:.3f}",
                f"- raw expected calibration error: {engine['expected_calibration_error']:.3f}",
                f"- monotonic Brier: {engine['monotonic_calibration']['brier_score']:.3f}",
                f"- monotonic expected calibration error: {engine['monotonic_calibration']['expected_calibration_error']:.3f}",
                f"- monotonic out-of-sample: {str(engine['monotonic_calibration']['out_of_sample']).lower()}",
                f"- base-rate probability: {engine['base_rate_calibration']['base_rate_probability']:.3f}",
                f"- base-rate Brier: {engine['base_rate_calibration']['brier_score']:.3f}",
                f"- base-rate expected calibration error: {engine['base_rate_calibration']['expected_calibration_error']:.3f}",
                f"- probability ready: {str(engine['probability_ready']).lower()}",
                f"- probability kind: {engine['probability_kind']}",
                "",
                "### Stability Checks",
                "",
                "| slice | eligible slices | min hit rate | max hit rate | max abs error | stable |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for name, profile in engine.get("stability", {}).items():
            lines.append(
                f"| {name} | {profile['eligible_slices']} | {profile['min_hit_rate']:.3f} | "
                f"{profile['max_hit_rate']:.3f} | {profile['max_abs_error_from_reference']:.3f} | "
                f"{str(profile['stable']).lower()} |"
            )
        lines.extend(
            [
                "",
                "### Raw Evidence Buckets",
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
        lines.extend(
            [
                "### Monotonic Calibration Blocks",
                "",
                "| evidence range | train count | avg evidence | calibrated probability |",
                "|---|---:|---:|---:|",
            ]
        )
        for block in engine["monotonic_calibration"]["blocks"]:
            low, high = block["range"]
            lines.append(
                f"| {low:.1f}-{high:.1f} | {block['count']} | "
                f"{block['avg_evidence_strength']:.3f} | {block['calibrated_probability']:.3f} |"
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
    parser.add_argument("--adaptive-min-support", type=int, default=24)
    parser.add_argument("--adaptive-min-test-support", type=int, default=8)
    parser.add_argument("--adaptive-validation-holdout", type=float, default=0.35)
    parser.add_argument("--adaptive-min-confidence", type=float, default=0.52)
    parser.add_argument("--adaptive-min-expected-edge-bps", type=float, default=70.0)
    parser.add_argument("--adaptive-max-opposition", type=float, default=0.62)
    parser.add_argument("--disable-adaptive-trend-alignment", action="store_true")
    parser.add_argument("--adaptive-performance-lookback", type=int, default=8)
    parser.add_argument("--adaptive-min-recent-edge-bps", type=float, default=20.0)
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
        adaptive_min_support=args.adaptive_min_support,
        adaptive_min_test_support=args.adaptive_min_test_support,
        adaptive_validation_holdout=args.adaptive_validation_holdout,
        adaptive_min_confidence=args.adaptive_min_confidence,
        adaptive_min_expected_edge_bps=args.adaptive_min_expected_edge_bps,
        adaptive_max_opposition=args.adaptive_max_opposition,
        adaptive_trend_alignment=not args.disable_adaptive_trend_alignment,
        adaptive_performance_lookback=args.adaptive_performance_lookback,
        adaptive_min_recent_edge_bps=args.adaptive_min_recent_edge_bps,
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
