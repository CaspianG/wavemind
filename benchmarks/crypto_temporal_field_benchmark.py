from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import collapse_overlapping_events, _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    INTRADAY_PATH_FEATURES,
    FeatureRow,
    _matrix,
    build_feature_rows,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    BASE_FEATURES,
    add_multiyear_market_features,
    assign_calendar_folds,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


@dataclass(frozen=True)
class TemporalFieldScale:
    name: str
    decay: float
    speed: float
    nonlin: float


DEFAULT_SCALES = (
    TemporalFieldScale("short", decay=0.90, speed=0.18, nonlin=0.012),
    TemporalFieldScale("medium", decay=0.97, speed=0.12, nonlin=0.008),
    TemporalFieldScale("long", decay=0.995, speed=0.08, nonlin=0.004),
)

DEFAULT_LAGGED_FEATURES = (
    "return_1",
    "return_3",
    "return_6",
    "return_12",
    "return_18",
    "return_36",
    "return_72",
    "return_126",
    "return_180",
    "volatility_6",
    "volatility_18",
    "volatility_36",
    "volatility_72",
    "volatility_180",
    "range_bps",
    "quote_volume_z18",
    "taker_imbalance",
    "taker_imbalance_mean6",
    "taker_imbalance_change6",
    "oi_change_1",
    "oi_change_6",
    "oi_change_36",
    "top_account_log",
    "top_position_log",
    "global_ratio_log",
    "taker_ratio_log",
    "funding_rate_bps",
    "funding_mean36_bps",
    "premium_bps",
    "premium_mean36_bps",
    "btc_return_6",
    "btc_return_36",
    "btc_return_180",
    "market_return_6_mean",
    "market_return_36_mean",
    "market_return_180_mean",
    "market_breadth_6",
    "market_breadth_36",
    "relative_return_6",
    "relative_return_36",
    "relative_return_180",
    "bull_regime",
    "high_volatility_regime",
)
DEFAULT_LAGS = (1, 2, 3, 6, 12, 18)


