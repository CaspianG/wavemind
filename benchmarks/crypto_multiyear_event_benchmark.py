from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
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
    CROSS_ASSET_FEATURES,
    DERIVATIVE_FEATURES,
    EXTENDED_DERIVATIVE_FEATURES,
    EXTENDED_PRICE_FEATURES,
    PRICE_FEATURES,
    FeatureRow,
    _matrix,
    add_cross_asset_features,
    build_feature_rows,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


MARKET_FEATURES = (
    "btc_return_36",
    "btc_return_180",
    "btc_volatility_36",
    "btc_volatility_180",
    "btc_oi_change_36",
    "btc_funding_mean36_bps",
    "market_return_36_mean",
    "market_return_180_mean",
    "market_volatility_36_mean",
    "market_dispersion_6",
    "market_dispersion_36",
    "market_breadth_6",
    "market_breadth_36",
    "relative_return_6",
    "relative_return_36",
    "relative_return_180",
    "trend_alignment_6_36",
    "trend_alignment_36_180",
    "btc_trend_alignment_36",
    "funding_trend_interaction",
    "oi_trend_interaction",
    "global_crowding_trend_interaction",
    "taker_crowding_trend_interaction",
    "premium_trend_interaction",
    "breadth_trend_interaction",
    "volatility_ratio_6_180",
    "volatility_ratio_36_180",
    "market_dispersion_ratio",
    "bull_regime",
    "high_volatility_regime",
    "positive_breadth_regime",
)

BASE_FEATURES = (
    PRICE_FEATURES
    + EXTENDED_PRICE_FEATURES
    + DERIVATIVE_FEATURES
    + EXTENDED_DERIVATIVE_FEATURES
    + CROSS_ASSET_FEATURES
    + MARKET_FEATURES
)

def add_multiyear_market_features(
    rows_by_symbol: Mapping[str, Sequence[FeatureRow]],
) -> list[FeatureRow]:
    base_rows = add_cross_asset_features(rows_by_symbol)
    by_timestamp: dict[int, list[FeatureRow]] = {}
    for row in base_rows:
        by_timestamp.setdefault(row.timestamp, []).append(row)

    output: list[FeatureRow] = []
    for timestamp, market in sorted(by_timestamp.items()):
        by_symbol = {row.symbol: row for row in market}
        btc = by_symbol.get("BTCUSDT")
        if btc is None or len(market) < 2:
            continue
        returns_6 = np.asarray([row.features["return_6"] for row in market], dtype=float)
        returns_36 = np.asarray([row.features["return_36"] for row in market], dtype=float)
        returns_180 = np.asarray([row.features["return_180"] for row in market], dtype=float)
        volatility_36 = np.asarray([row.features["volatility_36"] for row in market], dtype=float)
        market_values = {
            "btc_return_36": float(btc.features["return_36"]),
            "btc_return_180": float(btc.features["return_180"]),
            "btc_volatility_36": float(btc.features["volatility_36"]),
            "btc_volatility_180": float(btc.features["volatility_180"]),
            "btc_oi_change_36": float(btc.features["oi_change_36"]),
            "btc_funding_mean36_bps": float(btc.features["funding_mean36_bps"]),
            "market_return_36_mean": float(np.mean(returns_36)),
            "market_return_180_mean": float(np.mean(returns_180)),
            "market_volatility_36_mean": float(np.mean(volatility_36)),
            "market_dispersion_6": float(np.std(returns_6)),
            "market_dispersion_36": float(np.std(returns_36)),
            "market_breadth_6": float(np.mean(returns_6 > 0.0)),
            "market_breadth_36": float(np.mean(returns_36 > 0.0)),
        }
        for row in market:
            features = row.features
            additions = market_values | {
                "relative_return_6": float(features["return_6"] - np.mean(returns_6)),
                "relative_return_36": float(features["return_36"] - np.mean(returns_36)),
                "relative_return_180": float(features["return_180"] - np.mean(returns_180)),
                "trend_alignment_6_36": float(
                    features["return_6"] * features["return_36"] / 10_000.0
                ),
                "trend_alignment_36_180": float(
                    features["return_36"] * features["return_180"] / 10_000.0
                ),
                "btc_trend_alignment_36": float(
                    features["return_36"] * btc.features["return_36"] / 10_000.0
                ),
                "funding_trend_interaction": float(
                    features["funding_mean36_bps"] * features["return_36"] / 100.0
                ),
                "oi_trend_interaction": float(
                    features["oi_change_36"] * features["return_36"] / 10_000.0
                ),
                "global_crowding_trend_interaction": float(
                    features["global_ratio_log"] * features["return_36"]
                ),
                "taker_crowding_trend_interaction": float(
                    features["taker_ratio_change6"] * features["return_6"]
                ),
                "premium_trend_interaction": float(
                    features["premium_mean36_bps"] * features["return_36"] / 100.0
                ),
                "breadth_trend_interaction": float(
                    market_values["market_breadth_36"] * features["return_36"]
                ),
                "volatility_ratio_6_180": float(
                    features["volatility_6"] / max(features["volatility_180"], 1e-9)
                ),
                "volatility_ratio_36_180": float(
                    features["volatility_36"] / max(features["volatility_180"], 1e-9)
                ),
                "market_dispersion_ratio": float(
                    market_values["market_dispersion_6"]
                    / max(market_values["market_dispersion_36"], 1e-9)
                ),
                "bull_regime": float(btc.features["return_180"] > 0.0),
                "high_volatility_regime": float(
                    btc.features["volatility_36"] > btc.features["volatility_180"]
                ),
                "positive_breadth_regime": float(
                    market_values["market_breadth_36"] >= 0.5
                ),
            }
            output.append(
                FeatureRow(**(asdict(row) | {"features": dict(features) | additions}))
            )
    return output


