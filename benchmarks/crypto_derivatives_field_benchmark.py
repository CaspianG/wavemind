from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import evaluate_accuracy_gate  # noqa: E402
from benchmarks.crypto_binance_archive import (  # noqa: E402
    ArchiveBundle,
    BookDepthPoint,
    FuturesMetric,
    load_bundle,
)


PRICE_FEATURES = (
    "return_1",
    "return_3",
    "return_6",
    "return_12",
    "return_18",
    "return_36",
    "volatility_6",
    "volatility_18",
    "volatility_36",
    "range_bps",
    "quote_volume_z18",
    "trades_z18",
    "taker_imbalance",
    "taker_imbalance_mean6",
    "taker_imbalance_change6",
)

DERIVATIVE_FEATURES = (
    "oi_change_1",
    "oi_change_3",
    "oi_change_6",
    "oi_change_18",
    "top_account_log",
    "top_account_change6",
    "top_position_log",
    "top_position_change6",
    "global_ratio_log",
    "global_ratio_change6",
    "taker_ratio_log",
    "taker_ratio_change6",
    "funding_rate_bps",
    "funding_mean6_bps",
    "premium_bps",
    "premium_mean6_bps",
    "premium_change6_bps",
    "oi_intrabar_change_bps",
    "oi_intrabar_range_bps",
    "global_ratio_intrabar_mean_log",
    "global_ratio_intrabar_std",
    "taker_ratio_intrabar_mean_log",
    "taker_ratio_intrabar_std",
    "top_account_intrabar_mean_log",
    "top_position_intrabar_mean_log",
    "premium_range_bps",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
)

MICROSTRUCTURE_FEATURES = (
    "depth_imbalance_1pct",
    "depth_imbalance_5pct",
    "depth_imbalance_1pct_mean",
    "depth_imbalance_5pct_mean",
    "depth_imbalance_1pct_std",
    "depth_imbalance_5pct_std",
    "depth_imbalance_1pct_change",
    "depth_imbalance_5pct_change",
    "depth_total_1pct_z",
    "depth_total_5pct_z",
)

CROSS_ASSET_FEATURES = (
    "btc_return_6",
    "btc_oi_change_6",
    "btc_global_ratio_log",
    "market_return_6_mean",
    "market_oi_change_6_mean",
)


@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    timestamp: int
    target_timestamp: int
    fold_index: int
    features: Mapping[str, float]
    future_return_bps: float


