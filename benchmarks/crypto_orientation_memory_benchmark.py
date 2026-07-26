from __future__ import annotations

import argparse
import heapq
import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_current_forecast import guarded_state_direction  # noqa: E402
from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    make_ohlcv_windows,
)

FOLD_BOUNDARIES = (
    ("2024-01-01", "2024-07-01"),
    ("2024-07-01", "2025-01-01"),
    ("2025-01-01", "2025-07-01"),
    ("2025-07-01", "2026-01-01"),
    ("2026-01-01", "2026-07-01"),
)


@dataclass(frozen=True)
class DirectionEvent:
    symbol: str
    observed_at: int
    target_at: int
    fold_index: int
    actual_up: bool
    guard_up: bool
    momentum_up: bool
    regime: tuple[str, ...]


class OrientationMemory:
    """Past-only memory that chooses the guard rule or its inverse."""

    def __init__(
        self,
        *,
        global_lookback: int = 120,
        symbol_lookback: int = 60,
        regime_lookback: int = 80,
        prior_strength: float = 12.0,
    ) -> None:
        self.prior_strength = float(prior_strength)
        self.global_hits: deque[float] = deque(maxlen=global_lookback)
        self.symbol_hits: defaultdict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=symbol_lookback)
        )
        self.regime_hits: defaultdict[tuple[str, ...], deque[float]] = defaultdict(
            lambda: deque(maxlen=regime_lookback)
        )

    def predict(self, event: DirectionEvent) -> tuple[bool, float]:
        global_score = self._posterior(self.global_hits)
        symbol_score = self._posterior(self.symbol_hits[event.symbol])
        regime_score = self._posterior(self.regime_hits[event.regime])
        reliability = (
            0.45 * global_score
            + 0.35 * symbol_score
            + 0.20 * regime_score
        )
        return (
            event.guard_up if reliability >= 0.5 else not event.guard_up,
            reliability,
        )

    def observe(self, event: DirectionEvent) -> None:
        hit = float(event.guard_up == event.actual_up)
        self.global_hits.append(hit)
        self.symbol_hits[event.symbol].append(hit)
        self.regime_hits[event.regime].append(hit)

    def _posterior(self, hits: Sequence[float]) -> float:
        return (
            sum(hits) + 0.5 * self.prior_strength
        ) / (len(hits) + self.prior_strength)


