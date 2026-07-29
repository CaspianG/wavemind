from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import (  # noqa: E402
    FuturesBar,
    load_bundle,
)
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    _confirmation_matches,
)
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_episode_transition_benchmark import (  # noqa: E402
    candidate_probabilities,
)
from benchmarks.crypto_cross_sectional_field_benchmark import (  # noqa: E402
    _topological_wavefield_probability,
)


CALIBRATION_END = "2024-01-01"
DEVELOPMENT_START = "2024-01-01"
DEVELOPMENT_END = "2025-01-01"
FINAL_START = "2025-01-01"
FINAL_END = "2026-07-01"
RETURN_QUANTILE = 0.01
OI_QUANTILE = 0.10
CONFIRMATION = "decelerating_selloff"
MIN_FINAL_SIGNALS = 40
MIN_SLICE_SIGNALS = 5
MIN_RESOLUTION_RATE = 0.80
MIN_UPLIFT = 0.05
MODEL_FEATURES = (
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
)
MODEL_ORDER = (
    "always_rebound",
    "always_continuation",
    "majority",
    "logistic",
    "extra_trees",
    "knn",
    "wavefield",
    "field_tree_hybrid",
    "topological_wavefield",
    "topological_tree_hybrid",
)


@dataclass(frozen=True)
class PathConfig:
    horizon_bars: int
    barrier_bps: float

    def __post_init__(self) -> None:
        if self.horizon_bars < 1:
            raise ValueError("horizon_bars must be positive")
        if self.barrier_bps <= 0.0:
            raise ValueError("barrier_bps must be positive")


@dataclass(frozen=True)
class PathBar:
    close_timestamp: int
    close: float


@dataclass(frozen=True)
class PathEvent:
    symbol: str
    timestamp: int
    target_timestamp: int
    year: int
    outcome: str
    hit: bool
    resolved: bool
    bars_to_resolution: int | None
    terminal_return_bps: float
    max_return_bps: float
    min_return_bps: float
    features: tuple[float, ...]


CANDIDATE_CONFIGS = tuple(
    PathConfig(horizon_bars=horizon, barrier_bps=barrier)
    for horizon in (6, 12, 18, 42)
    for barrier in (50.0, 100.0, 150.0, 200.0, 300.0)
)
_BAR_INDEX_CACHE: dict[int, dict[int, int]] = {}


def load_rows_and_bundles(
    paths: Sequence[str | Path],
    *,
    rows_cache: str | Path | Sequence[str | Path] | None = None,
    bars_cache: str | Path | Sequence[str | Path] | None = None,
) -> tuple[list[FeatureRow], dict[str, tuple[PathBar, ...]]]:
    if not paths:
        raise ValueError("at least one bundle path is required")
    expected_symbols = {
        Path(path).name.split("_", 1)[0].upper()
        for path in paths
    }
    bars_cache_paths = _cache_paths(bars_cache)
    if bars_cache_paths and all(path.exists() for path in bars_cache_paths):
        bars_by_symbol: dict[str, tuple[PathBar, ...]] = {}
        for path in bars_cache_paths:
            loaded = load_bars_cache(path)
            overlap = sorted(set(bars_by_symbol) & set(loaded))
            if overlap:
                raise ValueError(
                    "bar caches contain duplicate symbols: "
                    + ", ".join(overlap)
                )
            bars_by_symbol.update(loaded)
        if set(bars_by_symbol) != expected_symbols:
            raise ValueError("bar cache symbols do not match bundle paths")
        if rows_cache is None:
            raise ValueError("rows_cache is required when reusing bars_cache")
        rows = load_cached_rows(rows_cache, symbols=expected_symbols)
        return (
            sorted(rows, key=lambda row: (row.timestamp, row.symbol)),
            bars_by_symbol,
        )

    bars_by_symbol: dict[str, tuple[PathBar, ...]] = {}
    rows: list[FeatureRow] = []
    for path in paths:
        bundle = load_bundle(path)
        if bundle.symbol in bars_by_symbol:
            raise ValueError(f"duplicate bundle for {bundle.symbol}")
        bars_by_symbol[bundle.symbol] = tuple(
            PathBar(
                close_timestamp=int(bar.close_timestamp),
                close=float(bar.close),
            )
            for bar in bundle.bars
        )
        if rows_cache is None:
            feature_rows = build_feature_rows(
                bundle,
                horizon=42,
                lookback=180,
                include_microstructure=False,
                include_intraday=False,
                extended_features=True,
            )
            rows.extend(_slim_row(row) for row in feature_rows)
    if rows_cache is not None:
        rows = load_cached_rows(rows_cache, symbols=set(bars_by_symbol))
    if bars_cache_paths:
        if len(bars_cache_paths) != 1:
            raise ValueError(
                "multiple bar caches can only be reused when all exist"
            )
        save_bars_cache(bars_cache_paths[0], bars_by_symbol)
    return (
        sorted(rows, key=lambda row: (row.timestamp, row.symbol)),
        bars_by_symbol,
    )