def run_temporal_field_benchmark(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    feature_names: Sequence[str] = BASE_FEATURES,
    calibration_timestamps: int = 1620,
    include_lightgbm: bool = False,
    random_state: int = 2027,
) -> dict[str, Any]:
    try:
        from sklearn.ensemble import ExtraTreesClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError('Install the research extra: pip install -e ".[crypto-ml]"') from exc

    model_factories: list[tuple[str, Any]] = [
        (
            "Logistic",
            lambda seed: make_pipeline(
                SimpleImputer(strategy="median"),
                StandardScaler(),
                LogisticRegression(
                    C=0.15,
                    max_iter=2500,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ),
        (
            "ExtraTrees",
            lambda seed: make_pipeline(
                SimpleImputer(strategy="median"),
                ExtraTreesClassifier(
                    n_estimators=240,
                    max_depth=10,
                    min_samples_leaf=30,
                    max_features=0.65,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=seed,
                ),
            ),
        ),
    ]
    if include_lightgbm:
        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:
            raise RuntimeError('LightGBM research requires: pip install -e ".[crypto-ml]"') from exc
        model_factories.append(
            (
                "LightGBM",
                lambda seed: make_pipeline(
                    SimpleImputer(strategy="median"),
                    LGBMClassifier(
                        n_estimators=300,
                        learning_rate=0.03,
                        num_leaves=15,
                        min_child_samples=80,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        reg_alpha=1.0,
                        reg_lambda=5.0,
                        class_weight="balanced",
                        deterministic=True,
                        force_col_wise=True,
                        verbosity=-1,
                        n_jobs=-1,
                        random_state=seed,
                    ),
                ),
            )
        )

    events: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    fold_audits: list[dict[str, Any]] = []
    folds = sorted({row.fold_index for row in rows if row.fold_index >= 0})
    for fold in folds:
        test_rows = sorted(
            (row for row in rows if row.fold_index == fold),
            key=lambda row: (row.timestamp, row.symbol),
        )
        test_start = min(row.timestamp for row in test_rows)
        history = sorted(
            (row for row in rows if row.target_timestamp < test_start),
            key=lambda row: (row.timestamp, row.symbol),
        )
        timestamps = sorted({row.timestamp for row in history})
        if len(timestamps) <= calibration_timestamps:
            raise ValueError(f"Fold {fold} has insufficient pre-test history")
        calibration_set = set(timestamps[-calibration_timestamps:])
        base_rows = [row for row in history if row.timestamp not in calibration_set]
        calibration_rows = [row for row in history if row.timestamp in calibration_set]
        calibration_times = sorted(calibration_set)
        policy_cut = calibration_times[len(calibration_times) // 2]
        calibration_rows = [row for row in calibration_rows if row.timestamp < policy_cut]
        policy_rows = [row for row in history if policy_cut <= row.timestamp < test_start]

        all_rows = sorted(
            [*history, *test_rows],
            key=lambda row: (row.symbol, row.timestamp),
        )
        temporal_features, field_names = encode_temporal_field_features(
            all_rows,
            fit_rows=base_rows,
            feature_names=feature_names,
            scales=DEFAULT_SCALES,
            seed=random_state + fold * 1009,
        )
        lag_source_features = tuple(
            name for name in DEFAULT_LAGGED_FEATURES if name in feature_names
        )
        lagged_features, lagged_names = encode_lagged_state_features(
            all_rows,
            feature_names=lag_source_features,
            lags=DEFAULT_LAGS,
        )

        def row_key(row: FeatureRow) -> tuple[str, int]:
            return row.symbol, row.timestamp

        base_temporal = np.asarray([temporal_features[row_key(row)] for row in base_rows])
        calibration_temporal = np.asarray(
            [temporal_features[row_key(row)] for row in calibration_rows]
        )
        policy_temporal = np.asarray([temporal_features[row_key(row)] for row in policy_rows])
        test_temporal = np.asarray([temporal_features[row_key(row)] for row in test_rows])
        base_lagged = np.asarray([lagged_features[row_key(row)] for row in base_rows])
        calibration_lagged = np.asarray(
            [lagged_features[row_key(row)] for row in calibration_rows]
        )
        policy_lagged = np.asarray(
            [lagged_features[row_key(row)] for row in policy_rows]
        )
        test_lagged = np.asarray([lagged_features[row_key(row)] for row in test_rows])
        matrices = {
            "base": _matrix(base_rows, feature_names),
            "calibration": _matrix(calibration_rows, feature_names),
            "policy": _matrix(policy_rows, feature_names),
            "test": _matrix(test_rows, feature_names),
        }
        temporal_matrices = {
            "base": np.column_stack((matrices["base"], base_temporal)),
            "calibration": np.column_stack(
                (matrices["calibration"], calibration_temporal)
            ),
            "policy": np.column_stack((matrices["policy"], policy_temporal)),
            "test": np.column_stack((matrices["test"], test_temporal)),
        }
        lagged_matrices = {
            "base": np.column_stack((matrices["base"], base_lagged)),
            "calibration": np.column_stack(
                (matrices["calibration"], calibration_lagged)
            ),
            "policy": np.column_stack((matrices["policy"], policy_lagged)),
            "test": np.column_stack((matrices["test"], test_lagged)),
        }
        y_base = np.asarray([row.future_return_bps > 0.0 for row in base_rows], dtype=int)
        y_calibration = np.asarray(
            [row.future_return_bps > 0.0 for row in calibration_rows], dtype=int
        )

        for model_index, (model_name, factory) in enumerate(model_factories):
            for treatment, selected_matrices in (
                ("Raw", matrices),
                ("Lagged causal state", lagged_matrices),
                ("Temporal WaveField", temporal_matrices),
            ):
                engine = f"{treatment} {model_name}"
                model = factory(random_state + fold * 101 + model_index * 17)
                model.fit(selected_matrices["base"], y_base)
                calibration_probability = _predict_probability(
                    model, selected_matrices["calibration"]
                )
                policy_probability = _predict_probability(
                    model, selected_matrices["policy"]
                )
                test_probability = _predict_probability(
                    model, selected_matrices["test"]
                )
                calibration_hits = np.asarray(
                    (calibration_probability >= 0.5) == y_calibration,
                    dtype=int,
                )
                quality_model = make_pipeline(
                    SimpleImputer(strategy="median"),
                    StandardScaler(),
                    LogisticRegression(
                        C=0.08,
                        max_iter=2000,
                        class_weight="balanced",
                        random_state=random_state + fold * 101 + model_index * 17 + 7,
                    ),
                )
                quality_model.fit(
                    _quality_matrix(
                        selected_matrices["calibration"],
                        calibration_probability,
                    ),
                    calibration_hits,
                )
                policy_quality = _predict_probability(
                    quality_model,
                    _quality_matrix(selected_matrices["policy"], policy_probability),
                )
                test_quality = _predict_probability(
                    quality_model,
                    _quality_matrix(selected_matrices["test"], test_probability),
                )
                policy_events = _events(
                    engine,
                    fold,
                    policy_rows,
                    policy_probability,
                    quality=policy_quality,
                    horizon_seconds=horizon_seconds,
                )
                threshold = _select_quality_threshold(policy_events)
                test_events = _events(
                    engine,
                    fold,
                    test_rows,
                    test_probability,
                    quality=test_quality,
                    horizon_seconds=horizon_seconds,
                )
                for event in test_events:
                    event["selected"] = bool(
                        float(event["quality_probability"]) >= threshold
                    )
                    event["policy_threshold"] = threshold
                events.extend(test_events)
                selected_policy = _independent(
                    event
                    for event in policy_events
                    if float(event["quality_probability"]) >= threshold
                )
                policies.append(
                    {
                        "engine": engine,
                        "fold_index": fold,
                        "threshold": threshold,
                        "policy_signals": len(selected_policy),
                        "policy_accuracy": _accuracy(selected_policy),
                    }
                )

        fold_audits.append(
            {
                "fold_index": fold,
                "test_start_utc": datetime.fromtimestamp(
                    test_start, tz=timezone.utc
                ).isoformat(),
                "base_rows": len(base_rows),
                "calibration_rows": len(calibration_rows),
                "policy_rows": len(policy_rows),
                "test_rows": len(test_rows),
                "temporal_feature_count": len(field_names),
                "lagged_feature_count": len(lagged_names),
            }
        )

    summaries = [
        _summarize_engine(
            engine,
            [event for event in events if event["engine"] == engine],
        )
        for engine in sorted({str(event["engine"]) for event in events})
    ]
    final_holdout = [
        _summarize_engine(
            engine,
            [
                event
                for event in events
                if event["engine"] == engine and int(event["fold_index"]) == max(folds)
            ],
        )
        for engine in sorted({str(event["engine"]) for event in events})
    ]
    return {
        "methodology": {
            "data": "Verified Binance USD-M archive, 2022-01-01 through 2026-06-30",
            "assets": sorted({row.symbol for row in rows}),
            "horizon": _horizon_label(horizon_seconds),
            "folds": "Five fixed calendar half-years from 2024-H1 through 2026-H1",
            "field": (
                "Three causal wavemind.core.WaveField reservoirs per asset. "
                "Each test state depends only on completed current/past features; "
                "target labels are never fed into the reservoirs."
            ),
            "scales": [asdict(scale) for scale in DEFAULT_SCALES],
            "raw_feature_count": len(feature_names),
            "lagged_source_features": list(lag_source_features),
            "lags": list(DEFAULT_LAGS),
            "lightgbm": include_lightgbm,
            "nested_selection": (
                "Models fit on pre-calibration history, isotonic calibration uses "
                "the first half of the trailing calibration window, and confidence "
                "thresholds use its second half. Test labels select nothing."
            ),
        },
        "fold_audits": fold_audits,
        "policies": policies,
        "summaries": summaries,
        "final_holdout_2026_h1": final_holdout,
        "admitted_70": [
            summary["engine"] for summary in summaries if _admitted(summary, 0.70)
        ],
        "events": events,
    }


def encode_lagged_state_features(
    rows: Sequence[FeatureRow],
    *,
    feature_names: Sequence[str],
    lags: Sequence[int] = DEFAULT_LAGS,
) -> tuple[dict[tuple[str, int], np.ndarray], tuple[str, ...]]:
    if not feature_names:
        raise ValueError("feature_names cannot be empty")
    if not lags or any(int(lag) <= 0 for lag in lags):
        raise ValueError("lags must contain positive integers")
    ordered_lags = tuple(dict.fromkeys(int(lag) for lag in lags))
    output: dict[tuple[str, int], np.ndarray] = {}
    by_symbol: dict[str, list[FeatureRow]] = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    for symbol, symbol_rows in sorted(by_symbol.items()):
        ordered = sorted(symbol_rows, key=lambda row: row.timestamp)
        matrix = _matrix(ordered, feature_names)
        for index, row in enumerate(ordered):
            values = []
            for lag in ordered_lags:
                if index >= lag:
                    values.extend(matrix[index - lag].astype(float).tolist())
                else:
                    values.extend([math.nan] * len(feature_names))
            output[(symbol, row.timestamp)] = np.asarray(values, dtype=np.float32)
    names = tuple(
        f"lag_{lag}_{feature}"
        for lag in ordered_lags
        for feature in feature_names
    )
    return output, names


def encode_temporal_field_features(
    rows: Sequence[FeatureRow],
    *,
    fit_rows: Sequence[FeatureRow],
    feature_names: Sequence[str],
    scales: Sequence[TemporalFieldScale] = DEFAULT_SCALES,
    seed: int = 2027,
    width: int = 16,
    height: int = 16,
    layers: int = 3,
    pool_size: int = 4,
) -> tuple[dict[tuple[str, int], np.ndarray], tuple[str, ...]]:
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    if width % pool_size or height % pool_size:
        raise ValueError("Field dimensions must be divisible by pool_size")
    if not fit_rows:
        raise ValueError("fit_rows cannot be empty")
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    imputer.fit(_matrix(fit_rows, feature_names))
    scaler.fit(imputer.transform(_matrix(fit_rows, feature_names)))
    projector = FieldProjector(width, height, len(feature_names), seed=seed)
    output: dict[tuple[str, int], np.ndarray] = {}
    by_symbol: dict[str, list[FeatureRow]] = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, []).append(row)

    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        for symbol_index, (symbol, symbol_rows) in enumerate(sorted(by_symbol.items())):
            fields = [
                WaveField(
                    width=width,
                    height=height,
                    layers=layers,
                    decay=scale.decay,
                    speed=scale.speed,
                    nonlin=scale.nonlin,
                    max_amplitude=50.0,
                )
                for scale in scales
            ]
            ordered = sorted(symbol_rows, key=lambda row: row.timestamp)
            matrix = scaler.transform(imputer.transform(_matrix(ordered, feature_names)))
            for row_index, (row, vector) in enumerate(zip(ordered, matrix, strict=True)):
                pattern = projector.to_pattern(vector)
                features = []
                for scale_index, field in enumerate(fields):
                    pre_resonance = field.field_resonance(pattern)
                    pre_energy = np.log1p(field.energy() / (width * height * layers))
                    field.feed(pattern, strength=0.35)
                    field.evolve(1)
                    magnitude = np.sum(np.abs(field.state), axis=2)
                    norm = max(float(np.linalg.norm(magnitude)), 1e-9)
                    normalized = magnitude / norm
                    pooled = normalized.reshape(
                        height // pool_size,
                        pool_size,
                        width // pool_size,
                        pool_size,
                    ).mean(axis=(1, 3))
                    features.extend(
                        (
                            float(pre_resonance),
                            float(pre_energy),
                            float(1.0 - pre_resonance),
                            *pooled.reshape(-1).astype(float).tolist(),
                        )
                    )
                output[(symbol, row.timestamp)] = np.asarray(features, dtype=np.float32)
                if row_index % 256 == 0:
                    for field in fields:
                        np.clip(
                            field.state,
                            -field.max_amplitude,
                            field.max_amplitude,
                            out=field.state,
                        )
            del fields
            np.random.seed(seed + symbol_index + 1)
    finally:
        np.random.set_state(previous_state)

    names = []
    pooled_count = (height // pool_size) * (width // pool_size)
    for scale in scales:
        names.extend(
            (
                f"temporal_{scale.name}_resonance",
                f"temporal_{scale.name}_energy",
                f"temporal_{scale.name}_novelty",
            )
        )
        names.extend(
            f"temporal_{scale.name}_pool_{index}" for index in range(pooled_count)
        )
    return output, tuple(names)


def _events(
    engine: str,
    fold: int,
    rows: Sequence[FeatureRow],
    probabilities: Sequence[float],
    *,
    quality: Sequence[float] | None = None,
    horizon_seconds: int,
) -> list[dict[str, Any]]:
    output = []
    quality_values = (
        np.asarray(quality, dtype=float)
        if quality is not None
        else np.abs(np.asarray(probabilities, dtype=float) - 0.5) * 2.0
    )
    for row, probability, quality_probability in zip(
        rows, probabilities, quality_values, strict=True
    ):
        predicted_up = float(probability) >= 0.5
        actual_up = row.future_return_bps > 0.0
        margin = abs(float(probability) - 0.5) * 2.0
        output.append(
            {
                "engine": engine,
                "symbol": row.symbol,
                "timeframe": "4h",
                "fold_index": fold,
                "query_id": f"{row.symbol}-{row.timestamp}",
                "data_end_utc": datetime.fromtimestamp(
                    row.timestamp, tz=timezone.utc
                ).isoformat(),
                "target_end_utc": datetime.fromtimestamp(
                    min(row.target_timestamp, row.timestamp + horizon_seconds),
                    tz=timezone.utc,
                ).isoformat(),
                "probability_up": float(probability),
                "probability_margin": float(margin),
                "quality_probability": float(quality_probability),
                "actual_return_bps": float(row.future_return_bps),
                "direction_hit": float(predicted_up == actual_up),
            }
        )
    return output


def _select_quality_threshold(events: Sequence[Mapping[str, Any]]) -> float:
    best: tuple[float, float, int, float] | None = None
    for threshold in np.arange(0.0, 0.951, 0.025):
        selected = _independent(
            event
            for event in events
            if float(event["quality_probability"]) >= float(threshold)
        )
        if len(selected) < 40:
            continue
        hits = sum(int(event["direction_hit"]) for event in selected)
        candidate = (
            _wilson_low(hits, len(selected)),
            hits / len(selected),
            len(selected),
            float(threshold),
        )
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    return best[3] if best is not None else 1.0


def _quality_matrix(matrix: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    values = np.asarray(probabilities, dtype=float)
    return np.column_stack(
        (
            matrix,
            values,
            np.abs(values - 0.5) * 2.0,
            values * (1.0 - values),
        )
    )


def _predict_probability(model: Any, matrix: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names",
            category=UserWarning,
        )
        return np.asarray(model.predict_proba(matrix)[:, 1], dtype=float)


def _summarize_engine(
    engine: str,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    all_events = _independent(events)
    selected = _independent(event for event in events if event.get("selected"))
    return {
        "engine": engine,
        "all": _summary(all_events),
        "selected": _summary(selected),
    }


def _summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(event) for event in events]
    hits = sum(int(row["direction_hit"]) for row in rows)
    by_fold = _group_accuracy(rows, "fold_index")
    by_symbol = _group_accuracy(rows, "symbol")
    return {
        "signals": len(rows),
        "hits": hits,
        "accuracy": hits / len(rows) if rows else None,
        "wilson_low_95": _wilson_low(hits, len(rows)) if rows else None,
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "worst_fold_accuracy": min(
            (row["accuracy"] for row in by_fold), default=None
        ),
        "worst_symbol_accuracy": min(
            (row["accuracy"] for row in by_symbol), default=None
        ),
    }


def _group_accuracy(
    events: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    output = []
    for value in sorted({str(event[field]) for event in events}):
        selected = [event for event in events if str(event[field]) == value]
        output.append(
            {
                field: value,
                "signals": len(selected),
                "accuracy": _accuracy(selected),
            }
        )
    return output


def _admitted(summary: Mapping[str, Any], target: float) -> bool:
    selected = summary["selected"]
    accuracy = selected["accuracy"]
    return bool(
        accuracy is not None
        and float(accuracy) >= target
        and int(selected["signals"]) >= 40
        and float(selected["wilson_low_95"]) >= 0.65
        and selected["worst_fold_accuracy"] is not None
        and float(selected["worst_fold_accuracy"]) >= 0.65
        and selected["worst_symbol_accuracy"] is not None
        and float(selected["worst_symbol_accuracy"]) >= 0.65
    )


def _independent(
    events: Sequence[Mapping[str, Any]] | Any,
) -> list[dict[str, Any]]:
    return collapse_overlapping_events(dict(event) for event in events)


def _accuracy(events: Sequence[Mapping[str, Any]]) -> float | None:
    if not events:
        return None
    return float(np.mean([float(event["direction_hit"]) for event in events]))


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Causal Temporal State Benchmark",
        "",
        "Raw snapshots, explicit lagged state, and a multi-timescale WaveField reservoir are compared under the same causal protocol.",
        "",
        f"- horizon: {payload['methodology']['horizon']};",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        f"- admitted at 70%: {', '.join(payload['admitted_70']) or 'none'}.",
        "",
        "## Results",
        "",
        "| engine | all signals | all accuracy | selected signals | selected accuracy | Wilson low | worst fold | worst asset | 2026-H1 selected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    final_by_engine = {
        row["engine"]: row for row in payload["final_holdout_2026_h1"]
    }
    for row in payload["summaries"]:
        all_summary = row["all"]
        selected = row["selected"]
        final = final_by_engine[row["engine"]]["selected"]
        lines.append(
            "| {engine} | {all_n} | {all_acc} | {selected_n} | {selected_acc} | "
            "{wilson} | {worst_fold} | {worst_symbol} | {final_acc} |".format(
                engine=row["engine"],
                all_n=all_summary["signals"],
                all_acc=_percent(all_summary["accuracy"]),
                selected_n=selected["signals"],
                selected_acc=_percent(selected["accuracy"]),
                wilson=_percent(selected["wilson_low_95"]),
                worst_fold=_percent(selected["worst_fold_accuracy"]),
                worst_symbol=_percent(selected["worst_symbol_accuracy"]),
                final_acc=_percent(final["accuracy"]),
            )
        )
    lines.extend(
        (
            "",
            "## Admission Rule",
            "",
            "A 70% claim requires at least 40 independent selected signals, Wilson "
            "low >=65%, and every fold and asset slice >=65%. Thresholds are chosen "
            "only from pre-test policy data.",
            "",
        )
    )
    return "\n".join(lines)


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def _horizon_label(horizon_seconds: int) -> str:
    hours = horizon_seconds / 3600.0
    if hours % 24 == 0:
        days = int(hours // 24)
        return "24h" if days == 1 else f"{days}d"
    return f"{hours:g}h"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Causal multi-timescale temporal WaveField benchmark."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--include-intraday", action="store_true")
    parser.add_argument("--include-lightgbm", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()

    rows_by_symbol = {}
    data_audit = []
    for path in args.bundles:
        bundle = load_bundle(path)
        rows_by_symbol[bundle.symbol] = build_feature_rows(
            bundle,
            horizon=args.horizon_bars,
            lookback=180,
            include_microstructure=False,
            include_intraday=args.include_intraday,
            extended_features=True,
        )
        data_audit.append(
            {
                "symbol": bundle.symbol,
                "bars": len(bundle.bars),
                "metrics": len(bundle.metrics),
                "funding": len(bundle.funding),
                "premium": len(bundle.premium),
                "intraday_bars": len(bundle.intraday_bars),
                "missing_required_sources": len(bundle.missing_source_files),
            }
        )
        del bundle
    rows = assign_calendar_folds(add_multiyear_market_features(rows_by_symbol))
    feature_names = (
        BASE_FEATURES + INTRADAY_PATH_FEATURES
        if args.include_intraday
        else BASE_FEATURES
    )
    payload = run_temporal_field_benchmark(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        feature_names=feature_names,
        include_lightgbm=args.include_lightgbm,
    )
    payload["data_audit"] = data_audit
    events = payload.pop("events")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in events)
            + "\n",
            encoding="utf-8",
        )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