def assign_calendar_folds(
    rows: Sequence[FeatureRow],
    *,
    boundaries: Sequence[tuple[str, str]] = (
        ("2024-01-01", "2024-07-01"),
        ("2024-07-01", "2025-01-01"),
        ("2025-01-01", "2025-07-01"),
        ("2025-07-01", "2026-01-01"),
        ("2026-01-01", "2026-07-01"),
    ),
) -> list[FeatureRow]:
    intervals = [(_timestamp(start), _timestamp(end)) for start, end in boundaries]
    output = []
    for row in rows:
        fold = next(
            (index for index, (start, end) in enumerate(intervals) if start <= row.timestamp < end),
            -1,
        )
        output.append(FeatureRow(**(asdict(row) | {"fold_index": fold})))
    return output


def run_multiyear_benchmark(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    calibration_timestamps: int = 1620,
    random_state: int = 2027,
) -> dict[str, Any]:
    try:
        from sklearn.ensemble import (
            ExtraTreesClassifier,
            ExtraTreesRegressor,
            HistGradientBoostingClassifier,
        )
        from sklearn.impute import SimpleImputer
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError('Install the research extra: pip install -e ".[crypto-ml]"') from exc

    symbols = sorted({row.symbol for row in rows})
    feature_names = BASE_FEATURES
    events: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []

    for fold in sorted({row.fold_index for row in rows if row.fold_index >= 0}):
        test_rows = [row for row in rows if row.fold_index == fold]
        test_start = min(row.timestamp for row in test_rows)
        history = [row for row in rows if row.target_timestamp < test_start]
        timestamps = sorted({row.timestamp for row in history})
        if len(timestamps) <= calibration_timestamps:
            raise ValueError(f"Fold {fold} has insufficient pre-test history")
        calibration_set = set(timestamps[-calibration_timestamps:])
        base_rows = [row for row in history if row.timestamp not in calibration_set]
        calibration_rows = [row for row in history if row.timestamp in calibration_set]
        calibration_times = sorted(calibration_set)
        first_cut = calibration_times[len(calibration_times) // 3]
        second_cut = calibration_times[2 * len(calibration_times) // 3]
        reliability_rows = [row for row in calibration_rows if row.timestamp < first_cut]
        probability_rows = [row for row in calibration_rows if first_cut <= row.timestamp < second_cut]
        policy_rows = [row for row in calibration_rows if row.timestamp >= second_cut]

        x_base = _matrix(base_rows, feature_names)
        y_base_return = np.asarray([row.future_return_bps for row in base_rows], dtype=float)
        y_base = np.asarray(y_base_return > 0.0, dtype=int)
        models = (
            make_pipeline(
                SimpleImputer(strategy="median"),
                StandardScaler(),
                LogisticRegression(C=0.2, max_iter=2000, class_weight="balanced", random_state=random_state),
            ),
            make_pipeline(
                SimpleImputer(strategy="median"),
                HistGradientBoostingClassifier(
                    learning_rate=0.035,
                    max_iter=160,
                    max_leaf_nodes=15,
                    min_samples_leaf=60,
                    l2_regularization=4.0,
                    random_state=random_state,
                ),
            ),
            make_pipeline(
                SimpleImputer(strategy="median"),
                ExtraTreesClassifier(
                    n_estimators=180,
                    max_depth=10,
                    min_samples_leaf=30,
                    max_features=0.65,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=random_state,
                ),
            ),
        )
        for model in models:
            model.fit(x_base, y_base)
        move_threshold = float(np.quantile(np.abs(y_base_return), 0.70))
        event_model = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=160,
                max_depth=9,
                min_samples_leaf=35,
                max_features=0.7,
                class_weight="balanced",
                n_jobs=-1,
                random_state=random_state + 11,
            ),
        ).fit(x_base, np.asarray(np.abs(y_base_return) >= move_threshold, dtype=int))
        return_model = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesRegressor(
                n_estimators=160,
                max_depth=10,
                min_samples_leaf=30,
                max_features=0.65,
                n_jobs=-1,
                random_state=random_state + 23,
            ),
        ).fit(
            x_base,
            np.clip(
                y_base_return,
                np.quantile(y_base_return, 0.01),
                np.quantile(y_base_return, 0.99),
            ),
        )

        prediction_sets = {}
        return_scale = max(float(np.median(np.abs(y_base_return))), 1.0)
        for name, selected in (
            ("reliability", reliability_rows),
            ("probability", probability_rows),
            ("policy", policy_rows),
            ("test", test_rows),
        ):
            x = _matrix(selected, feature_names)
            expert = np.column_stack([model.predict_proba(x)[:, 1] for model in models])
            ensemble = expert @ np.asarray([0.20, 0.35, 0.45])
            event_probability = event_model.predict_proba(x)[:, 1]
            return_prediction = np.asarray(return_model.predict(x), dtype=float)
            return_probability = 1.0 / (
                1.0 + np.exp(-np.clip(return_prediction / return_scale, -30.0, 30.0))
            )
            momentum_6 = _heuristic_probability(selected, "return_6", scale=500.0)
            momentum_36 = _heuristic_probability(selected, "return_36", scale=1000.0)
            candidates = np.column_stack(
                (
                    expert,
                    ensemble,
                    return_probability,
                    momentum_6,
                    momentum_36,
                    1.0 - momentum_6,
                    1.0 - momentum_36,
                )
            )
            prediction_sets[name] = {
                "rows": selected,
                "x": x,
                "expert": expert,
                "ensemble": ensemble,
                "event": event_probability,
                "return": return_prediction,
                "candidates": candidates,
            }

        for prediction in prediction_sets.values():
            prediction["direction"] = np.asarray(prediction["expert"][:, 0], dtype=float)

        field_scores = _wavefield_reliability_scores(
            prediction_sets["reliability"],
            (prediction_sets["probability"], prediction_sets["policy"], prediction_sets["test"]),
            feature_names=feature_names,
            seed=random_state + fold * 101,
        )
        probability_quality = _quality_features(prediction_sets["probability"], field_scores[1])
        probability_hits = _direction_hits(prediction_sets["probability"])
        quality_model = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=220,
                max_depth=8,
                min_samples_leaf=18,
                max_features=0.7,
                class_weight="balanced",
                n_jobs=-1,
                random_state=random_state + 37,
            ),
        ).fit(probability_quality, probability_hits)

        policy_raw = quality_model.predict_proba(
            _quality_features(prediction_sets["policy"], field_scores[2])
        )[:, 1]
        policy_times = sorted({row.timestamp for row in policy_rows})
        policy_cut = policy_times[len(policy_times) // 2]
        probability_indices = np.asarray(
            [row.timestamp < policy_cut for row in policy_rows], dtype=bool
        )
        selection_indices = ~probability_indices
        policy_hits = _direction_hits(prediction_sets["policy"])
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
            policy_raw[probability_indices],
            policy_hits[probability_indices],
        )
        policy_quality = calibrator.predict(policy_raw)
        test_quality = calibrator.predict(
            quality_model.predict_proba(
                _quality_features(prediction_sets["test"], field_scores[3])
            )[:, 1]
        )
        policy_margin = np.abs(np.asarray(prediction_sets["policy"]["direction"]) - 0.5) * 2.0
        test_margin = np.abs(np.asarray(prediction_sets["test"]["direction"]) - 0.5) * 2.0
        score_sets = {
            "Static directional baseline": (
                np.ones(len(policy_rows), dtype=float),
                np.ones(len(test_rows), dtype=float),
            ),
            "Event-probability gate": (
                np.asarray(prediction_sets["policy"]["event"], dtype=float),
                np.asarray(prediction_sets["test"]["event"], dtype=float),
            ),
            "Direction-margin gate": (policy_margin, test_margin),
            "Direct WaveField regime gate": (field_scores[2], field_scores[3]),
            "Calibrated WaveField meta gate": (policy_quality, test_quality),
        }
        for engine, (policy_score, test_score) in score_sets.items():
            policy_events = _events_for_set(
                engine,
                fold,
                prediction_sets["policy"],
                policy_score,
                horizon_seconds=horizon_seconds,
            )
            selection_events = [
                event
                for event, selected in zip(policy_events, selection_indices, strict=True)
                if selected
            ]
            threshold = _select_policy_threshold(selection_events)
            fold_events = _events_for_set(
                engine,
                fold,
                prediction_sets["test"],
                test_score,
                horizon_seconds=horizon_seconds,
            )
            for event in fold_events:
                event["selected"] = bool(float(event["quality_probability"]) >= threshold)
                event["policy_threshold"] = threshold
            events.extend(fold_events)
            policy_selected = _independent_selected(selection_events, threshold)
            policies.append(
                {
                    "engine": engine,
                    "fold_index": fold,
                    "test_start_utc": datetime.fromtimestamp(test_start, tz=timezone.utc).isoformat(),
                    "base_rows": len(base_rows),
                    "reliability_rows": len(reliability_rows),
                    "probability_rows": len(probability_rows),
                    "policy_rows": len(policy_rows),
                    "threshold": threshold,
                    "policy_effective_signals": len(policy_selected),
                    "policy_accuracy": _accuracy(policy_selected),
                }
            )

    summaries = [
        {"engine": engine} | _summarize_selected([event for event in events if event["engine"] == engine])
        for engine in sorted({str(event["engine"]) for event in events})
    ]
    holdout = [
        {"engine": summary["engine"]}
        | _summarize_selected(
            [
                event
                for event in events
                if int(event["fold_index"]) == 4 and event["engine"] == summary["engine"]
            ]
        )
        for summary in summaries
    ]
    return {
        "methodology": {
            "data": "Verified Binance USD-M archive, 2022-01-01 through 2026-06-30",
            "assets": symbols,
            "horizon": _horizon_label(horizon_seconds),
            "folds": "Five fixed calendar half-years from 2024-H1 through 2026-H1",
            "nested_policy": (
                "For each fold, the preceding 180 days are split chronologically into reliability training, "
                "probability calibration, and policy selection. Test labels never select the threshold."
            ),
            "field": "Actual wavemind.core.WaveField correct-vs-wrong regime memory",
            "feature_count": len(feature_names),
        },
        "policies": policies,
        "summaries": summaries,
        "final_holdout_2026_h1": holdout,
        "admitted_75": [summary["engine"] for summary in summaries if _admitted(summary, target=0.75)],
        "admitted_80": [summary["engine"] for summary in summaries if _admitted(summary, target=0.80)],
        "events": events,
    }


