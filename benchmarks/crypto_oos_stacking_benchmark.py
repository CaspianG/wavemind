from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_online_wavefield_router import QueryPanel, load_query_panels  # noqa: E402


def run_stacking_benchmark(
    panels: Sequence[QueryPanel],
    *,
    training_folds: Sequence[int] = (0, 1, 2),
    validation_fold: int = 3,
    test_fold: int = 4,
    random_state: int = 2027,
) -> dict[str, Any]:
    try:
        from lightgbm import LGBMClassifier
        from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError('Install the research extra: pip install -e ".[crypto-ml]"') from exc

    experts = sorted(next(iter(panels)).predictions)
    symbols = sorted({panel.symbol for panel in panels})
    train = [panel for panel in panels if panel.fold_index in set(training_folds)]
    validation = [panel for panel in panels if panel.fold_index == validation_fold]
    test = [panel for panel in panels if panel.fold_index == test_fold]
    if not train or not validation or not test:
        raise ValueError("Training, validation, and test panels must all be non-empty")

    x_train = feature_matrix(train, experts=experts, symbols=symbols)
    y_train = labels(train)
    x_validation = feature_matrix(validation, experts=experts, symbols=symbols)
    x_test = feature_matrix(test, experts=experts, symbols=symbols)
    candidates = {
        "logistic_stacker": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                C=0.1,
                max_iter=3000,
                class_weight="balanced",
                random_state=random_state,
            ),
        ),
        "histogram_stacker": make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=0.03,
                max_iter=220,
                max_leaf_nodes=15,
                min_samples_leaf=60,
                l2_regularization=5.0,
                random_state=random_state,
            ),
        ),
        "extra_trees_stacker": make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=300,
                max_depth=8,
                min_samples_leaf=30,
                max_features=0.65,
                class_weight="balanced",
                n_jobs=-1,
                random_state=random_state,
            ),
        ),
        "lightgbm_stacker": make_pipeline(
            SimpleImputer(strategy="median"),
            LGBMClassifier(
                n_estimators=300,
                learning_rate=0.03,
                num_leaves=15,
                min_child_samples=60,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=1.0,
                reg_lambda=5.0,
                class_weight="balanced",
                deterministic=True,
                force_col_wise=True,
                verbosity=-1,
                n_jobs=-1,
                random_state=random_state,
            ),
        ),
    }
    validation_results = []
    fitted = {}
    for name, model in candidates.items():
        model.fit(x_train, y_train)
        fitted[name] = model
        probability = np.asarray(model.predict_proba(x_validation)[:, 1], dtype=float)
        validation_results.append(
            {
                "model": name,
                "full_coverage": prediction_summary(validation, probability),
                "frontier": confidence_frontier(validation, probability),
            }
        )
    selected_model = max(
        validation_results,
        key=lambda row: (
            float(row["full_coverage"]["wilson_low_95"] or 0.0),
            float(row["full_coverage"]["accuracy"] or 0.0),
        ),
    )
    threshold_row = max(
        selected_model["frontier"],
        key=lambda row: (
            float(row["summary"]["wilson_low_95"] or 0.0),
            float(row["summary"]["accuracy"] or 0.0),
            int(row["summary"]["signals"]),
        ),
    )
    model = fitted[str(selected_model["model"])]
    test_probability = np.asarray(model.predict_proba(x_test)[:, 1], dtype=float)
    full_test = prediction_summary(test, test_probability)
    selective_test = prediction_summary(
        test,
        test_probability,
        confidence_threshold=float(threshold_row["confidence_threshold"]),
    )
    best_expert = max(
        experts,
        key=lambda expert: _expert_summary(train, expert)["accuracy"] or 0.0,
    )
    return {
        "methodology": {
            "protocol": (
                f"Meta-model training folds {list(training_folds)}; model and confidence threshold selection "
                f"on fold {validation_fold}; one final evaluation on fold {test_fold}."
            ),
            "inputs": "Only out-of-sample base-expert predictions and causal calendar/symbol metadata.",
            "overlap_policy": "one non-overlapping forecast per symbol and horizon",
            "experts": experts,
            "symbols": symbols,
            "panels": len(panels),
        },
        "validation_candidates": validation_results,
        "selected_model": selected_model["model"],
        "selected_confidence_threshold": threshold_row["confidence_threshold"],
        "selected_validation": threshold_row["summary"],
        "final_test": {
            "full_coverage": full_test,
            "selective": selective_test,
        },
        "baselines": {
            "development_selected_expert": best_expert,
            "single_expert_test": _expert_summary(test, best_expert),
            "majority_vote_test": _majority_summary(test, experts),
        },
        "admitted_70": _admitted_70(selective_test),
    }