def load_direction_events(
    bundle_paths: Sequence[str | Path],
    *,
    horizon_bars: int = 6,
    window_bars: int = 32,
) -> list[DirectionEvent]:
    events: list[DirectionEvent] = []
    seen: set[str] = set()
    boundaries = [
        (_timestamp(start), _timestamp(end))
        for start, end in FOLD_BOUNDARIES
    ]
    for path in bundle_paths:
        bundle = load_bundle(path)
        if bundle.symbol in seen:
            raise ValueError(f"Duplicate bundle for {bundle.symbol}")
        seen.add(bundle.symbol)
        bars = [
            OHLCVBar(
                timestamp=int(bar.timestamp),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in bundle.bars
        ]
        windows = make_ohlcv_windows(
            bars,
            symbol=bundle.symbol,
            timeframe="4h",
            window=window_bars,
            horizon=horizon_bars,
            stride=horizon_bars,
            direction_threshold_bps=0.0,
        )
        for window in windows:
            fold = next(
                (
                    index
                    for index, (start, end) in enumerate(boundaries)
                    if start <= window.observed_until_ts < end
                ),
                -1,
            )
            fallback_up = float(window.features["recent_return_bps"]) >= 0.0
            guard_direction, _ = guarded_state_direction(
                window.features,
                fallback_direction="up" if fallback_up else "down",
            )
            regime = (
                str(window.features["trend"]),
                str(window.features["recent_trend"]),
                str(window.features["rsi_bucket"]),
                str(window.features["volatility_bucket"]),
            )
            events.append(
                DirectionEvent(
                    symbol=bundle.symbol,
                    observed_at=window.observed_until_ts,
                    target_at=window.target_until_ts,
                    fold_index=fold,
                    actual_up=window.future_return_bps > 0.0,
                    guard_up=guard_direction == "up",
                    momentum_up=fallback_up,
                    regime=regime,
                )
            )
    return sorted(events, key=lambda item: (item.observed_at, item.symbol))


def run_benchmark(events: Sequence[DirectionEvent]) -> dict[str, Any]:
    if not events:
        raise ValueError("events must not be empty")
    memory = OrientationMemory()
    pending: list[tuple[int, int, DirectionEvent]] = []
    sequence = 0
    predictions: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in sorted(events, key=lambda item: (item.observed_at, item.symbol)):
        while pending and pending[0][0] <= event.observed_at:
            _, _, matured = heapq.heappop(pending)
            memory.observe(matured)

        memory_up, reliability = memory.predict(event)
        if event.fold_index >= 0:
            candidates = {
                "guarded_state": event.guard_up,
                "inverse_guarded_state": not event.guard_up,
                "momentum": event.momentum_up,
                "mean_reversion": not event.momentum_up,
                "orientation_memory": memory_up,
                "always_up": True,
            }
            for engine, predicted_up in candidates.items():
                predictions[engine].append(
                    {
                        "symbol": event.symbol,
                        "fold_index": event.fold_index,
                        "observed_at": event.observed_at,
                        "target_at": event.target_at,
                        "predicted_up": predicted_up,
                        "actual_up": event.actual_up,
                        "hit": predicted_up == event.actual_up,
                        "guard_reliability": reliability,
                    }
                )
        heapq.heappush(pending, (event.target_at, sequence, event))
        sequence += 1

    summaries = [
        _summarize(engine, rows)
        for engine, rows in sorted(predictions.items())
    ]
    return {
        "benchmark": "full-coverage causal orientation memory",
        "methodology": {
            "data": "verified Binance USD-M 4h archives",
            "horizon": "24h",
            "sampling": "one non-overlapping forecast per 24h horizon",
            "test_folds": [list(item) for item in FOLD_BOUNDARIES],
            "online_rule": (
                "Orientation memory observes a target only after target_at is "
                "not later than the next query's observed_at."
            ),
            "admission": (
                "At least 70% accuracy, at least 100 signals, Wilson low at "
                "least 65%, every fold and supported symbol at least 60%."
            ),
        },
        "assets": sorted({event.symbol for event in events}),
        "summaries": summaries,
        "admitted_engines": [
            row["engine"] for row in summaries if row["admitted_70"]
        ],
    }


def _summarize(
    engine: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    signals = len(rows)
    hits = sum(int(row["hit"]) for row in rows)
    by_fold = _group(rows, "fold_index")
    by_symbol = _group(rows, "symbol")
    supported_symbols = [
        row for row in by_symbol if int(row["signals"]) >= 20
    ]
    accuracy = hits / signals if signals else None
    wilson = _wilson_low(hits, signals) if signals else None
    admitted = bool(
        signals >= 100
        and accuracy is not None
        and accuracy >= 0.70
        and wilson is not None
        and wilson >= 0.65
        and by_fold
        and all(float(row["accuracy"]) >= 0.60 for row in by_fold)
        and supported_symbols
        and all(
            float(row["accuracy"]) >= 0.60
            for row in supported_symbols
        )
    )
    return {
        "engine": engine,
        "signals": signals,
        "hits": hits,
        "accuracy": accuracy,
        "wilson_low_95": wilson,
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "worst_fold_accuracy": min(
            (float(row["accuracy"]) for row in by_fold),
            default=None,
        ),
        "worst_supported_symbol_accuracy": min(
            (float(row["accuracy"]) for row in supported_symbols),
            default=None,
        ),
        "admitted_70": admitted,
    }


def _group(
    rows: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    output = []
    for value in sorted({row[field] for row in rows}):
        selected = [row for row in rows if row[field] == value]
        hits = sum(int(row["hit"]) for row in selected)
        output.append(
            {
                field: value,
                "signals": len(selected),
                "hits": hits,
                "accuracy": hits / len(selected),
            }
        )
    return output


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Universal Direction Orientation Benchmark",
        "",
        (
            "A full-coverage, causal 24h benchmark. Every independent market "
            "window receives an up/down prediction."
        ),
        "",
        "| engine | signals | accuracy | Wilson low 95% | worst fold | worst asset | admitted 70% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["summaries"]:
        lines.append(
            f"| {row['engine']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} | "
            f"{_percent(row['worst_fold_accuracy'])} | "
            f"{_percent(row['worst_supported_symbol_accuracy'])} | "
            f"{'yes' if row['admitted_70'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            (
                "The orientation-memory engine can invert the guard only from "
                "already matured historical outcomes. Failure to reach the gate "
                "is retained as evidence against a universal 70% claim."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate causal guard/inversion orientation memory."
    )
    parser.add_argument("--bundle", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    payload = run_benchmark(load_direction_events(args.bundle))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    report = render_markdown(payload)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