def _wavefield_reliability_scores(
    training: Mapping[str, Any],
    evaluations: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
    seed: int,
) -> tuple[np.ndarray, ...]:
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    train_x = scaler.fit_transform(imputer.fit_transform(training["x"]))
    eval_x = [scaler.transform(imputer.transform(item["x"])) for item in evaluations]
    hits = _direction_hits(training)
    projector = FieldProjector(28, 28, len(feature_names), seed=seed)
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        correct = WaveField(width=28, height=28, layers=4, decay=0.997, speed=0.09, nonlin=0.01)
        wrong = WaveField(width=28, height=28, layers=4, decay=0.997, speed=0.09, nonlin=0.01)
        counts = {0: max(1, int(np.sum(hits == 0))), 1: max(1, int(np.sum(hits == 1)))}
        for vector, hit in zip(train_x, hits, strict=True):
            target = correct if hit else wrong
            target.feed(projector.to_pattern(vector), strength=400.0 / counts[int(hit)])
        correct.evolve(4)
        wrong.evolve(4)
    finally:
        np.random.set_state(previous_state)

    def scores(matrix: np.ndarray) -> np.ndarray:
        differences = np.asarray(
            [
                correct.field_resonance(projector.to_pattern(vector))
                - wrong.field_resonance(projector.to_pattern(vector))
                for vector in matrix
            ],
            dtype=float,
        )
        return 1.0 / (1.0 + np.exp(-np.clip(differences * 80.0, -30.0, 30.0)))

    return (scores(train_x), *(scores(matrix) for matrix in eval_x))