def save_bars_cache(
    path: str | Path,
    bars_by_symbol: Mapping[str, Sequence[PathBar]],
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "wavemind.crypto.capitulation-path-bars-v1",
        "symbols": {
            symbol: [
                [int(bar.close_timestamp), float(bar.close)]
                for bar in bars
            ]
            for symbol, bars in sorted(bars_by_symbol.items())
        },
    }
    with gzip.open(output, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, separators=(",", ":"))


def load_bars_cache(
    path: str | Path,
) -> dict[str, tuple[PathBar, ...]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema") != "wavemind.crypto.capitulation-path-bars-v1":
        raise ValueError("unsupported bar cache schema")
    return {
        str(symbol): tuple(
            PathBar(close_timestamp=int(row[0]), close=float(row[1]))
            for row in rows
        )
        for symbol, rows in payload["symbols"].items()
    }


def load_cached_rows(
    path: str | Path | Sequence[str | Path],
    *,
    symbols: set[str],
) -> list[FeatureRow]:
    rows = []
    for source in _cache_paths(path):
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError("row cache must contain a rows list")
        rows.extend(
            _slim_row(
                FeatureRow(
                    symbol=str(row["symbol"]),
                    timestamp=int(row["timestamp"]),
                    target_timestamp=int(row["target_timestamp"]),
                    fold_index=int(row.get("fold_index", -1)),
                    features={
                        str(name): float(value)
                        for name, value in row["features"].items()
                    },
                    future_return_bps=float(row["future_return_bps"]),
                )
            )
            for row in payload["rows"]
            if str(row["symbol"]) in symbols
        )
    deduplicated = {
        (row.symbol, row.timestamp): row
        for row in rows
    }
    rows = list(deduplicated.values())
    if {row.symbol for row in rows} != symbols:
        missing = sorted(symbols - {row.symbol for row in rows})
        raise ValueError("row cache is missing symbols: " + ", ".join(missing))
    return rows


def _cache_paths(
    value: str | Path | Sequence[str | Path] | None,
) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(path) for path in value]


def _slim_row(row: FeatureRow) -> FeatureRow:
    return FeatureRow(
        symbol=row.symbol,
        timestamp=row.timestamp,
        target_timestamp=row.target_timestamp,
        fold_index=row.fold_index,
        features={
            name: float(row.features[name])
            for name in MODEL_FEATURES
        },
        future_return_bps=row.future_return_bps,
    )