def feature_matrix(
    panels: Sequence[QueryPanel],
    *,
    experts: Sequence[str],
    symbols: Sequence[str],
) -> np.ndarray:
    rows = []
    for panel in panels:
        probabilities = np.asarray(
            [float(panel.predictions[expert]["probability_up"]) for expert in experts],
            dtype=float,
        )
        qualities = np.asarray(
            [float(panel.predictions[expert].get("quality_probability", 0.5)) for expert in experts],
            dtype=float,
        )
        events = np.asarray(
            [float(panel.predictions[expert].get("event_probability", 0.5)) for expert in experts],
            dtype=float,
        )
        opened = datetime.fromisoformat(panel.data_end_utc)
        rows.append(
            np.concatenate(
                (
                    probabilities,
                    qualities,
                    events,
                    np.asarray(
                        [
                            float(np.mean(probabilities)),
                            float(np.std(probabilities)),
                            float(np.min(probabilities)),
                            float(np.max(probabilities)),
                            float(np.mean(probabilities >= 0.5)),
                            math.sin(2.0 * math.pi * opened.month / 12.0),
                            math.cos(2.0 * math.pi * opened.month / 12.0),
                            math.sin(2.0 * math.pi * opened.weekday() / 7.0),
                            math.cos(2.0 * math.pi * opened.weekday() / 7.0),
                        ],
                        dtype=float,
                    ),
                    np.asarray([float(panel.symbol == symbol) for symbol in symbols], dtype=float),
                )
            )
        )
    return np.asarray(rows, dtype=float)


def labels(panels: Sequence[QueryPanel]) -> np.ndarray:
    return np.asarray([panel.actual_return_bps > 0.0 for panel in panels], dtype=int)


def confidence_frontier(
    panels: Sequence[QueryPanel],
    probability: np.ndarray,
    *,
    min_signals: int = 100,
    min_coverage: float = 0.10,
) -> list[dict[str, Any]]:
    output = []
    for threshold in np.arange(0.0, 0.451, 0.025):
        summary = prediction_summary(
            panels,
            probability,
            confidence_threshold=float(threshold),
        )
        coverage = int(summary["signals"]) / max(len(panels), 1)
        if int(summary["signals"]) < min_signals or coverage < min_coverage:
            continue
        output.append(
            {
                "confidence_threshold": float(threshold),
                "coverage": coverage,
                "summary": summary,
            }
        )
    if not output:
        raise ValueError("No confidence threshold satisfies the validation sample constraints")
    return output


def prediction_summary(
    panels: Sequence[QueryPanel],
    probability: np.ndarray,
    *,
    confidence_threshold: float = 0.0,
) -> dict[str, Any]:
    if len(panels) != len(probability):
        raise ValueError("Panel and probability lengths differ")
    selected = []
    for panel, value in zip(panels, probability, strict=True):
        if abs(float(value) - 0.5) * 2.0 < confidence_threshold:
            continue
        selected.append(
            {
                "symbol": panel.symbol,
                "fold_index": panel.fold_index,
                "direction_hit": float((float(value) >= 0.5) == (panel.actual_return_bps > 0.0)),
            }
        )
    return _summary(selected, total=len(panels))


def _expert_summary(panels: Sequence[QueryPanel], expert: str) -> dict[str, Any]:
    rows = [
        {
            "symbol": panel.symbol,
            "fold_index": panel.fold_index,
            "direction_hit": float(
                (panel.predictions[expert]["probability_up"] >= 0.5)
                == (panel.actual_return_bps > 0.0)
            ),
        }
        for panel in panels
    ]
    return _summary(rows, total=len(panels))


