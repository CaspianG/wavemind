from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)

DEFAULT_FOLD_BOUNDARIES = (
    ("2024-01-01", "2024-07-01"),
    ("2024-07-01", "2025-01-01"),
    ("2025-01-01", "2025-07-01"),
    ("2025-07-01", "2026-01-01"),
    ("2026-01-01", "2026-07-01"),
)
EARLY_REPLICATION_BOUNDARIES = (
    ("2023-07-01", "2023-10-01"),
    ("2023-10-01", "2024-01-01"),
)


@dataclass(frozen=True)
class TailCondition:
    feature: str
    quantile: float
    tail: str = "low"

    def __post_init__(self) -> None:
        if not 0.0 < self.quantile < 0.5:
            raise ValueError("quantile must be between 0 and 0.5")
        if self.tail not in {"low", "high"}:
            raise ValueError("tail must be low or high")


@dataclass(frozen=True)
class CapitulationRule:
    name: str
    conditions: tuple[TailCondition, ...]
    direction: str = "up"

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("conditions must not be empty")
        if self.direction not in {"up", "down"}:
            raise ValueError("direction must be up or down")


# Frozen before evaluating the third, asset-disjoint holdout.
FROZEN_CAPITULATION_RULE = CapitulationRule(
    name="capitulation-rebound-v1",
    conditions=(
        TailCondition("return_12", 0.01, "low"),
        TailCondition("oi_change_1", 0.10, "low"),
    ),
    direction="up",
)


def load_feature_rows(
    bundle_paths: Sequence[str | Path],
    *,
    horizon_bars: int = 6,
    boundaries: Sequence[tuple[str, str]] = DEFAULT_FOLD_BOUNDARIES,
) -> list[FeatureRow]:
    return assign_calendar_folds(
        load_unfolded_feature_rows(
            bundle_paths,
            horizon_bars=horizon_bars,
        ),
        boundaries=boundaries,
    )


def load_unfolded_feature_rows(
    bundle_paths: Sequence[str | Path],
    *,
    horizon_bars: int = 6,
) -> list[FeatureRow]:
    if not bundle_paths:
        raise ValueError("bundle_paths must not be empty")
    rows: list[FeatureRow] = []
    symbols: set[str] = set()
    for path in bundle_paths:
        bundle = load_bundle(path)
        if bundle.symbol in symbols:
            raise ValueError(f"Duplicate bundle for {bundle.symbol}")
        symbols.add(bundle.symbol)
        feature_rows = build_feature_rows(
            bundle,
            horizon=horizon_bars,
            lookback=180,
            include_microstructure=False,
            include_intraday=False,
            extended_features=True,
        )
        rows.extend(feature_rows)
    return rows


def evaluate_capitulation_rule(
    rows: Sequence[FeatureRow],
    *,
    rule: CapitulationRule = FROZEN_CAPITULATION_RULE,
    min_slice_support: int = 5,
) -> dict[str, Any]:
    independent = _independent_rows(rows)
    folds = sorted({row.fold_index for row in independent if row.fold_index >= 0})
    if not folds:
        raise ValueError("rows must include at least one test fold")

    events: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for fold in folds:
        test = [row for row in independent if row.fold_index == fold]
        test_start = min(row.timestamp for row in test)
        history = [row for row in independent if row.target_timestamp < test_start]
        if not history:
            raise ValueError(f"Fold {fold} has no matured history")
        thresholds = {
            condition.feature: _tail_threshold(history, condition)
            for condition in rule.conditions
        }
        selected = [
            row
            for row in test
            if all(
                _condition_matches(
                    float(row.features[condition.feature]),
                    thresholds[condition.feature],
                    condition.tail,
                )
                for condition in rule.conditions
            )
        ]
        for row in selected:
            predicted_up = rule.direction == "up"
            actual_up = row.future_return_bps > 0.0
            events.append(
                {
                    "fold_index": fold,
                    "symbol": row.symbol,
                    "timestamp": row.timestamp,
                    "timestamp_utc": _iso(row.timestamp),
                    "target_timestamp": row.target_timestamp,
                    "target_timestamp_utc": _iso(row.target_timestamp),
                    "prediction": rule.direction,
                    "future_return_bps": row.future_return_bps,
                    "direction_hit": predicted_up == actual_up,
                    "field_energy": _field_energy(
                        row,
                        conditions=rule.conditions,
                        thresholds=thresholds,
                    ),
                    "features": {
                        condition.feature: float(row.features[condition.feature])
                        for condition in rule.conditions
                    },
                    "thresholds": dict(thresholds),
                }
            )
        audits.append(
            {
                "fold_index": fold,
                "test_start_utc": _iso(test_start),
                "matured_history_rows": len(history),
                "independent_test_rows": len(test),
                "signals": len(selected),
                "thresholds": thresholds,
            }
        )

    summary = summarize_with_slices(
        events,
        min_slice_support=min_slice_support,
    )
    total_test_rows = sum(int(audit["independent_test_rows"]) for audit in audits)
    summary["independent_test_rows"] = total_test_rows
    summary["coverage"] = (
        int(summary["signals"]) / total_test_rows if total_test_rows else None
    )
    return {
        "rule": {
            "name": rule.name,
            "direction": rule.direction,
            "conditions": [asdict(condition) for condition in rule.conditions],
        },
        "methodology": {
            "forecast_horizon": "24h from a completed 4h candle",
            "threshold_fit": (
                "Each fold uses feature quantiles from independent rows whose "
                "forecast targets matured before the fold started."
            ),
            "selection": (
                "The rule and quantile levels are frozen before asset-disjoint "
                "holdout evaluation."
            ),
            "overlap_control": (
                "At most one observation per asset and forecast horizon."
            ),
            "claim_gate": {
                "min_accuracy": 0.70,
                "min_signals": 40,
                "min_wilson_low_95": 0.65,
                "min_supported_slice_accuracy": 0.65,
                "min_slice_support": min_slice_support,
            },
        },
        "summary": summary,
        "aggregate_evidence_70": aggregate_evidence_70(summary),
        "admitted_70": admitted_70(
            summary,
            expected_folds=len(folds),
            min_slice_support=min_slice_support,
        ),
        "fold_audits": audits,
        "events": events,
    }


