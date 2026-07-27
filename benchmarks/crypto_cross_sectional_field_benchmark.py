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
VALIDATION_END = 1_735_689_600  # 2025-01-01
HORIZON_BARS = 6
HORIZON_SECONDS = 24 * 60 * 60
LOOKBACK_BARS = 180
MIN_ASSETS = 6
PORTFOLIO_SIDE = 2
ROUND_TRIP_COST_BPS = 20.0
MIN_FINAL_EPISODES = 300
MIN_YEAR_EPISODES = 100
MODEL_ORDER = (
    "relative_momentum",
    "relative_reversion",
    "logistic",
    "extra_trees",
    "knn",
    "wavefield",
    "field_tree_hybrid",
    "topological_wavefield",
    "topological_tree_hybrid",
)


@dataclass(frozen=True)
class CrossSectionalObservation:
    symbol: str
    timestamp: int
    target_timestamp: int
    features: tuple[float, ...]
    future_return_bps: float
    excess_return_bps: float
    outperform: bool


def build_cross_sectional_observations(
    rows: Sequence[FeatureRow],
    *,
    feature_names: Sequence[str] = BASE_FEATURES,
    horizon_seconds: int = HORIZON_SECONDS,
    min_assets: int = MIN_ASSETS,
) -> list[CrossSectionalObservation]:
    if horizon_seconds < 1:
        raise ValueError("horizon_seconds must be positive")
    if min_assets < 4:
        raise ValueError("min_assets must be at least four")
    by_timestamp: dict[int, list[FeatureRow]] = {}
    for row in rows:
        if (row.timestamp + 1) % horizon_seconds == 0:
            by_timestamp.setdefault(row.timestamp, []).append(row)

    observations: list[CrossSectionalObservation] = []
    for timestamp, market_rows in sorted(by_timestamp.items()):
        symbols = {row.symbol for row in market_rows}
        if len(symbols) < min_assets or len(symbols) != len(market_rows):
            continue
        market_return = float(
            np.median([row.future_return_bps for row in market_rows])
        )
        for row in sorted(market_rows, key=lambda item: item.symbol):
            excess = float(row.future_return_bps - market_return)
            observations.append(
                CrossSectionalObservation(
                    symbol=row.symbol,
                    timestamp=timestamp,
                    target_timestamp=row.target_timestamp,
                    features=tuple(
                        float(row.features[name]) for name in feature_names
                    ),
                    future_return_bps=float(row.future_return_bps),
                    excess_return_bps=excess,
                    outperform=excess > 0.0,
                )
            )
    return observations


def run_cross_sectional_benchmark(
    observations: Sequence[CrossSectionalObservation],
    *,
    train_end: int = TRAIN_END,
    validation_end: int = VALIDATION_END,
    seed: int = 2027,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any]:
    ordered = sorted(observations, key=lambda row: (row.timestamp, row.symbol))
    train = [row for row in ordered if row.target_timestamp < train_end]
    validation = [
        row
        for row in ordered
        if train_end <= row.timestamp and row.target_timestamp < validation_end
    ]
    final = [row for row in ordered if row.timestamp >= validation_end]
    if min(len(train), len(validation), len(final)) < 100:
        raise ValueError("train, validation, and final need at least 100 rows")

    fitted = fit_candidates(train, seed=seed)
    validation_scores = score_candidates(fitted, validation, seed=seed)
    validation_results = {
        name: summarize_ranking(validation, scores, cost_bps=cost_bps)
        for name, scores in validation_scores.items()
    }
    selected_model = max(
        MODEL_ORDER,
        key=lambda name: _selection_key(validation_results[name], name),
    )

    final_scores = score_candidates(fitted, final, seed=seed)
    final_results = {
        name: summarize_ranking(final, scores, cost_bps=cost_bps)
        for name, scores in final_scores.items()
    }
    selected_final = final_results[selected_model]
    return {
        "benchmark": "causal cross-sectional relative-strength memory",
        "methodology": {
            "target": (
                "rank each asset against the same timestamp's median future "
                "24h return"
            ),
            "sampling": "one completed UTC-day snapshot per 24h horizon",
            "train_end": _iso(train_end),
            "validation_end": _iso(validation_end),
            "selection": (
                "model family is selected on 2024 only; 2025-2026 is read "
                "once as the final temporal holdout"
            ),
            "independence": (
                "admission uses one long-short result per UTC day; correlated "
                "asset rows are not counted as independent trials"
            ),
            "portfolio": {
                "long": f"top {PORTFOLIO_SIDE} ranked assets",
                "short": f"bottom {PORTFOLIO_SIDE} ranked assets",
                "round_trip_cost_bps": cost_bps,
            },
            "models": list(MODEL_ORDER),
        },
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "final": len(final),
        },
        "episodes": {
            "train": _episode_count(train),
            "validation": _episode_count(validation),
            "final": _episode_count(final),
        },
        "selected_model": selected_model,
        "validation": validation_results,
        "final": final_results,
        "selected_final": selected_final,
        "admitted_70": ranking_admitted_70(selected_final),
    }


