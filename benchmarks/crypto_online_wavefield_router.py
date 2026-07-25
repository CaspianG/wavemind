from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


@dataclass(frozen=True)
class RouterConfig:
    name: str
    half_life_days: float
    prior_strength: float
    symbol_shrinkage: float
    field_weight: float


@dataclass(frozen=True)
class QueryPanel:
    symbol: str
    timeframe: str
    fold_index: int
    query_id: str
    data_end_utc: str
    target_end_utc: str
    actual_return_bps: float
    predictions: Mapping[str, Mapping[str, float]]


@dataclass
class DecayedAccuracy:
    hits: float = 0.0
    total: float = 0.0
    last_timestamp: int | None = None

    def observe(self, hit: float, timestamp: int, *, half_life_seconds: float) -> None:
        self._decay(timestamp, half_life_seconds=half_life_seconds)
        self.hits += float(hit)
        self.total += 1.0

    def posterior(
        self,
        timestamp: int,
        *,
        half_life_seconds: float,
        prior_strength: float,
    ) -> tuple[float, float]:
        hits, total = self._values_at(timestamp, half_life_seconds=half_life_seconds)
        accuracy = (hits + prior_strength * 0.5) / (total + prior_strength)
        return float(accuracy), float(total)

    def _decay(self, timestamp: int, *, half_life_seconds: float) -> None:
        hits, total = self._values_at(timestamp, half_life_seconds=half_life_seconds)
        self.hits = hits
        self.total = total
        self.last_timestamp = int(timestamp)

    def _values_at(self, timestamp: int, *, half_life_seconds: float) -> tuple[float, float]:
        if self.last_timestamp is None or timestamp <= self.last_timestamp:
            return self.hits, self.total
        elapsed = float(timestamp - self.last_timestamp)
        factor = 0.5 ** (elapsed / max(half_life_seconds, 1.0))
        return self.hits * factor, self.total * factor