def _heuristic_probability(
    rows: Sequence[FeatureRow], feature: str, *, scale: float
) -> np.ndarray:
    values = np.asarray([float(row.features[feature]) for row in rows], dtype=float)
    return 1.0 / (1.0 + np.exp(-np.clip(values / scale, -30.0, 30.0)))


def _quality_features(prediction: Mapping[str, Any], field_score: np.ndarray) -> np.ndarray:
    expert = np.asarray(prediction["expert"], dtype=float)
    ensemble = np.asarray(prediction["ensemble"], dtype=float)
    direction = np.asarray(prediction["direction"], dtype=float)
    return np.column_stack(
        (
            prediction["x"],
            expert,
            np.abs(expert - 0.5) * 2.0,
            np.max(expert, axis=1) - np.min(expert, axis=1),
            np.abs(ensemble - 0.5) * 2.0,
            np.abs(direction - 0.5) * 2.0,
            np.max(prediction["candidates"], axis=1) - np.min(prediction["candidates"], axis=1),
            prediction["event"],
            np.tanh(np.abs(prediction["return"]) / 500.0),
            field_score,
        )
    )


def _direction_hits(prediction: Mapping[str, Any]) -> np.ndarray:
    predicted = np.asarray(prediction["direction"], dtype=float) >= 0.5
    actual = np.asarray(
        [row.future_return_bps > 0.0 for row in prediction["rows"]], dtype=bool
    )
    return np.asarray(predicted == actual, dtype=int)