def build_feature_rows(bundle: ArchiveBundle, *, horizon: int = 6, lookback: int = 36) -> list[FeatureRow]:
    bars = list(bundle.bars)
    metrics = list(bundle.metrics)
    funding = list(bundle.funding)
    book_depth = list(bundle.book_depth)
    premium_by_open = {row.timestamp: row for row in bundle.premium}
    metric_cursor = 0
    funding_cursor = 0
    depth_cursor = 0
    latest_metric: dict[str, float] = {}
    latest_metric_timestamp: dict[str, int] = {}
    latest_funding: float | None = None
    states: list[dict[str, float] | None] = []
    required_metric_fields = (
        "open_interest",
        "open_interest_value",
        "top_trader_account_ratio",
        "top_trader_position_ratio",
        "global_long_short_ratio",
        "taker_long_short_ratio",
    )
    for bar in bars:
        cutoff = int(bar.close_timestamp)
        interval_metrics: list[FuturesMetric] = []
        while metric_cursor < len(metrics) and metrics[metric_cursor].timestamp <= cutoff:
            metric = metrics[metric_cursor]
            interval_metrics.append(metric)
            for field in required_metric_fields:
                value = getattr(metric, field)
                if value is not None and math.isfinite(float(value)):
                    latest_metric[field] = float(value)
                    latest_metric_timestamp[field] = int(metric.timestamp)
            metric_cursor += 1
        interval_depth: list[BookDepthPoint] = []
        while depth_cursor < len(book_depth) and book_depth[depth_cursor].timestamp <= cutoff:
            interval_depth.append(book_depth[depth_cursor])
            depth_cursor += 1
        while funding_cursor < len(funding) and funding[funding_cursor].timestamp <= cutoff:
            latest_funding = float(funding[funding_cursor].funding_rate)
            funding_cursor += 1
        premium = premium_by_open.get(bar.timestamp)
        if (
            premium is None
            or latest_funding is None
            or any(field not in latest_metric for field in required_metric_fields)
            or not interval_metrics
            or not interval_depth
        ):
            states.append(None)
            continue
        funding_age = cutoff - int(funding[max(0, funding_cursor - 1)].timestamp)
        depth_age = cutoff - int(book_depth[max(0, depth_cursor - 1)].timestamp)
        if (
            not _metric_fields_are_fresh(
                cutoff,
                latest_metric_timestamp,
                required_metric_fields,
                max_age_seconds=15 * 60,
            )
            or funding_age > 12 * 60 * 60
            or depth_age > 15 * 60
        ):
            states.append(None)
            continue
        taker_imbalance = 0.0
        if bar.volume > 0.0:
            taker_imbalance = 2.0 * float(bar.taker_buy_volume) / float(bar.volume) - 1.0
        oi_interval = _metric_values(interval_metrics, "open_interest_value")
        global_interval = _metric_values(interval_metrics, "global_long_short_ratio")
        taker_interval = _metric_values(interval_metrics, "taker_long_short_ratio")
        top_account_interval = _metric_values(interval_metrics, "top_trader_account_ratio")
        top_position_interval = _metric_values(interval_metrics, "top_trader_position_ratio")
        depth_1 = np.asarray([_depth_imbalance(row, 1) for row in interval_depth], dtype=float)
        depth_5 = np.asarray([_depth_imbalance(row, 5) for row in interval_depth], dtype=float)
        depth_total_1 = np.asarray(
            [row.bid_notional_1pct + row.ask_notional_1pct for row in interval_depth], dtype=float
        )
        depth_total_5 = np.asarray(
            [row.bid_notional_5pct + row.ask_notional_5pct for row in interval_depth], dtype=float
        )
        if any(
            len(values) < 2
            for values in (
                oi_interval,
                global_interval,
                taker_interval,
                top_account_interval,
                top_position_interval,
                depth_1,
                depth_5,
            )
        ):
            states.append(None)
            continue
        opened = datetime.fromtimestamp(bar.timestamp, tz=timezone.utc)
        states.append(
            {
                "close": float(bar.close),
                "high": float(bar.high),
                "low": float(bar.low),
                "quote_volume": float(bar.quote_volume),
                "trades": float(bar.trades),
                "taker_imbalance": float(taker_imbalance),
                "open_interest_value": latest_metric["open_interest_value"],
                "top_trader_account_ratio": latest_metric["top_trader_account_ratio"],
                "top_trader_position_ratio": latest_metric["top_trader_position_ratio"],
                "global_long_short_ratio": latest_metric["global_long_short_ratio"],
                "taker_long_short_ratio": latest_metric["taker_long_short_ratio"],
                "funding_rate": latest_funding,
                "premium": float(premium.close),
                "oi_intrabar_change_bps": _log_change(oi_interval, len(oi_interval) - 1) * 10_000.0,
                "oi_intrabar_range_bps": math.log(
                    max(float(np.max(oi_interval)), 1e-12) / max(float(np.min(oi_interval)), 1e-12)
                )
                * 10_000.0,
                "global_ratio_intrabar_mean_log": float(math.log(max(float(np.mean(global_interval)), 1e-12))),
                "global_ratio_intrabar_std": float(np.std(np.log(np.maximum(global_interval, 1e-12)))),
                "taker_ratio_intrabar_mean_log": float(math.log(max(float(np.mean(taker_interval)), 1e-12))),
                "taker_ratio_intrabar_std": float(np.std(np.log(np.maximum(taker_interval, 1e-12)))),
                "top_account_intrabar_mean_log": float(
                    math.log(max(float(np.mean(top_account_interval)), 1e-12))
                ),
                "top_position_intrabar_mean_log": float(
                    math.log(max(float(np.mean(top_position_interval)), 1e-12))
                ),
                "premium_range_bps": float(premium.high - premium.low) * 10_000.0,
                "hour_sin": math.sin(2.0 * math.pi * opened.hour / 24.0),
                "hour_cos": math.cos(2.0 * math.pi * opened.hour / 24.0),
                "weekday_sin": math.sin(2.0 * math.pi * opened.weekday() / 7.0),
                "weekday_cos": math.cos(2.0 * math.pi * opened.weekday() / 7.0),
                "depth_imbalance_1pct": float(depth_1[-1]),
                "depth_imbalance_5pct": float(depth_5[-1]),
                "depth_imbalance_1pct_mean": float(np.mean(depth_1)),
                "depth_imbalance_5pct_mean": float(np.mean(depth_5)),
                "depth_imbalance_1pct_std": float(np.std(depth_1)),
                "depth_imbalance_5pct_std": float(np.std(depth_5)),
                "depth_imbalance_1pct_change": float(depth_1[-1] - depth_1[0]),
                "depth_imbalance_5pct_change": float(depth_5[-1] - depth_5[0]),
                "depth_total_1pct": float(depth_total_1[-1]),
                "depth_total_5pct": float(depth_total_5[-1]),
            }
        )

    rows: list[FeatureRow] = []
    for index in range(lookback, len(bars) - horizon):
        history = states[index - lookback : index + 1]
        if any(item is None for item in history):
            continue
        current = history[-1]
        assert current is not None
        features = _features_from_history([item for item in history if item is not None])
        future_return = (float(bars[index + horizon].close) / float(bars[index].close) - 1.0) * 10_000.0
        rows.append(
            FeatureRow(
                symbol=bundle.symbol,
                timestamp=int(bars[index].close_timestamp),
                target_timestamp=int(bars[index + horizon].close_timestamp),
                fold_index=-1,
                features=features,
                future_return_bps=float(future_return),
            )
        )
    return rows