def _majority_summary(panels: Sequence[QueryPanel], experts: Sequence[str]) -> dict[str, Any]:
    rows = []
    for panel in panels:
        score = sum(
            1 if panel.predictions[expert]["probability_up"] >= 0.5 else -1 for expert in experts
        )
        rows.append(
            {
                "symbol": panel.symbol,
                "fold_index": panel.fold_index,
                "direction_hit": float((score >= 0) == (panel.actual_return_bps > 0.0)),
            }
        )
    return _summary(rows, total=len(panels))


def _summary(events: Sequence[Mapping[str, Any]], *, total: int) -> dict[str, Any]:
    hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in events)
    by_symbol = []
    for symbol in sorted({str(row["symbol"]) for row in events}):
        selected = [row for row in events if str(row["symbol"]) == symbol]
        symbol_hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in selected)
        by_symbol.append(
            {
                "symbol": symbol,
                "signals": len(selected),
                "hits": symbol_hits,
                "accuracy": symbol_hits / len(selected),
            }
        )
    return {
        "signals": len(events),
        "hits": hits,
        "coverage": len(events) / max(total, 1),
        "accuracy": hits / len(events) if events else None,
        "wilson_low_95": _wilson_low(hits, len(events)) if events else None,
        "by_symbol": by_symbol,
        "worst_symbol_accuracy": min((row["accuracy"] for row in by_symbol), default=None),
        "worst_symbol_signals": min((row["signals"] for row in by_symbol), default=0),
    }


def _admitted_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= 100
        and float(summary["coverage"]) >= 0.10
        and summary["accuracy"] is not None
        and float(summary["accuracy"]) >= 0.70
        and summary["wilson_low_95"] is not None
        and float(summary["wilson_low_95"]) >= 0.65
        and summary["worst_symbol_accuracy"] is not None
        and float(summary["worst_symbol_accuracy"]) >= 0.60
        and int(summary["worst_symbol_signals"]) >= 5
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    final = payload["final_test"]
    baselines = payload["baselines"]
    lines = [
        "# Out-of-Sample Crypto Stacking Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        "## Final Test",
        "",
        "| engine | signals | coverage | accuracy | Wilson low | worst symbol |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, summary in (
        (f"{payload['selected_model']} full coverage", final["full_coverage"]),
        (
            f"{payload['selected_model']} selective",
            final["selective"],
        ),
        (
            f"Single expert ({baselines['development_selected_expert']})",
            baselines["single_expert_test"],
        ),
        ("Majority vote", baselines["majority_vote_test"]),
    ):
        lines.append(
            f"| {name} | {summary['signals']} | {_rate(summary['coverage'])} | "
            f"{_rate(summary['accuracy'])} | {_rate(summary['wilson_low_95'])} | "
            f"{_rate(summary['worst_symbol_accuracy'])} |"
        )
    lines.extend(
        (
            "",
            f"- selected confidence threshold: `{payload['selected_confidence_threshold']:.3f}`;",
            f"- strict 70% admission: **{'passed' if payload['admitted_70'] else 'rejected'}**;",
            "- model and threshold were selected before the final test.",
            "",
            "## Validation Candidates",
            "",
            "| model | full accuracy | full Wilson low | best selective accuracy | selective signals |",
            "|---|---:|---:|---:|---:|",
        )
    )
    for candidate in payload["validation_candidates"]:
        best = max(
            candidate["frontier"],
            key=lambda row: (
                float(row["summary"]["wilson_low_95"] or 0.0),
                float(row["summary"]["accuracy"] or 0.0),
            ),
        )
        lines.append(
            f"| {candidate['model']} | {_rate(candidate['full_coverage']['accuracy'])} | "
            f"{_rate(candidate['full_coverage']['wilson_low_95'])} | "
            f"{_rate(best['summary']['accuracy'])} | {best['summary']['signals']} |"
        )
    return "\n".join(lines) + "\n"


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict train/validation/test stacker over out-of-sample crypto experts."
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    panels = load_query_panels(args.events)
    payload = run_stacking_benchmark(panels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