def _events_for_set(
    engine: str,
    fold: int,
    prediction: Mapping[str, Any],
    quality: Sequence[float],
    *,
    horizon_seconds: int,
) -> list[dict[str, Any]]:
    output = []
    for row, probability, event_probability, predicted_return, quality_probability in zip(
        prediction["rows"],
        prediction["direction"],
        prediction["event"],
        prediction["return"],
        quality,
        strict=True,
    ):
        predicted_up = float(probability) >= 0.5
        actual_up = row.future_return_bps > 0.0
        signed_return = abs(float(predicted_return)) * (1.0 if predicted_up else -1.0)
        output.append(
            {
                "engine": engine,
                "symbol": row.symbol,
                "timeframe": "4h",
                "fold_index": fold,
                "query_id": f"{row.symbol}-{row.timestamp}",
                "data_end_utc": datetime.fromtimestamp(row.timestamp, tz=timezone.utc).isoformat(),
                "target_end_utc": datetime.fromtimestamp(
                    min(row.target_timestamp, row.timestamp + horizon_seconds), tz=timezone.utc
                ).isoformat(),
                "predicted_return_bps": signed_return,
                "actual_return_bps": row.future_return_bps,
                "probability_up": float(probability),
                "event_probability": float(event_probability),
                "quality_probability": float(quality_probability),
                "direction_hit": 1.0 if predicted_up == actual_up else 0.0,
            }
        )
    return output


def _select_policy_threshold(events: Sequence[Mapping[str, Any]]) -> float:
    best: tuple[float, float, int, float] | None = None
    for threshold in np.arange(0.10, 0.951, 0.025):
        selected = _independent_selected(events, float(threshold))
        if len(selected) < 40:
            continue
        accuracy = _accuracy(selected)
        wilson = _wilson_low(sum(int(row["direction_hit"]) for row in selected), len(selected))
        candidate = (wilson, accuracy, len(selected), float(threshold))
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    return best[3] if best is not None else 1.0