class OnlineWaveFieldRouter:
    def __init__(
        self,
        experts: Sequence[str],
        config: RouterConfig,
        *,
        seed: int = 2027,
    ) -> None:
        self.experts = tuple(experts)
        self.config = config
        self.half_life_seconds = config.half_life_days * 86_400.0
        self.global_accuracy = {name: DecayedAccuracy() for name in self.experts}
        self.symbol_accuracy: dict[tuple[str, str], DecayedAccuracy] = defaultdict(DecayedAccuracy)
        self.projector = (
            FieldProjector(18, 18, len(self.experts) * 3, seed=seed)
            if config.field_weight > 0.0
            else None
        )
        self.correct_fields = (
            {
                name: WaveField(
                    width=18,
                    height=18,
                    layers=3,
                    decay=0.998,
                    speed=0.08,
                    nonlin=0.01,
                )
                for name in self.experts
            }
            if config.field_weight > 0.0
            else {}
        )
        self.wrong_fields = (
            {
                name: WaveField(
                    width=18,
                    height=18,
                    layers=3,
                    decay=0.998,
                    speed=0.08,
                    nonlin=0.01,
                )
                for name in self.experts
            }
            if config.field_weight > 0.0
            else {}
        )
        self.field_counts = {name: [0, 0] for name in self.experts}
        self.rng = np.random.default_rng(seed)

    def predict(self, query: QueryPanel) -> dict[str, Any]:
        timestamp = _timestamp(query.data_end_utc)
        pattern = self._pattern(query) if self.projector is not None else None
        contributions = []
        reliabilities = {}
        for expert in self.experts:
            prediction = query.predictions[expert]
            global_accuracy, global_total = self.global_accuracy[expert].posterior(
                timestamp,
                half_life_seconds=self.half_life_seconds,
                prior_strength=self.config.prior_strength,
            )
            symbol_accuracy, symbol_total = self.symbol_accuracy[(query.symbol, expert)].posterior(
                timestamp,
                half_life_seconds=self.half_life_seconds,
                prior_strength=self.config.prior_strength,
            )
            symbol_weight = symbol_total / (symbol_total + self.config.symbol_shrinkage)
            statistical_accuracy = (
                symbol_weight * symbol_accuracy + (1.0 - symbol_weight) * global_accuracy
            )
            field_accuracy = self._field_accuracy(expert, pattern) if pattern is not None else 0.5
            field_support = min(self.field_counts[expert]) / 30.0
            active_field_weight = self.config.field_weight * min(1.0, field_support)
            reliability = (
                (1.0 - active_field_weight) * statistical_accuracy
                + active_field_weight * field_accuracy
            )
            probability_up = float(prediction["probability_up"])
            predicted_sign = 1.0 if probability_up >= 0.5 else -1.0
            confidence = max(0.05, abs(probability_up - 0.5) * 2.0)
            edge = float(np.clip(reliability - 0.5, -0.24, 0.24))
            contribution = predicted_sign * edge * confidence
            contributions.append(contribution)
            reliabilities[expert] = {
                "reliability": reliability,
                "statistical": statistical_accuracy,
                "field": field_accuracy,
                "global_effective_samples": global_total,
                "symbol_effective_samples": symbol_total,
                "contribution": contribution,
            }

        score = float(np.sum(contributions))
        if abs(score) < 1e-12:
            score = float(
                np.mean(
                    [
                        1.0 if query.predictions[name]["probability_up"] >= 0.5 else -1.0
                        for name in self.experts
                    ]
                )
            )
        predicted_up = score >= 0.0
        return {
            "predicted_up": predicted_up,
            "router_score": score,
            "reliabilities": reliabilities,
        }

    def observe(self, query: QueryPanel) -> None:
        timestamp = _timestamp(query.target_end_utc)
        actual_up = query.actual_return_bps > 0.0
        pattern = self._pattern(query) if self.projector is not None else None
        previous_state = np.random.get_state()
        np.random.seed(int(self.rng.integers(0, 2**31 - 1)))
        try:
            for expert in self.experts:
                predicted_up = query.predictions[expert]["probability_up"] >= 0.5
                hit = float(predicted_up == actual_up)
                self.global_accuracy[expert].observe(
                    hit,
                    timestamp,
                    half_life_seconds=self.half_life_seconds,
                )
                self.symbol_accuracy[(query.symbol, expert)].observe(
                    hit,
                    timestamp,
                    half_life_seconds=self.half_life_seconds,
                )
                if pattern is not None:
                    target = self.correct_fields[expert] if hit else self.wrong_fields[expert]
                    target.feed(pattern, strength=0.35)
                    self.field_counts[expert][int(hit)] += 1
            if pattern is not None:
                for field in (*self.correct_fields.values(), *self.wrong_fields.values()):
                    field.evolve(1)
        finally:
            np.random.set_state(previous_state)

    def _pattern(self, query: QueryPanel) -> np.ndarray:
        if self.projector is None:
            raise RuntimeError("WaveField pattern requested for a statistical-only router")
        values = []
        for expert in self.experts:
            prediction = query.predictions[expert]
            probability = float(prediction["probability_up"])
            values.extend(
                (
                    probability,
                    float(prediction.get("quality_probability", 0.5)),
                    float(prediction.get("event_probability", 0.5)),
                )
            )
        return self.projector.to_pattern(np.asarray(values, dtype=np.float32))

    def _field_accuracy(self, expert: str, pattern: np.ndarray) -> float:
        correct_count, wrong_count = self.field_counts[expert][1], self.field_counts[expert][0]
        if correct_count < 5 or wrong_count < 5:
            return 0.5
        difference = self.correct_fields[expert].field_resonance(
            pattern
        ) - self.wrong_fields[expert].field_resonance(pattern)
        return float(1.0 / (1.0 + math.exp(-float(np.clip(difference * 80.0, -30.0, 30.0)))))


DEFAULT_CONFIGS = (
    RouterConfig("statistical_fast", 30.0, 20.0, 20.0, 0.0),
    RouterConfig("statistical_slow", 180.0, 40.0, 50.0, 0.0),
    RouterConfig("wavefield_fast", 30.0, 20.0, 20.0, 0.35),
    RouterConfig("wavefield_slow", 180.0, 40.0, 50.0, 0.35),
)