def run_path_benchmark(
    development_rows: Sequence[FeatureRow],
    development_bundles: Mapping[str, Sequence[PathBar]],
    final_rows: Sequence[FeatureRow],
    final_bundles: Mapping[str, Sequence[PathBar]],
    *,
    calibration_end: int = 1_704_067_200,
    development_end: int = 1_735_689_600,
    final_end: int = 1_782_864_000,
) -> dict[str, Any]:
    development_candidates = [
        evaluate_config(
            development_rows,
            development_bundles,
            config=config,
            calibration_end=calibration_end,
            start=calibration_end,
            end=development_end,
        )
        for config in CANDIDATE_CONFIGS
    ]
    supported = [
        row
        for row in development_candidates
        if int(row["summary"]["signals"]) >= 20
    ]
    if not supported:
        raise ValueError("no path configuration has enough development support")
    selected = max(supported, key=_selection_key)
    selected_config = PathConfig(**selected["config"])
    training = evaluate_config(
        development_rows,
        development_bundles,
        config=selected_config,
        calibration_end=calibration_end,
        start=_timestamp("2023-01-01"),
        end=calibration_end,
    )
    training_events = [
        PathEvent(**event)
        for event in training["events"]
    ]
    validation_events = [
        PathEvent(**event)
        for event in selected["events"]
    ]
    validation_models = evaluate_path_models(
        training_events,
        validation_events,
        seed=2027,
    )
    selected_model = max(
        MODEL_ORDER,
        key=lambda name: _model_selection_key(validation_models[name], name),
    )
    final = evaluate_config(
        final_rows,
        final_bundles,
        config=selected_config,
        calibration_end=calibration_end,
        start=_timestamp(FINAL_START),
        end=final_end,
    )
    final_events = [
        PathEvent(**event)
        for event in final["events"]
    ]
    final_models = evaluate_path_models(
        training_events + validation_events,
        final_events,
        seed=2027,
    )
    selected_final = final_models[selected_model]
    return {
        "benchmark": "post-capitulation symmetric barrier path",
        "methodology": {
            "source": "official Binance USD-M completed 4h archives",
            "trigger": {
                "return_feature": "return_12",
                "return_quantile": RETURN_QUANTILE,
                "open_interest_feature": "oi_change_1",
                "open_interest_quantile": OI_QUANTILE,
                "confirmation": CONFIRMATION,
            },
            "development": (
                "barrier and horizon are selected on development assets in "
                f"{DEVELOPMENT_START} through {DEVELOPMENT_END}"
            ),
            "final": (
                "the selected configuration is evaluated once on different "
                f"assets in {FINAL_START} through {FINAL_END}"
            ),
            "outcome": (
                "whether a completed 4h close reaches the symmetric upper "
                "barrier before the lower barrier; unresolved paths count as "
                "misses in conservative accuracy"
            ),
            "overlap_control": (
                "at most one signal per asset until the configured path "
                "horizon matures"
            ),
            "claim_gate": {
                "minimum_signals": MIN_FINAL_SIGNALS,
                "minimum_conservative_accuracy": 0.70,
                "minimum_wilson_low_95": 0.65,
                "minimum_resolution_rate": MIN_RESOLUTION_RATE,
                "minimum_supported_year_accuracy": 0.65,
                "minimum_supported_symbol_accuracy": 0.65,
                "minimum_uplift_over_unconditional": MIN_UPLIFT,
            },
            "model_selection": (
                "trigger quantiles and models use 2023 training data only, "
                "model family is selected on 2024, "
                "then refit on development history and evaluated once on "
                "asset-disjoint 2025-2026"
            ),
        },
        "development_assets": sorted(development_bundles),
        "final_assets": sorted(final_bundles),
        "asset_disjoint": not bool(
            set(development_bundles) & set(final_bundles)
        ),
        "development_candidates": development_candidates,
        "selected_config": asdict(selected_config),
        "training": training,
        "development_selected": selected,
        "selected_model": selected_model,
        "validation_models": validation_models,
        "final": final,
        "final_models": final_models,
        "selected_final": selected_final,
        "admitted_70": path_admitted_70(selected_final),
    }


