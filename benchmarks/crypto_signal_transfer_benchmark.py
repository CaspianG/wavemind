from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import (  # noqa: E402
    _wilson_low,
    collapse_overlapping_events,
)


AGREEMENT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
STRENGTH_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5)
MAGNITUDE_GRID = (0.0, 50.0, 100.0, 200.0, 300.0, 500.0)
VOLATILITY_GRID: tuple[float | None, ...] = (
    None,
    100.0,
    150.0,
    200.0,
    250.0,
    350.0,
)


def load_signal_events(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    content = source.read_bytes()
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = content.decode("utf-16")
    else:
        text = content.decode("utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("Signal event JSON must be an array")
        events = [dict(row) for row in payload]
    else:
        events = [
            dict(json.loads(line))
            for line in text.splitlines()
            if line.strip()
        ]
    _validate_events(events)
    return events


def run_signal_transfer_benchmark(
    events: Sequence[Mapping[str, Any]],
    *,
    target_accuracy: float = 0.70,
    min_training_signals: int = 20,
    min_test_signals: int = 40,
    min_wilson_low_95: float = 0.65,
    min_fold_accuracy: float = 0.60,
    min_slice_accuracy: float = 0.60,
) -> dict[str, Any]:
    if not 0.5 < target_accuracy <= 1.0:
        raise ValueError("target_accuracy must be in (0.5, 1.0]")
    if min_training_signals <= 0 or min_test_signals <= 0:
        raise ValueError("minimum signal counts must be positive")
    raw = [dict(row) for row in events]
    _validate_events(raw)
    independent = collapse_overlapping_events(raw)
    timeframes = sorted({str(row.get("timeframe", "unknown")) for row in raw})
    by_timeframe = [
        _timeframe_transfer(
            independent,
            timeframe=timeframe,
            target_accuracy=target_accuracy,
            min_training_signals=min_training_signals,
        )
        for timeframe in timeframes
    ]
    transferred = [
        event
        for row in by_timeframe
        for fold in row["folds"]
        for event in fold.pop("_selected_events")
    ]
    summary = _summary(transferred)
    by_fold = _group_summary(transferred, "fold_index")
    by_slice = _slice_summary(transferred)
    fold_ready = bool(by_fold) and all(
        row["signals"] >= 5
        and row["accuracy"] is not None
        and row["accuracy"] >= min_fold_accuracy
        for row in by_fold
    )
    slice_ready = bool(by_slice) and all(
        row["signals"] >= 5
        and row["accuracy"] is not None
        and row["accuracy"] >= min_slice_accuracy
        for row in by_slice
    )
    admitted = bool(
        summary["signals"] >= min_test_signals
        and summary["accuracy"] is not None
        and summary["accuracy"] >= target_accuracy
        and summary["wilson_low_95"] is not None
        and summary["wilson_low_95"] >= min_wilson_low_95
        and fold_ready
        and slice_ready
    )
    return {
        "methodology": {
            "protocol": (
                "Forecasts are collapsed to one independent observation per "
                "horizon. A threshold policy is selected from earlier folds "
                "only and then frozen for the next fold."
            ),
            "raw_events": len(raw),
            "independent_events": len(independent),
            "target_accuracy": target_accuracy,
            "min_training_signals": min_training_signals,
            "min_test_signals": min_test_signals,
            "min_wilson_low_95": min_wilson_low_95,
            "min_fold_accuracy": min_fold_accuracy,
            "min_slice_accuracy": min_slice_accuracy,
        },
        "by_timeframe": by_timeframe,
        "transferred_summary": summary,
        "transferred_by_fold": by_fold,
        "transferred_by_slice": by_slice,
        "fold_ready": fold_ready,
        "slice_ready": slice_ready,
        "admitted_70": admitted,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    methodology = payload["methodology"]
    summary = payload["transferred_summary"]
    lines = [
        "# Nested Signal-Policy Transfer Benchmark",
        "",
        str(methodology["protocol"]),
        "",
        f"- raw events: {methodology['raw_events']};",
        f"- independent events: {methodology['independent_events']};",
        f"- transferred signals: {summary['signals']};",
        f"- transferred accuracy: {_rate(summary['accuracy'])};",
        f"- Wilson lower 95%: {_rate(summary['wilson_low_95'])};",
        f"- admitted at 70%: {'yes' if payload['admitted_70'] else 'no'}.",
        "",
        "## Fold Transfer",
        "",
        "| timeframe | test fold | selection | train signals | train accuracy | policy | test signals | test accuracy | Wilson low |",
        "|---|---:|---|---:|---:|---|---:|---:|---:|",
    ]
    for timeframe in payload["by_timeframe"]:
        for fold in timeframe["folds"]:
            lines.append(
                f"| {timeframe['timeframe']} | {fold['test_fold']} | "
                f"{fold['selection_status']} | "
                f"{fold['training']['signals']} | "
                f"{_rate(fold['training']['accuracy'])} | "
                f"{_format_policy(fold['policy'])} | "
                f"{fold['test']['signals']} | {_rate(fold['test']['accuracy'])} | "
                f"{_rate(fold['test']['wilson_low_95'])} |"
            )
    lines.extend(
        [
            "",
            "## Transferred Slices",
            "",
            "| symbol | timeframe | signals | accuracy | Wilson low |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in payload["transferred_by_slice"]:
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['signals']} | "
            f"{_rate(row['accuracy'])} | {_rate(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            (
                "The policy passes the transfer gate."
                if payload["admitted_70"]
                else "No policy passes the independent 70% transfer gate."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _timeframe_transfer(
    events: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    target_accuracy: float,
    min_training_signals: int,
) -> dict[str, Any]:
    timeframe_events = [
        dict(row)
        for row in events
        if str(row.get("timeframe", "unknown")) == timeframe
    ]
    folds = sorted({int(row["fold_index"]) for row in timeframe_events})
    transfers = []
    for test_fold in folds[1:]:
        training = [
            row for row in timeframe_events if int(row["fold_index"]) < test_fold
        ]
        test = [
            row for row in timeframe_events if int(row["fold_index"]) == test_fold
        ]
        policy, training_selected, selection_status = _select_training_policy(
            training,
            target_accuracy=target_accuracy,
            min_selected=min_training_signals,
        )
        test_selected = _select_policy(test, policy)
        transfers.append(
            {
                "test_fold": test_fold,
                "policy": policy,
                "selection_status": selection_status,
                "training": _summary(training_selected),
                "test": _summary(test_selected),
                "_selected_events": test_selected,
            }
        )
    return {
        "timeframe": timeframe,
        "independent_events": len(timeframe_events),
        "folds": transfers,
    }


def _select_training_policy(
    events: Sequence[Mapping[str, Any]],
    *,
    target_accuracy: float,
    min_selected: int,
) -> tuple[dict[str, float | None], list[dict[str, Any]], str]:
    candidates = []
    for policy in _policies():
        selected = _select_policy(events, policy)
        if len(selected) < min_selected:
            continue
        summary = _summary(selected)
        candidates.append((policy, selected, summary))
    if not candidates:
        policy = {
            "min_agreement": 0.0,
            "min_strength": 0.0,
            "min_magnitude_bps": 0.0,
            "max_volatility_bps": None,
        }
        return policy, _select_policy(events, policy), "insufficient_history"
    eligible = [
        row
        for row in candidates
        if row[2]["accuracy"] is not None
        and row[2]["accuracy"] >= target_accuracy
    ]
    if eligible:
        policy, selected, _summary_row = max(
            eligible,
            key=lambda row: (
                row[2]["signals"],
                row[2]["wilson_low_95"] or 0.0,
                row[2]["accuracy"] or 0.0,
            ),
        )
        return policy, selected, "target_reached"
    policy, selected, _summary_row = max(
        candidates,
        key=lambda row: (
            row[2]["wilson_low_95"] or 0.0,
            row[2]["signals"],
            row[2]["accuracy"] or 0.0,
        ),
    )
    return policy, selected, "best_available"


def _policies() -> Iterable[dict[str, float | None]]:
    for agreement in AGREEMENT_GRID:
        for strength in STRENGTH_GRID:
            for magnitude in MAGNITUDE_GRID:
                for volatility in VOLATILITY_GRID:
                    yield {
                        "min_agreement": agreement,
                        "min_strength": strength,
                        "min_magnitude_bps": magnitude,
                        "max_volatility_bps": volatility,
                    }


def _select_policy(
    events: Sequence[Mapping[str, Any]],
    policy: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    output = []
    for row in events:
        if float(row["agreement"]) < float(policy["min_agreement"] or 0.0):
            continue
        if float(row["strength"]) < float(policy["min_strength"] or 0.0):
            continue
        if float(row["magnitude_bps"]) < float(
            policy["min_magnitude_bps"] or 0.0
        ):
            continue
        maximum = policy["max_volatility_bps"]
        if maximum is not None and float(row["volatility_bps"]) > float(maximum):
            continue
        output.append(dict(row))
    return output


def _summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    signals = len(events)
    hits = sum(float(row["direction_hit"]) >= 0.5 for row in events)
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": hits / signals if signals else None,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def _group_summary(
    events: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    return [
        {field: value}
        | _summary([row for row in events if row.get(field) == value])
        for value in sorted({row.get(field) for row in events})
    ]


def _slice_summary(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    slices = sorted(
        {
            (str(row["symbol"]), str(row.get("timeframe", "unknown")))
            for row in events
        }
    )
    return [
        {"symbol": symbol, "timeframe": timeframe}
        | _summary(
            [
                row
                for row in events
                if str(row["symbol"]) == symbol
                and str(row.get("timeframe", "unknown")) == timeframe
            ]
        )
        for symbol, timeframe in slices
    ]


def _validate_events(events: Sequence[Mapping[str, Any]]) -> None:
    required = {
        "engine",
        "symbol",
        "timeframe",
        "fold_index",
        "query_id",
        "data_end_utc",
        "target_end_utc",
        "direction_hit",
        "agreement",
        "strength",
        "magnitude_bps",
        "volatility_bps",
    }
    for index, row in enumerate(events):
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(
                f"Signal event {index} is missing: {', '.join(missing)}"
            )
        for field in (
            "direction_hit",
            "agreement",
            "strength",
            "magnitude_bps",
            "volatility_bps",
        ):
            if not math.isfinite(float(row[field])):
                raise ValueError(f"Signal event {index} has non-finite {field}")


def _format_policy(policy: Mapping[str, Any]) -> str:
    maximum = policy["max_volatility_bps"]
    volatility = "inf" if maximum is None else f"{float(maximum):.0f}"
    return (
        f"a>={float(policy['min_agreement']):.2f}, "
        f"s>={float(policy['min_strength']):.2f}, "
        f"m>={float(policy['min_magnitude_bps']):.0f}, v<={volatility}"
    )


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure whether a past-selected signal policy transfers."
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--target-accuracy", type=float, default=0.70)
    parser.add_argument("--min-training-signals", type=int, default=20)
    parser.add_argument("--min-test-signals", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = run_signal_transfer_benchmark(
        load_signal_events(args.events),
        target_accuracy=args.target_accuracy,
        min_training_signals=args.min_training_signals,
        min_test_signals=args.min_test_signals,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