def load_query_panels(path: str | Path) -> list[QueryPanel]:
    grouped: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    source = Path(path)
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            key = (
                str(event["symbol"]),
                str(event.get("timeframe", "unknown")),
                int(event["fold_index"]),
                str(event["query_id"]),
            )
            row = grouped.setdefault(
                key,
                {
                    "symbol": key[0],
                    "timeframe": key[1],
                    "fold_index": key[2],
                    "query_id": key[3],
                    "data_end_utc": str(event["data_end_utc"]),
                    "target_end_utc": str(event["target_end_utc"]),
                    "actual_return_bps": float(event["actual_return_bps"]),
                    "predictions": {},
                },
            )
            for field in ("data_end_utc", "target_end_utc"):
                if row[field] != str(event[field]):
                    raise ValueError(f"Inconsistent {field} at {source}:{line_number}")
            if not math.isclose(
                row["actual_return_bps"],
                float(event["actual_return_bps"]),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(f"Inconsistent outcome at {source}:{line_number}")
            engine = str(event["engine"])
            if engine in row["predictions"]:
                raise ValueError(f"Duplicate engine {engine!r} at {source}:{line_number}")
            row["predictions"][engine] = {
                "probability_up": float(event["probability_up"]),
                "quality_probability": float(event.get("quality_probability", 0.5)),
                "event_probability": float(event.get("event_probability", 0.5)),
                "predicted_return_bps": float(event.get("predicted_return_bps", 0.0)),
            }

    if not grouped:
        raise ValueError(f"No events found in {source}")
    expert_sets = {tuple(sorted(row["predictions"])) for row in grouped.values()}
    if len(expert_sets) != 1:
        raise ValueError("Every query must contain the same expert set")
    panels = [QueryPanel(**row) for row in grouped.values()]
    return _collapse_overlapping_panels(panels)


def _collapse_overlapping_panels(panels: Iterable[QueryPanel]) -> list[QueryPanel]:
    grouped: dict[tuple[str, str, int], list[QueryPanel]] = defaultdict(list)
    for panel in panels:
        grouped[(panel.symbol, panel.timeframe, panel.fold_index)].append(panel)
    selected = []
    for rows in grouped.values():
        next_allowed = -math.inf
        for row in sorted(rows, key=lambda item: _timestamp(item.data_end_utc)):
            data_end = _timestamp(row.data_end_utc)
            target_end = _timestamp(row.target_end_utc)
            if data_end < next_allowed:
                continue
            selected.append(row)
            next_allowed = target_end
    return sorted(selected, key=lambda item: (_timestamp(item.data_end_utc), item.symbol))


def simulate_router(
    panels: Sequence[QueryPanel],
    config: RouterConfig,
    *,
    seed: int = 2027,
) -> list[dict[str, Any]]:
    experts = sorted(next(iter(panels)).predictions)
    router = OnlineWaveFieldRouter(experts, config, seed=seed)
    pending: list[tuple[int, int, QueryPanel]] = []
    output = []
    sequence = 0
    for panel in sorted(panels, key=lambda item: (_timestamp(item.data_end_utc), item.symbol)):
        data_end = _timestamp(panel.data_end_utc)
        while pending and pending[0][0] <= data_end:
            _, _, matured = heapq.heappop(pending)
            router.observe(matured)
        prediction = router.predict(panel)
        actual_up = panel.actual_return_bps > 0.0
        output.append(
            {
                "config": config.name,
                "symbol": panel.symbol,
                "timeframe": panel.timeframe,
                "fold_index": panel.fold_index,
                "query_id": panel.query_id,
                "data_end_utc": panel.data_end_utc,
                "target_end_utc": panel.target_end_utc,
                "predicted_up": bool(prediction["predicted_up"]),
                "actual_up": actual_up,
                "direction_hit": float(bool(prediction["predicted_up"]) == actual_up),
                "actual_return_bps": panel.actual_return_bps,
                "router_score": float(prediction["router_score"]),
            }
        )
        heapq.heappush(pending, (_timestamp(panel.target_end_utc), sequence, panel))
        sequence += 1
    return output


def run_benchmark(
    panels: Sequence[QueryPanel],
    *,
    configs: Sequence[RouterConfig] = DEFAULT_CONFIGS,
    validation_fold: int = 3,
    test_fold: int = 4,
) -> dict[str, Any]:
    if not panels:
        raise ValueError("At least one query panel is required")
    experts = sorted(next(iter(panels)).predictions)
    simulations = {config.name: simulate_router(panels, config) for config in configs}
    candidates = []
    for config in configs:
        validation = _summary(
            row for row in simulations[config.name] if int(row["fold_index"]) == validation_fold
        )
        candidates.append(
            {
                "config": config.name,
                "parameters": {
                    "half_life_days": config.half_life_days,
                    "prior_strength": config.prior_strength,
                    "symbol_shrinkage": config.symbol_shrinkage,
                    "field_weight": config.field_weight,
                },
                "validation": validation,
            }
        )
    selected = max(
        candidates,
        key=lambda row: (
            float(row["validation"]["wilson_low_95"] or 0.0),
            float(row["validation"]["accuracy"] or 0.0),
            -float(row["parameters"]["field_weight"]),
        ),
    )
    selected_events = simulations[str(selected["config"])]
    test = _summary(row for row in selected_events if int(row["fold_index"]) == test_fold)
    all_summary = _summary(selected_events)

    development_panels = [panel for panel in panels if panel.fold_index < validation_fold]
    expert_development = [
        {
            "engine": expert,
            "development": _expert_summary(development_panels, expert),
        }
        for expert in experts
    ]
    selected_expert = max(
        expert_development,
        key=lambda row: (
            float(row["development"]["wilson_low_95"] or 0.0),
            float(row["development"]["accuracy"] or 0.0),
        ),
    )["engine"]
    static_test = _expert_summary(
        [panel for panel in panels if panel.fold_index == test_fold],
        str(selected_expert),
    )
    majority_test = _majority_summary(
        [panel for panel in panels if panel.fold_index == test_fold],
        experts,
    )
    admitted_70 = _admitted_70(test)
    return {
        "methodology": {
            "protocol": (
                "All base predictions are out-of-sample. Router state is updated only after target_end_utc. "
                f"Configuration is selected on fold {validation_fold}; fold {test_fold} is the final test."
            ),
            "overlap_policy": "one non-overlapping forecast per symbol and horizon",
            "experts": experts,
            "panels": len(panels),
            "validation_fold": validation_fold,
            "test_fold": test_fold,
        },
        "candidates": candidates,
        "selected_config": selected["config"],
        "selected_validation": selected["validation"],
        "final_test": test,
        "all_periods": all_summary,
        "baselines": {
            "development_selected_expert": selected_expert,
            "single_expert_test": static_test,
            "majority_vote_test": majority_test,
        },
        "admitted_70": admitted_70,
        "events": selected_events,
    }


def _expert_summary(panels: Sequence[QueryPanel], expert: str) -> dict[str, Any]:
    rows = []
    for panel in panels:
        predicted_up = panel.predictions[expert]["probability_up"] >= 0.5
        rows.append(
            {
                "symbol": panel.symbol,
                "fold_index": panel.fold_index,
                "direction_hit": float(predicted_up == (panel.actual_return_bps > 0.0)),
            }
        )
    return _summary(rows)


def _majority_summary(panels: Sequence[QueryPanel], experts: Sequence[str]) -> dict[str, Any]:
    rows = []
    for panel in panels:
        score = sum(
            1 if panel.predictions[expert]["probability_up"] >= 0.5 else -1 for expert in experts
        )
        predicted_up = score >= 0
        rows.append(
            {
                "symbol": panel.symbol,
                "fold_index": panel.fold_index,
                "direction_hit": float(predicted_up == (panel.actual_return_bps > 0.0)),
            }
        )
    return _summary(rows)


def _summary(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in events]
    hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in rows)
    by_fold = _group_summary(rows, "fold_index")
    by_symbol = _group_summary(rows, "symbol")
    return {
        "signals": len(rows),
        "hits": hits,
        "accuracy": hits / len(rows) if rows else None,
        "wilson_low_95": _wilson_low(hits, len(rows)) if rows else None,
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "worst_fold_accuracy": min((row["accuracy"] for row in by_fold), default=None),
        "worst_symbol_accuracy": min((row["accuracy"] for row in by_symbol), default=None),
    }