def add_cross_asset_features(rows_by_symbol: Mapping[str, Sequence[FeatureRow]]) -> list[FeatureRow]:
    by_timestamp: dict[int, dict[str, FeatureRow]] = {}
    for symbol, rows in rows_by_symbol.items():
        for row in rows:
            by_timestamp.setdefault(row.timestamp, {})[symbol] = row
    output: list[FeatureRow] = []
    for timestamp, market in sorted(by_timestamp.items()):
        btc = market.get("BTCUSDT")
        if btc is None or len(market) < 2:
            continue
        mean_return = float(np.mean([row.features["return_6"] for row in market.values()]))
        mean_oi = float(np.mean([row.features["oi_change_6"] for row in market.values()]))
        for row in market.values():
            features = dict(row.features)
            features.update(
                {
                    "btc_return_6": float(btc.features["return_6"]),
                    "btc_oi_change_6": float(btc.features["oi_change_6"]),
                    "btc_global_ratio_log": float(btc.features["global_ratio_log"]),
                    "market_return_6_mean": mean_return,
                    "market_oi_change_6_mean": mean_oi,
                }
            )
            output.append(FeatureRow(**(asdict(row) | {"features": features})))
    return output


def assign_walk_forward_folds(
    rows: Sequence[FeatureRow], *, folds: int = 4, test_timestamps: int = 180
) -> list[FeatureRow]:
    timestamps = sorted({row.timestamp for row in rows})
    required = folds * test_timestamps
    if len(timestamps) <= required:
        raise ValueError("Not enough timestamps for requested walk-forward folds")
    selected = timestamps[-required:]
    fold_by_timestamp = {
        timestamp: index // test_timestamps for index, timestamp in enumerate(selected)
    }
    return [
        FeatureRow(**(asdict(row) | {"fold_index": fold_by_timestamp.get(row.timestamp, -1)}))
        for row in rows
    ]