def evaluate_config(
    rows: Sequence[FeatureRow],
    bundles: Mapping[str, Sequence[PathBar]],
    *,
    config: PathConfig,
    calibration_end: int,
    start: int,
    end: int,
) -> dict[str, Any]:
    calibration = [
        row
        for row in rows
        if row.timestamp < calibration_end
        and row.symbol in bundles
    ]
    if not calibration:
        raise ValueError("calibration split is empty")
    return_threshold = float(
        np.quantile(
            [float(row.features["return_12"]) for row in calibration],
            RETURN_QUANTILE,
        )
    )
    oi_threshold = float(
        np.quantile(
            [float(row.features["oi_change_1"]) for row in calibration],
            OI_QUANTILE,
        )
    )
    selected = [
        row
        for row in rows
        if start <= row.timestamp < end
        and row.symbol in bundles
        and float(row.features["return_12"]) <= return_threshold
        and float(row.features["oi_change_1"]) <= oi_threshold
        and _confirmation_matches(row, CONFIRMATION)
    ]
    selected = collapse_overlapping_rows(selected, horizon_bars=config.horizon_bars)
    events = [
        event
        for row in selected
        if (
            event := resolve_path(
                row,
                bundles[row.symbol],
                config=config,
            )
        )
        is not None
    ]
    baseline = unconditional_barrier_rate(
        rows,
        bundles,
        config=config,
        start=start,
        end=end,
    )
    summary = summarize_events(events, unconditional_up_rate=baseline)
    return {
        "config": asdict(config),
        "thresholds": {
            "return_12_bps": return_threshold,
            "oi_change_1_bps": oi_threshold,
        },
        "summary": summary,
        "events": [asdict(event) for event in events],
    }


def resolve_path(
    row: FeatureRow,
    bars: Sequence[PathBar] | Sequence[FuturesBar],
    *,
    config: PathConfig,
) -> PathEvent | None:
    index_by_close = _bar_index(bars)
    index = index_by_close.get(int(row.timestamp))
    if index is None or index + config.horizon_bars >= len(bars):
        return None
    current = float(bars[index].close)
    future = bars[index + 1 : index + config.horizon_bars + 1]
    returns = np.asarray(
        [(float(bar.close) / current - 1.0) * 10_000.0 for bar in future],
        dtype=float,
    )
    outcome = "unresolved"
    bars_to_resolution: int | None = None
    for offset, value in enumerate(returns, start=1):
        if value >= config.barrier_bps:
            outcome = "up"
            bars_to_resolution = offset
            break
        if value <= -config.barrier_bps:
            outcome = "down"
            bars_to_resolution = offset
            break
    resolved = outcome != "unresolved"
    return PathEvent(
        symbol=row.symbol,
        timestamp=int(row.timestamp),
        target_timestamp=int(future[-1].close_timestamp),
        year=_year(row.timestamp),
        outcome=outcome,
        hit=outcome == "up",
        resolved=resolved,
        bars_to_resolution=bars_to_resolution,
        terminal_return_bps=float(returns[-1]),
        max_return_bps=float(np.max(returns)),
        min_return_bps=float(np.min(returns)),
        features=tuple(
            float(row.features[name])
            for name in MODEL_FEATURES
        ),
    )


def _bar_index(
    bars: Sequence[PathBar] | Sequence[FuturesBar],
) -> dict[int, int]:
    cache_key = id(bars)
    cached = _BAR_INDEX_CACHE.get(cache_key)
    if cached is None:
        cached = {
            int(bar.close_timestamp): index
            for index, bar in enumerate(bars)
        }
        _BAR_INDEX_CACHE[cache_key] = cached
    return cached


def collapse_overlapping_rows(
    rows: Sequence[FeatureRow],
    *,
    horizon_bars: int,
) -> list[FeatureRow]:
    horizon_seconds = horizon_bars * 4 * 60 * 60
    next_allowed: dict[str, int] = {}
    output = []
    for row in sorted(rows, key=lambda item: (item.timestamp, item.symbol)):
        if row.timestamp < next_allowed.get(row.symbol, 0):
            continue
        output.append(row)
        next_allowed[row.symbol] = row.timestamp + horizon_seconds
    return output


