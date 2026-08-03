from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Iterable

from benchmarks.crypto_ohlcv import OHLCVWindow
from benchmarks.crypto_walk_forward_benchmark import _regime_signature_from_window


CenterPredictor = Callable[[list[OHLCVWindow], OHLCVWindow], float]
ScalePredictor = Callable[[list[OHLCVWindow], OHLCVWindow, int], float]


@dataclass(frozen=True)
class PredictionInterval:
    center_return_bps: float
    lower_return_bps: float
    upper_return_bps: float
    nominal_coverage: float
    calibration_samples: int
    calibration_coverage: float
    conformal_quantile: float
    observable_scale_bps: float
    status: str
    note: str


def mature_history(
    windows: Iterable[OHLCVWindow],
    *,
    current: OHLCVWindow,
) -> list[OHLCVWindow]:
    return [
        window
        for window in windows
        if window.start_ts < current.start_ts and window.future_end_ts <= current.end_ts
    ]


def observable_return_scale(window: OHLCVWindow, *, horizon: int) -> float:
    """Estimate future-return scale from information observable at query time."""
    features = window.features
    per_bar_volatility = abs(float(features.get("volatility_bps", 0.0)))
    recent_range = abs(float(features.get("range_bps", 0.0)))
    volatility_scale = per_bar_volatility * math.sqrt(max(1.0, float(horizon)))
    range_scale = recent_range * math.sqrt(max(1.0, float(horizon)) / max(1.0, len(window.bars)))
    return max(10.0, volatility_scale, range_scale)


def wave_risk_scale(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    horizon: int,
) -> float:
    """Estimate move magnitude from analogous states without predicting direction."""
    observable = observable_return_scale(query, horizon=horizon)
    if len(history) < 16:
        return observable
    query_signature = set(_regime_signature_from_window(query))
    scored: list[tuple[float, float]] = []
    recent_history = history[-384:]
    for index, window in enumerate(recent_history):
        signature = set(_regime_signature_from_window(window))
        overlap = len(query_signature.intersection(signature))
        if overlap < 2:
            continue
        recency = (index + 1) / len(recent_history)
        score = float(overlap) + 0.10 * recency
        scored.append((score, abs(float(window.future_return_bps))))
    if len(scored) < 12:
        return observable
    scored.sort(key=lambda item: item[0], reverse=True)
    analogue_magnitude = statistics.median(value for _, value in scored[:64])
    return max(10.0, math.sqrt(observable * max(10.0, analogue_magnitude)))


def conformal_quantile(scores: Iterable[float], *, nominal_coverage: float) -> float:
    values = sorted(float(value) for value in scores if math.isfinite(float(value)))
    if not values:
        raise ValueError("at least one finite conformity score is required")
    if not 0.0 < nominal_coverage < 1.0:
        raise ValueError("nominal_coverage must be between zero and one")
    rank = math.ceil((len(values) + 1) * float(nominal_coverage))
    return values[min(len(values), max(1, rank)) - 1]


def fit_prediction_interval(
    history: Iterable[OHLCVWindow],
    query: OHLCVWindow,
    *,
    predictor: CenterPredictor,
    scale_predictor: ScalePredictor | None = None,
    horizon: int,
    nominal_coverage: float = 0.80,
    calibration_windows: int = 120,
    min_prior_windows: int = 24,
    min_calibration_samples: int = 30,
) -> PredictionInterval:
    """Fit a causal adaptive conformal interval and predict one future return."""
    if calibration_windows <= 0:
        raise ValueError("calibration_windows must be positive")
    ordered = sorted(mature_history(history, current=query), key=lambda item: item.start_ts)
    center = float(predictor(ordered, query)) if ordered else 0.0
    scale_model = scale_predictor or _observable_scale_predictor
    query_scale = max(10.0, float(scale_model(ordered, query, horizon)))
    if len(ordered) < min_prior_windows + min_calibration_samples:
        return PredictionInterval(
            center_return_bps=center,
            lower_return_bps=math.nan,
            upper_return_bps=math.nan,
            nominal_coverage=float(nominal_coverage),
            calibration_samples=0,
            calibration_coverage=0.0,
            conformal_quantile=math.nan,
            observable_scale_bps=query_scale,
            status="insufficient_calibration",
            note="No interval is published until enough matured causal calibration windows exist.",
        )

    start = max(int(min_prior_windows), len(ordered) - int(calibration_windows))
    scores: list[float] = []
    for index in range(start, len(ordered)):
        calibration_query = ordered[index]
        prior = mature_history(ordered[:index], current=calibration_query)
        if len(prior) < min_prior_windows:
            continue
        predicted = float(predictor(prior, calibration_query))
        scale = max(10.0, float(scale_model(prior, calibration_query, horizon)))
        scores.append(abs(float(calibration_query.future_return_bps) - predicted) / scale)

    if len(scores) < min_calibration_samples:
        return PredictionInterval(
            center_return_bps=center,
            lower_return_bps=math.nan,
            upper_return_bps=math.nan,
            nominal_coverage=float(nominal_coverage),
            calibration_samples=len(scores),
            calibration_coverage=0.0,
            conformal_quantile=math.nan,
            observable_scale_bps=query_scale,
            status="insufficient_calibration",
            note="No interval is published until enough matured causal calibration windows exist.",
        )

    quantile = conformal_quantile(scores, nominal_coverage=nominal_coverage)
    half_width = quantile * query_scale
    empirical_coverage = sum(score <= quantile for score in scores) / len(scores)
    return PredictionInterval(
        center_return_bps=center,
        lower_return_bps=center - half_width,
        upper_return_bps=center + half_width,
        nominal_coverage=float(nominal_coverage),
        calibration_samples=len(scores),
        calibration_coverage=float(empirical_coverage),
        conformal_quantile=float(quantile),
        observable_scale_bps=float(query_scale),
        status="calibrated",
        note=(
            "Adaptive conformal range calibrated only on matured historical errors; "
            "nominal coverage is not a probability that the center forecast is correct."
        ),
    )


def _observable_scale_predictor(
    history: list[OHLCVWindow],
    query: OHLCVWindow,
    horizon: int,
) -> float:
    del history
    return observable_return_scale(query, horizon=horizon)


def interval_score(
    actual_return_bps: float,
    lower_return_bps: float,
    upper_return_bps: float,
    *,
    nominal_coverage: float,
) -> float:
    """Return the Winkler interval score; lower is better."""
    alpha = 1.0 - float(nominal_coverage)
    if not 0.0 < alpha < 1.0:
        raise ValueError("nominal_coverage must be between zero and one")
    actual = float(actual_return_bps)
    lower = float(lower_return_bps)
    upper = float(upper_return_bps)
    if upper < lower:
        raise ValueError("upper_return_bps must be greater than or equal to lower_return_bps")
    score = upper - lower
    if actual < lower:
        score += (2.0 / alpha) * (lower - actual)
    elif actual > upper:
        score += (2.0 / alpha) * (actual - upper)
    return float(score)