def fit_candidates(
    rows: Sequence[CrossSectionalObservation],
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

    matrix = np.asarray([row.features for row in rows], dtype=float)
    labels = np.asarray([row.outperform for row in rows], dtype=int)
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    normalized = scaler.fit_transform(imputer.fit_transform(matrix))
    components = min(24, len(rows) - 1, normalized.shape[1])
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


def score_candidates(
    fitted: Mapping[str, Any],
    rows: Sequence[CrossSectionalObservation],
    *,
    seed: int,
) -> dict[str, np.ndarray]:
    matrix = np.asarray([row.features for row in rows], dtype=float)
    normalized = fitted["scaler"].transform(
        fitted["imputer"].transform(matrix)
    )
    projected = fitted["pca"].transform(normalized)
    train_z = np.asarray(fitted["projected"], dtype=float)
    labels = np.asarray(fitted["labels"], dtype=int)
    tree_scores = fitted["trees"].predict_proba(projected)[:, 1]
    field_scores = _wavefield_probability(
        train_z,
        labels,
        projected,
        seed=seed,
    )
    topological_scores = _topological_wavefield_probability(
        np.asarray(fitted["normalized"], dtype=float),
        labels,
        normalized,
        seed=seed,
    )
    return {
        "relative_momentum": np.asarray(
            [_relative_feature(row, "relative_return_36") for row in rows],
            dtype=float,
        ),
        "relative_reversion": np.asarray(
            [-_relative_feature(row, "relative_return_36") for row in rows],
            dtype=float,
        ),
        "logistic": fitted["logistic"].predict_proba(projected)[:, 1],
        "extra_trees": tree_scores,
        "knn": _knn_scores(train_z, labels, projected),
        "wavefield": field_scores,
        "field_tree_hybrid": 0.5 * tree_scores + 0.5 * field_scores,
        "topological_wavefield": topological_scores,
        "topological_tree_hybrid": (
            0.5 * tree_scores + 0.5 * topological_scores
        ),
    }


def summarize_ranking(
    rows: Sequence[CrossSectionalObservation],
    scores: Sequence[float] | np.ndarray,
    *,
    cost_bps: float,
) -> dict[str, Any]:
    values = np.asarray(scores, dtype=float)
    if len(values) != len(rows):
        raise ValueError("rows and scores must align")
    by_timestamp: dict[int, list[int]] = {}
    for index, row in enumerate(rows):
        by_timestamp.setdefault(row.timestamp, []).append(index)

    episodes: list[dict[str, Any]] = []
    asset_hits = 0
    asset_total = 0
    for timestamp, indexes_list in sorted(by_timestamp.items()):
        indexes = np.asarray(indexes_list, dtype=int)
        order = indexes[np.argsort(values[indexes], kind="stable")]
        side = min(PORTFOLIO_SIDE, len(order) // 2)
        short_indexes = order[:side]
        long_indexes = order[-side:]
        gross_spread = float(
            np.mean([rows[index].future_return_bps for index in long_indexes])
            - np.mean(
                [rows[index].future_return_bps for index in short_indexes]
            )
        )
        score_ranks = _ranks(values[indexes])
        return_ranks = _ranks(
            np.asarray(
                [rows[index].future_return_bps for index in indexes],
                dtype=float,
            )
        )
        correlation = _rank_correlation(score_ranks, return_ranks)
        median_score = float(np.median(values[indexes]))
        predicted = values[indexes] > median_score
        actual = np.asarray(
            [rows[index].outperform for index in indexes],
            dtype=bool,
        )
        asset_hits += int(np.sum(predicted == actual))
        asset_total += len(indexes)
        episodes.append(
            {
                "timestamp": timestamp,
                "year": _year(timestamp),
                "gross_spread_bps": gross_spread,
                "net_spread_bps": gross_spread - cost_bps,
                "hit": gross_spread - cost_bps > 0.0,
                "rank_correlation": correlation,
                "top_asset_outperformed": bool(rows[order[-1]].outperform),
            }
        )

    hits = sum(bool(row["hit"]) for row in episodes)
    by_year = []
    for year in sorted({int(row["year"]) for row in episodes}):
        year_rows = [row for row in episodes if int(row["year"]) == year]
        year_hits = sum(bool(row["hit"]) for row in year_rows)
        by_year.append(
            {
                "year": year,
                "episodes": len(year_rows),
                "hits": year_hits,
                "spread_hit_rate": year_hits / len(year_rows),
                "mean_net_spread_bps": float(
                    np.mean([row["net_spread_bps"] for row in year_rows])
                ),
            }
        )
    supported_years = [
        row for row in by_year if int(row["episodes"]) >= MIN_YEAR_EPISODES
    ]
    return {
        "episodes": len(episodes),
        "spread_hits": hits,
        "spread_hit_rate": hits / len(episodes),
        "spread_wilson_low_95": _wilson_low(hits, len(episodes)),
        "mean_gross_spread_bps": float(
            np.mean([row["gross_spread_bps"] for row in episodes])
        ),
        "mean_net_spread_bps": float(
            np.mean([row["net_spread_bps"] for row in episodes])
        ),
        "mean_rank_correlation": float(
            np.mean([row["rank_correlation"] for row in episodes])
        ),
        "top_asset_hit_rate": float(
            np.mean([row["top_asset_outperformed"] for row in episodes])
        ),
        "asset_accuracy": asset_hits / asset_total,
        "by_year": by_year,
        "worst_supported_year_hit_rate": min(
            (
                float(row["spread_hit_rate"])
                for row in supported_years
            ),
            default=None,
        ),
    }


def ranking_admitted_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["episodes"]) >= MIN_FINAL_EPISODES
        and float(summary["spread_hit_rate"]) >= 0.70
        and float(summary["spread_wilson_low_95"]) >= 0.65
        and float(summary["worst_supported_year_hit_rate"] or 0.0) >= 0.65
        and float(summary["mean_net_spread_bps"]) > 0.0
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    selected = payload["selected_final"]
    lines = [
        "# Cross-Sectional WaveField Benchmark",
        "",
        (
            "This benchmark ranks assets by next-day relative strength. "
            "One UTC day, not one coin, is the independent evidence unit."
        ),
        "",
        "- training: completed outcomes before 2024-01-01;",
        "- model selection: 2024 only;",
        "- final temporal holdout: 2025-2026;",
        (
            f"- long top {PORTFOLIO_SIDE}, short bottom {PORTFOLIO_SIDE}, "
            f"{payload['methodology']['portfolio']['round_trip_cost_bps']:.1f} "
            "bps total cost;"
        ),
        "",
        "| model | validation spread hit | final spread hit | Wilson low | "
        "net spread | rank corr |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model in MODEL_ORDER:
        validation = payload["validation"][model]
        final = payload["final"][model]
        lines.append(
            f"| {model} | {_percent(validation['spread_hit_rate'])} | "
            f"{_percent(final['spread_hit_rate'])} | "
            f"{_percent(final['spread_wilson_low_95'])} | "
            f"{final['mean_net_spread_bps']:.1f} bps | "
            f"{final['mean_rank_correlation']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Selected on validation: `{payload['selected_model']}`.",
            "",
            (
                f"Final result: {_percent(selected['spread_hit_rate'])} "
                f"spread hit, Wilson low "
                f"{_percent(selected['spread_wilson_low_95'])}, "
                f"{selected['mean_net_spread_bps']:.1f} bps mean net spread."
            ),
            "",
            (
                "Strict 70% admission: "
                f"**{'passed' if payload['admitted_70'] else 'rejected'}**."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _knn_scores(
    train_x: np.ndarray,
    train_y: np.ndarray,
    evaluation_x: np.ndarray,
    *,
    neighbors: int = 31,
) -> np.ndarray:
    output = []
    for row in evaluation_x:
        distances = np.linalg.norm(train_x - row, axis=1)
        count = min(neighbors, len(distances))
        indexes = np.argpartition(distances, count - 1)[:count]
        weights = 1.0 / np.maximum(distances[indexes], 1e-6)
        output.append(float(np.average(train_y[indexes], weights=weights)))
    return np.asarray(output, dtype=float)


class CorrelationFieldProjector:
    def __init__(
        self,
        training: np.ndarray,
        *,
        width: int = 32,
        height: int = 16,
    ) -> None:
        matrix = np.asarray(training, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] < 2:
            raise ValueError("training must be a 2D multi-feature matrix")
        if width < 8 or height < 4 or width % 2:
            raise ValueError("field dimensions are too small")
        self.width = width
        self.height = height
        self.feature_count = matrix.shape[1]
        centered = matrix - np.mean(matrix, axis=0, keepdims=True)
        scale = np.std(centered, axis=0, keepdims=True)
        standardized = np.divide(
            centered,
            np.where(scale <= 1e-12, 1.0, scale),
            out=np.zeros_like(centered),
        )
        correlation = standardized.T @ standardized / max(len(matrix) - 1, 1)
        affinity = np.abs(correlation)
        np.fill_diagonal(affinity, 0.0)
        degree = np.sum(affinity, axis=1)
        inverse = 1.0 / np.sqrt(np.maximum(degree, 1e-9))
        normalized = inverse[:, None] * affinity * inverse[None, :]
        _, vectors = np.linalg.eigh(normalized)
        coordinates = vectors[:, -3:-1]
        self.coordinates = np.column_stack(
            (
                _scale_coordinates(coordinates[:, 0], 1, width // 2 - 2),
                _scale_coordinates(coordinates[:, 1], 1, height - 2),
            )
        ).astype(int)

    def to_pattern(self, vector: np.ndarray) -> np.ndarray:
        values = np.asarray(vector, dtype=float)
        if values.shape != (self.feature_count,):
            raise ValueError(
                f"expected {self.feature_count} features, got {values.shape}"
            )
        pattern = np.zeros((self.height, self.width), dtype=np.float32)
        half = self.width // 2
        for value, (x_base, y_base) in zip(
            np.clip(values, -4.0, 4.0),
            self.coordinates,
            strict=True,
        ):
            if value == 0.0:
                continue
            x = int(x_base + (half if value < 0.0 else 0))
            y = int(y_base)
            amplitude = float(abs(value))
            pattern[y, x] += amplitude
            pattern[y - 1, x] += amplitude * 0.35
            pattern[y + 1, x] += amplitude * 0.35
            pattern[y, x - 1] += amplitude * 0.35
            pattern[y, x + 1] += amplitude * 0.35
        norm = float(np.linalg.norm(pattern))
        if norm > 1e-12:
            pattern /= norm
        return pattern


def _topological_wavefield_probability(
    train_x: np.ndarray,
    train_y: np.ndarray,
    evaluation_x: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    projector = CorrelationFieldProjector(train_x)
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(
            width=projector.width,
            height=projector.height,
            layers=4,
            decay=0.99,
            speed=0.08,
            nonlin=0.004,
        )
        down_field = WaveField(
            width=projector.width,
            height=projector.height,
            layers=4,
            decay=0.99,
            speed=0.08,
            nonlin=0.004,
        )
        up_count = max(int(np.sum(train_y == 1)), 1)
        down_count = max(int(np.sum(train_y == 0)), 1)
        for index, (row, label) in enumerate(
            zip(train_x, train_y, strict=True)
        ):
            recency = 0.25 + 0.75 * (index + 1) / len(train_x)
            target = up_field if label else down_field
            count = up_count if label else down_count
            target.feed(
                projector.to_pattern(row),
                strength=recency * 500.0 / count,
            )
        up_field.evolve(2)
        down_field.evolve(2)
    finally:
        np.random.set_state(previous_state)

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
    evaluation_scores = orientation * _topological_field_scores(
        up_field,
        down_field,
        projector,
        evaluation_x,
    )
    z_score = np.clip((evaluation_scores - center) / scale, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z_score))


def _topological_field_scores(
    up_field: WaveField,
    down_field: WaveField,
    projector: CorrelationFieldProjector,
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


def _scale_coordinates(
    values: np.ndarray,
    minimum: int,
    maximum: int,
) -> np.ndarray:
    low = float(np.min(values))
    high = float(np.max(values))
    if high - low <= 1e-12:
        return np.full(len(values), (minimum + maximum) // 2, dtype=int)
    scaled = minimum + (values - low) * (maximum - minimum) / (high - low)
    return np.rint(scaled).astype(int)


def _relative_feature(
    row: CrossSectionalObservation,
    name: str,
) -> float:
    return float(row.features[BASE_FEATURES.index(name)])


def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    return ranks


def _rank_correlation(left: np.ndarray, right: np.ndarray) -> float:
    left_scale = float(np.std(left))
    right_scale = float(np.std(right))
    if left_scale <= 1e-12 or right_scale <= 1e-12:
        return 0.0
    return float(
        np.mean(
            ((left - np.mean(left)) / left_scale)
            * ((right - np.mean(right)) / right_scale)
        )
    )


def _selection_key(
    summary: Mapping[str, Any],
    model: str,
) -> tuple[float, float, float, float, int]:
    return (
        float(summary["spread_hit_rate"]),
        float(summary["spread_wilson_low_95"]),
        float(summary["mean_net_spread_bps"]),
        float(summary["mean_rank_correlation"]),
        -MODEL_ORDER.index(model),
    )


def _episode_count(rows: Sequence[CrossSectionalObservation]) -> int:
    return len({row.timestamp for row in rows})


def _year(timestamp: int) -> int:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _percent(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate causal cross-sectional WaveField ranking."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=ROUND_TRIP_COST_BPS,
    )
    args = parser.parse_args()

    rows_by_symbol: dict[str, list[FeatureRow]] = {}
    for path in args.bundles:
        bundle = load_bundle(path)
        rows_by_symbol[bundle.symbol] = build_feature_rows(
            bundle,
            horizon=HORIZON_BARS,
            lookback=LOOKBACK_BARS,
            include_microstructure=False,
            extended_features=True,
        )
    rows = add_multiyear_market_features(rows_by_symbol)
    observations = build_cross_sectional_observations(rows)
    payload = run_cross_sectional_benchmark(
        observations,
        cost_bps=args.cost_bps,
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
    selected = payload["selected_final"]
    print(
        f"model={payload['selected_model']} "
        f"spread_hit={_percent(selected['spread_hit_rate'])} "
        f"Wilson={_percent(selected['spread_wilson_low_95'])} "
        f"net={selected['mean_net_spread_bps']:.1f}bps "
        f"admitted={payload['admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
