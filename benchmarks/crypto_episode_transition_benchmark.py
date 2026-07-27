from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_bybit_capitulation_benchmark import (  # noqa: E402
    ANALOGUE_FEATURES,
    HORIZONS,
    _percent,
    build_analogue_feature_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_longitudinal_capitulation_benchmark import (  # noqa: E402
    load_longitudinal_dataset,
)
from benchmarks.crypto_temporal_analogue_benchmark import (  # noqa: E402
    FieldProjector,
)
from wavemind.core import WaveField  # noqa: E402


TRAIN_END = "2024-01-01"
VALIDATION_END = "2025-01-01"
RETURN_QUANTILE = 0.05
OI_QUANTILE = 0.20
MIN_FINAL_EPISODES = 40
MIN_YEAR_EPISODES = 12
PCA_COMPONENTS = 16
EXTRA_TREES_CONFIG = {
    "n_estimators": 400,
    "max_depth": 4,
    "min_samples_leaf": 5,
    "max_features": 0.5,
    "class_weight": "balanced",
}
MODEL_ORDER = (
    "majority",
    "logistic",
    "extra_trees",
    "knn",
    "wavefield",
    "field_tree_hybrid",
)
AGGREGATIONS = ("mean", "median", "q10", "q90", "std", "min", "max")
MARKET_CONTEXT_FEATURES = (
    "return_1",
    "return_3",
    "return_12",
    "oi_change_1",
    "volatility_12",
    "volatility_72",
    "position_72",
    "drawdown_72",
)


@dataclass(frozen=True)
class EpisodePanel:
    timestamp: int
    target_timestamp: int
    features: tuple[float, ...]
    future_return_bps: float
    outcome_up: bool
    selected_assets: tuple[str, ...]
    available_assets: int


def build_episode_panels(
    rows: Sequence[FeatureRow],
    *,
    horizon_bars: int,
    calibration_end: int,
    return_quantile: float = RETURN_QUANTILE,
    oi_quantile: float = OI_QUANTILE,
) -> tuple[list[EpisodePanel], dict[str, float]]:
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be positive")
    if not 0.0 < return_quantile < 0.5:
        raise ValueError("return_quantile must be between 0 and 0.5")
    if not 0.0 < oi_quantile <= 0.5:
        raise ValueError("oi_quantile must be above 0 and at most 0.5")
    calibration = [row for row in rows if row.timestamp < calibration_end]
    if not calibration:
        raise ValueError("calibration period is empty")
    _require_features(calibration)
    return_threshold = float(
        np.quantile(
            [row.features["return_12"] for row in calibration],
            return_quantile,
        )
    )
    oi_threshold = float(
        np.quantile(
            [row.features["oi_change_1"] for row in calibration],
            oi_quantile,
        )
    )
    horizon_seconds = horizon_bars * 4 * 60 * 60
    by_timestamp: dict[int, list[FeatureRow]] = {}
    for row in rows:
        if row.timestamp % horizon_seconds == 0:
            by_timestamp.setdefault(row.timestamp, []).append(row)

    panels: list[EpisodePanel] = []
    for timestamp, market_rows in sorted(by_timestamp.items()):
        selected = [
            row
            for row in market_rows
            if row.features["return_12"] <= return_threshold
            and row.features["oi_change_1"] <= oi_threshold
        ]
        if not selected:
            continue
        future_return = float(
            np.median([row.future_return_bps for row in selected])
        )
        panels.append(
            EpisodePanel(
                timestamp=timestamp,
                target_timestamp=timestamp + horizon_seconds,
                features=_panel_features(selected, market_rows),
                future_return_bps=future_return,
                outcome_up=future_return > 0.0,
                selected_assets=tuple(sorted(row.symbol for row in selected)),
                available_assets=len(market_rows),
            )
        )
    return panels, {
        "return_threshold_bps": return_threshold,
        "oi_threshold_bps": oi_threshold,
    }


def run_episode_transition_benchmark(
    rows_by_horizon: Mapping[str, Sequence[FeatureRow]],
    *,
    train_end: int = 1_704_067_200,
    validation_end: int = 1_735_689_600,
    seed: int = 2027,
) -> dict[str, Any]:
    expected = {"24h", "48h"}
    if set(rows_by_horizon) != expected:
        raise ValueError("rows_by_horizon must contain 24h and 48h")
    horizons: dict[str, Any] = {}
    for label in ("24h", "48h"):
        panels, thresholds = build_episode_panels(
            rows_by_horizon[label],
            horizon_bars=HORIZONS[label],
            calibration_end=train_end,
        )
        horizons[label] = evaluate_transition_models(
            panels,
            train_end=train_end,
            validation_end=validation_end,
            seed=seed,
        ) | {"thresholds": thresholds}
    return {
        "benchmark": "causal market-episode bounce-vs-continuation transition",
        "methodology": {
            "source": (
                "official Bybit completed 4h candles and causally aligned "
                "open interest for 24 longitudinal holdout assets"
            ),
            "event_policy": {
                "return_quantile": RETURN_QUANTILE,
                "oi_quantile": OI_QUANTILE,
                "sampling": (
                    "one globally aligned, non-overlapping market decision "
                    "per forecast horizon"
                ),
            },
            "train_end": _iso(train_end),
            "validation_end": _iso(validation_end),
            "selection": (
                "model family is selected on 2024 only; 2025-2026 is read "
                "once as the final split"
            ),
            "models": list(MODEL_ORDER),
            "dependence_control": (
                "the unit of evidence is a globally aligned market episode, "
                "not a correlated per-asset signal"
            ),
        },
        "horizons": horizons,
        "primary_24h_admitted_70": horizons["24h"]["admitted_70"],
        "all_horizons_admitted_70": all(
            result["admitted_70"] for result in horizons.values()
        ),
    }


def evaluate_transition_models(
    panels: Sequence[EpisodePanel],
    *,
    train_end: int,
    validation_end: int,
    seed: int,
) -> dict[str, Any]:
    ordered = sorted(panels, key=lambda panel: panel.timestamp)
    train = [panel for panel in ordered if panel.timestamp < train_end]
    validation = [
        panel
        for panel in ordered
        if train_end <= panel.timestamp < validation_end
    ]
    final = [panel for panel in ordered if panel.timestamp >= validation_end]
    if min(len(train), len(validation), len(final)) < 10:
        raise ValueError("train, validation, and final splits need 10 episodes")

    train_x = np.asarray([panel.features for panel in train], dtype=float)
    train_y = np.asarray([panel.outcome_up for panel in train], dtype=int)
    validation_x = np.asarray(
        [panel.features for panel in validation],
        dtype=float,
    )
    validation_y = np.asarray(
        [panel.outcome_up for panel in validation],
        dtype=int,
    )
    final_x = np.asarray([panel.features for panel in final], dtype=float)
    final_y = np.asarray([panel.outcome_up for panel in final], dtype=int)

    validation_probabilities = candidate_probabilities(
        train_x,
        train_y,
        validation_x,
        seed=seed,
    )
    validation_results = {
        name: summarize_probabilities(
            validation_y,
            probabilities,
            timestamps=[panel.timestamp for panel in validation],
        )
        for name, probabilities in validation_probabilities.items()
    }
    selected_model = max(
        MODEL_ORDER,
        key=lambda name: _selection_key(validation_results[name], name),
    )
    final_probabilities = candidate_probabilities(
        train_x,
        train_y,
        final_x,
        seed=seed,
    )
    final_results = {
        name: summarize_probabilities(
            final_y,
            probabilities,
            timestamps=[panel.timestamp for panel in final],
        )
        for name, probabilities in final_probabilities.items()
    }
    selected_final = final_results[selected_model]
    majority_final = final_results["majority"]
    uplift = float(selected_final["accuracy"]) - float(
        majority_final["accuracy"]
    )
    return {
        "episodes": {
            "train": len(train),
            "validation": len(validation),
            "final": len(final),
        },
        "selected_model": selected_model,
        "validation": validation_results,
        "final": final_results,
        "selected_final": selected_final,
        "final_uplift_vs_train_majority": uplift,
        "admitted_70": transition_admitted_70(
            selected_final,
            uplift_vs_majority=uplift,
        ),
        "final_rows": [
            {
                "timestamp": panel.timestamp,
                "timestamp_utc": _iso(panel.timestamp),
                "target_timestamp": panel.target_timestamp,
                "target_timestamp_utc": _iso(panel.target_timestamp),
                "selected_assets": list(panel.selected_assets),
                "available_assets": panel.available_assets,
                "future_return_bps": panel.future_return_bps,
                "outcome_up": panel.outcome_up,
                "selected_probability_up": float(
                    final_probabilities[selected_model][index]
                ),
                "selected_prediction_up": bool(
                    final_probabilities[selected_model][index] >= 0.5
                ),
            }
            for index, panel in enumerate(final)
        ],
    }


def candidate_probabilities(
    train_x: np.ndarray,
    train_y: np.ndarray,
    evaluation_x: np.ndarray,
    *,
    seed: int,
) -> dict[str, np.ndarray]:
    try:
        from sklearn.decomposition import PCA
        from sklearn.ensemble import ExtraTreesClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            'Install research dependencies with pip install -e ".[crypto-ml]"'
        ) from exc
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    normalized = scaler.fit_transform(imputer.fit_transform(train_x))
    evaluation_normalized = scaler.transform(imputer.transform(evaluation_x))
    components = min(PCA_COMPONENTS, len(train_x) - 1, train_x.shape[1])
    pca = PCA(n_components=components, random_state=seed)
    train_z = pca.fit_transform(normalized)
    evaluation_z = pca.transform(evaluation_normalized)

    majority = float(np.mean(train_y) >= 0.5)
    logistic = LogisticRegression(
        C=0.3,
        class_weight="balanced",
        max_iter=2_000,
        random_state=seed,
    ).fit(train_z, train_y)
    trees = ExtraTreesClassifier(
        **EXTRA_TREES_CONFIG,
        random_state=seed,
        n_jobs=-1,
    ).fit(train_z, train_y)
    tree_probability = trees.predict_proba(evaluation_z)[:, 1]
    knn_probability = _knn_probability(
        train_z,
        train_y,
        evaluation_z,
        neighbors=min(31, len(train_z)),
    )
    field_probability = _wavefield_probability(
        train_z,
        train_y,
        evaluation_z,
        seed=seed,
    )
    return {
        "majority": np.full(len(evaluation_x), majority, dtype=float),
        "logistic": logistic.predict_proba(evaluation_z)[:, 1],
        "extra_trees": tree_probability,
        "knn": knn_probability,
        "wavefield": field_probability,
        "field_tree_hybrid": (
            0.50 * tree_probability + 0.50 * field_probability
        ),
    }