def run_benchmark(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int = 24 * 60 * 60,
    random_state: int = 17,
    train_timestamps: int | None = None,
    train_scope: str = "pooled",
    engines: Sequence[str] | None = None,
) -> dict[str, Any]:
    try:
        from sklearn.ensemble import (
            ExtraTreesClassifier,
            ExtraTreesRegressor,
            HistGradientBoostingClassifier,
            HistGradientBoostingRegressor,
        )
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError('Install the research extra: pip install -e ".[crypto-ml]"') from exc

    symbol_features = tuple(
        f"symbol_{symbol}" for symbol in sorted({row.symbol for row in rows}) if symbol != "BTCUSDT"
    )
    feature_sets = {
        "OHLCV logistic baseline": PRICE_FEATURES + symbol_features,
        "Derivatives logistic baseline": DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "kNN analogue baseline": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "Histogram gradient baseline": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "ExtraTrees baseline": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "Return regression ensemble": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "Large-move classifier": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
        "Tabular ensemble": PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES + symbol_features,
    }
    if train_scope not in {"pooled", "per-symbol"}:
        raise ValueError("train_scope must be 'pooled' or 'per-symbol'")
    if engines:
        unknown = sorted(set(engines) - set(feature_sets))
        if unknown:
            raise ValueError("Unknown engines: " + ", ".join(unknown))
        feature_sets = {name: feature_sets[name] for name in engines}

    def predict_engine(
        engine: str,
        x_train: np.ndarray,
        target_train: np.ndarray,
        x_test: np.ndarray,
    ) -> np.ndarray:
        y_train = np.asarray(target_train > 0.0, dtype=int)
        if engine in {"OHLCV logistic baseline", "Derivatives logistic baseline"}:
            model = make_pipeline(
                SimpleImputer(strategy="median"),
                StandardScaler(),
                LogisticRegression(C=0.15, max_iter=2000, class_weight="balanced", random_state=random_state),
            )
            return _fit_predict(model, x_train, y_train, x_test)
        if engine == "Return regression ensemble":
            clipped = np.clip(
                target_train,
                np.quantile(target_train, 0.01),
                np.quantile(target_train, 0.99),
            )
            regressors = (
                make_pipeline(
                    SimpleImputer(strategy="median"),
                    StandardScaler(),
                    KNeighborsRegressor(n_neighbors=63, weights="distance", p=2),
                ),
                make_pipeline(
                    SimpleImputer(strategy="median"),
                    HistGradientBoostingRegressor(
                        loss="absolute_error",
                        learning_rate=0.04,
                        max_iter=180,
                        max_leaf_nodes=15,
                        min_samples_leaf=35,
                        l2_regularization=2.0,
                        random_state=random_state,
                    ),
                ),
                make_pipeline(
                    SimpleImputer(strategy="median"),
                    ExtraTreesRegressor(
                        n_estimators=180,
                        max_depth=8,
                        min_samples_leaf=12,
                        max_features=0.7,
                        n_jobs=-1,
                        random_state=random_state,
                    ),
                ),
            )
            predictions = np.mean(
                [model.fit(x_train, clipped).predict(x_test) for model in regressors], axis=0
            )
            scale = max(float(np.median(np.abs(clipped))), 1.0)
            return 0.5 + 0.5 * np.tanh(np.asarray(predictions, dtype=float) / scale)
        if engine == "Large-move classifier":
            large_move = float(np.quantile(np.abs(target_train), 0.65))
            labels = np.where(target_train > large_move, 2, np.where(target_train < -large_move, 0, 1))
            model = make_pipeline(
                SimpleImputer(strategy="median"),
                ExtraTreesClassifier(
                    n_estimators=240,
                    max_depth=9,
                    min_samples_leaf=10,
                    max_features=0.8,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=random_state,
                ),
            )
            probabilities = np.asarray(model.fit(x_train, labels).predict_proba(x_test), dtype=float)
            return 0.5 + 0.5 * (probabilities[:, 2] - probabilities[:, 0])
        field = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            KNeighborsClassifier(n_neighbors=63, weights="distance", p=2),
        )
        nonlinear = make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=0.04,
                max_iter=180,
                max_leaf_nodes=15,
                min_samples_leaf=35,
                l2_regularization=2.0,
                random_state=random_state,
            ),
        )
        trees = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=180,
                max_depth=8,
                min_samples_leaf=12,
                max_features=0.7,
                class_weight="balanced",
                n_jobs=-1,
                random_state=random_state,
            ),
        )
        field_p = _fit_predict(field, x_train, y_train, x_test)
        if engine == "kNN analogue baseline":
            return field_p
        nonlinear_p = _fit_predict(nonlinear, x_train, y_train, x_test)
        if engine == "Histogram gradient baseline":
            return nonlinear_p
        trees_p = _fit_predict(trees, x_train, y_train, x_test)
        if engine == "ExtraTrees baseline":
            return trees_p
        return 0.35 * field_p + 0.35 * nonlinear_p + 0.30 * trees_p

    events: list[dict[str, Any]] = []
    fold_ids = sorted({row.fold_index for row in rows if row.fold_index >= 0})
    for fold in fold_ids:
        test_rows = [row for row in rows if row.fold_index == fold]
        test_start = min(row.timestamp for row in test_rows)
        train_rows = [row for row in rows if row.target_timestamp < test_start]
        if train_timestamps is not None:
            eligible_timestamps = sorted({row.timestamp for row in train_rows})[-int(train_timestamps) :]
            allowed = set(eligible_timestamps)
            train_rows = [row for row in train_rows if row.timestamp in allowed]
        if len(train_rows) < 500:
            raise ValueError(f"Fold {fold} has only {len(train_rows)} matured training rows")
        for engine, names in feature_sets.items():
            if train_scope == "pooled":
                probabilities = predict_engine(
                    engine,
                    _matrix(train_rows, names),
                    np.asarray([row.future_return_bps for row in train_rows], dtype=float),
                    _matrix(test_rows, names),
                )
            else:
                probabilities = np.zeros(len(test_rows), dtype=float)
                for symbol in sorted({row.symbol for row in test_rows}):
                    train_symbol = [row for row in train_rows if row.symbol == symbol]
                    test_indices = [index for index, row in enumerate(test_rows) if row.symbol == symbol]
                    test_symbol = [test_rows[index] for index in test_indices]
                    if len(train_symbol) < 300:
                        raise ValueError(f"Fold {fold} / {symbol} has only {len(train_symbol)} training rows")
                    predicted = predict_engine(
                        engine,
                        _matrix(train_symbol, names),
                        np.asarray([row.future_return_bps for row in train_symbol], dtype=float),
                        _matrix(test_symbol, names),
                    )
                    probabilities[test_indices] = predicted
            events.extend(
                _events(
                    f"{engine} ({train_scope})",
                    fold,
                    test_rows,
                    probabilities,
                    horizon_seconds=horizon_seconds,
                )
            )

    summary = _summarize(events)
    gate_75 = evaluate_accuracy_gate(
        events,
        target_accuracy=0.75,
        min_wilson_low_95=0.65,
        min_fold_accuracy=0.65,
        min_slice_accuracy=0.65,
        thresholds_bps=(0.0, 100.0, 200.0, 300.0, 400.0, 500.0),
    )
    gate_80 = evaluate_accuracy_gate(
        events,
        thresholds_bps=(0.0, 100.0, 200.0, 300.0, 400.0, 500.0),
    )
    return {
        "methodology": {
            "data": "Binance USD-M official archive",
            "horizon": _horizon_label(horizon_seconds) + " from completed 4h candles",
            "training": (
                f"rolling {train_timestamps}-timestamp window; target must mature before fold start"
                if train_timestamps is not None
                else "expanding window; target must mature before fold start"
            ),
            "train_timestamps": train_timestamps,
            "train_scope": train_scope,
            "features": {
                "price": list(PRICE_FEATURES),
                "derivatives": list(DERIVATIVE_FEATURES),
                "microstructure": list(MICROSTRUCTURE_FEATURES),
                "cross_asset": list(CROSS_ASSET_FEATURES),
            },
        },
        "summary": summary,
        "gate_75": gate_75,
        "gate_80": gate_80,
        "events": events,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Binance Futures Walk-Forward",
        "",
        "Official Binance USD-M data. Every test target matures after all training targets used by its fold.",
        "",
        f"- horizon: {payload['methodology']['horizon']};",
        f"- training: {payload['methodology']['training']};",
        f"- model scope: {payload['methodology'].get('model_scope', 'statistical baseline ablation')}",
        "",
        "| engine | signals | direction accuracy | avg model margin | worst fold | worst symbol |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["summary"]:
        lines.append(
            f"| {row['engine']} | {row['signals']} | {row['accuracy']:.1%} | "
            f"{row['avg_probability_margin']:.1%} | {row['worst_fold_accuracy']:.1%} | "
            f"{row['worst_symbol_accuracy']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Admission",
            "",
            "75% admitted: " + (", ".join(payload["gate_75"]["admitted_engines"]) or "none"),
            "",
            "80% admitted: " + (", ".join(payload["gate_80"]["admitted_engines"]) or "none"),
            "",
            "## Best Selective Frontier",
            "",
            "Best observed threshold per engine with at least 40 non-overlapping signals. This is diagnostic, not an admitted result.",
            "",
            "| engine | threshold | independent signals | accuracy | Wilson low | worst fold | worst symbol |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for engine in payload["gate_75"]["engines"]:
        eligible = [
            row
            for row in engine["frontier"]
            if int(row["effective"]["signals"]) >= 40
        ]
        if not eligible:
            continue
        best = max(
            eligible,
            key=lambda row: (float(row["effective"]["accuracy"]), int(row["effective"]["signals"])),
        )
        worst_fold = min(
            float(row["accuracy"])
            for row in best["by_fold"]
            if row["accuracy"] is not None
        )
        worst_slice = min(
            float(row["accuracy"])
            for row in best["by_slice"]
            if row["accuracy"] is not None
        )
        lines.append(
            f"| {engine['engine']} | {best['threshold_bps']:.0f} bps | "
            f"{best['effective']['signals']} | {best['effective']['accuracy']:.1%} | "
            f"{best['effective']['wilson_low_95']:.1%} | {worst_fold:.1%} | {worst_slice:.1%} |"
        )
    lines.append("")
    audits = payload.get("data_audit", [])
    if audits:
        lines.extend(
            [
                "## Source Audit",
                "",
                "| symbol | bars | metrics | depth snapshots | missing optional archives |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in audits:
            lines.append(
                f"| {row['symbol']} | {row['bars']} | {row['metrics']} | "
                f"{row['book_depth']} | {row['missing_source_files']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _features_from_history(history: Sequence[Mapping[str, float]]) -> dict[str, float]:
    close = np.asarray([row["close"] for row in history], dtype=float)
    returns = np.diff(np.log(close)) * 10_000.0
    quote_volume = np.asarray([row["quote_volume"] for row in history], dtype=float)
    trades = np.asarray([row["trades"] for row in history], dtype=float)
    imbalance = np.asarray([row["taker_imbalance"] for row in history], dtype=float)
    oi = np.asarray([row["open_interest_value"] for row in history], dtype=float)
    features: dict[str, float] = {}
    for period in (1, 3, 6, 12, 18, 36):
        features[f"return_{period}"] = _log_change(close, period) * 10_000.0
    for period in (6, 18, 36):
        features[f"volatility_{period}"] = float(np.std(returns[-period:]))
    current = history[-1]
    features["range_bps"] = (current["high"] / max(current["low"], 1e-12) - 1.0) * 10_000.0
    features["quote_volume_z18"] = _robust_z(quote_volume[-18:])
    features["trades_z18"] = _robust_z(trades[-18:])
    features["taker_imbalance"] = float(imbalance[-1])
    features["taker_imbalance_mean6"] = float(np.mean(imbalance[-6:]))
    features["taker_imbalance_change6"] = float(imbalance[-1] - imbalance[-7])
    for period in (1, 3, 6, 18):
        features[f"oi_change_{period}"] = _log_change(oi, period) * 10_000.0
    for prefix, source in (
        ("top_account", "top_trader_account_ratio"),
        ("top_position", "top_trader_position_ratio"),
        ("global_ratio", "global_long_short_ratio"),
        ("taker_ratio", "taker_long_short_ratio"),
    ):
        values = np.asarray([max(row[source], 1e-12) for row in history], dtype=float)
        features[f"{prefix}_log"] = float(math.log(values[-1]))
        features[f"{prefix}_change6"] = _log_change(values, 6)
    funding = np.asarray([row["funding_rate"] for row in history], dtype=float) * 10_000.0
    premium = np.asarray([row["premium"] for row in history], dtype=float) * 10_000.0
    features["funding_rate_bps"] = float(funding[-1])
    features["funding_mean6_bps"] = float(np.mean(funding[-6:]))
    features["premium_bps"] = float(premium[-1])
    features["premium_mean6_bps"] = float(np.mean(premium[-6:]))
    features["premium_change6_bps"] = float(premium[-1] - premium[-7])
    for name in (
        "oi_intrabar_change_bps",
        "oi_intrabar_range_bps",
        "global_ratio_intrabar_mean_log",
        "global_ratio_intrabar_std",
        "taker_ratio_intrabar_mean_log",
        "taker_ratio_intrabar_std",
        "top_account_intrabar_mean_log",
        "top_position_intrabar_mean_log",
        "premium_range_bps",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
    ):
        features[name] = float(current[name])
    for name in MICROSTRUCTURE_FEATURES:
        if name == "depth_total_1pct_z":
            values = np.asarray([row["depth_total_1pct"] for row in history[-18:]], dtype=float)
            features[name] = _robust_z(values)
        elif name == "depth_total_5pct_z":
            values = np.asarray([row["depth_total_5pct"] for row in history[-18:]], dtype=float)
            features[name] = _robust_z(values)
        else:
            features[name] = float(current[name])
    return features


def _matrix(rows: Sequence[FeatureRow], names: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [
            [
                (1.0 if row.symbol == name.removeprefix("symbol_") else 0.0)
                if name.startswith("symbol_")
                else float(row.features[name])
                for name in names
            ]
            for row in rows
        ],
        dtype=float,
    )


def _fit_predict(model: Any, x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    model.fit(x_train, y_train)
    return np.asarray(model.predict_proba(x_test)[:, 1], dtype=float)


def _events(
    engine: str,
    fold: int,
    rows: Sequence[FeatureRow],
    probabilities: Sequence[float],
    *,
    horizon_seconds: int,
) -> list[dict[str, Any]]:
    output = []
    for row, probability in zip(rows, probabilities):
        predicted_up = float(probability) >= 0.5
        actual_up = row.future_return_bps > 0.0
        margin = abs(float(probability) - 0.5) * 2.0
        predicted_return = (1.0 if predicted_up else -1.0) * margin * 1000.0
        output.append(
            {
                "engine": engine,
                "symbol": row.symbol,
                "timeframe": "4h",
                "fold_index": int(fold),
                "query_id": f"{row.symbol}-{row.timestamp}",
                "data_end_utc": datetime.fromtimestamp(row.timestamp, tz=timezone.utc).isoformat(),
                "target_end_utc": datetime.fromtimestamp(
                    min(row.target_timestamp, row.timestamp + horizon_seconds), tz=timezone.utc
                ).isoformat(),
                "predicted_return_bps": float(predicted_return),
                "actual_return_bps": float(row.future_return_bps),
                "direction_hit": 1.0 if predicted_up == actual_up else 0.0,
                "probability_up": float(probability),
                "probability_margin": float(margin),
            }
        )
    return output


def _summarize(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for engine in sorted({str(row["engine"]) for row in events}):
        selected = [row for row in events if row["engine"] == engine]
        by_fold = _accuracy_groups(selected, "fold_index")
        by_symbol = _accuracy_groups(selected, "symbol")
        output.append(
            {
                "engine": engine,
                "signals": len(selected),
                "accuracy": float(np.mean([row["direction_hit"] for row in selected])),
                "avg_probability_margin": float(np.mean([row["probability_margin"] for row in selected])),
                "worst_fold_accuracy": min(by_fold.values()),
                "worst_symbol_accuracy": min(by_symbol.values()),
                "by_fold": by_fold,
                "by_symbol": by_symbol,
            }
        )
    return output


def _accuracy_groups(events: Sequence[Mapping[str, Any]], field: str) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for row in events:
        values.setdefault(str(row[field]), []).append(float(row["direction_hit"]))
    return {key: float(np.mean(items)) for key, items in sorted(values.items())}


def _log_change(values: np.ndarray, period: int) -> float:
    return float(math.log(max(values[-1], 1e-12) / max(values[-1 - period], 1e-12)))


def _robust_z(values: np.ndarray) -> float:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return float((values[-1] - median) / max(mad * 1.4826, 1e-9))


def _metric_values(rows: Sequence[FuturesMetric], field: str) -> np.ndarray:
    values = [float(value) for row in rows if (value := getattr(row, field)) is not None]
    return np.asarray(values, dtype=float)


def _metric_fields_are_fresh(
    cutoff: int,
    timestamps: Mapping[str, int],
    required_fields: Sequence[str],
    *,
    max_age_seconds: int,
) -> bool:
    return all(
        field in timestamps and 0 <= cutoff - int(timestamps[field]) <= max_age_seconds
        for field in required_fields
    )


def _depth_imbalance(row: BookDepthPoint, level: int) -> float:
    bid = float(getattr(row, f"bid_notional_{level}pct"))
    ask = float(getattr(row, f"ask_notional_{level}pct"))
    return (bid - ask) / max(bid + ask, 1e-12)


def _horizon_label(horizon_seconds: int) -> str:
    hours = horizon_seconds / 3600.0
    if hours % 24 == 0:
        days = int(hours // 24)
        return f"{days}d" if days != 1 else "24h"
    return f"{hours:g}h"


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward benchmark on Binance derivatives data.")
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--train-timestamps", type=int)
    parser.add_argument("--train-scope", choices=("pooled", "per-symbol"), default="pooled")
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--engine", action="append", dest="engines")
    args = parser.parse_args()

    if args.horizon_bars <= 0:
        parser.error("--horizon-bars must be positive")
    rows_by_symbol = {}
    data_audit = []
    for path in args.bundles:
        bundle = load_bundle(path)
        feature_rows = build_feature_rows(bundle, horizon=args.horizon_bars)
        if not feature_rows:
            raise ValueError(
                f"{bundle.symbol}: no causally aligned feature rows; "
                "the bundle must include verified book-depth archives"
            )
        rows_by_symbol[bundle.symbol] = feature_rows
        data_audit.append(
            {
                "symbol": bundle.symbol,
                "bars": len(bundle.bars),
                "metrics": len(bundle.metrics),
                "book_depth": len(bundle.book_depth),
                "missing_source_files": len(bundle.missing_source_files),
            }
        )
        del bundle
    rows = assign_walk_forward_folds(add_cross_asset_features(rows_by_symbol))
    payload = run_benchmark(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        train_timestamps=args.train_timestamps,
        train_scope=args.train_scope,
        engines=args.engines,
    )
    payload["data_audit"] = data_audit
    events = payload.pop("events")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in events) + "\n", encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
