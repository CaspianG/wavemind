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
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_cross_sectional_field_benchmark import (  # noqa: E402
    CorrelationFieldProjector,
    _knn_scores,
    _topological_field_scores,
    _topological_wavefield_probability,
)
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_episode_transition_benchmark import (  # noqa: E402
    _wavefield_probability,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    BASE_FEATURES,
    add_multiyear_market_features,
)
from wavemind.core import WaveField  # noqa: E402


TRAIN_END = 1_704_067_200  # 2024-01-01
CALIBRATION_END = 1_719_792_000  # 2024-07-01
VALIDATION_END = 1_735_689_600  # 2025-01-01
HORIZON_BARS = 6
HORIZON_SECONDS = 24 * 60 * 60
LOOKBACK_BARS = 180
MIN_ASSETS = 6
MIN_FINAL_EPISODES = 300
MIN_YEAR_EPISODES = 100
MODEL_ORDER = (
    "majority",
    "logistic",
    "extra_trees",
    "knn",
    "wavefield",
    "field_tree_hybrid",
    "topological_wavefield",
    "topological_tree_hybrid",
    "online_topological_wavefield",
    "online_topological_tree_hybrid",
)
TASK_ORDER = (
    "market_direction",
    "large_market_move",
    "high_cross_asset_dispersion",
)


@dataclass(frozen=True)
class MarketRegimePanel:
    timestamp: int
    target_timestamp: int
    features: tuple[float, ...]
    future_market_return_bps: float
    future_absolute_move_bps: float
    future_dispersion_bps: float


def build_market_regime_panels(
    rows: Sequence[FeatureRow],
    *,
    feature_names: Sequence[str] = BASE_FEATURES,
    horizon_seconds: int = HORIZON_SECONDS,
    min_assets: int = MIN_ASSETS,
    target_symbols: set[str] | None = None,
) -> list[MarketRegimePanel]:
    if horizon_seconds < 1:
        raise ValueError("horizon_seconds must be positive")
    if min_assets < 4:
        raise ValueError("min_assets must be at least four")
    by_timestamp: dict[int, list[FeatureRow]] = {}
    for row in rows:
        if target_symbols is not None and row.symbol not in target_symbols:
            continue
        if (row.timestamp + 1) % horizon_seconds == 0:
            by_timestamp.setdefault(row.timestamp, []).append(row)

    panels = []
    for timestamp, market_rows in sorted(by_timestamp.items()):
        if len({row.symbol for row in market_rows}) < min_assets:
            continue
        feature_matrix = np.asarray(
            [
                [float(row.features[name]) for name in feature_names]
                for row in market_rows
            ],
            dtype=float,
        )
        returns = np.asarray(
            [row.future_return_bps for row in market_rows],
            dtype=float,
        )
        aggregates = np.concatenate(
            (
                np.nanmean(feature_matrix, axis=0),
                np.nanstd(feature_matrix, axis=0),
                np.nanquantile(feature_matrix, 0.10, axis=0),
                np.nanquantile(feature_matrix, 0.90, axis=0),
            )
        )
        market_return = float(np.median(returns))
        panels.append(
            MarketRegimePanel(
                timestamp=timestamp,
                target_timestamp=max(row.target_timestamp for row in market_rows),
                features=tuple(float(value) for value in aggregates),
                future_market_return_bps=market_return,
                future_absolute_move_bps=abs(market_return),
                future_dispersion_bps=float(np.std(returns)),
            )
        )
    return panels