def summarize_probabilities(
    labels: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    *,
    timestamps: Sequence[int],
) -> dict[str, Any]:
    truth = np.asarray(labels, dtype=int)
    probability = np.asarray(probabilities, dtype=float)
    if len(truth) != len(probability) or len(truth) != len(timestamps):
        raise ValueError("labels, probabilities, and timestamps must align")
    prediction = probability >= 0.5
    hits = prediction == truth
    by_year = []
    for year in sorted({_year(timestamp) for timestamp in timestamps}):
        indexes = [
            index
            for index, timestamp in enumerate(timestamps)
            if _year(timestamp) == year
        ]
        year_hits = int(np.sum(hits[indexes]))
        by_year.append(
            {
                "year": year,
                "episodes": len(indexes),
                "hits": year_hits,
                "accuracy": year_hits / len(indexes),
                "wilson_low_95": _wilson_low(year_hits, len(indexes)),
            }
        )
    supported_years = [
        row for row in by_year if int(row["episodes"]) >= MIN_YEAR_EPISODES
    ]
    hit_count = int(np.sum(hits))
    return {
        "episodes": len(truth),
        "hits": hit_count,
        "accuracy": hit_count / len(truth),
        "wilson_low_95": _wilson_low(hit_count, len(truth)),
        "brier_score": float(np.mean((probability - truth) ** 2)),
        "predicted_up_rate": float(np.mean(prediction)),
        "actual_up_rate": float(np.mean(truth)),
        "by_year": by_year,
        "worst_supported_year_accuracy": min(
            (float(row["accuracy"]) for row in supported_years),
            default=None,
        ),
    }