def _independent_selected(
    events: Sequence[Mapping[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    return collapse_overlapping_events(
        event for event in events if float(event["quality_probability"]) >= threshold
    )


def _summarize_selected(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    raw = [dict(event) for event in events]
    independent_all = collapse_overlapping_events(raw)
    selected = collapse_overlapping_events(event for event in raw if event.get("selected"))
    by_fold = _group_accuracy(selected, "fold_index")
    by_symbol = _group_accuracy(selected, "symbol")
    hits = sum(int(row["direction_hit"]) for row in selected)
    return {
        "raw_events": len(raw),
        "effective_events": len(independent_all),
        "selected_signals": len(selected),
        "coverage": len(selected) / max(len(independent_all), 1),
        "hits": hits,
        "accuracy": hits / len(selected) if selected else None,
        "wilson_low_95": _wilson_low(hits, len(selected)) if selected else None,
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "worst_fold_accuracy": min((row["accuracy"] for row in by_fold), default=None),
        "worst_symbol_accuracy": min((row["accuracy"] for row in by_symbol), default=None),
    }


def _group_accuracy(events: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    output = []
    values = sorted({str(row[field]) for row in events})
    for value in values:
        selected = [row for row in events if str(row[field]) == value]
        output.append({field: value, "signals": len(selected), "accuracy": _accuracy(selected)})
    return output


def _accuracy(events: Sequence[Mapping[str, Any]]) -> float | None:
    return (
        float(np.mean([float(row["direction_hit"]) for row in events])) if events else None
    )


def _admitted(summary: Mapping[str, Any], *, target: float) -> bool:
    accuracy = summary.get("accuracy")
    return bool(
        accuracy is not None
        and float(accuracy) >= target
        and int(summary["selected_signals"]) >= 40
        and float(summary["coverage"]) >= 0.05
        and float(summary["wilson_low_95"]) >= 0.65
        and summary["worst_fold_accuracy"] is not None
        and float(summary["worst_fold_accuracy"]) >= 0.65
        and summary["worst_symbol_accuracy"] is not None
        and float(summary["worst_symbol_accuracy"]) >= 0.65
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Multi-Year Binance Event Benchmark",
        "",
        "Strict nested walk-forward evaluation on verified Binance USD-M archives.",
        "",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        f"- horizon: {payload['methodology']['horizon']};",
        f"- field: {payload['methodology']['field']};",
        f"- admitted at 75%: {', '.join(payload['admitted_75']) or 'none'};",
        f"- admitted at 80%: {', '.join(payload['admitted_80']) or 'none'}.",
        "",
        "## Test Results",
        "",
        "| gate | signals | coverage | accuracy | Wilson low | worst fold | worst asset | 2026-H1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    holdout = {row["engine"]: row for row in payload["final_holdout_2026_h1"]}
    result_rows = []
    for summary in payload["summaries"]:
        current = holdout[summary["engine"]]
        result_rows.append(
            f"| {summary['engine']} | {summary['selected_signals']} | {summary['coverage']:.1%} | "
            f"{_rate(summary['accuracy'])} | {_rate(summary['wilson_low_95'])} | "
            f"{_rate(summary['worst_fold_accuracy'])} | {_rate(summary['worst_symbol_accuracy'])} | "
            f"{_rate(current['accuracy'])} |"
        )
    lines.extend(
        [
            *result_rows,
            "",
            "## Causal Policy Audit",
            "",
            "| gate | fold | test starts | past-only threshold | policy signals | policy accuracy |",
            "|---|---:|---|---:|---:|---:|",
        ]
    )
    for row in payload["policies"]:
        lines.append(
            f"| {row['engine']} | {row['fold_index']} | {row['test_start_utc'][:10]} | {row['threshold']:.2f} | "
            f"{row['policy_effective_signals']} | {_rate(row['policy_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "A threshold is chosen only from the preceding policy block. Test outcomes never tune it.",
            "",
        ]
    )
    return "\n".join(lines)


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def _horizon_label(seconds: int) -> str:
    days, remainder = divmod(seconds, 24 * 60 * 60)
    return f"{days}d" if remainder == 0 and days != 1 else "24h" if days == 1 else f"{seconds / 3600:g}h"


def main() -> int:
    parser = argparse.ArgumentParser(description="Nested multi-year Binance futures event benchmark.")
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--horizon-bars", type=int, default=6)
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
            extended_features=True,
        )
        data_audit.append(
            {
                "symbol": bundle.symbol,
                "bars": len(bundle.bars),
                "metrics": len(bundle.metrics),
                "funding": len(bundle.funding),
                "premium": len(bundle.premium),
                "missing_required_sources": len(bundle.missing_source_files),
            }
        )
        del bundle
    rows = assign_calendar_folds(add_multiyear_market_features(rows_by_symbol))
    payload = run_multiyear_benchmark(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
    )
    payload["data_audit"] = data_audit
    events = payload.pop("events")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in events) + "\n",
            encoding="utf-8",
        )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