def run_benchmark(
    *,
    development_bundle_paths: Sequence[str | Path],
    holdout_bundle_paths: Sequence[str | Path],
    replication_bundle_paths: Sequence[str | Path] = (),
    rule: CapitulationRule = FROZEN_CAPITULATION_RULE,
) -> dict[str, Any]:
    development_rows = load_feature_rows(development_bundle_paths)
    holdout_rows = load_feature_rows(holdout_bundle_paths)
    development_assets = sorted({row.symbol for row in development_rows})
    holdout_assets = sorted({row.symbol for row in holdout_rows})
    _validate_disjoint_asset_sets(
        development=development_assets,
        holdout=holdout_assets,
    )
    development = evaluate_capitulation_rule(development_rows, rule=rule)
    holdout = evaluate_capitulation_rule(holdout_rows, rule=rule)
    payload = {
        "benchmark": "frozen asset-transfer capitulation field",
        "data": "official Binance USD-M futures archives with SHA-256 verification",
        "development_assets": development_assets,
        "holdout_assets": holdout_assets,
        "development": development,
        "asset_disjoint_holdout": holdout,
        "aggregate_evidence_70": bool(holdout["aggregate_evidence_70"]),
        "admitted_70": bool(holdout["admitted_70"]),
    }
    if replication_bundle_paths:
        replication_base_rows = load_unfolded_feature_rows(
            replication_bundle_paths
        )
        replication_rows = assign_calendar_folds(
            replication_base_rows,
            boundaries=DEFAULT_FOLD_BOUNDARIES,
        )
        early_replication_rows = assign_calendar_folds(
            replication_base_rows,
            boundaries=EARLY_REPLICATION_BOUNDARIES,
        )
        replication_assets = sorted({row.symbol for row in replication_rows})
        early_replication_assets = sorted(
            {row.symbol for row in early_replication_rows}
        )
        if replication_assets != early_replication_assets:
            raise ValueError("Replication asset sets differ between time windows")
        _validate_disjoint_asset_sets(
            development=development_assets,
            holdout=holdout_assets,
            replication=replication_assets,
        )
        replication = evaluate_capitulation_rule(
            replication_rows,
            rule=rule,
        )
        early_replication = evaluate_capitulation_rule(
            early_replication_rows,
            rule=rule,
        )
        combined_summary = summarize_with_slices(
            list(holdout["events"]) + list(replication["events"]),
            min_slice_support=5,
        )
        combined_test_rows = (
            int(holdout["summary"]["independent_test_rows"])
            + int(replication["summary"]["independent_test_rows"])
        )
        combined_summary["independent_test_rows"] = combined_test_rows
        combined_summary["coverage"] = (
            int(combined_summary["signals"]) / combined_test_rows
            if combined_test_rows
            else None
        )
        combined_assets = sorted(holdout_assets + replication_assets)
        payload |= {
            "replication_assets": replication_assets,
            "combined_replication_assets": combined_assets,
            "asset_disjoint_replication": replication,
            "early_period_replication": early_replication,
            "combined_asset_replications": {
                "summary": combined_summary,
                "aggregate_evidence_70": aggregate_evidence_70(
                    combined_summary
                ),
                "admitted_70": admitted_70(
                    combined_summary,
                    expected_folds=len(DEFAULT_FOLD_BOUNDARIES),
                    min_slice_support=5,
                ),
            },
            "replication_protocol": {
                "asset_selection": (
                    "Eight active Binance USD-M perpetual assets not present in "
                    "development or the first holdout."
                ),
                "current_period_folds": [list(item) for item in DEFAULT_FOLD_BOUNDARIES],
                "early_period_folds": [
                    list(item) for item in EARLY_REPLICATION_BOUNDARIES
                ],
                "early_period_note": (
                    "A frozen retrospective time stress on previously unused "
                    "assets, not prospective post-freeze market evidence."
                ),
            },
        }
    return payload