def run_market_regime_benchmark(
    panels: Sequence[MarketRegimePanel],
    *,
    holdout_panels: Sequence[MarketRegimePanel] | None = None,
    train_end: int = TRAIN_END,
    calibration_end: int = CALIBRATION_END,
    validation_end: int = VALIDATION_END,
    seed: int = 2027,
) -> dict[str, Any]:
    ordered = sorted(panels, key=lambda panel: panel.timestamp)
    train = [panel for panel in ordered if panel.target_timestamp < train_end]
    calibration = [
        panel
        for panel in ordered
        if train_end <= panel.timestamp
        and panel.target_timestamp < calibration_end
    ]
    validation = [
        panel
        for panel in ordered
        if calibration_end <= panel.timestamp
        and panel.target_timestamp < validation_end
    ]
    final = [panel for panel in ordered if panel.timestamp >= validation_end]
    if min(len(train), len(calibration), len(validation), len(final)) < 100:
        raise ValueError("every split needs at least 100 independent panels")
    holdout_ordered = sorted(
        holdout_panels or (),
        key=lambda panel: panel.timestamp,
    )
    holdout_post_train = [
        panel for panel in holdout_ordered if panel.timestamp >= train_end
    ]
    holdout_final = [
        panel for panel in holdout_ordered if panel.timestamp >= validation_end
    ]
    if holdout_panels is not None and len(holdout_final) < 100:
        raise ValueError("holdout final split needs at least 100 panels")

    thresholds = _target_thresholds(train)
    holdout_thresholds = (
        _target_thresholds(
            [
                panel
                for panel in holdout_ordered
                if panel.target_timestamp < train_end
            ]
        )
        if holdout_panels is not None
        else None
    )
    tasks = {}
    for task in TASK_ORDER:
        train_y = _labels(train, task, thresholds)
        fitted = fit_regime_candidates(train, train_y, seed=seed)
        post_train = calibration + validation + final
        post_train_labels = _labels(post_train, task, thresholds)
        online_probabilities = online_topological_probabilities(
            fitted,
            post_train,
            post_train_labels,
            seed=seed,
        )
        calibration_stop = len(calibration)
        validation_stop = calibration_stop + len(validation)
        calibration_probabilities = score_regime_candidates(
            fitted,
            calibration,
            seed=seed,
        )
        _add_online_candidates(
            calibration_probabilities,
            online_probabilities[:calibration_stop],
        )
        decision_thresholds = {
            model: calibrate_decision_threshold(
                _labels(calibration, task, thresholds),
                probabilities,
            )
            for model, probabilities in calibration_probabilities.items()
        }
        validation_probabilities = score_regime_candidates(
            fitted,
            validation,
            seed=seed,
        )
        _add_online_candidates(
            validation_probabilities,
            online_probabilities[calibration_stop:validation_stop],
        )
        validation_results = {
            model: summarize_binary(
                _labels(validation, task, thresholds),
                probabilities,
                timestamps=[panel.timestamp for panel in validation],
                threshold=decision_thresholds[model],
            )
            for model, probabilities in validation_probabilities.items()
        }
        selected_model = max(
            MODEL_ORDER,
            key=lambda model: _selection_key(
                validation_results[model],
                model,
            ),
        )
        final_probabilities = score_regime_candidates(
            fitted,
            final,
            seed=seed,
        )
        _add_online_candidates(
            final_probabilities,
            online_probabilities[validation_stop:],
        )
        final_results = {
            model: summarize_binary(
                _labels(final, task, thresholds),
                probabilities,
                timestamps=[panel.timestamp for panel in final],
                threshold=decision_thresholds[model],
            )
            for model, probabilities in final_probabilities.items()
        }
        selected_final = final_results[selected_model]
        holdout_result = None
        if holdout_panels is not None:
            assert holdout_thresholds is not None
            holdout_fitted = domain_adapt_fitted(
                fitted,
                [
                    panel
                    for panel in holdout_ordered
                    if panel.timestamp < train_end
                ],
            )
            holdout_probabilities = score_regime_candidates(
                holdout_fitted,
                holdout_final,
                seed=seed,
            )
            holdout_online = online_topological_probabilities(
                holdout_fitted,
                holdout_post_train,
                _labels(holdout_post_train, task, holdout_thresholds),
                seed=seed,
            )
            holdout_final_start = len(holdout_post_train) - len(holdout_final)
            _add_online_candidates(
                holdout_probabilities,
                holdout_online[holdout_final_start:],
            )
            holdout_results = {
                model: summarize_binary(
                    _labels(holdout_final, task, holdout_thresholds),
                    probabilities,
                    timestamps=[
                        panel.timestamp for panel in holdout_final
                    ],
                    threshold=decision_thresholds[model],
                )
                for model, probabilities in holdout_probabilities.items()
            }
            selected_holdout = holdout_results[selected_model]
            holdout_result = {
                "selected_model": selected_model,
                "final": holdout_results,
                "selected_final": selected_holdout,
                "raw_accuracy_uplift_vs_majority": (
                    float(selected_holdout["accuracy"])
                    - float(holdout_results["majority"]["accuracy"])
                ),
                "admitted": regime_admitted(selected_holdout),
            }
        tasks[task] = {
            "selected_model": selected_model,
            "decision_thresholds": decision_thresholds,
            "validation": validation_results,
            "final": final_results,
            "selected_final": selected_final,
            "raw_accuracy_uplift_vs_majority": (
                float(selected_final["accuracy"])
                - float(final_results["majority"]["accuracy"])
            ),
            "admitted": regime_admitted(selected_final),
            "asset_holdout": holdout_result,
        }
    return {
        "benchmark": "causal market regime predictability map",
        "methodology": {
            "source": (
                "official completed Binance USD-M 4h bars and causally "
                "available derivatives features"
            ),
            "sampling": "one independent completed UTC-day panel",
            "train_end": _iso(train_end),
            "threshold_calibration_end": _iso(calibration_end),
            "validation_end": _iso(validation_end),
            "selection": (
                "model thresholds use 2024-H1, model family uses 2024-H2, "
                "and 2025-2026 is read once"
            ),
            "targets": list(TASK_ORDER),
            "models": list(MODEL_ORDER),
        },
        "thresholds": thresholds,
        "asset_holdout_thresholds": holdout_thresholds,
        "panels": {
            "train": len(train),
            "calibration": len(calibration),
            "validation": len(validation),
            "final": len(final),
            "asset_holdout_final": len(holdout_final),
        },
        "tasks": tasks,
        "any_task_admitted": any(
            result["admitted"] for result in tasks.values()
        ),
        "any_task_cross_asset_admitted": any(
            result["admitted"]
            and result["asset_holdout"] is not None
            and result["asset_holdout"]["admitted"]
            for result in tasks.values()
        ),
    }