def unconditional_barrier_rate(
    rows: Sequence[FeatureRow],
    bundles: Mapping[str, Sequence[PathBar]],
    *,
    config: PathConfig,
    start: int,
    end: int,
) -> float:
    candidates = [
        row
        for row in rows
        if start <= row.timestamp < end
        and row.symbol in bundles
    ]
    candidates = collapse_overlapping_rows(
        candidates,
        horizon_bars=config.horizon_bars,
    )
    events = [
        event
        for row in candidates
        if (
            event := resolve_path(
                row,
                bundles[row.symbol],
                config=config,
            )
        )
        is not None
    ]
    return (
        sum(event.hit for event in events) / len(events)
        if events
        else 0.0
    )


def summarize_events(
    events: Sequence[PathEvent],
    *,
    unconditional_up_rate: float,
) -> dict[str, Any]:
    signals = len(events)
    hits = sum(event.hit for event in events)
    resolved = sum(event.resolved for event in events)
    by_year = _group(events, "year")
    by_symbol = _group(events, "symbol")
    supported_years = [
        row for row in by_year if int(row["signals"]) >= MIN_SLICE_SIGNALS
    ]
    supported_symbols = [
        row for row in by_symbol if int(row["signals"]) >= MIN_SLICE_SIGNALS
    ]
    conservative_accuracy = hits / signals if signals else 0.0
    return {
        "signals": signals,
        "hits": hits,
        "resolved": resolved,
        "unresolved": signals - resolved,
        "resolution_rate": resolved / signals if signals else 0.0,
        "conservative_accuracy": conservative_accuracy,
        "resolved_accuracy": hits / resolved if resolved else 0.0,
        "wilson_low_95": _wilson_low(hits, signals) if signals else 0.0,
        "unconditional_up_rate": unconditional_up_rate,
        "uplift_over_unconditional": (
            conservative_accuracy - unconditional_up_rate
        ),
        "by_year": by_year,
        "by_symbol": by_symbol,
        "worst_supported_year_accuracy": min(
            (
                float(row["conservative_accuracy"])
                for row in supported_years
            ),
            default=None,
        ),
        "worst_supported_symbol_accuracy": min(
            (
                float(row["conservative_accuracy"])
                for row in supported_symbols
            ),
            default=None,
        ),
    }


def evaluate_path_models(
    training_events: Sequence[PathEvent],
    evaluation_events: Sequence[PathEvent],
    *,
    seed: int,
) -> dict[str, dict[str, Any]]:
    if len(training_events) < 10 or len(evaluation_events) < 10:
        raise ValueError(
            "path model evaluation needs at least 10 events per split: "
            f"train={len(training_events)}, evaluation={len(evaluation_events)}"
        )
    train_x = np.asarray(
        [event.features for event in training_events],
        dtype=float,
    )
    train_y = np.asarray(
        [event.outcome == "up" for event in training_events],
        dtype=int,
    )
    evaluation_x = np.asarray(
        [event.features for event in evaluation_events],
        dtype=float,
    )
    if len(np.unique(train_y)) < 2:
        raise ValueError("path model training needs both outcome classes")
    probabilities = candidate_probabilities(
        train_x,
        train_y,
        evaluation_x,
        seed=seed,
    )
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            'Install research dependencies with pip install -e ".[crypto-ml]"'
        ) from exc
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    normalized_train = scaler.fit_transform(imputer.fit_transform(train_x))
    normalized_evaluation = scaler.transform(
        imputer.transform(evaluation_x)
    )
    topological = _topological_wavefield_probability(
        normalized_train,
        train_y,
        normalized_evaluation,
        seed=seed,
    )
    probabilities = {
        "always_rebound": np.ones(len(evaluation_events), dtype=float),
        "always_continuation": np.zeros(len(evaluation_events), dtype=float),
        **probabilities,
        "topological_wavefield": topological,
        "topological_tree_hybrid": (
            0.5 * probabilities["extra_trees"] + 0.5 * topological
        ),
    }
    return {
        name: summarize_model_predictions(
            evaluation_events,
            values,
        )
        for name, values in probabilities.items()
    }