def _validate_disjoint_asset_sets(**asset_sets: Sequence[str]) -> None:
    labels = list(asset_sets)
    for index, left_label in enumerate(labels):
        for right_label in labels[index + 1 :]:
            overlap = sorted(
                set(asset_sets[left_label]) & set(asset_sets[right_label])
            )
            if overlap:
                raise ValueError(
                    f"{left_label} and {right_label} assets overlap: "
                    + ", ".join(overlap)
                )


def summarize_with_slices(
    events: Sequence[Mapping[str, Any]],
    *,
    min_slice_support: int,
) -> dict[str, Any]:
    summary = _summarize(events)
    by_fold = _group(events, "fold_index")
    by_symbol = _group(events, "symbol")
    supported_folds = [
        row for row in by_fold if int(row["signals"]) >= min_slice_support
    ]
    supported_symbols = [
        row for row in by_symbol if int(row["signals"]) >= min_slice_support
    ]
    return summary | {
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "supported_folds": supported_folds,
        "supported_symbols": supported_symbols,
        "undersupported_folds": [
            row for row in by_fold if int(row["signals"]) < min_slice_support
        ],
        "undersupported_symbols": [
            row for row in by_symbol if int(row["signals"]) < min_slice_support
        ],
        "worst_supported_fold_accuracy": min(
            (float(row["accuracy"]) for row in supported_folds),
            default=None,
        ),
        "worst_supported_symbol_accuracy": min(
            (float(row["accuracy"]) for row in supported_symbols),
            default=None,
        ),
    }


def admitted_70(
    summary: Mapping[str, Any],
    *,
    expected_folds: int,
    min_slice_support: int,
) -> bool:
    return bool(
        summary["accuracy"] is not None
        and float(summary["accuracy"]) >= 0.70
        and int(summary["signals"]) >= 40
        and float(summary["wilson_low_95"]) >= 0.65
        and len(summary["supported_folds"]) == expected_folds
        and all(
            float(row["accuracy"]) >= 0.65
            for row in summary["supported_folds"]
        )
        and all(
            int(row["signals"]) < min_slice_support
            or float(row["accuracy"]) >= 0.65
            for row in summary["by_symbol"]
        )
    )