def fit_regime_candidates(
    panels: Sequence[MarketRegimePanel],
    labels: np.ndarray,
    *,
    seed: int,
) -> dict[str, Any]:
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
    matrix = np.asarray([panel.features for panel in panels], dtype=float)
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    normalized = scaler.fit_transform(imputer.fit_transform(matrix))
    components = min(32, len(panels) - 1, normalized.shape[1])
    pca = PCA(n_components=components, random_state=seed)
    projected = pca.fit_transform(normalized)
    logistic = LogisticRegression(
        C=0.3,
        class_weight="balanced",
        max_iter=2_000,
        random_state=seed,
    ).fit(projected, labels)
    trees = ExtraTreesClassifier(
        n_estimators=500,
        max_depth=6,
        min_samples_leaf=8,
        max_features=0.5,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1,
    ).fit(projected, labels)
    return {
        "imputer": imputer,
        "scaler": scaler,
        "pca": pca,
        "normalized": normalized,
        "projected": projected,
        "labels": labels,
        "logistic": logistic,
        "trees": trees,
    }


def score_regime_candidates(
    fitted: Mapping[str, Any],
    panels: Sequence[MarketRegimePanel],
    *,
    seed: int,
) -> dict[str, np.ndarray]:
    matrix = np.asarray([panel.features for panel in panels], dtype=float)
    normalized = fitted["scaler"].transform(
        fitted["imputer"].transform(matrix)
    )
    projected = fitted["pca"].transform(normalized)
    train_z = np.asarray(fitted["projected"], dtype=float)
    labels = np.asarray(fitted["labels"], dtype=int)
    tree_probability = fitted["trees"].predict_proba(projected)[:, 1]
    field_probability = _wavefield_probability(
        train_z,
        labels,
        projected,
        seed=seed,
    )
    topological_probability = _topological_wavefield_probability(
        np.asarray(fitted["normalized"], dtype=float),
        labels,
        normalized,
        seed=seed,
    )
    return {
        "majority": np.full(len(panels), float(np.mean(labels)), dtype=float),
        "logistic": fitted["logistic"].predict_proba(projected)[:, 1],
        "extra_trees": tree_probability,
        "knn": _knn_scores(train_z, labels, projected),
        "wavefield": field_probability,
        "field_tree_hybrid": (
            0.5 * tree_probability + 0.5 * field_probability
        ),
        "topological_wavefield": topological_probability,
        "topological_tree_hybrid": (
            0.5 * tree_probability + 0.5 * topological_probability
        ),
    }