def summarize_model_predictions(
    events: Sequence[PathEvent],
    probabilities: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    probability = np.asarray(probabilities, dtype=float)
    if len(events) != len(probability):
        raise ValueError("events and probabilities must align")
    truth = np.asarray([event.outcome == "up" for event in events], dtype=bool)
    resolved = np.asarray([event.resolved for event in events], dtype=bool)
    prediction = probability >= 0.5
    correct = resolved & (prediction == truth)
    by_year = _group_predictions(events, correct, "year")
    by_symbol = _group_predictions(events, correct, "symbol")
    supported_years = [
        row for row in by_year if int(row["signals"]) >= MIN_SLICE_SIGNALS
    ]
    supported_symbols = [
        row for row in by_symbol if int(row["signals"]) >= MIN_SLICE_SIGNALS
    ]
    signals = len(events)
    hits = int(np.sum(correct))
    resolved_count = int(np.sum(resolved))
    always_up_hits = int(np.sum(resolved & truth))
    always_down_hits = int(np.sum(resolved & ~truth))
    best_constant = max(always_up_hits, always_down_hits) / signals
    accuracy = hits / signals
    resolved_indexes = np.flatnonzero(resolved)
    brier = (
        float(
            np.mean(
                (probability[resolved_indexes] - truth[resolved_indexes]) ** 2
            )
        )
        if len(resolved_indexes)
        else 1.0
    )
    return {
        "signals": signals,
        "hits": hits,
        "resolved": resolved_count,
        "unresolved": signals - resolved_count,
        "resolution_rate": resolved_count / signals,
        "conservative_accuracy": accuracy,
        "resolved_accuracy": hits / resolved_count if resolved_count else 0.0,
        "wilson_low_95": _wilson_low(hits, signals),
        "best_constant_accuracy": best_constant,
        "unconditional_up_rate": best_constant,
        "uplift_over_unconditional": accuracy - best_constant,
        "brier_score_resolved": brier,
        "predicted_up_rate": float(np.mean(prediction)),
        "actual_up_rate_resolved": (
            float(np.mean(truth[resolved_indexes]))
            if len(resolved_indexes)
            else 0.0
        ),
        "by_year": by_year,
        "by_symbol": by_symbol,
        "worst_supported_year_accuracy": min(
            (
                float(row["conservative_accuracy"])
                for row in supported_years
            ),
            default=None,
        ),
        "worst_supported_symbol_accuracy": min(
            (
                float(row["conservative_accuracy"])
                for row in supported_symbols
            ),
            default=None,
        ),
    }


def path_admitted_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= MIN_FINAL_SIGNALS
        and float(summary["conservative_accuracy"]) >= 0.70
        and float(summary["wilson_low_95"]) >= 0.65
        and float(summary["resolution_rate"]) >= MIN_RESOLUTION_RATE
        and float(summary["worst_supported_year_accuracy"] or 0.0) >= 0.65
        and float(summary["worst_supported_symbol_accuracy"] or 0.0) >= 0.65
        and float(summary["uplift_over_unconditional"]) >= MIN_UPLIFT
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    development = payload["development_selected"]["summary"]
    final = payload["selected_final"]
    config = payload["selected_config"]
    lines = [
        "# Post-Capitulation Barrier Path Benchmark",
        "",
        (
            "A symmetric barrier race tests whether a post-capitulation rebound "
            "reaches the upper target before the equal lower target."
        ),
        "",
        f"- selected horizon: {config['horizon_bars'] * 4}h;",
        f"- symmetric barrier: {config['barrier_bps']:.0f} bps;",
        f"- selected outcome model: {payload['selected_model']};",
        "- unresolved paths count as misses;",
        (
            "- final assets are disjoint from development assets;"
            if payload["asset_disjoint"]
            else "- this is the temporal development test; asset-disjoint "
            "replication is still required;"
        ),
        "",
        "| split | signals | conservative accuracy | resolved accuracy | resolution | Wilson low | unconditional | uplift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        _summary_row("development", development),
        _summary_row("final", final),
        "",
        "## Model Transfer",
        "",
        "| model | validation accuracy | final accuracy | final Wilson | final uplift |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in MODEL_ORDER:
        validation = payload["validation_models"][model]
        model_final = payload["final_models"][model]
        lines.append(
            f"| {model} | "
            f"{_percent(validation['conservative_accuracy'])} | "
            f"{_percent(model_final['conservative_accuracy'])} | "
            f"{_percent(model_final['wilson_low_95'])} | "
            f"{_percent(model_final['uplift_over_unconditional'])} |"
        )
    lines.extend(
        [
        "",
        f"Strict 70% admission: **{'passed' if payload['admitted_70'] else 'rejected'}**.",
        "",
        ]
    )
    return "\n".join(lines)


def _summary_row(name: str, summary: Mapping[str, Any]) -> str:
    return (
        f"| {name} | {summary['signals']} | "
        f"{_percent(summary['conservative_accuracy'])} | "
        f"{_percent(summary['resolved_accuracy'])} | "
        f"{_percent(summary['resolution_rate'])} | "
        f"{_percent(summary['wilson_low_95'])} | "
        f"{_percent(summary['unconditional_up_rate'])} | "
        f"{_percent(summary['uplift_over_unconditional'])} |"
    )


def _selection_key(result: Mapping[str, Any]) -> tuple[float, float, float, int]:
    summary = result["summary"]
    return (
        float(summary["worst_supported_year_accuracy"] or 0.0),
        float(summary["wilson_low_95"]),
        float(summary["uplift_over_unconditional"]),
        int(summary["signals"]),
    )


def _model_selection_key(
    summary: Mapping[str, Any],
    model: str,
) -> tuple[float, float, float, float, int]:
    return (
        float(summary["worst_supported_year_accuracy"] or 0.0),
        float(summary["wilson_low_95"]),
        float(summary["uplift_over_unconditional"]),
        -MODEL_ORDER.index(model),
        -float(summary["brier_score_resolved"]),
    )


def _group(events: Sequence[PathEvent], field: str) -> list[dict[str, Any]]:
    values = sorted({getattr(event, field) for event in events})
    output = []
    for value in values:
        selected = [event for event in events if getattr(event, field) == value]
        hits = sum(event.hit for event in selected)
        resolved = sum(event.resolved for event in selected)
        output.append(
            {
                field: value,
                "signals": len(selected),
                "hits": hits,
                "resolved": resolved,
                "conservative_accuracy": hits / len(selected),
                "resolved_accuracy": hits / resolved if resolved else 0.0,
                "wilson_low_95": _wilson_low(hits, len(selected)),
            }
        )
    return output


def _group_predictions(
    events: Sequence[PathEvent],
    correct: np.ndarray,
    field: str,
) -> list[dict[str, Any]]:
    values = sorted({getattr(event, field) for event in events})
    output = []
    for value in values:
        indexes = [
            index
            for index, event in enumerate(events)
            if getattr(event, field) == value
        ]
        hits = int(np.sum(correct[indexes]))
        output.append(
            {
                field: value,
                "signals": len(indexes),
                "hits": hits,
                "conservative_accuracy": hits / len(indexes),
                "wilson_low_95": _wilson_low(hits, len(indexes)),
            }
        )
    return output


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _year(timestamp: int) -> int:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{100.0 * float(value):.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a strict post-capitulation barrier path."
    )
    parser.add_argument("--development-bundles", nargs="+", type=Path, required=True)
    parser.add_argument("--final-bundles", nargs="+", type=Path, required=True)
    parser.add_argument("--development-rows-cache", nargs="+", type=Path)
    parser.add_argument("--final-rows-cache", nargs="+", type=Path)
    parser.add_argument("--development-bars-cache", nargs="+", type=Path)
    parser.add_argument("--final-bars-cache", nargs="+", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    development_rows, development_bundles = load_rows_and_bundles(
        args.development_bundles,
        rows_cache=args.development_rows_cache,
        bars_cache=args.development_bars_cache,
    )
    final_rows, final_bundles = load_rows_and_bundles(
        args.final_bundles,
        rows_cache=args.final_rows_cache,
        bars_cache=args.final_bars_cache,
    )
    payload = run_path_benchmark(
        development_rows,
        development_bundles,
        final_rows,
        final_bundles,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