def aggregate_evidence_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        summary["accuracy"] is not None
        and float(summary["accuracy"]) >= 0.70
        and int(summary["signals"]) >= 40
        and float(summary["wilson_low_95"]) >= 0.65
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    rule = payload["development"]["rule"]
    lines = [
        "# Frozen Asset-Transfer Capitulation Field",
        "",
        (
            "A causal, asset-disjoint test of a frozen extreme-state memory rule "
            "on verified Binance USD-M futures archives."
        ),
        "",
        "## Frozen Rule",
        "",
        f"- direction: **{rule['direction']}**;",
    ]
    for condition in rule["conditions"]:
        lines.append(
            f"- `{condition['feature']}` in the {condition['tail']} "
            f"{float(condition['quantile']):.1%} tail;"
        )
    lines.extend(
        [
            "- thresholds use matured past observations only;",
            "- one independent signal per asset per 24-hour horizon.",
            "",
            "## Results",
            "",
            "| split | assets | signals | coverage | accuracy | Wilson low 95% | aggregate 70% | stable gate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    result_rows = [
        (
            "development walk-forward",
            "development",
            "development_assets",
        ),
        (
            "first asset-disjoint holdout",
            "asset_disjoint_holdout",
            "holdout_assets",
        ),
    ]
    if "asset_disjoint_replication" in payload:
        result_rows.extend(
            [
                (
                    "second asset-disjoint replication",
                    "asset_disjoint_replication",
                    "replication_assets",
                ),
                (
                    "early-2023 temporal stress",
                    "early_period_replication",
                    "replication_assets",
                ),
                (
                    "combined asset replications",
                    "combined_asset_replications",
                    "combined_replication_assets",
                ),
            ]
        )
    for label, key, asset_key in result_rows:
        result = payload[key]
        summary = result["summary"]
        lines.append(
            f"| {label} | {len(payload[asset_key])} | "
            f"{summary['signals']} | {_percent(summary['coverage'])} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{'yes' if result['aggregate_evidence_70'] else 'no'} | "
            f"{'yes' if result['admitted_70'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Holdout Slices",
            "",
            "| asset | signals | accuracy | Wilson low 95% |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["asset_disjoint_holdout"]["summary"]["by_symbol"]:
        lines.append(
            f"| {row['symbol']} | {row['signals']} | {_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    if "asset_disjoint_replication" in payload:
        lines.extend(
            [
                "",
                "## Replication Slices",
                "",
                "| period | asset | signals | accuracy | Wilson low 95% |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for period, key in (
            ("2024-2026", "asset_disjoint_replication"),
            ("2023", "early_period_replication"),
        ):
            for row in payload[key]["summary"]["by_symbol"]:
                lines.append(
                    f"| {period} | {row['symbol']} | {row['signals']} | "
                    f"{_percent(row['accuracy'])} | "
                    f"{_percent(row['wilson_low_95'])} |"
                )
        lines.extend(
            [
                "",
                "The early-2023 result is a frozen retrospective time stress on "
                "previously unused assets. It is not prospective post-freeze "
                "market evidence.",
            ]
        )
    lines.extend(
        [
            "",
            "This is a sparse conditional rebound signal, not a universal price "
            "forecast. Aggregate evidence and stable admission are separate: the "
            "stable gate remains false unless the untouched asset holdout also "
            "clears the predeclared fold and asset checks.",
            "",
        ]
    )
    return "\n".join(lines)


def _tail_threshold(
    rows: Sequence[FeatureRow],
    condition: TailCondition,
) -> float:
    values = np.asarray(
        [float(row.features[condition.feature]) for row in rows],
        dtype=float,
    )
    quantile = condition.quantile if condition.tail == "low" else 1.0 - condition.quantile
    return float(np.quantile(values, quantile))


def _condition_matches(value: float, threshold: float, tail: str) -> bool:
    return value <= threshold if tail == "low" else value >= threshold


def _field_energy(
    row: FeatureRow,
    *,
    conditions: Sequence[TailCondition],
    thresholds: Mapping[str, float],
) -> float:
    energy = 0.0
    for condition in conditions:
        value = float(row.features[condition.feature])
        threshold = float(thresholds[condition.feature])
        scale = max(abs(threshold), 1e-9)
        depth = (
            (threshold - value) / scale
            if condition.tail == "low"
            else (value - threshold) / scale
        )
        energy += max(0.0, depth)
    return float(energy)


def _independent_rows(rows: Sequence[FeatureRow]) -> list[FeatureRow]:
    by_symbol: defaultdict[str, list[FeatureRow]] = defaultdict(list)
    for row in rows:
        by_symbol[row.symbol].append(row)
    output: list[FeatureRow] = []
    for symbol_rows in by_symbol.values():
        next_allowed = -math.inf
        for row in sorted(symbol_rows, key=lambda item: item.timestamp):
            if row.timestamp < next_allowed:
                continue
            output.append(row)
            next_allowed = row.target_timestamp
    return sorted(output, key=lambda row: (row.timestamp, row.symbol))


def _summarize(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    signals = len(events)
    hits = sum(int(event["direction_hit"]) for event in events)
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": hits / signals if signals else None,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def _group(
    events: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    values = sorted({event[field] for event in events})
    return [
        {field: value}
        | _summarize([event for event in events if event[field] == value])
        for value in values
    ]


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a frozen capitulation field on asset-disjoint data."
    )
    parser.add_argument(
        "--development-bundle",
        action="append",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--holdout-bundle",
        action="append",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--replication-bundle",
        action="append",
        default=[],
        type=Path,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    payload = run_benchmark(
        development_bundle_paths=args.development_bundle,
        holdout_bundle_paths=args.holdout_bundle,
        replication_bundle_paths=args.replication_bundle,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(
            render_markdown(payload),
            encoding="utf-8",
        )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