def domain_adapt_fitted(
    fitted: Mapping[str, Any],
    reference_panels: Sequence[MarketRegimePanel],
) -> dict[str, Any]:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            'Install research dependencies with pip install -e ".[crypto-ml]"'
        ) from exc
    if len(reference_panels) < 100:
        raise ValueError("domain adaptation needs 100 historical panels")
    matrix = np.asarray(
        [panel.features for panel in reference_panels],
        dtype=float,
    )
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    scaler.fit(imputer.fit_transform(matrix))
    return dict(fitted) | {
        "imputer": imputer,
        "scaler": scaler,
    }


def online_topological_probabilities(
    fitted: Mapping[str, Any],
    panels: Sequence[MarketRegimePanel],
    labels: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    normalized = fitted["scaler"].transform(
        fitted["imputer"].transform(
            np.asarray([panel.features for panel in panels], dtype=float)
        )
    )
    train_x = np.asarray(fitted["normalized"], dtype=float)
    train_y = np.asarray(fitted["labels"], dtype=int)
    projector = CorrelationFieldProjector(train_x)
    up_field, down_field = _fit_online_fields(
        projector,
        train_x,
        train_y,
        seed=seed,
    )
    train_scores = _topological_field_scores(
        up_field,
        down_field,
        projector,
        train_x,
    )
    orientation = (
        1.0
        if float(np.mean(train_scores[train_y == 1]))
        >= float(np.mean(train_scores[train_y == 0]))
        else -1.0
    )
    oriented_train = orientation * train_scores
    center = float(np.median(oriented_train))
    scale = max(float(np.std(oriented_train)), 1e-6)

    probabilities = []
    next_feedback = 0
    previous_state = np.random.get_state()
    np.random.seed(seed + 1)
    try:
        for index, (panel, vector) in enumerate(
            zip(panels, normalized, strict=True)
        ):
            updated = False
            while (
                next_feedback < index
                and panels[next_feedback].target_timestamp < panel.timestamp
            ):
                feedback_pattern = projector.to_pattern(
                    normalized[next_feedback]
                )
                target = up_field if labels[next_feedback] else down_field
                target.feed(feedback_pattern, strength=0.40)
                next_feedback += 1
                updated = True
            if updated:
                up_field.evolve(1)
                down_field.evolve(1)
            raw_score = orientation * (
                up_field.field_resonance(projector.to_pattern(vector))
                - down_field.field_resonance(projector.to_pattern(vector))
            )
            z_score = float(np.clip((raw_score - center) / scale, -30.0, 30.0))
            probabilities.append(1.0 / (1.0 + np.exp(-z_score)))
    finally:
        np.random.set_state(previous_state)
    return np.asarray(probabilities, dtype=float)


def _fit_online_fields(
    projector: CorrelationFieldProjector,
    train_x: np.ndarray,
    train_y: np.ndarray,
    *,
    seed: int,
) -> tuple[WaveField, WaveField]:
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(
            width=projector.width,
            height=projector.height,
            layers=4,
            decay=0.995,
            speed=0.06,
            nonlin=0.003,
        )
        down_field = WaveField(
            width=projector.width,
            height=projector.height,
            layers=4,
            decay=0.995,
            speed=0.06,
            nonlin=0.003,
        )
        up_count = max(int(np.sum(train_y == 1)), 1)
        down_count = max(int(np.sum(train_y == 0)), 1)
        for index, (row, label) in enumerate(
            zip(train_x, train_y, strict=True)
        ):
            recency = 0.20 + 0.80 * (index + 1) / len(train_x)
            target = up_field if label else down_field
            count = up_count if label else down_count
            target.feed(
                projector.to_pattern(row),
                strength=recency * 500.0 / count,
            )
        up_field.evolve(2)
        down_field.evolve(2)
        return up_field, down_field
    finally:
        np.random.set_state(previous_state)


def _add_online_candidates(
    probabilities: dict[str, np.ndarray],
    online: np.ndarray,
) -> None:
    probabilities["online_topological_wavefield"] = online
    probabilities["online_topological_tree_hybrid"] = (
        0.5 * probabilities["extra_trees"] + 0.5 * online
    )


def calibrate_decision_threshold(
    labels: np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
) -> float:
    values = np.asarray(probabilities, dtype=float)
    candidates = np.unique(
        np.concatenate(
            (
                np.asarray([0.5]),
                np.quantile(values, np.linspace(0.05, 0.95, 19)),
            )
        )
    )
    return float(
        max(
            candidates,
            key=lambda threshold: (
                _balanced_accuracy(labels, values >= threshold),
                _accuracy(labels, values >= threshold),
                -abs(float(threshold) - 0.5),
            ),
        )
    )


def summarize_binary(
    labels: np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    *,
    timestamps: Sequence[int],
    threshold: float,
) -> dict[str, Any]:
    truth = np.asarray(labels, dtype=int)
    values = np.asarray(probabilities, dtype=float)
    prediction = values >= threshold
    hits = prediction == truth
    hit_count = int(np.sum(hits))
    true_positive = int(np.sum(prediction & (truth == 1)))
    false_positive = int(np.sum(prediction & (truth == 0)))
    false_negative = int(np.sum((~prediction) & (truth == 1)))
    by_year = []
    for year in sorted({_year(timestamp) for timestamp in timestamps}):
        indexes = np.asarray(
            [
                index
                for index, timestamp in enumerate(timestamps)
                if _year(timestamp) == year
            ],
            dtype=int,
        )
        by_year.append(
            {
                "year": year,
                "episodes": len(indexes),
                "accuracy": _accuracy(truth[indexes], prediction[indexes]),
                "balanced_accuracy": _balanced_accuracy(
                    truth[indexes],
                    prediction[indexes],
                ),
            }
        )
    supported_years = [
        row for row in by_year if int(row["episodes"]) >= MIN_YEAR_EPISODES
    ]
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "episodes": len(truth),
        "hits": hit_count,
        "accuracy": hit_count / len(truth),
        "wilson_low_95": _wilson_low(hit_count, len(truth)),
        "balanced_accuracy": _balanced_accuracy(truth, prediction),
        "roc_auc": _roc_auc(truth, values),
        "precision": precision,
        "recall": recall,
        "f1": 2.0 * precision * recall / max(precision + recall, 1e-12),
        "positive_rate": float(np.mean(truth)),
        "predicted_positive_rate": float(np.mean(prediction)),
        "brier_score": float(np.mean((values - truth) ** 2)),
        "decision_threshold": threshold,
        "by_year": by_year,
        "worst_supported_year_balanced_accuracy": min(
            (
                float(row["balanced_accuracy"])
                for row in supported_years
            ),
            default=None,
        ),
    }


