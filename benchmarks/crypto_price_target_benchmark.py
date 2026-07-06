from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_current_forecast import (  # noqa: E402
    _momentum_directional_return,
    forced_directional_forecast,
)
from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    OHLCVWindow,
    fetch_ohlcv_ccxt,
    generate_synthetic_ohlcv,
    load_ohlcv_csv,
    make_ohlcv_windows,
    save_ohlcv_csv,
    timeframe_to_seconds,
)
from benchmarks.crypto_walk_forward_benchmark import _regime_signature_from_window  # noqa: E402


DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT", "DOGE/USDT", "LINK/USDT", "AVAX/USDT")
DEFAULT_TIMEFRAMES = ("1h", "4h", "1d")
DEFAULT_HORIZONS = {"1h": 24, "4h": 6, "1d": 7}
DEFAULT_EVENT_SAMPLE_SIZE = 240


@dataclass(frozen=True)
class PriceTargetEvent:
    engine: str
    symbol: str
    timeframe: str
    fold_index: int
    query_id: str
    data_end_utc: str
    target_end_utc: str
    last_close: float
    actual_return_bps: float
    predicted_return_bps: float
    actual_price: float
    predicted_price: float
    abs_return_error_bps: float
    abs_price_error: float
    abs_pct_error: float
    squared_return_error_bps: float
    direction_hit: float
    predicted_direction: str
    actual_direction: str
    support: int
    method: str


@dataclass(frozen=True)
class ReturnCalibration:
    slope: float
    intercept_bps: float
    cap_abs_bps: float
    samples: int
    raw_mae_bps: float
    calibrated_mae_bps: float
    note: str


@dataclass(frozen=True)
class EnsembleCalibration:
    weights: dict[str, float]
    component_mae_bps: dict[str, float]
    samples: int
    validation_mae_bps: float
    best_component: str
    note: str


@dataclass(frozen=True)
class TargetModelCalibration:
    enabled: bool
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept_bps: float
    cap_abs_bps: float
    alpha: float
    validation_mae_bps: float
    validation_direction_hit: float
    robust_validation_mae_bps: float
    robust_validation_direction_hit: float
    samples: int
    note: str


@dataclass(frozen=True)
class DirectionalPolicyCalibration:
    selected_candidate: str
    validation_direction_hit: float
    validation_mae_bps: float
    samples: int
    candidate_direction_hit: dict[str, float]
    candidate_mae_bps: dict[str, float]
    note: str


def run_price_target_benchmark(
    *,
    markets: list[dict],
    engines: Iterable[str],
    train_windows: int = 360,
    test_windows: int = 90,
    folds: int = 4,
    fold_stride: int | None = None,
    calibration_windows: int = 120,
) -> dict:
    engine_keys = [_normalize_engine_key(engine) for engine in engines]
    events: list[PriceTargetEvent] = []
    by_market: list[dict] = []
    for market in markets:
        windows = list(market["windows"])
        starts = _fold_starts(windows, train_windows=train_windows, test_windows=test_windows, folds=folds, fold_stride=fold_stride)
        for fold_index, fold_start in enumerate(starts):
            queries = windows[fold_start : fold_start + test_windows]
            fold_calibration = _fit_wave_calibration(
                windows[:fold_start],
                horizon=int(market["horizon"]),
                calibration_windows=calibration_windows,
            )
            fold_ensemble = _fit_ensemble_calibration(
                windows[:fold_start],
                horizon=int(market["horizon"]),
                calibration_windows=calibration_windows,
            )
            fold_target_model = (
                _fit_target_model(
                    windows[:fold_start],
                    horizon=int(market["horizon"]),
                    calibration=fold_calibration,
                    calibration_windows=calibration_windows,
                )
                if "wavemind-learned-target" in engine_keys
                else _disabled_target_model("not_requested")
            )
            fold_directional_policy = (
                _fit_directional_policy(
                    windows[:fold_start],
                    horizon=int(market["horizon"]),
                    calibration=fold_calibration,
                    calibration_windows=calibration_windows,
                )
                if "wavemind-perp-field-target" in engine_keys
                else _default_directional_policy("not_requested")
            )
            fold_events: list[PriceTargetEvent] = []
            for query in queries:
                history = _mature_history(windows, current=query)
                if len(history) < 4:
                    continue
                for engine_key in engine_keys:
                    predicted_return_bps, support, method = _predict_return(
                        engine_key,
                        history,
                        query,
                        horizon=int(market["horizon"]),
                        calibration=fold_calibration,
                        ensemble=fold_ensemble,
                        target_model=fold_target_model,
                        directional_policy=fold_directional_policy,
                    )
                    event = _price_target_event(
                        engine=_engine_name(engine_key),
                        window=query,
                        predicted_return_bps=predicted_return_bps,
                        support=support,
                        method=method,
                        fold_index=fold_index,
                    )
                    events.append(event)
                    fold_events.append(event)
            for engine_key in engine_keys:
                engine_events = [event for event in fold_events if event.engine == _engine_name(engine_key)]
                fold_metadata = {
                    "fold_start": int(fold_start),
                    "calibration": asdict(fold_calibration),
                    "ensemble": asdict(fold_ensemble),
                }
                if "wavemind-learned-target" in engine_keys:
                    fold_metadata["target_model"] = asdict(fold_target_model)
                if "wavemind-perp-field-target" in engine_keys:
                    fold_metadata["directional_policy"] = asdict(fold_directional_policy)
                by_market.append(
                    _summarize_events(
                        engine_events,
                        engine=_engine_name(engine_key),
                        symbol=str(market["symbol"]),
                        timeframe=str(market["timeframe"]),
                        fold_index=fold_index,
                    )
                    | fold_metadata
                )
    results = [_summarize_events([event for event in events if event.engine == _engine_name(engine)], engine=_engine_name(engine)) for engine in engine_keys]
    _attach_robustness(results, by_market)
    return {
        "scenario": {
            "name": "crypto_price_target_walk_forward",
            "target": "predict future close price, not only up/down direction",
            "train_windows": int(train_windows),
            "test_windows": int(test_windows),
            "folds": int(folds),
            "fold_stride": int(fold_stride) if fold_stride is not None else None,
            "calibration_windows": int(calibration_windows),
            "markets": [
                {
                    "symbol": str(market["symbol"]),
                    "timeframe": str(market["timeframe"]),
                    "horizon_bars": int(market["horizon"]),
                    "horizon_seconds": int(market["horizon"]) * timeframe_to_seconds(str(market["timeframe"])),
                    "bars": len(market["bars"]),
                    "windows": len(market["windows"]),
                    "source": str(market["source"]),
                }
                for market in markets
            ],
            "note": "Research benchmark only. It checks historical target-price error without lookahead; it is not financial advice.",
        },
        "results": results,
        "by_market": by_market,
        "event_metrics": [asdict(event) for event in events],
    }


