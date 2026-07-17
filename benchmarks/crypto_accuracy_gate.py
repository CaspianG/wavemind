from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_THRESHOLDS_BPS = (0.0, 50.0, 100.0, 150.0, 200.0, 250.0)


def load_events(paths: Iterable[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int, str]] = set()
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = (
                str(row.get("engine", "")),
                str(row.get("symbol", "")),
                str(row.get("timeframe", "unknown")),
                int(row.get("fold_index", -1)),
                str(row.get("query_id", "")),
            )
            if not all((key[0], key[1], key[2], key[4])):
                raise ValueError(f"Invalid event identity at {path}:{line_number}")
            if key in seen:
                continue
            seen.add(key)
            events.append(dict(row))
    return events


def collapse_overlapping_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep one observation per horizon for each engine/symbol/timeframe/fold."""
    grouped: dict[tuple[str, str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[
            (
                str(event["engine"]),
                str(event["symbol"]),
                str(event.get("timeframe", "unknown")),
                int(event["fold_index"]),
            )
        ].append(event)

    selected: list[dict[str, Any]] = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda row: _timestamp(str(row["data_end_utc"])))
        next_allowed = -math.inf
        for row in ordered:
            data_end = _timestamp(str(row["data_end_utc"]))
            target_end = _timestamp(str(row["target_end_utc"]))
            horizon = max(1, target_end - data_end)
            if data_end < next_allowed:
                continue
            selected.append(dict(row))
            next_allowed = data_end + horizon
    return selected


def evaluate_accuracy_gate(
    events: Iterable[Mapping[str, Any]],
    *,
    target_accuracy: float = 0.80,
    min_effective_signals: int = 40,
    min_effective_coverage: float = 0.05,
    min_wilson_low_95: float = 0.70,
    min_fold_accuracy: float = 0.70,
    min_fold_signals: int = 5,
    min_slice_accuracy: float = 0.70,
    min_slice_signals: int = 5,
    thresholds_bps: Iterable[float] = DEFAULT_THRESHOLDS_BPS,
) -> dict[str, Any]:
    raw = [dict(event) for event in events]
    independent = collapse_overlapping_events(raw)
    engines = sorted({str(event["engine"]) for event in raw})
    results = []
    for engine in engines:
        engine_raw = [event for event in raw if event["engine"] == engine]
        engine_independent = [event for event in independent if event["engine"] == engine]
        frontiers = []
        for threshold in thresholds_bps:
            raw_selected = _at_threshold(engine_raw, float(threshold))
            effective_selected = _at_threshold(engine_independent, float(threshold))
            effective_summary = _accuracy_summary(effective_selected)
            fold_summaries = [
                {"fold_index": fold} | _accuracy_summary(
                    [event for event in effective_selected if int(event["fold_index"]) == fold]
                )
                for fold in sorted({int(event["fold_index"]) for event in engine_independent})
            ]
            fold_ready = bool(fold_summaries) and all(
                row["signals"] >= int(min_fold_signals)
                and row["accuracy"] is not None
                and row["accuracy"] >= float(min_fold_accuracy)
                for row in fold_summaries
            )
            slice_summaries = [
                {"symbol": symbol, "timeframe": timeframe} | _accuracy_summary(
                    [
                        event
                        for event in effective_selected
                        if str(event["symbol"]) == symbol
                        and str(event.get("timeframe", "unknown")) == timeframe
                    ]
                )
                for symbol, timeframe in sorted(
                    {
                        (str(event["symbol"]), str(event.get("timeframe", "unknown")))
                        for event in engine_independent
                    }
                )
            ]
            slice_ready = bool(slice_summaries) and all(
                row["signals"] >= int(min_slice_signals)
                and row["accuracy"] is not None
                and row["accuracy"] >= float(min_slice_accuracy)
                for row in slice_summaries
            )
            coverage = len(effective_selected) / max(1, len(engine_independent))
            admitted = bool(
                effective_summary["signals"] >= int(min_effective_signals)
                and coverage >= float(min_effective_coverage)
                and effective_summary["accuracy"] is not None
                and effective_summary["accuracy"] >= float(target_accuracy)
                and effective_summary["wilson_low_95"] is not None
                and effective_summary["wilson_low_95"] >= float(min_wilson_low_95)
                and fold_ready
                and slice_ready
            )
            frontiers.append(
                {
                    "threshold_bps": float(threshold),
                    "raw": _accuracy_summary(raw_selected),
                    "effective": effective_summary,
                    "effective_coverage": float(coverage),
                    "by_fold": fold_summaries,
                    "by_slice": slice_summaries,
                    "fold_ready": fold_ready,
                    "slice_ready": slice_ready,
                    "admitted": admitted,
                }
            )
        results.append(
            {
                "engine": engine,
                "raw_events": len(engine_raw),
                "effective_events": len(engine_independent),
                "admitted": any(row["admitted"] for row in frontiers),
                "frontier": frontiers,
            }
        )
    return {
        "gate": {
            "target_accuracy": float(target_accuracy),
            "min_effective_signals": int(min_effective_signals),
            "min_effective_coverage": float(min_effective_coverage),
            "min_wilson_low_95": float(min_wilson_low_95),
            "min_fold_accuracy": float(min_fold_accuracy),
            "min_fold_signals": int(min_fold_signals),
            "min_slice_accuracy": float(min_slice_accuracy),
            "min_slice_signals": int(min_slice_signals),
            "overlap_policy": "one observation per forecast horizon, engine, symbol, timeframe, and fold",
        },
        "raw_events": len(raw),
        "effective_events": len(independent),
        "engines": results,
        "admitted_engines": [row["engine"] for row in results if row["admitted"]],
    }


def _at_threshold(events: Iterable[Mapping[str, Any]], threshold_bps: float) -> list[dict[str, Any]]:
    return [
        dict(event)
        for event in events
        if abs(float(event["predicted_return_bps"])) >= float(threshold_bps)
    ]


def _accuracy_summary(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(events)
    signals = len(selected)
    hits = sum(1 for event in selected if float(event["direction_hit"]) >= 0.5)
    accuracy = hits / signals if signals else None
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": accuracy,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def _wilson_low(hits: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    p = hits / total
    denominator = 1.0 + z * z / total
    center = p + z * z / (2.0 * total)
    spread = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return float((center - spread) / denominator)


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def render_markdown(payload: Mapping[str, Any]) -> str:
    gate = payload["gate"]
    lines = [
        "# WaveMind Crypto 80% Accuracy Admission Gate",
        "",
        "This report prevents overlapping forecasts or tiny samples from being presented as an 80% edge.",
        "",
        "## Admission Rule",
        "",
        f"- direction accuracy >= {float(gate['target_accuracy']):.0%};",
        f"- >= {int(gate['min_effective_signals'])} non-overlapping signals;",
        f"- >= {float(gate['min_effective_coverage']):.0%} effective coverage;",
        f"- 95% Wilson lower bound >= {float(gate['min_wilson_low_95']):.0%};",
        f"- every fold has >= {int(gate['min_fold_signals'])} signals and >= {float(gate['min_fold_accuracy']):.0%} accuracy.",
        f"- every symbol/timeframe slice has >= {int(gate['min_slice_signals'])} signals and >= {float(gate['min_slice_accuracy']):.0%} accuracy.",
        "",
        "## Frontier",
        "",
        "| engine | threshold | raw accuracy | effective signals | effective accuracy | Wilson low | coverage | worst fold | worst slice | admitted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for engine in payload["engines"]:
        for row in engine["frontier"]:
            raw_accuracy = row["raw"]["accuracy"]
            accuracy = row["effective"]["accuracy"]
            wilson = row["effective"]["wilson_low_95"]
            fold_accuracies = [
                fold["accuracy"]
                for fold in row["by_fold"]
                if fold["accuracy"] is not None and fold["signals"] >= int(gate["min_fold_signals"])
            ]
            worst_fold = min(fold_accuracies) if fold_accuracies else None
            slice_accuracies = [
                item["accuracy"]
                for item in row["by_slice"]
                if item["accuracy"] is not None and item["signals"] >= int(gate["min_slice_signals"])
            ]
            worst_slice = min(slice_accuracies) if slice_accuracies else None
            lines.append(
                f"| {engine['engine']} | {row['threshold_bps']:.0f} bps | "
                f"{_rate(raw_accuracy)} | {row['effective']['signals']} | {_rate(accuracy)} | "
                f"{_rate(wilson)} | {row['effective_coverage']:.1%} | {_rate(worst_fold)} | {_rate(worst_slice)} | "
                f"{'yes' if row['admitted'] else 'no'} |"
            )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            (
                "Admitted engines: " + ", ".join(payload["admitted_engines"])
                if payload["admitted_engines"]
                else "No engine currently passes the 80% admission gate."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether crypto forecasts have a defensible 80% edge.")
    parser.add_argument("--events", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/crypto/accuracy_gate.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/results/crypto/accuracy_gate.md"))
    args = parser.parse_args()

    payload = evaluate_accuracy_gate(load_events(args.events))
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