def regime_admitted(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["episodes"]) >= MIN_FINAL_EPISODES
        and float(summary["accuracy"]) >= 0.70
        and float(summary["wilson_low_95"]) >= 0.65
        and float(summary["balanced_accuracy"]) >= 0.65
        and float(summary["roc_auc"]) >= 0.70
        and float(
            summary["worst_supported_year_balanced_accuracy"] or 0.0
        )
        >= 0.60
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Market Regime WaveField Benchmark",
        "",
        (
            "This benchmark asks whether the field predicts direction, "
            "large-move risk, or cross-asset dispersion on independent days."
        ),
        "",
        "- train: outcomes completed before 2024;",
        "- probability threshold calibration: 2024-H1;",
        "- model selection: 2024-H2;",
        "- final holdout: 2025-2026;",
        "",
        "| task | selected model | accuracy | majority | balanced accuracy | "
        "AUC | worst year balanced | admitted |",
        "|---|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for task in TASK_ORDER:
        result = payload["tasks"][task]
        final = result["selected_final"]
        majority = result["final"]["majority"]
        lines.append(
            f"| {task} | {result['selected_model']} | "
            f"{_percent(final['accuracy'])} | "
            f"{_percent(majority['accuracy'])} | "
            f"{_percent(final['balanced_accuracy'])} | "
            f"{final['roc_auc']:.3f} | "
            f"{_optional_percent(final['worst_supported_year_balanced_accuracy'])} | "
            f"{'yes' if result['admitted'] else 'no'} |"
        )
    if any(
        payload["tasks"][task]["asset_holdout"] is not None
        for task in TASK_ORDER
    ):
        lines.extend(
            [
                "",
                "## Asset-Disjoint Holdout",
                "",
                "| task | frozen model | accuracy | majority | "
                "balanced accuracy | AUC | admitted |",
                "|---|---|---:|---:|---:|---:|:---:|",
            ]
        )
        for task in TASK_ORDER:
            holdout = payload["tasks"][task]["asset_holdout"]
            if holdout is None:
                continue
            final = holdout["selected_final"]
            majority = holdout["final"]["majority"]
            lines.append(
                f"| {task} | {holdout['selected_model']} | "
                f"{_percent(final['accuracy'])} | "
                f"{_percent(majority['accuracy'])} | "
                f"{_percent(final['balanced_accuracy'])} | "
                f"{final['roc_auc']:.3f} | "
                f"{'yes' if holdout['admitted'] else 'no'} |"
            )
    lines.extend(
        [
            "",
            "## Final Model Audit",
            "",
        ]
    )
    for task in TASK_ORDER:
        lines.extend(
            [
                f"### {task}",
                "",
                "| model | accuracy | balanced accuracy | AUC | F1 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for model in MODEL_ORDER:
            row = payload["tasks"][task]["final"][model]
            lines.append(
                f"| {model} | {_percent(row['accuracy'])} | "
                f"{_percent(row['balanced_accuracy'])} | "
                f"{row['roc_auc']:.3f} | {row['f1']:.3f} |"
            )
        lines.append("")
    return "\n".join(lines)


def _labels(
    panels: Sequence[MarketRegimePanel],
    task: str,
    thresholds: Mapping[str, float],
) -> np.ndarray:
    if task == "market_direction":
        return np.asarray(
            [panel.future_market_return_bps > 0.0 for panel in panels],
            dtype=int,
        )
    if task == "large_market_move":
        threshold = thresholds["large_market_move_bps"]
        return np.asarray(
            [
                panel.future_absolute_move_bps >= threshold
                for panel in panels
            ],
            dtype=int,
        )
    if task == "high_cross_asset_dispersion":
        threshold = thresholds["high_cross_asset_dispersion_bps"]
        return np.asarray(
            [panel.future_dispersion_bps >= threshold for panel in panels],
            dtype=int,
        )
    raise ValueError(f"unknown task: {task}")


def _target_thresholds(
    panels: Sequence[MarketRegimePanel],
) -> dict[str, float]:
    if len(panels) < 100:
        raise ValueError("target thresholds need 100 historical panels")
    return {
        "large_market_move_bps": float(
            np.quantile(
                [panel.future_absolute_move_bps for panel in panels],
                0.75,
            )
        ),
        "high_cross_asset_dispersion_bps": float(
            np.quantile(
                [panel.future_dispersion_bps for panel in panels],
                0.75,
            )
        ),
    }


def _balanced_accuracy(labels: np.ndarray, prediction: np.ndarray) -> float:
    truth = np.asarray(labels, dtype=int)
    predicted = np.asarray(prediction, dtype=bool)
    positive = truth == 1
    negative = ~positive
    true_positive_rate = float(np.mean(predicted[positive])) if np.any(positive) else 0.5
    true_negative_rate = float(np.mean(~predicted[negative])) if np.any(negative) else 0.5
    return 0.5 * (true_positive_rate + true_negative_rate)


def _accuracy(labels: np.ndarray, prediction: np.ndarray) -> float:
    return float(
        np.mean(np.asarray(labels, dtype=int) == np.asarray(prediction, dtype=int))
    )


def _roc_auc(labels: np.ndarray, probabilities: np.ndarray) -> float:
    truth = np.asarray(labels, dtype=int)
    values = np.asarray(probabilities, dtype=float)
    positive = values[truth == 1]
    negative = values[truth == 0]
    if not len(positive) or not len(negative):
        return 0.5
    comparisons = positive[:, None] - negative[None, :]
    return float(
        np.mean(comparisons > 0.0) + 0.5 * np.mean(comparisons == 0.0)
    )


def _selection_key(
    summary: Mapping[str, Any],
    model: str,
) -> tuple[float, float, float, float, int]:
    return (
        float(summary["balanced_accuracy"]),
        float(summary["roc_auc"]),
        float(summary["accuracy"]),
        -float(summary["brier_score"]),
        -MODEL_ORDER.index(model),
    )


def _year(timestamp: int) -> int:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _percent(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _optional_percent(value: float | None) -> str:
    return "n/a" if value is None else _percent(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate causal WaveField market-regime prediction."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--holdout-bundles", type=Path, nargs="+")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    rows_by_symbol, _ = _load_feature_rows(args.bundles)
    rows = add_multiyear_market_features(rows_by_symbol)
    panels = build_market_regime_panels(rows)
    holdout_panels = None
    if args.holdout_bundles:
        holdout_rows_by_symbol, holdout_symbols = _load_feature_rows(
            args.holdout_bundles
        )
        if "BTCUSDT" not in holdout_rows_by_symbol:
            raise ValueError(
                "--holdout-bundles must include BTCUSDT as market context"
            )
        holdout_symbols.discard("BTCUSDT")
        holdout_rows = add_multiyear_market_features(
            holdout_rows_by_symbol
        )
        holdout_panels = build_market_regime_panels(
            holdout_rows,
            target_symbols=holdout_symbols,
        )
    payload = run_market_regime_benchmark(
        panels,
        holdout_panels=holdout_panels,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    for task in TASK_ORDER:
        result = payload["tasks"][task]
        final = result["selected_final"]
        print(
            f"{task}: model={result['selected_model']} "
            f"accuracy={_percent(final['accuracy'])} "
            f"balanced={_percent(final['balanced_accuracy'])} "
            f"auc={final['roc_auc']:.3f} admitted={result['admitted']}"
        )
    return 0


def _load_feature_rows(
    paths: Sequence[Path],
) -> tuple[dict[str, list[FeatureRow]], set[str]]:
    rows_by_symbol: dict[str, list[FeatureRow]] = {}
    symbols = set()
    for path in paths:
        bundle = load_bundle(path)
        symbols.add(bundle.symbol)
        rows_by_symbol[bundle.symbol] = build_feature_rows(
            bundle,
            horizon=HORIZON_BARS,
            lookback=LOOKBACK_BARS,
            include_microstructure=False,
            extended_features=True,
        )
    return rows_by_symbol, symbols


if __name__ == "__main__":
    raise SystemExit(main())