def transition_admitted_70(
    summary: Mapping[str, Any],
    *,
    uplift_vs_majority: float,
) -> bool:
    return bool(
        int(summary["episodes"]) >= MIN_FINAL_EPISODES
        and float(summary["accuracy"]) >= 0.70
        and float(summary["wilson_low_95"]) >= 0.65
        and float(summary["worst_supported_year_accuracy"] or 0.0) >= 0.65
        and uplift_vs_majority >= 0.05
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Market-Episode Transition Benchmark",
        "",
        (
            "This benchmark predicts bounce versus continuation after a "
            "cross-asset capitulation event. Evidence is counted at the "
            "globally aligned market-episode level."
        ),
        "",
        "- train: before 2024-01-01;",
        "- model selection: 2024 only;",
        "- final split: 2025-01-01 through 2026-07-27;",
        "- event thresholds: frozen from the training period;",
        "",
        (
            "| horizon | train | validation | final | selected model | "
            "final accuracy | Wilson low | majority | uplift | admitted |"
        ),
        "|---|---:|---:|---:|---|---:|---:|---:|---:|:---:|",
    ]
    for label, result in payload["horizons"].items():
        episodes = result["episodes"]
        selected = result["selected_final"]
        majority = result["final"]["majority"]
        lines.append(
            f"| {label} | {episodes['train']} | {episodes['validation']} | "
            f"{episodes['final']} | {result['selected_model']} | "
            f"{_percent(selected['accuracy'])} | "
            f"{_percent(selected['wilson_low_95'])} | "
            f"{_percent(majority['accuracy'])} | "
            f"{_percent(result['final_uplift_vs_train_majority'])} | "
            f"{'yes' if result['admitted_70'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## 24h Model Audit",
            "",
            "| model | validation accuracy | final accuracy | final Wilson | Brier |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    primary = payload["horizons"]["24h"]
    for model in MODEL_ORDER:
        validation = primary["validation"][model]
        final = primary["final"][model]
        lines.append(
            f"| {model} | {_percent(validation['accuracy'])} | "
            f"{_percent(final['accuracy'])} | "
            f"{_percent(final['wilson_low_95'])} | "
            f"{final['brier_score']:.3f} |"
        )
    lines.extend(
        [
            "",
            (
                "A 70% claim is admitted only when final support, Wilson, "
                "calendar-year stability, and uplift over the train-frozen "
                "majority baseline all pass."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _panel_features(
    selected: Sequence[FeatureRow],
    market_rows: Sequence[FeatureRow],
) -> tuple[float, ...]:
    values: list[float] = [
        float(len(selected)),
        len(selected) / len(market_rows),
    ]
    for feature in ANALOGUE_FEATURES:
        values.extend(
            _aggregate([float(row.features[feature]) for row in selected])
        )
    for feature in MARKET_CONTEXT_FEATURES:
        values.extend(
            _aggregate([float(row.features[feature]) for row in market_rows])
        )
    values.extend(
        [
            sum(row.features["return_1"] > 0.0 for row in market_rows)
            / len(market_rows),
            sum(row.features["return_12"] < 0.0 for row in market_rows)
            / len(market_rows),
        ]
    )
    return tuple(values)


def _aggregate(values: Sequence[float]) -> tuple[float, ...]:
    array = np.asarray(values, dtype=float)
    return (
        float(np.mean(array)),
        float(np.median(array)),
        float(np.quantile(array, 0.10)),
        float(np.quantile(array, 0.90)),
        float(np.std(array)),
        float(np.min(array)),
        float(np.max(array)),
    )


def _require_features(rows: Sequence[FeatureRow]) -> None:
    required = set(ANALOGUE_FEATURES)
    for row in rows:
        missing = required - set(row.features)
        if missing:
            raise ValueError(
                f"{row.symbol} is missing analogue features: "
                + ", ".join(sorted(missing))
            )


def _knn_probability(
    train_x: np.ndarray,
    train_y: np.ndarray,
    evaluation_x: np.ndarray,
    *,
    neighbors: int,
) -> np.ndarray:
    output = []
    for row in evaluation_x:
        distances = np.linalg.norm(train_x - row, axis=1)
        count = min(neighbors, len(distances))
        indexes = np.argpartition(distances, count - 1)[:count]
        weights = 1.0 / np.maximum(distances[indexes], 1e-6)
        output.append(float(np.average(train_y[indexes], weights=weights)))
    return np.asarray(output, dtype=float)


def _wavefield_probability(
    train_x: np.ndarray,
    train_y: np.ndarray,
    evaluation_x: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    projector = FieldProjector(24, 24, train_x.shape[1], seed=seed)
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(
            width=24,
            height=24,
            layers=4,
            decay=0.985,
            speed=0.12,
            nonlin=0.008,
        )
        down_field = WaveField(
            width=24,
            height=24,
            layers=4,
            decay=0.985,
            speed=0.12,
            nonlin=0.008,
        )
        for index, (row, label) in enumerate(
            zip(train_x, train_y, strict=True)
        ):
            recency = 0.20 + 0.80 * (index + 1) / len(train_x)
            target = up_field if label else down_field
            target.feed(projector.to_pattern(row), strength=3.0 * recency)
        up_field.evolve(4)
        down_field.evolve(4)
    finally:
        np.random.set_state(previous_state)

    train_scores = _field_scores(
        up_field,
        down_field,
        projector,
        train_x,
    )
    up_scores = train_scores[train_y == 1]
    down_scores = train_scores[train_y == 0]
    orientation = (
        1.0
        if float(np.mean(up_scores)) >= float(np.mean(down_scores))
        else -1.0
    )
    oriented_train = orientation * train_scores
    center = float(np.median(oriented_train))
    scale = max(float(np.std(oriented_train)), 1e-6)
    evaluation_scores = orientation * _field_scores(
        up_field,
        down_field,
        projector,
        evaluation_x,
    )
    z_score = np.clip((evaluation_scores - center) / scale, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z_score))


def _field_scores(
    up_field: WaveField,
    down_field: WaveField,
    projector: FieldProjector,
    rows: np.ndarray,
) -> np.ndarray:
    return np.asarray(
        [
            up_field.field_resonance(projector.to_pattern(row))
            - down_field.field_resonance(projector.to_pattern(row))
            for row in rows
        ],
        dtype=float,
    )


def _selection_key(
    summary: Mapping[str, Any],
    model: str,
) -> tuple[float, float, float, int]:
    return (
        float(summary["accuracy"]),
        float(summary["wilson_low_95"]),
        -float(summary["brier_score"]),
        -MODEL_ORDER.index(model),
    )


def _year(timestamp: int) -> int:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate market-episode bounce-vs-continuation models."
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    instruments, _, _ = load_longitudinal_dataset()
    rows_by_horizon = {
        label: build_analogue_feature_rows(
            instruments,
            horizon=HORIZONS[label],
        )
        for label in ("24h", "48h")
    }
    payload = run_episode_transition_benchmark(rows_by_horizon)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    primary = payload["horizons"]["24h"]
    print(
        f"24h model={primary['selected_model']} "
        f"accuracy={_percent(primary['selected_final']['accuracy'])} "
        f"Wilson={_percent(primary['selected_final']['wilson_low_95'])} "
        f"admitted={primary['admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