def sampled_event_payload(payload: dict, *, sample_size: int = DEFAULT_EVENT_SAMPLE_SIZE) -> dict:
    """Return a repo-friendly payload with bounded event-level records."""
    events = list(payload.get("event_metrics", []))
    copied = dict(payload)
    copied["event_metrics_total"] = len(events)
    copied["event_metrics_sample_size"] = min(int(sample_size), len(events))
    copied["event_metrics_truncated"] = len(events) > int(sample_size)
    copied["event_metrics"] = events[: int(sample_size)]
    return copied


def load_markets(
    *,
    dataset: str,
    symbols: Iterable[str],
    timeframes: Iterable[str],
    exchange: str,
    cache_dir: Path,
    bars: int,
    window: int,
    seed: int = 7,
) -> list[dict]:
    markets = []
    for symbol in symbols:
        normalized_symbol = _normalize_symbol(symbol)
        for timeframe in timeframes:
            horizon = DEFAULT_HORIZONS.get(timeframe)
            if horizon is None:
                raise ValueError(f"No default horizon for timeframe {timeframe!r}")
            source = dataset
            if dataset == "synthetic":
                raw_bars = generate_synthetic_ohlcv(symbol=normalized_symbol, timeframe=timeframe, bars=bars, seed=seed)
            elif dataset == "cached":
                path = _cache_path(cache_dir, exchange, normalized_symbol, timeframe)
                raw_bars = load_ohlcv_csv(path)
                source = str(path)
            elif dataset == "ccxt":
                raw_bars = fetch_ohlcv_ccxt(exchange_id=exchange, symbol=normalized_symbol, timeframe=timeframe, limit=bars)
                path = _cache_path(cache_dir, exchange, normalized_symbol, timeframe)
                save_ohlcv_csv(path, raw_bars)
                source = f"{exchange}:{normalized_symbol}:{timeframe}"
            else:
                raise ValueError("dataset must be synthetic, cached, or ccxt")
            selected_bars = list(raw_bars)[-bars:]
            windows = make_ohlcv_windows(
                selected_bars,
                symbol=normalized_symbol,
                timeframe=timeframe,
                window=window,
                horizon=horizon,
                direction_threshold_bps=0.0,
            )
            markets.append(
                {
                    "symbol": normalized_symbol,
                    "timeframe": timeframe,
                    "horizon": horizon,
                    "bars": selected_bars,
                    "windows": windows,
                    "source": source,
                }
            )
    return markets