def _group_summary(events: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    output = []
    for value in sorted({str(row[field]) for row in events}):
        selected = [row for row in events if str(row[field]) == value]
        hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in selected)
        output.append(
            {
                field: value,
                "signals": len(selected),
                "hits": hits,
                "accuracy": hits / len(selected),
            }
        )
    return output


def _admitted_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= 100
        and summary["accuracy"] is not None
        and float(summary["accuracy"]) >= 0.70
        and summary["wilson_low_95"] is not None
        and float(summary["wilson_low_95"]) >= 0.65
        and summary["worst_symbol_accuracy"] is not None
        and float(summary["worst_symbol_accuracy"]) >= 0.60
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    final_test = payload["final_test"]
    baselines = payload["baselines"]
    lines = [
        "# Causal Online WaveField Router",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        "## Final Test",
        "",
        "| engine | signals | accuracy | Wilson low | worst symbol |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, summary in (
        (f"WaveField router ({payload['selected_config']})", final_test),
        (
            f"Single expert ({baselines['development_selected_expert']})",
            baselines["single_expert_test"],
        ),
        ("Majority vote", baselines["majority_vote_test"]),
    ):
        lines.append(
            f"| {name} | {summary['signals']} | {_rate(summary['accuracy'])} | "
            f"{_rate(summary['wilson_low_95'])} | {_rate(summary['worst_symbol_accuracy'])} |"
        )
    lines.extend(
        (
            "",
            f"- strict 70% admission: **{'passed' if payload['admitted_70'] else 'rejected'}**;",
            f"- selected only on validation: `{payload['selected_config']}`;",
            "- test labels never choose the router configuration.",
            "",
            "## Validation Selection",
            "",
            "| candidate | field weight | validation signals | validation accuracy | Wilson low |",
            "|---|---:|---:|---:|---:|",
        )
    )
    for row in payload["candidates"]:
        summary = row["validation"]
        lines.append(
            f"| {row['config']} | {row['parameters']['field_weight']:.2f} | "
            f"{summary['signals']} | {_rate(summary['accuracy'])} | "
            f"{_rate(summary['wilson_low_95'])} |"
        )
    return "\n".join(lines) + "\n"


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Causal online WaveField router over out-of-sample crypto experts."
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--selected-events", type=Path)
    args = parser.parse_args()

    panels = load_query_panels(args.events)
    payload = run_benchmark(panels)
    events = payload.pop("events")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    if args.selected_events:
        args.selected_events.parent.mkdir(parents=True, exist_ok=True)
        args.selected_events.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in events) + "\n",
            encoding="utf-8",
        )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