def render_markdown(payload: dict) -> str:
    lines = [
        "# WaveMind Crypto Price Target Benchmark",
        "",
        "Walk-forward benchmark for predicted future close price. This is not financial advice.",
        "",
        "## Summary",
        "",
        "| engine | queries | direction hit | MAE return | RMSE return | MAPE | within 50 bps | worst slice hit | worst slice MAPE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in payload["results"]:
        lines.append(
            "| "
            f"{result['engine']} | {result['queries']} | {result['direction_hit_rate']:.3f} | "
            f"{result['mean_abs_return_error_bps']:.1f} bps | {result['rmse_return_error_bps']:.1f} bps | "
            f"{result['mape_pct']:.2f}% | {result['within_50bps_rate']:.3f} | "
            f"{result.get('worst_slice_direction_hit_rate', 0.0):.3f} | {result.get('worst_slice_mape_pct', 0.0):.2f}% |"
        )
    lines.extend(
        [
            "",
            "## By Market",
            "",
            "| engine | symbol | timeframe | fold | queries | direction hit | MAE return | MAPE | bias |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["by_market"]:
        lines.append(
            "| "
            f"{row['engine']} | {row['symbol']} | {row['timeframe']} | {row['fold_index']} | "
            f"{row['queries']} | {row['direction_hit_rate']:.3f} | "
            f"{row['mean_abs_return_error_bps']:.1f} bps | {row['mape_pct']:.2f}% | "
            f"{row['bias_bps']:.1f} bps |"
        )
    lines.extend(
        [
            "",
            "The benchmark uses only matured historical windows for every query. A prediction can be wrong; the point of this report is to measure where price targets are stable and where the model needs more work.",
            "",
        ]
    )
    return "\n".join(lines)


def _predict_return(
    engine_key: str,
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
    ensemble: EnsembleCalibration,
    target_model: TargetModelCalibration,
    directional_policy: DirectionalPolicyCalibration,
) -> tuple[float, int, str]:
    if engine_key == "wavemind-ensemble":
        components = _component_predictions(history, query, horizon=horizon)
        value = sum(float(components[name]) * float(weight) for name, weight in ensemble.weights.items())
        support = len(_regime_matches(history, query))
        method = f"fold_local_field_ensemble:{ensemble.best_component}"
        return _force_nonzero(value, fallback=components.get("wave", _last_actual_return(history))), support, method
    if engine_key == "wavemind-robust-target":
        return _robust_target_return(history, query, horizon=horizon, calibration=calibration)
    if engine_key == "wavemind-market-field-target":
        return _market_field_target_return(history, query, horizon=horizon, calibration=calibration)
    if engine_key == "wavemind-perp-field-target":
        return _perp_field_target_return(
            history,
            query,
            horizon=horizon,
            calibration=calibration,
            directional_policy=directional_policy,
        )
    if engine_key == "wavemind-learned-target":
        features = _target_model_features(history, query, horizon=horizon, calibration=calibration)
        robust_value, robust_suffix = _robust_value_from_features(features, query.timeframe)
        robust_support = int(max(0.0, round(features.get("support_count", 0.0))))
        robust_method = f"feature_components+{robust_suffix}"
        if not target_model.enabled:
            return robust_value, robust_support, f"{robust_method}+learned_disabled:{target_model.note}"
        value = _predict_target_model_from_features(target_model, features)
        value = math.copysign(min(abs(value), abs(robust_value)), robust_value)
        return _force_nonzero(value, fallback=robust_value), robust_support, f"{robust_method}+learned_ridge_safe"
    if engine_key in {"wavemind-target", "wavemind-calibrated"}:
        forecast = forced_directional_forecast(history, query, horizon=horizon)
        value = forecast.expected_return_bps
        method = forecast.method
        if engine_key == "wavemind-calibrated":
            value = _apply_calibration(value, calibration)
            method = f"{method}+fold_calibration"
        return _force_nonzero(value, fallback=forecast.expected_return_bps), forecast.support, method
    if engine_key == "momentum":
        value = _momentum_directional_return(query, horizon=horizon)
        return _force_nonzero(value, fallback=_last_actual_return(history)), 0, "momentum"
    if engine_key == "regime-mean":
        matches = _regime_matches(history, query)
        value = statistics.mean(window.future_return_bps for window in matches) if matches else _last_actual_return(history)
        return _force_nonzero(value, fallback=_last_actual_return(history)), len(matches), "regime_mean"
    if engine_key == "historical-mean":
        value = statistics.mean(window.future_return_bps for window in history)
        return _force_nonzero(value, fallback=_last_actual_return(history)), len(history), "historical_mean"
    if engine_key == "naive-last":
        value = _last_actual_return(history)
        return _force_nonzero(value, fallback=1.0), 1, "last_mature_outcome"
    raise ValueError(f"Unknown engine {engine_key!r}")


def _robust_target_return(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
) -> tuple[float, int, str]:
    forecast = forced_directional_forecast(history, query, horizon=horizon)
    matches = _regime_matches(history, query)
    last_outcome = _last_actual_return(history)
    raw_wave = _force_nonzero(forecast.expected_return_bps, fallback=last_outcome)
    calibrated_wave = _force_nonzero(_apply_calibration(raw_wave, calibration), fallback=raw_wave)
    momentum = _force_nonzero(_momentum_directional_return(query, horizon=horizon), fallback=last_outcome)
    regime = _force_nonzero(
        statistics.mean(window.future_return_bps for window in matches) if matches else last_outcome,
        fallback=last_outcome,
    )
    historical = _force_nonzero(statistics.mean(window.future_return_bps for window in history), fallback=last_outcome)
    naive = _force_nonzero(last_outcome, fallback=1.0)

    if query.timeframe == "1h":
        value = _robust_1h_target_value(
            calibrated_wave=calibrated_wave,
            momentum=momentum,
            naive=naive,
            features=query.features,
        )
        method = f"{forecast.method}+robust_1h_rsi_extreme_guard"
    elif query.timeframe == "4h":
        value = 0.35 * raw_wave + 0.45 * historical + 0.20 * calibrated_wave
        method = f"{forecast.method}+robust_4h_error_guard"
    elif query.timeframe == "1d":
        value = _robust_1d_target_value(
            calibrated_wave=calibrated_wave,
            momentum=momentum,
            regime=regime,
            features=query.features,
        )
        method = f"{forecast.method}+robust_1d_volatility_guard"
    else:
        value = calibrated_wave
        method = f"{forecast.method}+robust_calibration"
    support = max(int(forecast.support), len(matches))
    return _force_nonzero(value, fallback=calibrated_wave), support, method


def _market_field_target_return(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
) -> tuple[float, int, str]:
    features = _target_model_features(history, query, horizon=horizon, calibration=calibration)
    value, suffix = _market_field_value_from_features(features, query.timeframe)
    support = int(max(0.0, round(features.get("support_count", 0.0))))
    return value, support, f"timeframe_market_field_v1:{suffix}"


def _perp_field_target_return(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
    directional_policy: DirectionalPolicyCalibration,
) -> tuple[float, int, str]:
    features = _target_model_features(history, query, horizon=horizon, calibration=calibration)
    value, suffix = _perp_field_value_from_features(features, query.timeframe, directional_policy)
    support = int(max(0.0, round(features.get("support_count", 0.0))))
    return value, support, f"fold_local_perp_field_v1:{suffix}"


TARGET_MODEL_FEATURES = (
    "raw_wave",
    "calibrated_wave",
    "momentum",
    "regime",
    "historical",
    "naive",
    "support_log",
    "wave_momentum_agreement",
    "wave_regime_agreement",
    "window_return_bps",
    "recent_return_bps",
    "range_bps",
    "volatility_bps",
    "drawdown_bps",
    "trend_slope_bps",
    "macd_bps",
    "bollinger_position",
    "range_compression",
    "volume_ratio",
    "rsi",
    "close_position",
    "trend_code",
    "recent_trend_code",
)


def _disabled_target_model(note: str) -> TargetModelCalibration:
    return TargetModelCalibration(
        enabled=False,
        feature_names=(),
        means=(),
        scales=(),
        coefficients=(),
        intercept_bps=0.0,
        cap_abs_bps=0.0,
        alpha=0.0,
        validation_mae_bps=math.inf,
        validation_direction_hit=0.0,
        robust_validation_mae_bps=math.inf,
        robust_validation_direction_hit=0.0,
        samples=0,
        note=note,
    )


def _fit_target_model(
    history: list[OHLCVWindow],
    *,
    horizon: int,
    calibration: ReturnCalibration,
    calibration_windows: int,
) -> TargetModelCalibration:
    timeframe = str(history[-1].timeframe) if history else ""
    if timeframe != "1h":
        return _disabled_target_model("learned_magnitude_head_enabled_for_1h_only")
    if len(history) < max(90, calibration_windows):
        return _disabled_target_model("insufficient_history")
    model_windows = min(int(calibration_windows), 72)
    start = max(32, len(history) - model_windows)
    rows: list[tuple[dict[str, float], float, float]] = []
    for index in range(start, len(history)):
        prior = history[:index]
        if len(prior) < 24:
            continue
        features = _target_model_features(prior, history[index], horizon=horizon, calibration=calibration)
        robust_value, _ = _robust_value_from_features(features, history[index].timeframe)
        rows.append((features, float(history[index].future_return_bps), float(robust_value)))
    if len(rows) < 48:
        return _disabled_target_model("insufficient_calibration_samples")

    names = TARGET_MODEL_FEATURES
    x_all = np.array([[features.get(name, 0.0) for name in names] for features, _, _ in rows], dtype=float)
    y_all = np.array([actual for _, actual, _ in rows], dtype=float)
    robust_all = np.array([robust for _, _, robust in rows], dtype=float)
    split = min(len(rows) - 12, max(24, int(len(rows) * 0.70)))
    if split <= 0 or split >= len(rows):
        return _disabled_target_model("invalid_validation_split")

    x_train, y_train = x_all[:split], y_all[:split]
    x_val, y_val = x_all[split:], y_all[split:]
    robust_val = robust_all[split:]
    robust_mae = float(np.mean(np.abs(robust_val - y_val)))
    robust_hit = float(np.mean([1.0 if _signed_direction(pred) == _signed_direction(actual) else 0.0 for pred, actual in zip(robust_val, y_val)]))

    best: tuple[float, float, float, TargetModelCalibration] | None = None
    for alpha in (0.1, 1.0, 10.0, 100.0, 1000.0):
        candidate = _fit_ridge_target_model(names, x_train, y_train, alpha=alpha)
        predicted = np.array([_predict_target_model_from_array(candidate, row) for row in x_val], dtype=float)
        predicted = np.copysign(np.minimum(np.abs(predicted), np.abs(robust_val)), robust_val)
        mae = float(np.mean(np.abs(predicted - y_val)))
        hit = float(np.mean([1.0 if _signed_direction(pred) == _signed_direction(actual) else 0.0 for pred, actual in zip(predicted, y_val)]))
        score = mae * (1.0 + max(0.0, robust_hit - hit))
        ranked = (score, mae, -hit, candidate)
        if best is None or ranked < best:
            best = ranked

    assert best is not None
    _, validation_mae, negative_hit, _ = best
    validation_hit = -negative_hit
    materially_lower_error = validation_mae <= robust_mae * 0.965 and validation_hit >= robust_hit - 0.02
    materially_better_direction = validation_hit >= robust_hit + 0.05 and validation_mae <= robust_mae * 1.01
    if not (materially_lower_error or materially_better_direction):
        disabled = _disabled_target_model("validation_not_better_than_robust")
        return TargetModelCalibration(
            enabled=disabled.enabled,
            feature_names=disabled.feature_names,
            means=disabled.means,
            scales=disabled.scales,
            coefficients=disabled.coefficients,
            intercept_bps=disabled.intercept_bps,
            cap_abs_bps=disabled.cap_abs_bps,
            alpha=disabled.alpha,
            validation_mae_bps=validation_mae,
            validation_direction_hit=validation_hit,
            robust_validation_mae_bps=robust_mae,
            robust_validation_direction_hit=robust_hit,
            samples=len(rows),
            note=disabled.note,
        )

    final_model = _fit_ridge_target_model(names, x_all, y_all, alpha=best[3].alpha)
    return TargetModelCalibration(
        enabled=True,
        feature_names=final_model.feature_names,
        means=final_model.means,
        scales=final_model.scales,
        coefficients=final_model.coefficients,
        intercept_bps=final_model.intercept_bps,
        cap_abs_bps=final_model.cap_abs_bps,
        alpha=final_model.alpha,
        validation_mae_bps=validation_mae,
        validation_direction_hit=validation_hit,
        robust_validation_mae_bps=robust_mae,
        robust_validation_direction_hit=robust_hit,
        samples=len(rows),
        note="fold-local ridge target head enabled after validation gate",
    )


def _fit_ridge_target_model(
    feature_names: tuple[str, ...],
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    alpha: float,
) -> TargetModelCalibration:
    means = x_values.mean(axis=0)
    scales = x_values.std(axis=0)
    scales = np.where(scales <= 1e-9, 1.0, scales)
    centered = (x_values - means) / scales
    y_mean = float(y_values.mean())
    system = centered.T @ centered + float(alpha) * np.eye(centered.shape[1])
    target = centered.T @ (y_values - y_mean)
    try:
        coefficients = np.linalg.solve(system, target)
    except np.linalg.LinAlgError:
        coefficients = np.linalg.pinv(system) @ target
    cap_abs_bps = max(25.0, float(np.quantile(np.abs(y_values), 0.90)) * 1.25)
    return TargetModelCalibration(
        enabled=True,
        feature_names=tuple(feature_names),
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept_bps=y_mean,
        cap_abs_bps=cap_abs_bps,
        alpha=float(alpha),
        validation_mae_bps=math.inf,
        validation_direction_hit=0.0,
        robust_validation_mae_bps=math.inf,
        robust_validation_direction_hit=0.0,
        samples=int(len(y_values)),
        note="ridge target model",
    )


def _predict_target_model(
    model: TargetModelCalibration,
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
) -> float:
    features = _target_model_features(history, query, horizon=horizon, calibration=calibration)
    row = np.array([features.get(name, 0.0) for name in model.feature_names], dtype=float)
    return _predict_target_model_from_array(model, row)


def _predict_target_model_from_features(model: TargetModelCalibration, features: dict[str, float]) -> float:
    row = np.array([features.get(name, 0.0) for name in model.feature_names], dtype=float)
    return _predict_target_model_from_array(model, row)


def _predict_target_model_from_array(model: TargetModelCalibration, row: np.ndarray) -> float:
    means = np.array(model.means, dtype=float)
    scales = np.array(model.scales, dtype=float)
    coefficients = np.array(model.coefficients, dtype=float)
    value = float(model.intercept_bps + np.dot((row - means) / scales, coefficients))
    return float(np.clip(value, -model.cap_abs_bps, model.cap_abs_bps))


def _robust_value_from_features(features: dict[str, float], timeframe: str) -> tuple[float, str]:
    raw_wave = float(features.get("raw_wave", 0.0))
    calibrated_wave = float(features.get("calibrated_wave", raw_wave))
    momentum = float(features.get("momentum", calibrated_wave))
    regime = float(features.get("regime", calibrated_wave))
    historical = float(features.get("historical", calibrated_wave))
    naive = float(features.get("naive", momentum))
    if timeframe == "1h":
        value = _robust_1h_target_value(
            calibrated_wave=calibrated_wave,
            momentum=momentum,
            naive=naive,
            features=features,
        )
        return _force_nonzero(value, fallback=calibrated_wave), "robust_1h_rsi_extreme_guard"
    if timeframe == "4h":
        return _force_nonzero(0.35 * raw_wave + 0.45 * historical + 0.20 * calibrated_wave, fallback=calibrated_wave), "robust_4h_error_guard"
    if timeframe == "1d":
        value = _robust_1d_target_value(
            calibrated_wave=calibrated_wave,
            momentum=momentum,
            regime=regime,
            features=features,
        )
        return _force_nonzero(value, fallback=calibrated_wave), "robust_1d_volatility_guard"
    return _force_nonzero(calibrated_wave, fallback=raw_wave), "robust_calibration"


def _market_field_value_from_features(features: dict[str, float], timeframe: str) -> tuple[float, str]:
    raw_wave = float(features.get("raw_wave", 0.0))
    calibrated_wave = float(features.get("calibrated_wave", raw_wave))
    momentum = float(features.get("momentum", calibrated_wave))
    regime = float(features.get("regime", calibrated_wave))
    historical = float(features.get("historical", calibrated_wave))
    if timeframe == "1h":
        return _force_nonzero(-regime, fallback=-momentum), "intraday_regime_reversion"
    if timeframe == "4h":
        return _force_nonzero(-momentum, fallback=-raw_wave), "swing_momentum_reversion"
    if timeframe == "1d":
        return _force_nonzero(-historical, fallback=calibrated_wave), "daily_historical_reversion"
    robust, suffix = _robust_value_from_features(features, timeframe)
    return robust, f"robust_fallback:{suffix}"


def _perp_field_value_from_features(
    features: dict[str, float],
    timeframe: str,
    directional_policy: DirectionalPolicyCalibration,
) -> tuple[float, str]:
    candidates = _directional_candidate_values(features, timeframe)
    selected = directional_policy.selected_candidate
    if selected not in candidates:
        robust, suffix = _robust_value_from_features(features, timeframe)
        return _force_nonzero(robust, fallback=float(features.get("momentum", 1.0))), f"fallback:{suffix}"
    value = _force_nonzero(candidates[selected], fallback=float(features.get("momentum", 1.0)))
    note = (
        f"{selected}:validation_hit={directional_policy.validation_direction_hit:.3f}:"
        f"validation_mae={directional_policy.validation_mae_bps:.1f}"
    )
    return value, note


def _directional_candidate_values(features: dict[str, float], timeframe: str) -> dict[str, float]:
    raw_wave = _force_nonzero(float(features.get("raw_wave", 0.0)), fallback=float(features.get("naive", 1.0)))
    calibrated_wave = _force_nonzero(float(features.get("calibrated_wave", raw_wave)), fallback=raw_wave)
    momentum = _force_nonzero(float(features.get("momentum", calibrated_wave)), fallback=calibrated_wave)
    regime = _force_nonzero(float(features.get("regime", calibrated_wave)), fallback=calibrated_wave)
    historical = _force_nonzero(float(features.get("historical", calibrated_wave)), fallback=calibrated_wave)
    naive = _force_nonzero(float(features.get("naive", momentum)), fallback=momentum)
    robust, _ = _robust_value_from_features(features, timeframe)
    market_field, _ = _market_field_value_from_features(features, timeframe)
    base = {
        "raw_wave": raw_wave,
        "calibrated_wave": calibrated_wave,
        "momentum": momentum,
        "regime": regime,
        "historical": historical,
        "naive": naive,
        "robust": _force_nonzero(robust, fallback=calibrated_wave),
        "market_field": _force_nonzero(market_field, fallback=calibrated_wave),
    }
    inverted = {f"inv_{name}": -value for name, value in base.items()}
    return base | inverted


def _default_directional_policy(note: str) -> DirectionalPolicyCalibration:
    return DirectionalPolicyCalibration(
        selected_candidate="robust",
        validation_direction_hit=0.0,
        validation_mae_bps=math.inf,
        samples=0,
        candidate_direction_hit={},
        candidate_mae_bps={},
        note=note,
    )


def _fit_directional_policy(
    history: list[OHLCVWindow],
    *,
    horizon: int,
    calibration: ReturnCalibration,
    calibration_windows: int,
) -> DirectionalPolicyCalibration:
    if len(history) < max(40, calibration_windows // 2):
        return _default_directional_policy("insufficient_history")
    start = max(24, len(history) - calibration_windows)
    rows: list[tuple[dict[str, float], float]] = []
    for index in range(start, len(history)):
        prior = history[:index]
        if len(prior) < 16:
            continue
        features = _target_model_features(prior, history[index], horizon=horizon, calibration=calibration)
        rows.append((_directional_candidate_values(features, history[index].timeframe), float(history[index].future_return_bps)))
    if len(rows) < 12:
        return _default_directional_policy("insufficient_calibration_samples")

    names = sorted(
        name
        for name in {name for candidates, _ in rows for name in candidates}
        if name not in {"naive", "inv_naive"}
    )
    candidate_hit: dict[str, float] = {}
    candidate_mae: dict[str, float] = {}
    candidate_magnitude: dict[str, float] = {}
    for name in names:
        predictions = [float(candidates[name]) for candidates, _ in rows if name in candidates]
        actuals = [actual for candidates, actual in rows if name in candidates]
        if not predictions:
            continue
        candidate_hit[name] = statistics.mean(
            1.0 if _signed_direction(prediction) == _signed_direction(actual) else 0.0
            for prediction, actual in zip(predictions, actuals, strict=False)
        )
        candidate_mae[name] = statistics.mean(
            abs(prediction - actual)
            for prediction, actual in zip(predictions, actuals, strict=False)
        )
        candidate_magnitude[name] = statistics.mean(abs(prediction) for prediction in predictions)

    if not candidate_hit:
        return _default_directional_policy("no_candidate_predictions")
    robust_hit = candidate_hit.get("robust", -math.inf)
    robust_mae = candidate_mae.get("robust", math.inf)
    eligible = [
        name
        for name in candidate_hit
        if candidate_hit[name] >= robust_hit + 0.10 and candidate_mae.get(name, math.inf) <= robust_mae * 0.85
    ]
    if eligible:
        selected = max(
            eligible,
            key=lambda name: (
                candidate_hit[name],
                -candidate_mae.get(name, math.inf),
                candidate_magnitude.get(name, 0.0),
            ),
        )
        note = "fold-local component selector beat robust guard on matured pre-test history"
    else:
        selected = "robust" if "robust" in candidate_hit else max(
            candidate_hit,
            key=lambda name: (
                candidate_hit[name],
                -candidate_mae.get(name, math.inf),
                candidate_magnitude.get(name, 0.0),
            ),
        )
        note = "robust anchor kept because no component cleared fold-local improvement guard"
    return DirectionalPolicyCalibration(
        selected_candidate=selected,
        validation_direction_hit=float(candidate_hit[selected]),
        validation_mae_bps=float(candidate_mae[selected]),
        samples=len(rows),
        candidate_direction_hit={name: float(candidate_hit[name]) for name in sorted(candidate_hit)},
        candidate_mae_bps={name: float(candidate_mae[name]) for name in sorted(candidate_mae)},
        note=note,
    )


def _robust_1h_target_value(
    *,
    calibrated_wave: float,
    momentum: float,
    naive: float,
    features: dict[str, object],
) -> float:
    weighted = 0.40 * float(calibrated_wave) + 0.40 * float(momentum) + 0.20 * float(naive)
    sign_source = weighted if _is_rsi_extreme(features) else float(momentum)
    return math.copysign(abs(weighted), sign_source)


def _is_rsi_extreme(features: dict[str, object]) -> bool:
    rsi = _float_feature(features, "rsi", 50.0)
    return rsi < 35.0 or rsi > 65.0


def _robust_1d_target_value(
    *,
    calibrated_wave: float,
    momentum: float,
    regime: float,
    features: dict[str, object],
) -> float:
    base = 0.40 * float(calibrated_wave) + 0.25 * float(momentum) + 0.35 * float(regime)
    volatility_bps = abs(_float_feature(features, "volatility_bps"))
    trend_bps = abs(_float_feature(features, "trend_slope_bps"))
    risk_scale = 1.0 / (1.0 + 1.50 * volatility_bps / 500.0 + trend_bps / 500.0)
    return math.copysign(abs(base) * risk_scale, base)


def _float_feature(features: dict[str, object], name: str, default: float = 0.0) -> float:
    try:
        return float(features.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _target_model_features(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    *,
    horizon: int,
    calibration: ReturnCalibration,
) -> dict[str, float]:
    forecast = forced_directional_forecast(history, query, horizon=horizon)
    matches = _regime_matches(history, query)
    last_outcome = _last_actual_return(history)
    raw_wave = _force_nonzero(forecast.expected_return_bps, fallback=last_outcome)
    calibrated_wave = _force_nonzero(_apply_calibration(raw_wave, calibration), fallback=raw_wave)
    momentum = _force_nonzero(_momentum_directional_return(query, horizon=horizon), fallback=last_outcome)
    regime = _force_nonzero(
        statistics.mean(window.future_return_bps for window in matches) if matches else last_outcome,
        fallback=last_outcome,
    )
    historical = _force_nonzero(statistics.mean(window.future_return_bps for window in history), fallback=last_outcome)
    features = query.features
    return {
        "raw_wave": raw_wave,
        "calibrated_wave": calibrated_wave,
        "momentum": momentum,
        "regime": regime,
        "historical": historical,
        "naive": _force_nonzero(last_outcome, fallback=1.0),
        "support_count": float(max(int(forecast.support), len(matches))),
        "support_log": math.log1p(max(int(forecast.support), len(matches))),
        "wave_momentum_agreement": 1.0 if _signed_direction(raw_wave) == _signed_direction(momentum) else -1.0,
        "wave_regime_agreement": 1.0 if _signed_direction(raw_wave) == _signed_direction(regime) else -1.0,
        "window_return_bps": float(features.get("window_return_bps", 0.0)),
        "recent_return_bps": float(features.get("recent_return_bps", 0.0)),
        "range_bps": float(features.get("range_bps", 0.0)),
        "volatility_bps": float(features.get("volatility_bps", 0.0)),
        "drawdown_bps": float(features.get("drawdown_bps", 0.0)),
        "trend_slope_bps": float(features.get("trend_slope_bps", 0.0)),
        "macd_bps": float(features.get("macd_bps", 0.0)),
        "bollinger_position": float(features.get("bollinger_position", 0.0)),
        "range_compression": float(features.get("range_compression", 0.0)),
        "volume_ratio": float(features.get("volume_ratio", 0.0)),
        "rsi": float(features.get("rsi", 50.0)),
        "close_position": float(features.get("close_position", 0.5)),
        "trend_code": _trend_code(features.get("trend")),
        "recent_trend_code": _trend_code(features.get("recent_trend")),
    }


def _trend_code(value: object) -> float:
    key = str(value or "flat").strip().lower()
    if key == "up":
        return 1.0
    if key == "down":
        return -1.0
    return 0.0


def _component_predictions(history: list[OHLCVWindow], query: OHLCVWindow, *, horizon: int) -> dict[str, float]:
    forecast = forced_directional_forecast(history, query, horizon=horizon)
    matches = _regime_matches(history, query)
    return {
        "wave": _force_nonzero(forecast.expected_return_bps, fallback=_last_actual_return(history)),
        "momentum": _force_nonzero(_momentum_directional_return(query, horizon=horizon), fallback=_last_actual_return(history)),
        "regime": _force_nonzero(
            statistics.mean(window.future_return_bps for window in matches) if matches else _last_actual_return(history),
            fallback=_last_actual_return(history),
        ),
        "historical": _force_nonzero(statistics.mean(window.future_return_bps for window in history), fallback=_last_actual_return(history)),
        "naive": _force_nonzero(_last_actual_return(history), fallback=1.0),
    }


def _fit_ensemble_calibration(
    history: list[OHLCVWindow],
    *,
    horizon: int,
    calibration_windows: int,
) -> EnsembleCalibration:
    if len(history) < max(40, calibration_windows // 2):
        return EnsembleCalibration(
            weights={"wave": 1.0},
            component_mae_bps={},
            samples=0,
            validation_mae_bps=math.inf,
            best_component="wave",
            note="insufficient_history",
        )
    start = max(24, len(history) - calibration_windows)
    rows: list[tuple[dict[str, float], float]] = []
    for index in range(start, len(history)):
        prior = history[:index]
        if len(prior) < 16:
            continue
        rows.append((_component_predictions(prior, history[index], horizon=horizon), float(history[index].future_return_bps)))
    if len(rows) < 12:
        return EnsembleCalibration(
            weights={"wave": 1.0},
            component_mae_bps={},
            samples=len(rows),
            validation_mae_bps=math.inf,
            best_component="wave",
            note="insufficient_calibration_samples",
        )
    component_names = sorted(rows[0][0])
    component_mae = {
        name: statistics.mean(abs(components[name] - actual) for components, actual in rows)
        for name in component_names
    }
    best_component = min(component_mae, key=component_mae.__getitem__)
    inverse = {
        name: 1.0 / max(component_mae[name], 1e-9) ** 2
        for name in component_names
    }
    cutoff = sorted(component_mae.values())[min(2, len(component_mae) - 1)]
    inverse = {name: value if component_mae[name] <= cutoff else 0.0 for name, value in inverse.items()}
    total = sum(inverse.values())
    weights = {name: (inverse[name] / total if total > 0.0 else 0.0) for name in component_names}
    if total <= 0.0:
        weights = {best_component: 1.0}
    ensemble_errors = [
        abs(sum(components[name] * weights.get(name, 0.0) for name in component_names) - actual)
        for components, actual in rows
    ]
    ensemble_mae = statistics.mean(ensemble_errors)
    best_mae = component_mae[best_component]
    if ensemble_mae > best_mae:
        weights = {best_component: 1.0}
        ensemble_mae = best_mae
    else:
        weights = {name: weight for name, weight in weights.items() if weight > 1e-9}
    return EnsembleCalibration(
        weights=weights,
        component_mae_bps=component_mae,
        samples=len(rows),
        validation_mae_bps=ensemble_mae,
        best_component=best_component,
        note="fold-local component weighting fitted on matured history only",
    )


def _fit_wave_calibration(
    history: list[OHLCVWindow],
    *,
    horizon: int,
    calibration_windows: int,
) -> ReturnCalibration:
    if len(history) < max(40, calibration_windows // 2):
        return ReturnCalibration(1.0, 0.0, 500.0, 0, math.inf, math.inf, "insufficient_history")
    start = max(24, len(history) - calibration_windows)
    raw_predictions = []
    actuals = []
    for index in range(start, len(history)):
        prior = history[:index]
        if len(prior) < 16:
            continue
        forecast = forced_directional_forecast(prior, history[index], horizon=horizon)
        raw_predictions.append(float(forecast.expected_return_bps))
        actuals.append(float(history[index].future_return_bps))
    if len(raw_predictions) < 12:
        return ReturnCalibration(1.0, 0.0, 500.0, len(raw_predictions), math.inf, math.inf, "insufficient_calibration_samples")
    raw_mean = statistics.mean(raw_predictions)
    actual_mean = statistics.mean(actuals)
    variance = sum((value - raw_mean) ** 2 for value in raw_predictions)
    covariance = sum((predicted - raw_mean) * (actual - actual_mean) for predicted, actual in zip(raw_predictions, actuals, strict=False))
    slope = covariance / variance if variance > 1e-12 else 0.35
    slope = min(1.25, max(0.10, float(slope)))
    intercept = float(actual_mean - slope * raw_mean)
    abs_actual = sorted(abs(value) for value in actuals)
    cap_index = min(len(abs_actual) - 1, max(0, int(round(0.80 * (len(abs_actual) - 1)))))
    cap_abs = max(10.0, float(abs_actual[cap_index]))
    raw_errors = [abs(predicted - actual) for predicted, actual in zip(raw_predictions, actuals, strict=False)]
    calibrated = [_clip_return(slope * predicted + intercept, cap_abs) for predicted in raw_predictions]
    calibrated_errors = [abs(predicted - actual) for predicted, actual in zip(calibrated, actuals, strict=False)]
    raw_mae = statistics.mean(raw_errors)
    calibrated_mae = statistics.mean(calibrated_errors)
    if calibrated_mae > raw_mae:
        return ReturnCalibration(
            slope=1.0,
            intercept_bps=0.0,
            cap_abs_bps=max(max(abs(value) for value in raw_predictions), max(abs(value) for value in actuals), 500.0),
            samples=len(raw_predictions),
            raw_mae_bps=raw_mae,
            calibrated_mae_bps=raw_mae,
            note="raw target kept because fold-local calibration did not improve matured-history MAE",
        )
    return ReturnCalibration(
        slope=slope,
        intercept_bps=intercept,
        cap_abs_bps=cap_abs,
        samples=len(raw_predictions),
        raw_mae_bps=raw_mae,
        calibrated_mae_bps=calibrated_mae,
        note="fold-local linear shrinkage fitted on matured history only",
    )


def _apply_calibration(value: float, calibration: ReturnCalibration) -> float:
    calibrated = calibration.slope * float(value) + calibration.intercept_bps
    return _clip_return(calibrated, calibration.cap_abs_bps)


def _clip_return(value: float, cap_abs_bps: float) -> float:
    cap = max(1.0, float(cap_abs_bps))
    return min(cap, max(-cap, float(value)))


def _price_target_event(
    *,
    engine: str,
    window: OHLCVWindow,
    predicted_return_bps: float,
    support: int,
    method: str,
    fold_index: int,
) -> PriceTargetEvent:
    last_close = float(window.bars[-1].close)
    actual_price = last_close * (1.0 + float(window.future_return_bps) / 10_000.0)
    predicted_price = last_close * (1.0 + float(predicted_return_bps) / 10_000.0)
    abs_price_error = abs(predicted_price - actual_price)
    actual_direction = _signed_direction(window.future_return_bps)
    predicted_direction = _signed_direction(predicted_return_bps)
    error_bps = float(predicted_return_bps) - float(window.future_return_bps)
    return PriceTargetEvent(
        engine=engine,
        symbol=window.symbol,
        timeframe=window.timeframe,
        fold_index=int(fold_index),
        query_id=window.id,
        data_end_utc=window.end_time,
        target_end_utc=window_target_end_time(window),
        last_close=last_close,
        actual_return_bps=float(window.future_return_bps),
        predicted_return_bps=float(predicted_return_bps),
        actual_price=float(actual_price),
        predicted_price=float(predicted_price),
        abs_return_error_bps=abs(error_bps),
        abs_price_error=float(abs_price_error),
        abs_pct_error=float(abs_price_error / max(abs(actual_price), 1e-12) * 100.0),
        squared_return_error_bps=error_bps * error_bps,
        direction_hit=1.0 if predicted_direction == actual_direction else 0.0,
        predicted_direction=predicted_direction,
        actual_direction=actual_direction,
        support=int(support),
        method=method,
    )


def window_target_end_time(window: OHLCVWindow) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(window.future_end_ts, tz=timezone.utc).isoformat()


def _summarize_events(
    events: list[PriceTargetEvent],
    *,
    engine: str,
    symbol: str = "",
    timeframe: str = "",
    fold_index: int | None = None,
) -> dict:
    if not events:
        return {
            "engine": engine,
            "symbol": symbol,
            "timeframe": timeframe,
            "fold_index": -1 if fold_index is None else int(fold_index),
            "queries": 0,
            "direction_hit_rate": 0.0,
            "mean_abs_return_error_bps": math.inf,
            "median_abs_return_error_bps": math.inf,
            "rmse_return_error_bps": math.inf,
            "mean_abs_price_error": math.inf,
            "mape_pct": math.inf,
            "smape_pct": math.inf,
            "bias_bps": math.inf,
            "within_25bps_rate": 0.0,
            "within_50bps_rate": 0.0,
            "within_100bps_rate": 0.0,
            "within_200bps_rate": 0.0,
        }
    errors = [event.abs_return_error_bps for event in events]
    signed_errors = [event.predicted_return_bps - event.actual_return_bps for event in events]
    return {
        "engine": engine,
        "symbol": symbol,
        "timeframe": timeframe,
        "fold_index": -1 if fold_index is None else int(fold_index),
        "queries": len(events),
        "direction_hit_rate": statistics.mean(event.direction_hit for event in events),
        "mean_abs_return_error_bps": statistics.mean(errors),
        "median_abs_return_error_bps": statistics.median(errors),
        "rmse_return_error_bps": math.sqrt(statistics.mean(event.squared_return_error_bps for event in events)),
        "mean_abs_price_error": statistics.mean(event.abs_price_error for event in events),
        "mape_pct": statistics.mean(event.abs_pct_error for event in events),
        "smape_pct": statistics.mean(
            abs(event.predicted_price - event.actual_price)
            / max((abs(event.predicted_price) + abs(event.actual_price)) / 2.0, 1e-12)
            * 100.0
            for event in events
        ),
        "bias_bps": statistics.mean(signed_errors),
        "within_25bps_rate": _within_rate(errors, 25.0),
        "within_50bps_rate": _within_rate(errors, 50.0),
        "within_100bps_rate": _within_rate(errors, 100.0),
        "within_200bps_rate": _within_rate(errors, 200.0),
        "mean_support": statistics.mean(event.support for event in events),
        "avg_latency_ms": 0.0,
    }


def _attach_robustness(results: list[dict], by_market: list[dict]) -> None:
    for result in results:
        slices = [row for row in by_market if row["engine"] == result["engine"] and row["queries"] > 0]
        if not slices:
            continue
        result["market_slices"] = len(slices)
        result["positive_direction_slices"] = sum(1 for row in slices if row["direction_hit_rate"] >= 0.5)
        result["slice_positive_rate"] = result["positive_direction_slices"] / max(1, len(slices))
        result["worst_slice_direction_hit_rate"] = min(row["direction_hit_rate"] for row in slices)
        result["worst_slice_mape_pct"] = max(row["mape_pct"] for row in slices)
        result["worst_slice_mae_return_bps"] = max(row["mean_abs_return_error_bps"] for row in slices)


def _fold_starts(
    windows: list[OHLCVWindow],
    *,
    train_windows: int,
    test_windows: int,
    folds: int,
    fold_stride: int | None,
) -> list[int]:
    first = int(train_windows)
    max_start = len(windows) - int(test_windows)
    if max_start < first:
        raise ValueError(f"not enough windows: need at least {first + test_windows}, got {len(windows)}")
    if folds <= 1:
        return [first]
    if fold_stride is not None:
        starts = [first + index * int(fold_stride) for index in range(int(folds))]
        return [start for start in starts if start <= max_start] or [first]
    span = max_start - first
    return sorted({int(round(first + span * index / max(1, int(folds) - 1))) for index in range(int(folds))})


def _mature_history(windows: list[OHLCVWindow], *, current: OHLCVWindow) -> list[OHLCVWindow]:
    return [window for window in windows if window.start_ts < current.start_ts and window.future_end_ts <= current.end_ts]


def _regime_matches(history: list[OHLCVWindow], query: OHLCVWindow) -> list[OHLCVWindow]:
    signature = set(_regime_signature_from_window(query))
    if not signature:
        return []
    matches = []
    for window in history:
        overlap = len(signature.intersection(_regime_signature_from_window(window)))
        if overlap >= 2:
            matches.append(window)
    return matches[-64:]


def _last_actual_return(history: list[OHLCVWindow]) -> float:
    return float(history[-1].future_return_bps) if history else 1.0


def _force_nonzero(value: float, *, fallback: float) -> float:
    if not math.isclose(float(value), 0.0, abs_tol=1e-9):
        return float(value)
    if not math.isclose(float(fallback), 0.0, abs_tol=1e-9):
        return float(fallback)
    return 1.0


def _within_rate(errors: list[float], threshold: float) -> float:
    return sum(1 for error in errors if error <= threshold) / max(1, len(errors))


def _signed_direction(value: float) -> str:
    return "up" if float(value) >= 0.0 else "down"


def _normalize_engine_key(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    aliases = {
        "wavemind": "wavemind-target",
        "wave": "wavemind-target",
        "wavemind-target": "wavemind-target",
        "wavemind-ensemble": "wavemind-ensemble",
        "ensemble": "wavemind-ensemble",
        "wavemind-market-field": "wavemind-market-field-target",
        "wavemind-market-field-target": "wavemind-market-field-target",
        "market-field": "wavemind-market-field-target",
        "market-field-target": "wavemind-market-field-target",
        "wavemind-perp-field": "wavemind-perp-field-target",
        "wavemind-perp-field-target": "wavemind-perp-field-target",
        "perp-field": "wavemind-perp-field-target",
        "perp-field-target": "wavemind-perp-field-target",
        "wavemind-robust": "wavemind-robust-target",
        "wavemind-robust-target": "wavemind-robust-target",
        "robust": "wavemind-robust-target",
        "robust-target": "wavemind-robust-target",
        "wavemind-learned": "wavemind-learned-target",
        "wavemind-learned-target": "wavemind-learned-target",
        "learned": "wavemind-learned-target",
        "learned-target": "wavemind-learned-target",
        "wavemind-calibrated": "wavemind-calibrated",
        "calibrated": "wavemind-calibrated",
        "momentum": "momentum",
        "regime": "regime-mean",
        "regime-mean": "regime-mean",
        "historical": "historical-mean",
        "historical-mean": "historical-mean",
        "naive": "naive-last",
        "naive-last": "naive-last",
    }
    if key not in aliases:
        raise ValueError(f"Unknown engine {value!r}")
    return aliases[key]


def _engine_name(key: str) -> str:
    return {
        "wavemind-target": "WaveMind price target",
        "wavemind-ensemble": "WaveMind ensemble target",
        "wavemind-market-field-target": "WaveMind market-field target",
        "wavemind-perp-field-target": "WaveMind perp field target",
        "wavemind-robust-target": "WaveMind robust target",
        "wavemind-learned-target": "WaveMind learned target",
        "wavemind-calibrated": "WaveMind calibrated target",
        "momentum": "Momentum baseline",
        "regime-mean": "Regime mean baseline",
        "historical-mean": "Historical mean baseline",
        "naive-last": "Naive last-outcome baseline",
    }[key]


def _normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if "/" not in cleaned and cleaned.endswith("USDT"):
        cleaned = f"{cleaned[:-4]}/USDT"
    elif "/" not in cleaned:
        cleaned = f"{cleaned}/USDT"
    return cleaned


def _cache_path(cache_dir: Path, exchange: str, symbol: str, timeframe: str) -> Path:
    safe_symbol = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("_")
    return cache_dir / exchange / f"{safe_symbol}_{timeframe}.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward price target benchmark for WaveMind crypto research.")
    parser.add_argument("--dataset", choices=["cached", "ccxt", "synthetic"], default="cached")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--cache-dir", type=Path, default=Path("benchmarks/data/crypto_ohlcv"))
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument(
        "--engines",
        nargs="+",
        default=[
            "wavemind-market-field-target",
            "wavemind-perp-field-target",
            "wavemind-robust-target",
            "wavemind-calibrated",
            "wavemind-target",
            "momentum",
            "regime-mean",
            "historical-mean",
            "naive-last",
        ],
    )
    parser.add_argument("--bars", type=int, default=1200)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--train-windows", type=int, default=360)
    parser.add_argument("--test-windows", type=int, default=90)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--calibration-windows", type=int, default=120)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_price_target_results.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/crypto_price_target_report.md"))
    parser.add_argument(
        "--events-output",
        type=Path,
        default=None,
        help="Optional compact JSONL dump with all event-level predictions. The checked-in summary JSON stores only a sample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = load_markets(
        dataset=args.dataset,
        symbols=args.symbols,
        timeframes=args.timeframes,
        exchange=args.exchange,
        cache_dir=args.cache_dir,
        bars=args.bars,
        window=args.window,
        seed=args.seed,
    )
    payload = run_price_target_benchmark(
        markets=markets,
        engines=args.engines,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        calibration_windows=args.calibration_windows,
    )
    if args.events_output is not None:
        args.events_output.parent.mkdir(parents=True, exist_ok=True)
        with args.events_output.open("w", encoding="utf-8") as handle:
            for event in payload["event_metrics"]:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"Wrote {args.events_output}")
    output_payload = sampled_event_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = render_markdown(output_payload)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
