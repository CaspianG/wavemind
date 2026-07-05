from __future__ import annotations

import argparse
import html
import itertools
import json
import math
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    OHLCVWindow,
    fetch_ohlcv_ccxt,
    generate_synthetic_ohlcv,
    load_ohlcv_csv,
    make_ohlcv_windows,
    save_ohlcv_csv,
    window_to_text,
)
from wavemind import WaveMind  # noqa: E402
from wavemind.encoders import TextVectorEncoder, create_text_encoder  # noqa: E402


REGIME_FEATURE_KEYS = (
    "trend",
    "recent_trend",
    "rsi_bucket",
    "volatility_bucket",
    "volume_bucket",
    "close_position_bucket",
    "drawdown_bucket",
    "macd_bucket",
    "bollinger_bucket",
)


@dataclass(frozen=True)
class MarketDataset:
    symbol: str
    timeframe: str
    bars: list[OHLCVBar]
    windows: list[OHLCVWindow]
    source: str = ""
    source_path: str = ""


@dataclass(frozen=True)
class AnalogueMatch:
    id: str
    score: float
    direction: str
    future_return_bps: float
    max_favorable_excursion_bps: float
    max_adverse_excursion_bps: float
    future_realized_vol_bps: float
    start_time: str
    end_time: str
    text: str
    regime_signature: tuple[str, ...] = ()


@dataclass(frozen=True)
class Prediction:
    direction: str
    expected_return_bps: float
    latency_ms: float
    analogues: list[AnalogueMatch]
    confidence: float = 1.0
    raw_direction: str = ""
    candidate_direction: str = ""
    candidate_expected_return_bps: float = 0.0
    filtered: bool = False
    filter_reason: str = ""
    analogue_agreement: float = 1.0
    regime_agreement: float = 1.0


@dataclass(frozen=True)
class EventMetric:
    engine: str
    symbol: str
    timeframe: str
    query_id: str
    actual_direction: str
    predicted_direction: str
    actual_return_bps: float
    actual_mfe_bps: float
    actual_mae_bps: float
    actual_future_vol_bps: float
    predicted_return_bps: float
    predicted_mfe_bps: float
    predicted_mae_bps: float
    predicted_future_vol_bps: float
    direction_at_1: float
    direction_at_3: float
    abs_return_error_bps: float
    abs_mfe_error_bps: float
    abs_mae_error_bps: float
    abs_future_vol_error_bps: float
    predicted_large_move: float
    actual_large_move: float
    large_move_true_positive: float
    large_move_false_positive: float
    position_size: float
    confidence: float
    raw_direction: str
    candidate_direction: str
    candidate_expected_return_bps: float
    filter_reason: str
    analogue_agreement: float
    regime_agreement: float
    regime_signature: tuple[str, ...]
    features: dict[str, object]
    filtered: float
    net_return_bps: float
    sized_net_return_bps: float
    latency_ms: float


class MarketEngine:
    name = "engine"

    def add(self, window: OHLCVWindow) -> None:
        raise NotImplementedError

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        raise NotImplementedError

    def close(self) -> None:
        return None


class StaticKnnEngine(MarketEngine):
    name = "Static kNN"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.records: list[OHLCVWindow] = []
        self.texts: list[str] = []
        self.vectors = np.zeros((0, encoder.vector_dim), dtype=np.float32)

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=False)
        vector = self.encoder.encode_vector(text)
        self.records.append(window)
        self.texts.append(text)
        self.vectors = np.vstack([self.vectors, vector.reshape(1, -1)])

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False))
        scores = self.vectors @ query_vector
        order = np.argsort(scores)[::-1][:top_k]
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            _analogue_from_window(self.records[int(index)], self.texts[int(index)], float(scores[int(index)]))
            for index in order
        ]
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
        )


class WaveMindEngine(MarketEngine):
    name = "WaveMind field"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        use_field: bool = True,
        calibrated: bool = False,
        min_analogue_agreement: float = 0.6,
        confidence_threshold: float = 0.65,
        regime_filter: bool = True,
        large_move_bps: float = 75.0,
        min_expected_edge_bps: float = 0.0,
        db_label: str | None = None,
        memory_store: str = "disk",
        vector_weight: float | None = None,
        field_weight: float | None = None,
        priority_weight: float | None = None,
        lexical_weight: float | None = None,
    ):
        if calibrated:
            self.name = "WaveMind calibrated" if use_field else "WaveMind field-off calibrated"
        else:
            self.name = "WaveMind field" if use_field else "WaveMind field-off"
        self.namespace = f"crypto:{symbol}:{timeframe}"
        self.temp_root = temp_root
        self.calibrated = calibrated
        self.min_analogue_agreement = float(min_analogue_agreement)
        self.confidence_threshold = float(confidence_threshold)
        self.regime_filter = bool(regime_filter)
        self.large_move_bps = float(large_move_bps)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        if db_label is None:
            if calibrated:
                db_label = "calibrated" if use_field else "fieldoffcalibrated"
            else:
                db_label = "field" if use_field else "fieldoff"
        if memory_store not in {"disk", "memory"}:
            raise ValueError("memory_store must be 'disk' or 'memory'")
        db_path = None if memory_store == "memory" else temp_root / f"{symbol.replace('/', '')}_{timeframe}_{db_label}.sqlite3"
        self.memory = WaveMind(
            db_path=db_path,
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            vector_weight=float(vector_weight) if vector_weight is not None else (0.72 if use_field else 0.94),
            field_weight=float(field_weight) if field_weight is not None else (0.08 if use_field else 0.0),
            priority_weight=float(priority_weight) if priority_weight is not None else (0.18 if use_field else 0.0),
            lexical_weight=float(lexical_weight) if lexical_weight is not None else 0.16,
            rerank_k=32,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )

    def add(self, window: OHLCVWindow) -> None:
        priority = 1.0 + min(4.0, abs(window.future_return_bps) / 45.0)
        self.memory.remember(
            window_to_text(window, include_outcome=False),
            namespace=self.namespace,
            tags=("crypto", window.symbol, window.timeframe, window.direction),
            priority=priority,
            metadata=_window_metadata(window),
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        results = self.memory.query(
            window_to_text(window, include_outcome=False),
            namespace=self.namespace,
            top_k=top_k,
        )
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            AnalogueMatch(
                id=str(result.metadata.get("window_id", result.id)),
                score=float(result.score),
                direction=str(result.metadata.get("direction", "flat")),
                future_return_bps=float(result.metadata.get("future_return_bps", 0.0)),
                max_favorable_excursion_bps=float(result.metadata.get("max_favorable_excursion_bps", 0.0)),
                max_adverse_excursion_bps=float(result.metadata.get("max_adverse_excursion_bps", 0.0)),
                future_realized_vol_bps=float(result.metadata.get("future_realized_vol_bps", 0.0)),
                start_time=str(result.metadata.get("start_time", "")),
                end_time=str(result.metadata.get("end_time", "")),
                text=result.text,
                regime_signature=_regime_signature_from_metadata(result.metadata),
            )
            for result in results
        ]
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        if self.calibrated:
            return _calibrated_prediction(
                query_window=window,
                analogues=analogues,
                latency_ms=latency,
                min_analogue_agreement=self.min_analogue_agreement,
                confidence_threshold=self.confidence_threshold,
                regime_filter=self.regime_filter,
                large_move_bps=self.large_move_bps,
                min_expected_edge_bps=self.min_expected_edge_bps,
            )
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
            confidence=_direction_agreement_from_analogues(top.direction, analogues),
            raw_direction=top.direction,
            analogue_agreement=_direction_agreement_from_analogues(top.direction, analogues),
        )

    def close(self) -> None:
        self.memory.close()


class WaveMindRegimeGateEngine(WaveMindEngine):
    name = "WaveMind regime-gated"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        min_support: float = 0.52,
        min_regime_agreement: float = 0.5,
        min_expected_edge_bps: float = 30.0,
        performance_lookback: int = 96,
        min_historical_edge_bps: float = 0.0,
        round_trip_cost_bps: float = 30.0,
        db_label: str = "regimegate",
        memory_store: str = "disk",
    ):
        super().__init__(
            encoder,
            symbol=symbol,
            timeframe=timeframe,
            temp_root=temp_root,
            use_field=True,
            db_label=db_label,
            memory_store=memory_store,
        )
        self.name = "WaveMind regime-gated"
        self.records: list[OHLCVWindow] = []
        self.min_support = float(min_support)
        self.min_regime_agreement = float(min_regime_agreement)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        self.performance_lookback = int(performance_lookback)
        self.min_historical_edge_bps = float(min_historical_edge_bps)
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    def add(self, window: OHLCVWindow) -> None:
        self.records.append(window)
        super().add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        memory_prediction = super().query(window, top_k=top_k)
        latest = self.records[-1]
        candidate_direction = latest.direction
        if candidate_direction == "flat" or not memory_prediction.analogues:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=memory_prediction.latency_ms,
                analogues=memory_prediction.analogues,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="flat_candidate",
                confidence=0.0,
            )
        selected = [match for match in memory_prediction.analogues if match.direction == candidate_direction]
        support = _weighted_direction_support(candidate_direction, memory_prediction.analogues)
        regime_agreement = _regime_agreement(window, selected)
        expected_return = _weighted_mean_return(selected) if selected else float(latest.future_return_bps)
        expected_edge = _directional_edge_after_cost_bps(
            candidate_direction,
            expected_return,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        historical_edge = _rolling_last_regime_edge(
            self.records,
            lookback=self.performance_lookback,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        confidence = float(support * (0.45 + 0.55 * regime_agreement))
        reasons = []
        if historical_edge < self.min_historical_edge_bps:
            reasons.append("negative_recent_edge")
        if support < self.min_support:
            reasons.append("low_memory_support")
        if regime_agreement < self.min_regime_agreement:
            reasons.append("regime_mismatch")
        if expected_edge < self.min_expected_edge_bps:
            reasons.append("low_expected_edge")
        if reasons:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=memory_prediction.latency_ms,
                analogues=memory_prediction.analogues,
                confidence=confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=",".join(reasons),
                analogue_agreement=support,
                regime_agreement=regime_agreement,
            )
        return Prediction(
            direction=candidate_direction,
            expected_return_bps=expected_return,
            latency_ms=memory_prediction.latency_ms,
            analogues=memory_prediction.analogues,
            confidence=confidence,
            raw_direction=candidate_direction,
            analogue_agreement=support,
            regime_agreement=regime_agreement,
        )


class WaveMindFourHourProfileEngine(WaveMindRegimeGateEngine):
    name = "WaveMind 4h profile"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        min_support: float = 0.52,
        min_regime_agreement: float = 0.5,
        min_expected_edge_bps: float = 30.0,
        performance_lookback: int = 96,
        min_historical_edge_bps: float = 0.0,
        round_trip_cost_bps: float = 30.0,
        memory_store: str = "disk",
    ):
        super().__init__(
            encoder,
            symbol=symbol,
            timeframe=timeframe,
            temp_root=temp_root,
            min_support=min_support,
            min_regime_agreement=min_regime_agreement,
            min_expected_edge_bps=min_expected_edge_bps,
            performance_lookback=performance_lookback,
            min_historical_edge_bps=min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            db_label="profile4h",
            memory_store=memory_store,
        )
        self.name = "WaveMind 4h profile"
        self.active_timeframe = "4h"

    def add(self, window: OHLCVWindow) -> None:
        if window.timeframe != self.active_timeframe:
            return
        super().add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        if window.timeframe != self.active_timeframe:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=0.0,
                analogues=[],
                confidence=0.0,
                raw_direction="flat",
                filtered=True,
                filter_reason="inactive_timeframe",
            )
        return super().query(window, top_k=top_k)


class WaveMindRiskOverlayEngine(WaveMindEngine):
    name = "WaveMind risk-overlay"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        max_opposition: float = 0.62,
        min_regime_agreement: float = 0.35,
        performance_lookback: int = 96,
        min_historical_edge_bps: float = -20.0,
        round_trip_cost_bps: float = 30.0,
        memory_store: str = "disk",
    ):
        super().__init__(
            encoder,
            symbol=symbol,
            timeframe=timeframe,
            temp_root=temp_root,
            use_field=True,
            db_label="riskoverlay",
            memory_store=memory_store,
        )
        self.name = "WaveMind risk-overlay"
        self.records: list[OHLCVWindow] = []
        self.max_opposition = float(max_opposition)
        self.min_regime_agreement = float(min_regime_agreement)
        self.performance_lookback = int(performance_lookback)
        self.min_historical_edge_bps = float(min_historical_edge_bps)
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    def add(self, window: OHLCVWindow) -> None:
        self.records.append(window)
        super().add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        memory_prediction = super().query(window, top_k=top_k)
        latest = self.records[-1]
        candidate_direction = latest.direction
        if candidate_direction == "flat" or not memory_prediction.analogues:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=memory_prediction.latency_ms,
                analogues=memory_prediction.analogues,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="flat_candidate",
                confidence=0.0,
            )
        opposite_direction = "down" if candidate_direction == "up" else "up"
        opposition = _weighted_direction_support(opposite_direction, memory_prediction.analogues)
        selected = [match for match in memory_prediction.analogues if match.direction == candidate_direction]
        regime_agreement = _regime_agreement(window, selected) if selected else 0.0
        historical_edge = _rolling_last_regime_edge(
            self.records,
            lookback=self.performance_lookback,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        confidence = float(max(0.0, min(1.0, 1.0 - opposition)))
        reasons = []
        if opposition > self.max_opposition:
            reasons.append("memory_opposition")
        if selected and regime_agreement < self.min_regime_agreement:
            reasons.append("regime_mismatch")
        if historical_edge < self.min_historical_edge_bps:
            reasons.append("negative_recent_edge")
        if reasons:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=memory_prediction.latency_ms,
                analogues=memory_prediction.analogues,
                confidence=confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=",".join(reasons),
                analogue_agreement=1.0 - opposition,
                regime_agreement=regime_agreement,
            )
        return Prediction(
            direction=candidate_direction,
            expected_return_bps=float(latest.future_return_bps),
            latency_ms=memory_prediction.latency_ms,
            analogues=memory_prediction.analogues,
            confidence=confidence,
            raw_direction=candidate_direction,
            analogue_agreement=1.0 - opposition,
            regime_agreement=regime_agreement,
        )


class WaveMindTrendRiskEngine(WaveMindRiskOverlayEngine):
    name = "WaveMind trend-risk"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        max_opposition: float = 0.62,
        min_regime_agreement: float = 0.35,
        performance_lookback: int = 96,
        min_historical_edge_bps: float = -20.0,
        round_trip_cost_bps: float = 30.0,
        memory_store: str = "disk",
    ):
        super().__init__(
            encoder,
            symbol=symbol,
            timeframe=timeframe,
            temp_root=temp_root,
            max_opposition=max_opposition,
            min_regime_agreement=min_regime_agreement,
            performance_lookback=performance_lookback,
            min_historical_edge_bps=min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
        self.name = "WaveMind trend-risk"

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        prediction = super().query(window, top_k=top_k)
        if prediction.direction == "flat":
            return prediction
        if not _direction_matches_window_trend(prediction.direction, window):
            reason = "trend_mismatch"
            if prediction.filter_reason:
                reason = f"{prediction.filter_reason},{reason}"
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=prediction.latency_ms,
                analogues=prediction.analogues,
                confidence=prediction.confidence,
                raw_direction=prediction.raw_direction or prediction.direction,
                filtered=True,
                filter_reason=reason,
                analogue_agreement=prediction.analogue_agreement,
                regime_agreement=prediction.regime_agreement,
            )
        return prediction


class WaveMindAdaptiveFieldEngine(WaveMindEngine):
    name = "WaveMind adaptive-field"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        min_support: int = 24,
        min_test_support: int = 8,
        validation_holdout: float = 0.35,
        min_confidence: float = 0.52,
        min_expected_edge_bps: float = 70.0,
        max_opposition: float = 0.62,
        require_trend_alignment: bool = True,
        performance_lookback: int = 8,
        min_recent_edge_bps: float = 20.0,
        round_trip_cost_bps: float = 30.0,
        memory_store: str = "disk",
        store_vector_memory: bool = False,
    ):
        self.store_vector_memory = bool(store_vector_memory)
        if self.store_vector_memory:
            super().__init__(
                encoder,
                symbol=symbol,
                timeframe=timeframe,
                temp_root=temp_root,
                use_field=True,
                db_label="adaptivefield",
                vector_weight=0.92,
                field_weight=0.04,
                priority_weight=0.04,
                lexical_weight=0.0,
                memory_store=memory_store,
            )
        self.name = "WaveMind adaptive-field"
        self.records: list[OHLCVWindow] = []
        self.return_history: list[float] = []
        self.relationship_history: dict[tuple[str, ...], list[tuple[int, float]]] = {}
        self.pending_predictions: dict[str, str] = {}
        self.realized_signal_nets: list[float] = []
        self.min_support = int(min_support)
        self.min_test_support = int(min_test_support)
        self.validation_holdout = float(validation_holdout)
        self.min_confidence = float(min_confidence)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        self.max_opposition = float(max_opposition)
        self.require_trend_alignment = bool(require_trend_alignment)
        self.performance_lookback = int(performance_lookback)
        self.min_recent_edge_bps = float(min_recent_edge_bps)
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    def add(self, window: OHLCVWindow) -> None:
        predicted_direction = self.pending_predictions.pop(window.id, None)
        if predicted_direction is not None:
            self.realized_signal_nets.append(
                _net_return_bps(
                    predicted_direction=predicted_direction,
                    actual_return_bps=window.future_return_bps,
                    round_trip_cost_bps=self.round_trip_cost_bps,
                )
        )
        index = len(self.records)
        self.records.append(window)
        self.return_history.append(float(window.future_return_bps))
        for relationship in _relationship_candidates(_regime_signature_from_window(window)):
            self.relationship_history.setdefault(relationship, []).append((index, float(window.future_return_bps)))
        if self.store_vector_memory:
            super().add(window)

    def close(self) -> None:
        if self.store_vector_memory:
            super().close()

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if len(self.records) < self.min_support:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=0.0,
                raw_direction="flat",
                filtered=True,
                filter_reason="insufficient_field_history",
            )
        recent_edge = _recent_mean(self.realized_signal_nets, lookback=self.performance_lookback)
        min_samples = min(max(4, self.performance_lookback // 3), self.performance_lookback)
        if len(self.realized_signal_nets) >= min_samples and recent_edge < self.min_recent_edge_bps:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=max(0.0, min(1.0, 0.5 + recent_edge / 200.0)),
                raw_direction="flat",
                filtered=True,
                filter_reason="negative_adaptive_recent_edge",
            )
        field_signal = _adaptive_relationship_field_signal_from_index(
            self.return_history,
            self.relationship_history,
            window,
            min_support=self.min_support,
            min_test_support=self.min_test_support,
            validation_holdout=self.validation_holdout,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        latest = self.records[-1]
        candidate_direction = latest.direction
        if candidate_direction == "flat":
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=float(field_signal["confidence"]),
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="flat_candidate",
                analogue_agreement=0.0,
                regime_agreement=float(field_signal["stability"]),
            )
        if self.require_trend_alignment and not _direction_matches_window_trend(candidate_direction, window):
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=float(field_signal["confidence"]),
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="adaptive_trend_mismatch",
                analogue_agreement=0.0,
                regime_agreement=float(field_signal["stability"]),
            )

        field_direction = str(field_signal["direction"])
        field_confidence = float(field_signal["confidence"])
        field_edge = float(field_signal["edge_bps"])
        opposite_direction = "down" if candidate_direction == "up" else "up"
        if (
            field_direction == opposite_direction
            and field_confidence >= self.min_confidence
            and field_edge >= self.min_expected_edge_bps
        ):
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=field_confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="adaptive_field_opposition",
                analogue_agreement=0.0,
                regime_agreement=float(field_signal["stability"]),
            )

        field_return = float(field_signal["expected_return_bps"])
        if field_direction == candidate_direction and field_confidence >= self.min_confidence:
            expected_return = 0.62 * field_return + 0.38 * float(latest.future_return_bps)
            confidence = field_confidence
            support = field_confidence
        else:
            expected_return = float(latest.future_return_bps)
            confidence = max(0.35, min(0.58, 0.35 + 0.23 * field_confidence))
            support = confidence
        edge = _directional_edge_after_cost_bps(
            candidate_direction,
            expected_return,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        reasons = []
        if edge < self.min_expected_edge_bps:
            reasons.append("low_expected_edge")
        if reasons:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=",".join(reasons),
                analogue_agreement=support,
                regime_agreement=float(field_signal["stability"]),
            )
        prediction = Prediction(
            direction=candidate_direction,
            expected_return_bps=expected_return,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            analogues=[],
            confidence=confidence,
            raw_direction=candidate_direction,
            analogue_agreement=support,
            regime_agreement=float(field_signal["stability"]),
        )
        self.pending_predictions[window.id] = prediction.direction
        return prediction


class WaveMindMicrostructureEngine(MarketEngine):
    name = "WaveMind microstructure"

    def __init__(
        self,
        *,
        min_support: int = 24,
        min_test_support: int = 8,
        validation_holdout: float = 0.35,
        opposition_confidence: float = 0.45,
        opposition_edge_bps: float = 50.0,
        boost_confidence: float = 0.50,
        min_expected_edge_bps: float = 20.0,
        performance_lookback: int = 8,
        min_recent_edge_bps: float = 20.0,
        round_trip_cost_bps: float = 30.0,
    ):
        self.ta = TaRulesEngine()
        self.records: list[OHLCVWindow] = []
        self.return_history: list[float] = []
        self.relationship_history: dict[tuple[str, ...], list[tuple[int, float]]] = {}
        self.pending_predictions: dict[str, str] = {}
        self.realized_signal_nets: list[float] = []
        self.min_support = int(min_support)
        self.min_test_support = int(min_test_support)
        self.validation_holdout = float(validation_holdout)
        self.opposition_confidence = float(opposition_confidence)
        self.opposition_edge_bps = float(opposition_edge_bps)
        self.boost_confidence = float(boost_confidence)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        self.performance_lookback = int(performance_lookback)
        self.min_recent_edge_bps = float(min_recent_edge_bps)
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    def add(self, window: OHLCVWindow) -> None:
        predicted_direction = self.pending_predictions.pop(window.id, None)
        if predicted_direction is not None:
            self.realized_signal_nets.append(
                _net_return_bps(
                    predicted_direction=predicted_direction,
                    actual_return_bps=window.future_return_bps,
                    round_trip_cost_bps=self.round_trip_cost_bps,
                )
            )
        index = len(self.records)
        self.records.append(window)
        self.return_history.append(float(window.future_return_bps))
        for relationship in _relationship_candidates(_regime_signature_from_window(window)):
            self.relationship_history.setdefault(relationship, []).append((index, float(window.future_return_bps)))
        self.ta.add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        recent_edge = _recent_mean(self.realized_signal_nets, lookback=self.performance_lookback)
        min_samples = min(max(4, self.performance_lookback // 3), self.performance_lookback)
        if len(self.realized_signal_nets) >= min_samples and recent_edge < self.min_recent_edge_bps:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=max(0.0, min(1.0, 0.5 + recent_edge / 200.0)),
                raw_direction="flat",
                filtered=True,
                filter_reason="negative_microstructure_recent_edge",
            )
        base = self.ta.query(window, top_k=top_k)
        candidate_direction = base.direction
        if candidate_direction == "flat":
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=base.latency_ms,
                analogues=base.analogues,
                confidence=base.confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="flat_candidate",
            )
        field_signal = _adaptive_relationship_field_signal_from_index(
            self.return_history,
            self.relationship_history,
            window,
            min_support=self.min_support,
            min_test_support=self.min_test_support,
            validation_holdout=self.validation_holdout,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        field_direction = str(field_signal["direction"])
        field_confidence = float(field_signal["confidence"])
        field_edge = float(field_signal["edge_bps"])
        field_stability = float(field_signal["stability"])
        opposite_direction = "down" if candidate_direction == "up" else "up"
        reasons = []
        if (
            field_direction == opposite_direction
            and field_confidence >= self.opposition_confidence
            and field_edge >= self.opposition_edge_bps
        ):
            reasons.append("field_opposition")
        if field_direction == candidate_direction and field_confidence >= self.boost_confidence:
            expected_return = 0.60 * float(field_signal["expected_return_bps"]) + 0.40 * base.expected_return_bps
            confidence = max(float(base.confidence), field_confidence)
        else:
            expected_return = base.expected_return_bps
            confidence = max(0.35, min(0.70, 0.35 + 0.35 * field_confidence))
        edge = _directional_edge_after_cost_bps(
            candidate_direction,
            expected_return,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        if edge < self.min_expected_edge_bps:
            reasons.append("low_expected_edge")
        if reasons:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=base.latency_ms,
                analogues=base.analogues,
                confidence=confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=",".join(reasons),
                analogue_agreement=field_confidence,
                regime_agreement=field_stability,
            )
        self.pending_predictions[window.id] = candidate_direction
        return Prediction(
            direction=candidate_direction,
            expected_return_bps=expected_return,
            latency_ms=base.latency_ms,
            analogues=base.analogues,
            confidence=confidence,
            raw_direction=candidate_direction,
            analogue_agreement=field_confidence,
            regime_agreement=field_stability,
        )


class WaveMindDailyTrendMemoryEngine(MarketEngine):
    name = "WaveMind daily trend-memory"

    def __init__(
        self,
        *,
        min_support: int = 18,
        min_test_support: int = 6,
        validation_holdout: float = 0.35,
        opposition_confidence: float = 0.42,
        opposition_edge_bps: float = 60.0,
        boost_confidence: float = 0.48,
        min_expected_edge_bps: float = 70.0,
        performance_lookback: int = 5,
        min_recent_edge_bps: float = -20.0,
        local_reliability_support: int = 16,
        round_trip_cost_bps: float = 30.0,
    ):
        self.base = TrendPersistenceEngine()
        self.records: list[OHLCVWindow] = []
        self.return_history: list[float] = []
        self.relationship_history: dict[tuple[str, ...], list[tuple[int, float]]] = {}
        self.pending_predictions: dict[str, str] = {}
        self.realized_signal_nets: list[float] = []
        self.min_support = int(min_support)
        self.min_test_support = int(min_test_support)
        self.validation_holdout = float(validation_holdout)
        self.opposition_confidence = float(opposition_confidence)
        self.opposition_edge_bps = float(opposition_edge_bps)
        self.boost_confidence = float(boost_confidence)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        self.performance_lookback = int(performance_lookback)
        self.min_recent_edge_bps = float(min_recent_edge_bps)
        self.local_reliability_support = int(local_reliability_support)
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    def add(self, window: OHLCVWindow) -> None:
        predicted_direction = self.pending_predictions.pop(window.id, None)
        if predicted_direction is not None:
            self.realized_signal_nets.append(
                _net_return_bps(
                    predicted_direction=predicted_direction,
                    actual_return_bps=window.future_return_bps,
                    round_trip_cost_bps=self.round_trip_cost_bps,
                )
            )
        index = len(self.records)
        self.records.append(window)
        self.return_history.append(float(window.future_return_bps))
        for relationship in _relationship_candidates(_regime_signature_from_window(window)):
            self.relationship_history.setdefault(relationship, []).append((index, float(window.future_return_bps)))
        self.base.add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if len(self.records) < self.min_support:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=0.0,
                raw_direction="flat",
                filtered=True,
                filter_reason="insufficient_daily_history",
            )
        recent_edge = _recent_mean(self.realized_signal_nets, lookback=self.performance_lookback)
        min_samples = min(max(3, self.performance_lookback // 2), self.performance_lookback)
        if len(self.realized_signal_nets) >= min_samples and recent_edge < self.min_recent_edge_bps:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=[],
                confidence=max(0.0, min(1.0, 0.5 + recent_edge / 200.0)),
                raw_direction="flat",
                filtered=True,
                filter_reason="negative_daily_recent_edge",
            )

        base = self.base.query(window, top_k=top_k)
        candidate_direction = base.direction
        if candidate_direction == "flat":
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=base.latency_ms,
                analogues=base.analogues,
                confidence=base.confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="flat_candidate",
            )

        features = window.features
        daily_guard_reason = ""
        if str(features.get("volume_bucket")) == "expanded":
            daily_guard_reason = "daily_expanded_volume_reversal_risk"
        elif (
            candidate_direction == "up"
            and str(features.get("recent_trend")) == "up"
            and str(features.get("bollinger_bucket")) == "middle"
        ):
            daily_guard_reason = "daily_mid_band_up_continuation_trap"
        elif (
            candidate_direction == "up"
            and str(features.get("volume_bucket")) == "quiet"
            and str(features.get("close_position_bucket")) == "near_high"
        ):
            daily_guard_reason = "daily_quiet_near_high_reversal_risk"
        if daily_guard_reason:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=base.analogues,
                confidence=base.confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=daily_guard_reason,
            )

        field_signal = _adaptive_relationship_field_signal_from_index(
            self.return_history,
            self.relationship_history,
            window,
            min_support=self.min_support,
            min_test_support=self.min_test_support,
            validation_holdout=self.validation_holdout,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        field_direction = str(field_signal["direction"])
        field_confidence = float(field_signal["confidence"])
        field_edge = float(field_signal["edge_bps"])
        field_stability = float(field_signal["stability"])
        opposite_direction = "down" if candidate_direction == "up" else "up"
        if (
            field_direction == opposite_direction
            and field_confidence >= self.opposition_confidence
            and field_edge >= self.opposition_edge_bps
        ):
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=base.analogues,
                confidence=field_confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="daily_field_opposition",
                analogue_agreement=field_confidence,
                regime_agreement=field_stability,
            )

        reliability = _local_regime_reliability(
            self.records,
            window,
            direction=candidate_direction,
            round_trip_cost_bps=self.round_trip_cost_bps,
            min_overlap=2,
            lookback=220,
        )
        if reliability["support"] >= self.local_reliability_support and (
            reliability["avg_net_bps"] < -35.0
            or (
                reliability["hit_rate"] < 0.42
                and reliability["avg_net_bps"] < 0.0
            )
        ):
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=base.analogues,
                confidence=min(field_confidence, max(0.0, reliability["hit_rate"])),
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason=(
                    "daily_local_regime_negative:"
                    f"support={int(reliability['support'])},"
                    f"hit={reliability['hit_rate']:.3f},"
                    f"net={reliability['avg_net_bps']:.2f}"
                ),
                analogue_agreement=field_confidence,
                regime_agreement=field_stability,
            )

        if field_direction == candidate_direction and field_confidence >= self.boost_confidence:
            expected_return = 0.52 * float(field_signal["expected_return_bps"]) + 0.48 * base.expected_return_bps
            confidence = max(0.55, min(1.0, field_confidence))
        else:
            expected_return = base.expected_return_bps
            confidence = max(0.35, min(0.62, 0.35 + 0.27 * field_confidence))
        edge = _directional_edge_after_cost_bps(
            candidate_direction,
            expected_return,
            round_trip_cost_bps=self.round_trip_cost_bps,
        )
        if edge < self.min_expected_edge_bps:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                analogues=base.analogues,
                confidence=confidence,
                raw_direction=candidate_direction,
                filtered=True,
                filter_reason="low_expected_edge",
                analogue_agreement=field_confidence,
                regime_agreement=field_stability,
            )

        self.pending_predictions[window.id] = candidate_direction
        return Prediction(
            direction=candidate_direction,
            expected_return_bps=expected_return,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            analogues=base.analogues,
            confidence=confidence,
            raw_direction=candidate_direction,
            analogue_agreement=field_confidence,
            regime_agreement=field_stability,
        )


class WaveMindTimeframePolicyEngine(MarketEngine):
    name = "WaveMind timeframe policy"

    def __init__(
        self,
        encoder: TextVectorEncoder,
        *,
        symbol: str,
        timeframe: str,
        temp_root: Path,
        adaptive_min_support: int = 24,
        adaptive_min_test_support: int = 8,
        adaptive_validation_holdout: float = 0.35,
        adaptive_min_confidence: float = 0.52,
        adaptive_min_expected_edge_bps: float = 70.0,
        adaptive_max_opposition: float = 0.62,
        adaptive_trend_alignment: bool = True,
        adaptive_performance_lookback: int = 8,
        adaptive_min_recent_edge_bps: float = 20.0,
        round_trip_cost_bps: float = 30.0,
        memory_store: str = "disk",
        max_policy_drawdown_bps: float = 400.0,
    ):
        self.timeframe = timeframe
        self.ta = TaRulesEngine()
        self.records: list[OHLCVWindow] = []
        self.pending_predictions: dict[str, str] = {}
        self.realized_signal_nets: list[float] = []
        self.round_trip_cost_bps = float(round_trip_cost_bps)
        self.max_policy_drawdown_bps = float(max_policy_drawdown_bps)
        self.apply_policy_veto = True
        self.child: MarketEngine | None = None
        if timeframe == "1h":
            self.child = WaveMindMicrostructureEngine(
                min_support=adaptive_min_support,
                min_test_support=adaptive_min_test_support,
                validation_holdout=adaptive_validation_holdout,
                performance_lookback=adaptive_performance_lookback,
                min_recent_edge_bps=adaptive_min_recent_edge_bps,
                round_trip_cost_bps=round_trip_cost_bps,
            )
        elif timeframe == "4h":
            self.child = WaveMindAdaptiveFieldEngine(
                encoder,
                symbol=symbol,
                timeframe=timeframe,
                temp_root=temp_root,
                min_support=adaptive_min_support,
                min_test_support=adaptive_min_test_support,
                validation_holdout=adaptive_validation_holdout,
                min_confidence=adaptive_min_confidence,
                min_expected_edge_bps=adaptive_min_expected_edge_bps,
                max_opposition=adaptive_max_opposition,
                require_trend_alignment=adaptive_trend_alignment,
                performance_lookback=adaptive_performance_lookback,
                min_recent_edge_bps=adaptive_min_recent_edge_bps,
                round_trip_cost_bps=round_trip_cost_bps,
                memory_store=memory_store,
            )

    def add(self, window: OHLCVWindow) -> None:
        predicted_direction = self.pending_predictions.pop(window.id, None)
        if predicted_direction is not None:
            self.realized_signal_nets.append(
                _net_return_bps(
                    predicted_direction=predicted_direction,
                    actual_return_bps=window.future_return_bps,
                    round_trip_cost_bps=self.round_trip_cost_bps,
                )
            )
        self.records.append(window)
        if self.child is not None:
            self.child.add(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        max_drawdown_bps = float(getattr(self, "max_policy_drawdown_bps", 0.0))
        realized_drawdown = _max_drawdown_bps(getattr(self, "realized_signal_nets", []))
        if max_drawdown_bps > 0.0 and realized_drawdown >= max_drawdown_bps:
            return Prediction(
                direction="flat",
                expected_return_bps=0.0,
                latency_ms=0.0,
                analogues=[],
                confidence=0.0,
                raw_direction="flat",
                filtered=True,
                filter_reason=f"policy_drawdown_circuit_breaker:{realized_drawdown:.2f}",
            )
        if self.child is not None:
            prediction = self.child.query(window, top_k=top_k)
            ta_prediction = self.ta.query(window, top_k=top_k) if self.apply_policy_veto else None
            if (
                ta_prediction is not None
                and prediction.direction in {"up", "down"}
                and ta_prediction.direction in {"up", "down"}
                and prediction.direction != ta_prediction.direction
            ):
                return Prediction(
                    direction="flat",
                    expected_return_bps=0.0,
                    latency_ms=prediction.latency_ms + ta_prediction.latency_ms,
                    analogues=prediction.analogues,
                    confidence=prediction.confidence,
                    raw_direction=prediction.raw_direction or prediction.direction,
                    candidate_direction=prediction.direction,
                    candidate_expected_return_bps=prediction.expected_return_bps,
                    filtered=True,
                    filter_reason="ta_conflict",
                    analogue_agreement=prediction.analogue_agreement,
                    regime_agreement=prediction.regime_agreement,
                )
            if self.timeframe == "4h" and self.apply_policy_veto and prediction.direction in {"up", "down"}:
                reliability = _local_regime_reliability(
                    self.records,
                    window,
                    direction=prediction.direction,
                    round_trip_cost_bps=self.round_trip_cost_bps,
                )
                if reliability["support"] >= 24 and (
                    reliability["avg_net_bps"] < -20.0
                    or (
                        reliability["hit_rate"] < 0.35
                        and reliability["avg_net_bps"] < -5.0
                    )
                    or (
                        prediction.confidence < 0.60
                        and reliability["hit_rate"] < 0.45
                    )
                ):
                    return Prediction(
                        direction="flat",
                        expected_return_bps=0.0,
                        latency_ms=prediction.latency_ms + (ta_prediction.latency_ms if ta_prediction else 0.0),
                        analogues=prediction.analogues,
                        confidence=min(prediction.confidence, max(0.0, reliability["hit_rate"])),
                        raw_direction=prediction.raw_direction or prediction.direction,
                        candidate_direction=prediction.direction,
                        candidate_expected_return_bps=prediction.expected_return_bps,
                        filtered=True,
                        filter_reason=(
                            "local_regime_negative:"
                            f"support={int(reliability['support'])},"
                            f"hit={reliability['hit_rate']:.3f},"
                            f"net={reliability['avg_net_bps']:.2f}"
                        ),
                        analogue_agreement=prediction.analogue_agreement,
                        regime_agreement=prediction.regime_agreement,
                    )
            if self.apply_policy_veto and prediction.direction in {"up", "down"}:
                guard_reason = ""
                features = window.features
                use_intraday_confidence_guard = self.timeframe in {"1h", "4h"}
                if use_intraday_confidence_guard and prediction.confidence < 0.40:
                    guard_reason = "low_policy_confidence"
                elif (
                    use_intraday_confidence_guard
                    and prediction.direction == "down"
                    and 0.60 <= prediction.confidence < 0.999
                ):
                    guard_reason = "short_squeeze_guard"
                elif use_intraday_confidence_guard and 0.60 <= prediction.confidence < 0.999:
                    guard_reason = "unstable_mid_confidence"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "down"
                    and str(features.get("trend")) == "up"
                ):
                    guard_reason = "one_hour_short_squeeze_guard"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "down"
                    and str(features.get("volume_bucket")) == "normal"
                    and str(features.get("bollinger_bucket")) == "lower_band"
                ):
                    guard_reason = "one_hour_normal_volume_breakdown_exhaustion"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "down"
                    and str(features.get("volume_bucket")) == "expanded"
                    and str(features.get("bollinger_bucket")) == "lower_band"
                ):
                    guard_reason = "one_hour_expanded_volume_breakdown_exhaustion"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "down"
                    and str(features.get("rsi_bucket")) == "overbought"
                    and str(features.get("close_position_bucket")) == "near_high"
                    and str(features.get("bollinger_bucket")) == "upper_band"
                ):
                    guard_reason = "one_hour_breakout_short_guard"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "up"
                    and str(features.get("bollinger_bucket")) == "lower_band"
                    and str(features.get("macd_bucket")) == "flat"
                    and str(features.get("volatility_bucket")) == "high"
                ):
                    guard_reason = "one_hour_stalled_lower_band_bounce"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("bollinger_bucket")) == "upper_band"
                    and str(features.get("volume_bucket")) == "quiet"
                    and prediction.confidence < 0.55
                ):
                    guard_reason = "four_hour_quiet_upper_band_long_exhaustion"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("close_position_bucket")) == "near_high"
                    and str(features.get("bollinger_bucket")) == "middle"
                ):
                    guard_reason = "four_hour_mid_band_near_high_long_exhaustion"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("volume_bucket")) == "quiet"
                    and str(features.get("close_position_bucket")) == "near_high"
                ):
                    guard_reason = "four_hour_quiet_near_high_long_exhaustion"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("volume_bucket")) == "expanded"
                    and str(features.get("close_position_bucket")) == "near_high"
                    and str(features.get("bollinger_bucket")) == "upper_band"
                ):
                    guard_reason = "four_hour_expanded_upper_near_high_long_exhaustion"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("recent_trend")) == "up"
                    and str(features.get("close_position_bucket")) == "middle"
                    and str(features.get("volatility_bucket")) == "high"
                    and str(features.get("drawdown_bucket")) == "deep"
                ):
                    guard_reason = "four_hour_midrange_continuation_trap"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "up"
                    and prediction.confidence < 0.999
                    and str(features.get("trend")) == "down"
                    and str(features.get("rsi_bucket")) == "oversold"
                ):
                    guard_reason = "one_hour_falling_knife_guard"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "up"
                    and str(features.get("rsi_bucket")) == "oversold"
                    and str(features.get("bollinger_bucket")) == "lower_band"
                    and str(features.get("close_position_bucket")) == "near_low"
                    and str(features.get("volatility_bucket")) == "high"
                    and str(features.get("drawdown_bucket")) == "deep"
                    and str(features.get("macd_bucket")) == "down"
                ):
                    range_compression = float(features.get("range_compression") or 0.0)
                    rsi = float(features.get("rsi") or 0.0)
                    if range_compression >= 0.95 or range_compression <= 0.65:
                        guard_reason = "one_hour_unconfirmed_falling_knife_reversal"
                    elif 25.0 <= rsi < 30.0:
                        guard_reason = "one_hour_mid_rsi_falling_knife_reversal"
                if (
                    self.timeframe == "1h"
                    and prediction.direction == "up"
                    and str(features.get("bollinger_bucket")) == "middle"
                    and str(features.get("close_position_bucket")) == "near_high"
                    and str(features.get("volume_bucket")) == "expanded"
                ):
                    guard_reason = "one_hour_expanded_mid_band_late_breakout"
                if (
                    self.timeframe == "4h"
                    and prediction.direction == "up"
                    and str(features.get("bollinger_bucket")) == "upper_band"
                    and str(features.get("close_position_bucket")) == "near_high"
                    and str(features.get("volatility_bucket")) == "high"
                    and str(features.get("drawdown_bucket")) == "deep"
                ):
                    guard_reason = "four_hour_high_vol_upper_band_long_exhaustion"
                recent_edge = _recent_mean(self.realized_signal_nets, lookback=8)
                if len(self.realized_signal_nets) >= 4 and recent_edge < -10.0:
                    defensive_allowed = (
                        self.timeframe == "1h"
                        and prediction.direction == "up"
                        and prediction.confidence >= 0.999
                        and str(features.get("trend")) == "up"
                    )
                    if not defensive_allowed:
                        guard_reason = f"negative_policy_recent_edge:{recent_edge:.2f}"
                elif len(self.realized_signal_nets) >= 4 and recent_edge < 5.0:
                    if 0.60 <= prediction.confidence < 0.999:
                        guard_reason = f"weak_policy_recent_edge:{recent_edge:.2f}"
                if guard_reason:
                    return Prediction(
                        direction="flat",
                        expected_return_bps=0.0,
                        latency_ms=prediction.latency_ms + (ta_prediction.latency_ms if ta_prediction else 0.0),
                        analogues=prediction.analogues,
                        confidence=prediction.confidence,
                        raw_direction=prediction.raw_direction or prediction.direction,
                        candidate_direction=prediction.direction,
                        candidate_expected_return_bps=prediction.expected_return_bps,
                        filtered=True,
                        filter_reason=guard_reason,
                        analogue_agreement=prediction.analogue_agreement,
                        regime_agreement=prediction.regime_agreement,
                    )
            if prediction.direction in {"up", "down"}:
                self.pending_predictions[window.id] = prediction.direction
            return Prediction(
                direction=prediction.direction,
                expected_return_bps=prediction.expected_return_bps,
                latency_ms=prediction.latency_ms + (ta_prediction.latency_ms if ta_prediction else 0.0),
                analogues=prediction.analogues,
                confidence=prediction.confidence,
                raw_direction=prediction.raw_direction,
                candidate_direction=(
                    prediction.candidate_direction
                    or prediction.raw_direction
                    or prediction.direction
                ),
                candidate_expected_return_bps=(
                    prediction.candidate_expected_return_bps
                    if prediction.candidate_expected_return_bps
                    else prediction.expected_return_bps
                ),
                filtered=prediction.filtered,
                filter_reason=prediction.filter_reason,
                analogue_agreement=prediction.analogue_agreement,
                regime_agreement=prediction.regime_agreement,
            )
        return Prediction(
            direction="flat",
            expected_return_bps=0.0,
            latency_ms=0.0,
            analogues=[],
            confidence=0.0,
            raw_direction="flat",
            filtered=True,
            filter_reason=f"unsupported_timeframe:{self.timeframe}",
        )

    def close(self) -> None:
        if self.child is not None:
            self.child.close()


class DtwKnnEngine(MarketEngine):
    name = "DTW kNN"

    def __init__(self):
        self.records: list[OHLCVWindow] = []
        self.texts: list[str] = []
        self.series: list[np.ndarray] = []

    def add(self, window: OHLCVWindow) -> None:
        self.records.append(window)
        self.texts.append(window_to_text(window, include_outcome=False))
        self.series.append(_window_dtw_series(window))

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_series = _window_dtw_series(window)
        distances = np.asarray([_dtw_distance(query_series, item) for item in self.series], dtype=np.float64)
        order = np.argsort(distances)[:top_k]
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            _analogue_from_window(
                self.records[int(index)],
                self.texts[int(index)],
                score=1.0 / (1.0 + float(distances[int(index)])),
            )
            for index in order
        ]
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
        )


class ShapeKnnEngine(MarketEngine):
    name = "OHLCV shape kNN"

    def __init__(self):
        self.records: list[OHLCVWindow] = []
        self.texts: list[str] = []
        self.vectors = np.zeros((0, 1), dtype=np.float32)

    def add(self, window: OHLCVWindow) -> None:
        vector = _window_shape_vector(window)
        if not self.records:
            self.vectors = vector.reshape(1, -1)
        else:
            self.vectors = np.vstack([self.vectors, vector.reshape(1, -1)])
        self.records.append(window)
        self.texts.append(window_to_text(window, include_outcome=False))

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = _window_shape_vector(window)
        distances = np.linalg.norm(self.vectors - query_vector.reshape(1, -1), axis=1)
        order = np.argsort(distances)[:top_k]
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            _analogue_from_window(
                self.records[int(index)],
                self.texts[int(index)],
                score=1.0 / (1.0 + float(distances[int(index)])),
            )
            for index in order
        ]
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
        )


class NaiveEngine(MarketEngine):
    name = "Naive last-regime"

    def __init__(self):
        self.records: list[OHLCVWindow] = []

    def add(self, window: OHLCVWindow) -> None:
        self.records.append(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        latest = self.records[-1]
        latency = (time.perf_counter() - started) * 1000.0
        analogue = _analogue_from_window(latest, window_to_text(latest, include_outcome=False), score=1.0)
        return Prediction(
            direction=latest.direction,
            expected_return_bps=latest.future_return_bps,
            latency_ms=latency,
            analogues=[analogue],
        )


class TrendPersistenceEngine(NaiveEngine):
    name = "Trend persistence"

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        prediction = super().query(window, top_k=top_k)
        if prediction.direction == "flat":
            return prediction
        if _direction_matches_window_trend(prediction.direction, window):
            return prediction
        return Prediction(
            direction="flat",
            expected_return_bps=0.0,
            latency_ms=prediction.latency_ms,
            analogues=prediction.analogues,
            confidence=prediction.confidence,
            raw_direction=prediction.direction,
            filtered=True,
            filter_reason="trend_mismatch",
            analogue_agreement=prediction.analogue_agreement,
            regime_agreement=prediction.regime_agreement,
        )


class TaRulesEngine(MarketEngine):
    name = "TA rules"

    def add(self, window: OHLCVWindow) -> None:
        return None

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        features = window.features
        rsi = float(features["rsi"])
        recent = float(features["recent_return_bps"])
        volume_ratio = float(features["volume_ratio"])
        close_position = float(features["close_position"])
        trend = str(features["trend"])
        if rsi < 35.0 and recent < 0:
            direction = "up"
        elif rsi > 65.0 and recent > 0:
            direction = "down"
        elif trend == "up" and close_position > 0.65 and volume_ratio >= 1.0:
            direction = "up"
        elif trend == "down" and close_position < 0.35 and volume_ratio >= 1.0:
            direction = "down"
        else:
            direction = "flat"
        expected = abs(recent) * 0.55
        if direction == "down":
            expected = -expected
        elif direction == "flat":
            expected = 0.0
        return Prediction(
            direction=direction,
            expected_return_bps=float(expected),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            analogues=[],
        )


class ChromaEngine(StaticKnnEngine):
    name = "Chroma"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.records_by_id: dict[str, tuple[OHLCVWindow, str]] = {}
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore
        except ImportError as exc:
            raise RuntimeError("chromadb is not installed; install the bench extra") from exc
        self.client = chromadb.Client(Settings(anonymized_telemetry=False, allow_reset=True, is_persistent=False))
        self.collection = self.client.create_collection(
            name=f"wmcrypto{uuid.uuid4().hex[:12]}",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=False)
        vector = self.encoder.encode_vector(text)
        self.records_by_id[window.id] = (window, text)
        self.collection.add(
            ids=[window.id],
            documents=[text],
            embeddings=[vector.astype(float).tolist()],
            metadatas=[_window_metadata(window)],
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records_by_id:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False))
        response = self.collection.query(
            query_embeddings=[query_vector.astype(float).tolist()],
            n_results=top_k,
        )
        latency = (time.perf_counter() - started) * 1000.0
        ids = response.get("ids", [[]])[0]
        distances = response.get("distances", [[]])[0]
        analogues = []
        for item_id, distance in zip(ids, distances):
            record, text = self.records_by_id[str(item_id)]
            analogues.append(_analogue_from_window(record, text, score=1.0 - float(distance)))
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        top = analogues[0]
        return Prediction(top.direction, top.future_return_bps, latency, analogues)


class QdrantEngine(StaticKnnEngine):
    name = "Qdrant"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.next_id = 1
        self.records_by_point: dict[int, tuple[OHLCVWindow, str]] = {}
        self.collection_name = f"wmcrypto_{uuid.uuid4().hex[:12]}"
        try:
            from qdrant_client import QdrantClient, models  # type: ignore
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed; install the bench extra") from exc
        self.models = models
        self.client = QdrantClient(":memory:")
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=encoder.vector_dim, distance=models.Distance.COSINE),
        )

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=False)
        vector = self.encoder.encode_vector(text)
        point_id = self.next_id
        self.next_id += 1
        self.records_by_point[point_id] = (window, text)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                self.models.PointStruct(
                    id=point_id,
                    vector=vector.astype(float).tolist(),
                    payload={"window_id": window.id},
                )
            ],
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records_by_point:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False)).astype(float).tolist()
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
            )
            points = response.points
        else:
            points = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
            )
        latency = (time.perf_counter() - started) * 1000.0
        analogues = []
        for point in points:
            point_id = int(point.id)
            record, text = self.records_by_point[point_id]
            analogues.append(_analogue_from_window(record, text, score=float(point.score)))
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        top = analogues[0]
        return Prediction(top.direction, top.future_return_bps, latency, analogues)


def run_walk_forward(
    *,
    markets: list[MarketDataset],
    engines: Iterable[str],
    train_windows: int = 180,
    test_windows: int = 60,
    folds: int = 1,
    fold_stride: int | None = None,
    top_k: int = 5,
    encoder_kind: str = "hash",
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    large_move_bps: float = 75.0,
    position_sizing: str = "fixed",
    analogue_limit: int = 18,
    confidence_threshold: float = 0.65,
    min_analogue_agreement: float = 0.6,
    regime_filter: bool = True,
    min_expected_edge_bps: float = 0.0,
    gate_min_support: float = 0.52,
    gate_min_regime_agreement: float = 0.5,
    gate_performance_lookback: int = 96,
    gate_min_historical_edge_bps: float = 0.0,
    risk_max_opposition: float = 0.62,
    risk_min_regime_agreement: float = 0.35,
    risk_min_historical_edge_bps: float = -20.0,
    adaptive_min_support: int = 24,
    adaptive_min_test_support: int = 8,
    adaptive_validation_holdout: float = 0.35,
    adaptive_min_confidence: float = 0.52,
    adaptive_min_expected_edge_bps: float = 70.0,
    adaptive_max_opposition: float = 0.62,
    adaptive_trend_alignment: bool = True,
    adaptive_performance_lookback: int = 8,
    adaptive_min_recent_edge_bps: float = 20.0,
    memory_store: str = "disk",
    include_event_metrics: bool = False,
) -> dict:
    engine_keys = _normalize_engines(engines)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    round_trip_cost_bps = 2.0 * (float(fee_bps) + float(slippage_bps))
    all_results = []
    by_market = []
    analogue_samples = []
    event_metrics = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for engine_key in engine_keys:
            engine_events: list[EventMetric] = []
            skipped_reason: str | None = None
            for market in markets:
                starts = _fold_starts(
                    market.windows,
                    train_windows=train_windows,
                    test_windows=test_windows,
                    folds=folds,
                    fold_stride=fold_stride,
                )
                for fold_index, fold_start in enumerate(starts):
                    fold_temp_root = (
                        temp_root
                        / _safe_path_part(engine_key)
                        / _safe_path_part(market.symbol)
                        / _safe_path_part(market.timeframe)
                        / f"fold{fold_index}"
                    )
                    fold_temp_root.mkdir(parents=True, exist_ok=True)
                    selected_queries = _select_test_windows(
                        market.windows,
                        train_windows=train_windows,
                        test_windows=test_windows,
                        fold_start=fold_start,
                    )
                    try:
                        engine = _create_engine(
                            engine_key,
                            encoder,
                            market=market,
                            temp_root=fold_temp_root,
                            large_move_bps=large_move_bps,
                            confidence_threshold=confidence_threshold,
                            min_analogue_agreement=min_analogue_agreement,
                            regime_filter=regime_filter,
                            min_expected_edge_bps=min_expected_edge_bps,
                            gate_min_support=gate_min_support,
                            gate_min_regime_agreement=gate_min_regime_agreement,
                            gate_performance_lookback=gate_performance_lookback,
                            gate_min_historical_edge_bps=gate_min_historical_edge_bps,
                            risk_max_opposition=risk_max_opposition,
                            risk_min_regime_agreement=risk_min_regime_agreement,
                            risk_min_historical_edge_bps=risk_min_historical_edge_bps,
                            adaptive_min_support=adaptive_min_support,
                            adaptive_min_test_support=adaptive_min_test_support,
                            adaptive_validation_holdout=adaptive_validation_holdout,
                            adaptive_min_confidence=adaptive_min_confidence,
                            adaptive_min_expected_edge_bps=adaptive_min_expected_edge_bps,
                            adaptive_max_opposition=adaptive_max_opposition,
                            adaptive_trend_alignment=adaptive_trend_alignment,
                            adaptive_performance_lookback=adaptive_performance_lookback,
                            adaptive_min_recent_edge_bps=adaptive_min_recent_edge_bps,
                            round_trip_cost_bps=round_trip_cost_bps,
                            memory_store=memory_store,
                        )
                    except RuntimeError as exc:
                        skipped_reason = str(exc)
                        break
                    added_ids: set[str] = set()
                    market_events: list[EventMetric] = []
                    try:
                        for query_window in selected_queries:
                            _add_mature_history(
                                engine,
                                market.windows,
                                current=query_window,
                                added_ids=added_ids,
                            )
                            prediction = engine.query(query_window, top_k=top_k)
                            event = _event_metric(
                                engine_name=engine.name,
                                window=query_window,
                                prediction=prediction,
                                round_trip_cost_bps=round_trip_cost_bps,
                                large_move_bps=large_move_bps,
                                position_sizing=position_sizing,
                            )
                            market_events.append(event)
                            if len(analogue_samples) < analogue_limit and prediction.analogues:
                                analogue_samples.append(
                                    _analogue_sample(engine.name, query_window, prediction)
                                )
                        engine_events.extend(market_events)
                        if include_event_metrics:
                            for event in market_events:
                                event_payload = asdict(event)
                                event_payload["fold_index"] = int(fold_index)
                                event_payload["fold_start"] = int(fold_start)
                                event_metrics.append(event_payload)
                        by_market.append(
                            _summarize_events(
                                engine.name,
                                market_events,
                                market.symbol,
                                market.timeframe,
                                fold_index=fold_index,
                                fold_start=fold_start,
                            )
                        )
                    finally:
                        engine.close()
                if skipped_reason is not None:
                    break
            if skipped_reason is not None:
                all_results.append(
                    {
                        "engine": _engine_display_name(engine_key),
                        "skipped": True,
                        "skip_reason": skipped_reason,
                    }
                )
            else:
                all_results.append(_summarize_events(_engine_display_name(engine_key), engine_events))

    _attach_slice_robustness(all_results, by_market)

    payload = {
        "scenario": {
            "name": "crypto_walk_forward",
            "dataset_markets": [
                {
                    "symbol": market.symbol,
                    "timeframe": market.timeframe,
                    "bars": len(market.bars),
                    "windows": len(market.windows),
                    "source": market.source,
                    "source_path": market.source_path,
                }
                for market in markets
            ],
            "train_windows": train_windows,
            "test_windows": test_windows,
            "folds": int(folds),
            "fold_stride": int(fold_stride) if fold_stride is not None else None,
            "top_k": top_k,
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "round_trip_cost_bps": round_trip_cost_bps,
            "large_move_bps": float(large_move_bps),
            "position_sizing": position_sizing,
            "confidence_threshold": float(confidence_threshold),
            "min_analogue_agreement": float(min_analogue_agreement),
            "regime_filter": bool(regime_filter),
            "min_expected_edge_bps": float(min_expected_edge_bps),
            "gate_min_support": float(gate_min_support),
            "gate_min_regime_agreement": float(gate_min_regime_agreement),
            "gate_performance_lookback": int(gate_performance_lookback),
            "gate_min_historical_edge_bps": float(gate_min_historical_edge_bps),
            "risk_max_opposition": float(risk_max_opposition),
            "risk_min_regime_agreement": float(risk_min_regime_agreement),
            "risk_min_historical_edge_bps": float(risk_min_historical_edge_bps),
            "adaptive_min_support": int(adaptive_min_support),
            "adaptive_min_test_support": int(adaptive_min_test_support),
            "adaptive_validation_holdout": float(adaptive_validation_holdout),
            "adaptive_min_confidence": float(adaptive_min_confidence),
            "adaptive_min_expected_edge_bps": float(adaptive_min_expected_edge_bps),
            "adaptive_max_opposition": float(adaptive_max_opposition),
            "adaptive_trend_alignment": bool(adaptive_trend_alignment),
            "adaptive_performance_lookback": int(adaptive_performance_lookback),
            "adaptive_min_recent_edge_bps": float(adaptive_min_recent_edge_bps),
            "memory_store": memory_store,
            "note": "Research walk-forward retrieval benchmark. This is not financial advice or a profit claim.",
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
        },
        "results": all_results,
        "by_market": by_market,
        "analogue_samples": analogue_samples,
    }
    if include_event_metrics:
        payload["event_metrics"] = event_metrics
    return payload


def load_markets_from_args(args: argparse.Namespace) -> list[MarketDataset]:
    markets: list[MarketDataset] = []
    direction_threshold = max(15.0, 2.0 * (float(args.fee_bps) + float(args.slippage_bps)))
    if args.dataset == "synthetic":
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                bars = generate_synthetic_ohlcv(symbol=symbol, timeframe=timeframe, bars=args.bars, seed=args.seed)
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=direction_threshold,
                )
                markets.append(
                    MarketDataset(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars=bars,
                        windows=windows,
                        source="synthetic",
                    )
                )
        return markets
    if args.dataset == "csv":
        if args.csv is None:
            raise ValueError("--csv is required for --dataset csv")
        if len(args.symbols) != 1 or len(args.timeframes) != 1:
            raise ValueError("--dataset csv expects one --symbols value and one --timeframes value")
        bars = load_ohlcv_csv(args.csv)
        windows = make_ohlcv_windows(
            bars,
            symbol=args.symbols[0],
            timeframe=args.timeframes[0],
            window=args.window,
            horizon=args.horizon,
            direction_threshold_bps=direction_threshold,
        )
        return [
            MarketDataset(
                symbol=args.symbols[0],
                timeframe=args.timeframes[0],
                bars=bars,
                windows=windows,
                source="csv",
                source_path=str(args.csv),
            )
        ]
    if args.dataset == "ccxt":
        if args.exchange is None:
            raise ValueError("--exchange is required for --dataset ccxt")
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                cache_path = _ccxt_cache_path(args.cache_dir, args.exchange, symbol, timeframe)
                if cache_path is not None and cache_path.exists() and not args.refresh_cache:
                    cached_bars = load_ohlcv_csv(cache_path)
                    if len(cached_bars) >= args.bars:
                        bars = cached_bars[-args.bars :]
                        source = f"ccxt_cache:{args.exchange}"
                        source_path = str(cache_path)
                    else:
                        bars = fetch_ohlcv_ccxt(
                            exchange_id=args.exchange,
                            symbol=symbol,
                            timeframe=timeframe,
                            limit=args.bars,
                        )
                        source = f"ccxt:{args.exchange}"
                        save_ohlcv_csv(cache_path, bars)
                        source_path = str(cache_path)
                else:
                    bars = fetch_ohlcv_ccxt(
                        exchange_id=args.exchange,
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=args.bars,
                    )
                    source = f"ccxt:{args.exchange}"
                    source_path = ""
                    if cache_path is not None:
                        save_ohlcv_csv(cache_path, bars)
                        source_path = str(cache_path)
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=direction_threshold,
                )
                markets.append(
                    MarketDataset(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars=bars,
                        windows=windows,
                        source=source,
                        source_path=source_path,
                    )
                )
        return markets
    raise ValueError(f"Unknown dataset: {args.dataset}")


def _ccxt_cache_path(cache_dir: Path | None, exchange: str, symbol: str, timeframe: str) -> Path | None:
    if cache_dir is None:
        return None
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    safe_timeframe = timeframe.replace("/", "_")
    return cache_dir / exchange / f"{safe_symbol}_{safe_timeframe}.csv"


def write_analogue_html(payload: Mapping[str, object], path: str | Path) -> None:
    rows = []
    for sample in payload.get("analogue_samples", []):  # type: ignore[union-attr]
        query = sample["query"]  # type: ignore[index]
        prediction = sample.get("prediction", {})  # type: ignore[union-attr]
        analogues = sample["analogues"]  # type: ignore[index]
        analogue_rows = "".join(
            "<tr>"
            f"<td>{html.escape(match['start_time'])}</td>"
            f"<td>{html.escape(match['direction'])}</td>"
            f"<td>{float(match['future_return_bps']):.1f}</td>"
            f"<td>{float(match.get('max_favorable_excursion_bps', 0.0)):.1f}</td>"
            f"<td>{float(match.get('max_adverse_excursion_bps', 0.0)):.1f}</td>"
            f"<td>{float(match['score']):.3f}</td>"
            "</tr>"
            for match in analogues
        )
        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(sample['engine'])} - {html.escape(query['symbol'])} {html.escape(query['timeframe'])}</h2>"
            f"<p class='muted'>Current window: {html.escape(query['start_time'])} -> {html.escape(query['end_time'])}</p>"
            f"<p>Actual next move: <strong>{html.escape(query['direction'])}</strong> "
            f"({float(query['future_return_bps']):.1f} bps)</p>"
            f"<p>Decision: <strong>{html.escape(str(prediction.get('direction', '')))}</strong> "
            f"(raw {html.escape(str(prediction.get('raw_direction', '')))}, "
            f"confidence {float(prediction.get('confidence', 0.0)):.3f}, "
            f"filtered {html.escape(str(prediction.get('filtered', False)))})</p>"
            "<table><thead><tr><th>Historical window</th><th>Next move</th><th>Return bps</th><th>MFE bps</th><th>MAE bps</th><th>Score</th></tr></thead>"
            f"<tbody>{analogue_rows}</tbody></table>"
            "</section>"
        )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>WaveMind Crypto Analogue Explorer</title>"
        "<style>"
        "body{font-family:Inter,Arial,sans-serif;margin:32px;background:#f7f7f5;color:#111}"
        "h1{font-size:28px;margin-bottom:4px}.muted{color:#666}.card{background:white;border:1px solid #ddd;"
        "border-radius:8px;padding:18px;margin:18px 0;box-shadow:0 1px 2px #0001}"
        "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #eee;"
        "padding:8px;text-align:left}th{background:#fafafa}"
        "</style></head><body>"
        "<h1>WaveMind Crypto Analogue Explorer</h1>"
        "<p class='muted'>Research view: current market windows and similar historical windows. Not financial advice.</p>"
        f"{''.join(rows) if rows else '<p>No analogue samples were produced.</p>'}"
        "</body></html>"
    )
    html_path = Path(path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(document, encoding="utf-8")


def print_table(payload: Mapping[str, object]) -> None:
    print(
        "| engine | direction@1 | active d1 | signal rate | sized net bps | "
        "profit factor | max DD bps | +slices | worst slice | large FP | filtered | avg latency | queries |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for result in payload["results"]:  # type: ignore[index]
        if result.get("skipped"):  # type: ignore[union-attr]
            print(
                f"| {result['engine']} | skipped | skipped | skipped | skipped | "
                "skipped | skipped | skipped | skipped | skipped | skipped | skipped | 0 |"
            )
            continue
        print(
            f"| {result['engine']} | "
            f"{result['direction_accuracy_at_1']:.3f} | "
            f"{result['active_direction_accuracy']:.3f} | "
            f"{result['signal_rate']:.3f} | "
            f"{result['avg_sized_net_return_bps']:.2f} | "
            f"{result['sized_profit_factor']:.3f} | "
            f"{result['sized_max_drawdown_bps']:.1f} | "
            f"{result.get('positive_market_slices', 0)}/{result.get('market_slices', 0)} | "
            f"{result.get('worst_market_slice_sized_net_bps', 0.0):.2f} | "
            f"{result['large_move_false_positive_rate']:.3f} | "
            f"{result['filtered_rate']:.3f} | "
            f"{result['avg_latency_ms']:.2f} ms | "
            f"{result['queries']} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["synthetic", "csv", "ccxt"], default="synthetic")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument(
        "--engines",
        nargs="+",
        default=[
            "wavemind",
            "4h-profile",
            "risk-overlay",
            "regime-gated",
            "calibrated",
            "field-off",
            "shape",
            "naive",
            "ta",
        ],
    )
    parser.add_argument("--bars", type=int, default=420)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--train-windows", type=int, default=180)
    parser.add_argument("--test-windows", type=int, default=60)
    parser.add_argument("--folds", type=int, default=1)
    parser.add_argument("--fold-stride", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--large-move-bps", type=float, default=75.0)
    parser.add_argument("--position-sizing", choices=["fixed", "confidence"], default="fixed")
    parser.add_argument("--confidence-threshold", type=float, default=0.65)
    parser.add_argument("--min-analogue-agreement", type=float, default=0.6)
    parser.add_argument("--min-expected-edge-bps", type=float, default=0.0)
    parser.add_argument("--gate-min-support", type=float, default=0.52)
    parser.add_argument("--gate-min-regime-agreement", type=float, default=0.5)
    parser.add_argument("--gate-performance-lookback", type=int, default=96)
    parser.add_argument("--gate-min-historical-edge-bps", type=float, default=0.0)
    parser.add_argument("--risk-max-opposition", type=float, default=0.62)
    parser.add_argument("--risk-min-regime-agreement", type=float, default=0.35)
    parser.add_argument("--risk-min-historical-edge-bps", type=float, default=-20.0)
    parser.add_argument("--adaptive-min-support", type=int, default=24)
    parser.add_argument("--adaptive-min-test-support", type=int, default=8)
    parser.add_argument("--adaptive-validation-holdout", type=float, default=0.35)
    parser.add_argument("--adaptive-min-confidence", type=float, default=0.52)
    parser.add_argument("--adaptive-min-expected-edge-bps", type=float, default=70.0)
    parser.add_argument("--adaptive-max-opposition", type=float, default=0.62)
    parser.add_argument("--disable-adaptive-trend-alignment", action="store_true")
    parser.add_argument("--adaptive-performance-lookback", type=int, default=8)
    parser.add_argument("--adaptive-min-recent-edge-bps", type=float, default=20.0)
    parser.add_argument("--memory-store", choices=["disk", "memory"], default="disk")
    parser.add_argument("--disable-regime-filter", action="store_true")
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--include-event-metrics",
        action="store_true",
        help="Include per-query event metrics in the JSON output for regime diagnostics.",
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_walk_forward_results.json"))
    parser.add_argument("--analogue-html", type=Path, default=Path("benchmarks/crypto_analogue_explorer.html"))
    args = parser.parse_args()

    markets = load_markets_from_args(args)
    payload = run_walk_forward(
        markets=markets,
        engines=args.engines,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        folds=args.folds,
        fold_stride=args.fold_stride,
        top_k=args.top_k,
        encoder_kind=args.encoder,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        large_move_bps=args.large_move_bps,
        position_sizing=args.position_sizing,
        confidence_threshold=args.confidence_threshold,
        min_analogue_agreement=args.min_analogue_agreement,
        regime_filter=not args.disable_regime_filter,
        min_expected_edge_bps=args.min_expected_edge_bps,
        gate_min_support=args.gate_min_support,
        gate_min_regime_agreement=args.gate_min_regime_agreement,
        gate_performance_lookback=args.gate_performance_lookback,
        gate_min_historical_edge_bps=args.gate_min_historical_edge_bps,
        risk_max_opposition=args.risk_max_opposition,
        risk_min_regime_agreement=args.risk_min_regime_agreement,
        risk_min_historical_edge_bps=args.risk_min_historical_edge_bps,
        adaptive_min_support=args.adaptive_min_support,
        adaptive_min_test_support=args.adaptive_min_test_support,
        adaptive_validation_holdout=args.adaptive_validation_holdout,
        adaptive_min_confidence=args.adaptive_min_confidence,
        adaptive_min_expected_edge_bps=args.adaptive_min_expected_edge_bps,
        adaptive_max_opposition=args.adaptive_max_opposition,
        adaptive_trend_alignment=not args.disable_adaptive_trend_alignment,
        adaptive_performance_lookback=args.adaptive_performance_lookback,
        adaptive_min_recent_edge_bps=args.adaptive_min_recent_edge_bps,
        memory_store=args.memory_store,
        include_event_metrics=args.include_event_metrics,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_analogue_html(payload, args.analogue_html)
    print_table(payload)
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.analogue_html}")
    return 0


def _normalize_engines(engines: Iterable[str]) -> list[str]:
    normalized = []
    for engine in engines:
        key = engine.lower()
        if key == "all":
            normalized.extend(
                [
                    "wavemind",
                    "4h-profile",
                    "risk-overlay",
                    "trend-risk",
                    "microstructure",
                    "daily-trend-memory",
                    "timeframe-policy",
                    "adaptive-field",
                    "regime-gated",
                    "calibrated",
                    "field-off",
                    "shape",
                    "naive",
                    "trend-persistence",
                    "ta",
                    "static",
                    "chroma",
                    "qdrant",
                ]
            )
        elif key == "market":
            normalized.extend(
                [
                    "wavemind",
                    "4h-profile",
                    "risk-overlay",
                    "trend-risk",
                    "microstructure",
                    "daily-trend-memory",
                    "timeframe-policy",
                    "adaptive-field",
                    "regime-gated",
                    "calibrated",
                    "field-off",
                    "shape",
                    "naive",
                    "trend-persistence",
                    "ta",
                ]
            )
        elif key == "storage-controls":
            normalized.extend(["static", "chroma", "qdrant"])
        else:
            normalized.append(key)
    valid = {
        "wavemind",
        "wavemind-field",
        "market-field",
        "wavemind-market-field",
        "calibrated",
        "wavemind-calibrated",
        "field-calibrated",
        "field-off-calibrated",
        "calibrated-field-off",
        "wavemind-field-off-calibrated",
        "regime-gated",
        "wavemind-regime-gated",
        "gate",
        "risk-overlay",
        "wavemind-risk-overlay",
        "risk",
        "trend-risk",
        "wavemind-trend-risk",
        "microstructure",
        "wavemind-microstructure",
        "daily-trend-memory",
        "wavemind-daily-trend-memory",
        "daily-memory",
        "timeframe-policy",
        "wavemind-timeframe-policy",
        "adaptive-field",
        "wavemind-adaptive-field",
        "validated-field",
        "4h-profile",
        "wavemind-4h-profile",
        "four-hour-profile",
        "field-off",
        "wavemind-field-off",
        "static",
        "static-knn",
        "dtw",
        "dtw-knn",
        "shape",
        "shape-knn",
        "ohlcv-shape",
        "chroma",
        "qdrant",
        "naive",
        "trend-persistence",
        "trend",
        "ta",
        "ta-rules",
    }
    unknown = [engine for engine in normalized if engine not in valid]
    if unknown:
        raise ValueError(f"Unknown engine(s): {', '.join(unknown)}")
    return normalized


def _create_engine(
    engine_key: str,
    encoder: TextVectorEncoder,
    *,
    market: MarketDataset,
    temp_root: Path,
    large_move_bps: float = 75.0,
    confidence_threshold: float = 0.65,
    min_analogue_agreement: float = 0.6,
    regime_filter: bool = True,
    min_expected_edge_bps: float = 0.0,
    gate_min_support: float = 0.52,
    gate_min_regime_agreement: float = 0.5,
    gate_performance_lookback: int = 96,
    gate_min_historical_edge_bps: float = 0.0,
    risk_max_opposition: float = 0.62,
    risk_min_regime_agreement: float = 0.35,
    risk_min_historical_edge_bps: float = -20.0,
    adaptive_min_support: int = 24,
    adaptive_min_test_support: int = 8,
    adaptive_validation_holdout: float = 0.35,
    adaptive_min_confidence: float = 0.52,
    adaptive_min_expected_edge_bps: float = 70.0,
    adaptive_max_opposition: float = 0.62,
    adaptive_trend_alignment: bool = True,
    adaptive_performance_lookback: int = 8,
    adaptive_min_recent_edge_bps: float = 20.0,
    round_trip_cost_bps: float = 30.0,
    memory_store: str = "disk",
) -> MarketEngine:
    if engine_key in {"wavemind", "wavemind-field"}:
        return WaveMindEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            memory_store=memory_store,
        )
    if engine_key in {"market-field", "wavemind-market-field"}:
        return WaveMindEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            use_field=True,
            db_label="marketfield",
            vector_weight=0.98,
            field_weight=0.02,
            priority_weight=0.0,
            lexical_weight=0.0,
            memory_store=memory_store,
        )
    if engine_key in {"calibrated", "wavemind-calibrated", "field-calibrated"}:
        return WaveMindEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            calibrated=True,
            min_analogue_agreement=min_analogue_agreement,
            confidence_threshold=confidence_threshold,
            regime_filter=regime_filter,
            large_move_bps=large_move_bps,
            min_expected_edge_bps=min_expected_edge_bps,
            memory_store=memory_store,
        )
    if engine_key in {"field-off-calibrated", "calibrated-field-off", "wavemind-field-off-calibrated"}:
        return WaveMindEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            use_field=False,
            calibrated=True,
            min_analogue_agreement=min_analogue_agreement,
            confidence_threshold=confidence_threshold,
            regime_filter=regime_filter,
            large_move_bps=large_move_bps,
            min_expected_edge_bps=min_expected_edge_bps,
            memory_store=memory_store,
        )
    if engine_key in {"regime-gated", "wavemind-regime-gated", "gate"}:
        return WaveMindRegimeGateEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            min_support=gate_min_support,
            min_regime_agreement=gate_min_regime_agreement,
            min_expected_edge_bps=min_expected_edge_bps,
            performance_lookback=gate_performance_lookback,
            min_historical_edge_bps=gate_min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"risk-overlay", "wavemind-risk-overlay", "risk"}:
        return WaveMindRiskOverlayEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            max_opposition=risk_max_opposition,
            min_regime_agreement=risk_min_regime_agreement,
            performance_lookback=gate_performance_lookback,
            min_historical_edge_bps=risk_min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"trend-risk", "wavemind-trend-risk"}:
        return WaveMindTrendRiskEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            max_opposition=risk_max_opposition,
            min_regime_agreement=risk_min_regime_agreement,
            performance_lookback=gate_performance_lookback,
            min_historical_edge_bps=risk_min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"adaptive-field", "wavemind-adaptive-field", "validated-field"}:
        return WaveMindAdaptiveFieldEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            min_support=adaptive_min_support,
            min_test_support=adaptive_min_test_support,
            validation_holdout=adaptive_validation_holdout,
            min_confidence=adaptive_min_confidence,
            min_expected_edge_bps=adaptive_min_expected_edge_bps,
            max_opposition=adaptive_max_opposition,
            require_trend_alignment=adaptive_trend_alignment,
            performance_lookback=adaptive_performance_lookback,
            min_recent_edge_bps=adaptive_min_recent_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"microstructure", "wavemind-microstructure"}:
        return WaveMindMicrostructureEngine(
            min_support=adaptive_min_support,
            min_test_support=adaptive_min_test_support,
            validation_holdout=adaptive_validation_holdout,
            round_trip_cost_bps=round_trip_cost_bps,
        )
    if engine_key in {"daily-trend-memory", "wavemind-daily-trend-memory", "daily-memory"}:
        return WaveMindDailyTrendMemoryEngine(
            min_support=max(18, int(adaptive_min_support * 0.75)),
            min_test_support=max(6, int(adaptive_min_test_support * 0.75)),
            validation_holdout=adaptive_validation_holdout,
            min_expected_edge_bps=adaptive_min_expected_edge_bps,
            performance_lookback=max(4, adaptive_performance_lookback),
            min_recent_edge_bps=-20.0,
            round_trip_cost_bps=round_trip_cost_bps,
        )
    if engine_key in {"timeframe-policy", "wavemind-timeframe-policy"}:
        return WaveMindTimeframePolicyEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            adaptive_min_support=adaptive_min_support,
            adaptive_min_test_support=adaptive_min_test_support,
            adaptive_validation_holdout=adaptive_validation_holdout,
            adaptive_min_confidence=adaptive_min_confidence,
            adaptive_min_expected_edge_bps=adaptive_min_expected_edge_bps,
            adaptive_max_opposition=adaptive_max_opposition,
            adaptive_trend_alignment=adaptive_trend_alignment,
            adaptive_performance_lookback=adaptive_performance_lookback,
            adaptive_min_recent_edge_bps=adaptive_min_recent_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"4h-profile", "wavemind-4h-profile", "four-hour-profile"}:
        return WaveMindFourHourProfileEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            min_support=gate_min_support,
            min_regime_agreement=gate_min_regime_agreement,
            min_expected_edge_bps=min_expected_edge_bps,
            performance_lookback=gate_performance_lookback,
            min_historical_edge_bps=gate_min_historical_edge_bps,
            round_trip_cost_bps=round_trip_cost_bps,
            memory_store=memory_store,
        )
    if engine_key in {"field-off", "wavemind-field-off"}:
        return WaveMindEngine(
            encoder,
            symbol=market.symbol,
            timeframe=market.timeframe,
            temp_root=temp_root,
            use_field=False,
            memory_store=memory_store,
        )
    if engine_key in {"static", "static-knn"}:
        return StaticKnnEngine(encoder)
    if engine_key in {"dtw", "dtw-knn"}:
        return DtwKnnEngine()
    if engine_key in {"shape", "shape-knn", "ohlcv-shape"}:
        return ShapeKnnEngine()
    if engine_key == "chroma":
        return ChromaEngine(encoder)
    if engine_key == "qdrant":
        return QdrantEngine(encoder)
    if engine_key == "naive":
        return NaiveEngine()
    if engine_key in {"trend-persistence", "trend"}:
        return TrendPersistenceEngine()
    if engine_key in {"ta", "ta-rules"}:
        return TaRulesEngine()
    raise ValueError(f"Unknown engine: {engine_key}")


def _engine_display_name(engine_key: str) -> str:
    return {
        "wavemind": "WaveMind field",
        "wavemind-field": "WaveMind field",
        "market-field": "WaveMind market-field",
        "wavemind-market-field": "WaveMind market-field",
        "calibrated": "WaveMind calibrated",
        "wavemind-calibrated": "WaveMind calibrated",
        "field-calibrated": "WaveMind calibrated",
        "field-off-calibrated": "WaveMind field-off calibrated",
        "calibrated-field-off": "WaveMind field-off calibrated",
        "wavemind-field-off-calibrated": "WaveMind field-off calibrated",
        "regime-gated": "WaveMind regime-gated",
        "wavemind-regime-gated": "WaveMind regime-gated",
        "gate": "WaveMind regime-gated",
        "risk-overlay": "WaveMind risk-overlay",
        "wavemind-risk-overlay": "WaveMind risk-overlay",
        "risk": "WaveMind risk-overlay",
        "trend-risk": "WaveMind trend-risk",
        "wavemind-trend-risk": "WaveMind trend-risk",
        "microstructure": "WaveMind microstructure",
        "wavemind-microstructure": "WaveMind microstructure",
        "daily-trend-memory": "WaveMind daily trend-memory",
        "wavemind-daily-trend-memory": "WaveMind daily trend-memory",
        "daily-memory": "WaveMind daily trend-memory",
        "timeframe-policy": "WaveMind timeframe policy",
        "wavemind-timeframe-policy": "WaveMind timeframe policy",
        "adaptive-field": "WaveMind adaptive-field",
        "wavemind-adaptive-field": "WaveMind adaptive-field",
        "validated-field": "WaveMind adaptive-field",
        "4h-profile": "WaveMind 4h profile",
        "wavemind-4h-profile": "WaveMind 4h profile",
        "four-hour-profile": "WaveMind 4h profile",
        "field-off": "WaveMind field-off",
        "wavemind-field-off": "WaveMind field-off",
        "static": "Static kNN",
        "static-knn": "Static kNN",
        "dtw": "DTW kNN",
        "dtw-knn": "DTW kNN",
        "shape": "OHLCV shape kNN",
        "shape-knn": "OHLCV shape kNN",
        "ohlcv-shape": "OHLCV shape kNN",
        "chroma": "Chroma",
        "qdrant": "Qdrant",
        "naive": "Naive last-regime",
        "trend-persistence": "Trend persistence",
        "trend": "Trend persistence",
        "ta": "TA rules",
        "ta-rules": "TA rules",
    }[engine_key]


def _select_test_windows(
    windows: list[OHLCVWindow],
    *,
    train_windows: int,
    test_windows: int,
    fold_start: int | None = None,
) -> list[OHLCVWindow]:
    if train_windows <= 0 or test_windows <= 0:
        raise ValueError("train_windows and test_windows must be positive")
    start = train_windows if fold_start is None else int(fold_start)
    if start < train_windows:
        raise ValueError("fold_start cannot be smaller than train_windows")
    end = start + test_windows
    if len(windows) < end:
        raise ValueError(
            f"not enough windows: need at least {end}, got {len(windows)}. "
            "Increase --bars or reduce train/test windows."
        )
    return windows[start:end]


def _fold_starts(
    windows: list[OHLCVWindow],
    *,
    train_windows: int,
    test_windows: int,
    folds: int,
    fold_stride: int | None,
) -> list[int]:
    if folds <= 0:
        raise ValueError("folds must be positive")
    if fold_stride is not None and fold_stride <= 0:
        raise ValueError("fold_stride must be positive")
    first = int(train_windows)
    max_start = len(windows) - int(test_windows)
    if max_start < first:
        raise ValueError(
            f"not enough windows: need at least {first + test_windows}, got {len(windows)}. "
            "Increase --bars or reduce train/test windows."
        )
    if folds == 1:
        return [first]
    if fold_stride is not None:
        starts = [first + index * int(fold_stride) for index in range(int(folds))]
        starts = [start for start in starts if start <= max_start]
        if not starts:
            return [first]
        return starts
    span = max_start - first
    if span <= 0:
        return [first]
    starts = [
        int(round(first + (span * index / max(1, int(folds) - 1))))
        for index in range(int(folds))
    ]
    return sorted(set(min(max_start, max(first, start)) for start in starts))


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "item"


def _add_mature_history(
    engine: MarketEngine,
    windows: list[OHLCVWindow],
    *,
    current: OHLCVWindow,
    added_ids: set[str],
) -> None:
    for historical in windows:
        if historical.id in added_ids:
            continue
        if historical.start_ts >= current.start_ts:
            break
        if historical.future_end_ts <= current.end_ts:
            engine.add(historical)
            added_ids.add(historical.id)


def _event_metric(
    *,
    engine_name: str,
    window: OHLCVWindow,
    prediction: Prediction,
    round_trip_cost_bps: float,
    large_move_bps: float,
    position_sizing: str,
) -> EventMetric:
    direction_at_1 = 1.0 if prediction.direction == window.direction else 0.0
    top3_directions = [match.direction for match in prediction.analogues[:3]]
    if not top3_directions:
        top3_directions = [prediction.direction]
    direction_at_3 = 1.0 if window.direction in top3_directions else 0.0
    net = _net_return_bps(
        predicted_direction=prediction.direction,
        actual_return_bps=window.future_return_bps,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    position_size = _position_size(
        prediction,
        large_move_bps=large_move_bps,
        mode=position_sizing,
    )
    top = prediction.analogues[0] if prediction.analogues else None
    predicted_mfe = float(top.max_favorable_excursion_bps) if top else max(0.0, prediction.expected_return_bps)
    predicted_mae = float(top.max_adverse_excursion_bps) if top else min(0.0, prediction.expected_return_bps)
    predicted_vol = float(top.future_realized_vol_bps) if top else abs(prediction.expected_return_bps)
    predicted_large = abs(float(prediction.expected_return_bps)) >= float(large_move_bps)
    actual_large = abs(float(window.future_return_bps)) >= float(large_move_bps)
    return EventMetric(
        engine=engine_name,
        symbol=window.symbol,
        timeframe=window.timeframe,
        query_id=window.id,
        actual_direction=window.direction,
        predicted_direction=prediction.direction,
        actual_return_bps=float(window.future_return_bps),
        actual_mfe_bps=float(window.max_favorable_excursion_bps),
        actual_mae_bps=float(window.max_adverse_excursion_bps),
        actual_future_vol_bps=float(window.future_realized_vol_bps),
        predicted_return_bps=float(prediction.expected_return_bps),
        predicted_mfe_bps=predicted_mfe,
        predicted_mae_bps=predicted_mae,
        predicted_future_vol_bps=predicted_vol,
        direction_at_1=direction_at_1,
        direction_at_3=direction_at_3,
        abs_return_error_bps=abs(float(prediction.expected_return_bps) - float(window.future_return_bps)),
        abs_mfe_error_bps=abs(predicted_mfe - float(window.max_favorable_excursion_bps)),
        abs_mae_error_bps=abs(predicted_mae - float(window.max_adverse_excursion_bps)),
        abs_future_vol_error_bps=abs(predicted_vol - float(window.future_realized_vol_bps)),
        predicted_large_move=1.0 if predicted_large else 0.0,
        actual_large_move=1.0 if actual_large else 0.0,
        large_move_true_positive=1.0 if predicted_large and actual_large else 0.0,
        large_move_false_positive=1.0 if predicted_large and not actual_large else 0.0,
        position_size=position_size,
        confidence=float(prediction.confidence),
        raw_direction=prediction.raw_direction,
        candidate_direction=prediction.candidate_direction,
        candidate_expected_return_bps=float(prediction.candidate_expected_return_bps),
        filter_reason=prediction.filter_reason,
        analogue_agreement=float(prediction.analogue_agreement),
        regime_agreement=float(prediction.regime_agreement),
        regime_signature=_regime_signature_from_window(window),
        features=dict(window.features),
        filtered=1.0 if prediction.filtered else 0.0,
        net_return_bps=net,
        sized_net_return_bps=net * position_size,
        latency_ms=float(prediction.latency_ms),
    )


def _net_return_bps(
    *,
    predicted_direction: str,
    actual_return_bps: float,
    round_trip_cost_bps: float,
) -> float:
    if predicted_direction == "up":
        return float(actual_return_bps) - round_trip_cost_bps
    if predicted_direction == "down":
        return -float(actual_return_bps) - round_trip_cost_bps
    return 0.0


def _directional_edge_after_cost_bps(
    direction: str,
    expected_return_bps: float,
    *,
    round_trip_cost_bps: float,
) -> float:
    if direction == "up":
        return float(expected_return_bps) - float(round_trip_cost_bps)
    if direction == "down":
        return -float(expected_return_bps) - float(round_trip_cost_bps)
    return 0.0


def _rolling_last_regime_edge(
    records: list[OHLCVWindow],
    *,
    lookback: int,
    round_trip_cost_bps: float,
) -> float:
    if len(records) < 2:
        return 0.0
    usable = records[-max(2, int(lookback) + 1) :]
    nets = [
        _net_return_bps(
            predicted_direction=previous.direction,
            actual_return_bps=current.future_return_bps,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        for previous, current in zip(usable, usable[1:], strict=False)
    ]
    return float(statistics.mean(nets)) if nets else 0.0


def _direction_matches_window_trend(direction: str, window: OHLCVWindow) -> bool:
    if direction == "up":
        return str(window.features.get("trend")) == "up"
    if direction == "down":
        return str(window.features.get("trend")) == "down"
    return False


def _adaptive_relationship_field_signal(
    records: list[OHLCVWindow],
    window: OHLCVWindow,
    *,
    min_support: int,
    min_test_support: int,
    validation_holdout: float,
    round_trip_cost_bps: float,
) -> dict[str, float | int | str]:
    return_history = [float(record.future_return_bps) for record in records]
    relationship_history: dict[tuple[str, ...], list[tuple[int, float]]] = {}
    for index, record in enumerate(records):
        for relationship in _relationship_candidates(_regime_signature_from_window(record)):
            relationship_history.setdefault(relationship, []).append((index, float(record.future_return_bps)))
    return _adaptive_relationship_field_signal_from_index(
        return_history,
        relationship_history,
        window,
        min_support=min_support,
        min_test_support=min_test_support,
        validation_holdout=validation_holdout,
        round_trip_cost_bps=round_trip_cost_bps,
    )


def _adaptive_relationship_field_signal_from_index(
    return_history: list[float],
    relationship_history: Mapping[tuple[str, ...], list[tuple[int, float]]],
    window: OHLCVWindow,
    *,
    min_support: int,
    min_test_support: int,
    validation_holdout: float,
    round_trip_cost_bps: float,
) -> dict[str, float | int | str]:
    tokens = tuple(sorted(set(_regime_signature_from_window(window))))
    if not tokens:
        return _flat_adaptive_signal("empty_regime_signature")
    candidates = _relationship_candidates(tokens)
    split = _adaptive_split_index_from_length(
        len(return_history),
        validation_holdout=validation_holdout,
        min_test_support=min_test_support,
    )
    train_returns = [(index, value) for index, value in enumerate(return_history[:split])]
    holdout_returns = [(index, value) for index, value in enumerate(return_history[split:], start=split)]
    if len(train_returns) < min_support or len(holdout_returns) < min_test_support:
        return _flat_adaptive_signal("insufficient_validation_history")

    train_global = _recency_weighted_mean_indexed(train_returns, max_index=split - 1)
    holdout_global = _recency_weighted_mean_indexed(holdout_returns, max_index=len(return_history) - 1)
    scored = []
    for candidate in candidates:
        candidate_history = relationship_history.get(candidate, [])
        train_group = [item for item in candidate_history if item[0] < split]
        holdout_group = [item for item in candidate_history if item[0] >= split]
        if len(train_group) < min_support or len(holdout_group) < min_test_support:
            continue
        train_avg = _recency_weighted_mean_indexed(train_group, max_index=split - 1)
        holdout_avg = _recency_weighted_mean_indexed(holdout_group, max_index=len(return_history) - 1)
        train_lift = train_avg - train_global
        holdout_lift = holdout_avg - holdout_global
        if abs(train_lift) < 1e-9:
            continue
        expected_lift_sign = 1.0 if train_lift > 0.0 else -1.0
        signed_holdout_lift = holdout_lift * expected_lift_sign
        if signed_holdout_lift <= 0.0:
            continue
        expected_return = 0.35 * train_avg + 0.65 * holdout_avg
        direction = "up" if expected_return > 0.0 else "down" if expected_return < 0.0 else "flat"
        edge = _directional_edge_after_cost_bps(
            direction,
            expected_return,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        if direction == "flat" or edge <= 0.0:
            continue
        stability = max(0.0, min(1.0, signed_holdout_lift / max(abs(train_lift), 1.0)))
        support = len(train_group) + len(holdout_group)
        specificity = 1.0 + 0.22 * (len(candidate) - 1)
        support_gain = math.log1p(support)
        score = edge * support_gain * specificity * (0.55 + 0.45 * stability)
        scored.append(
            {
                "direction": direction,
                "score": float(score),
                "expected_return_bps": float(expected_return),
                "edge_bps": float(edge),
                "stability": float(stability),
                "support": int(support),
                "features": " & ".join(candidate),
            }
        )
    if not scored:
        return _flat_adaptive_signal("no_validated_relationship")

    totals = {
        "up": sum(float(item["score"]) for item in scored if item["direction"] == "up"),
        "down": sum(float(item["score"]) for item in scored if item["direction"] == "down"),
    }
    direction = "up" if totals["up"] >= totals["down"] else "down"
    selected = [item for item in scored if item["direction"] == direction]
    total_score = max(sum(float(item["score"]) for item in selected), 1e-12)
    expected_return = sum(float(item["expected_return_bps"]) * float(item["score"]) for item in selected) / total_score
    total_all = max(totals["up"] + totals["down"], 1e-12)
    dominance = totals[direction] / total_all
    total_support = sum(int(item["support"]) for item in selected)
    support_factor = min(1.0, total_support / max(float(min_support * 5), 1.0))
    stability = sum(float(item["stability"]) * float(item["score"]) for item in selected) / total_score
    edge = _directional_edge_after_cost_bps(
        direction,
        expected_return,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    edge_factor = min(1.0, max(0.0, edge / max(float(round_trip_cost_bps) * 2.0, 1.0)))
    confidence = float(max(0.0, min(1.0, dominance * (0.25 + 0.30 * support_factor + 0.30 * stability + 0.15 * edge_factor))))
    return {
        "direction": direction,
        "expected_return_bps": float(expected_return),
        "edge_bps": float(edge),
        "confidence": confidence,
        "stability": float(stability),
        "support": int(total_support),
        "relationships": int(len(selected)),
        "reason": "",
    }


def _relationship_candidates(tokens: Iterable[str]) -> list[tuple[str, ...]]:
    unique = tuple(sorted(set(tokens)))
    candidates = [(token,) for token in unique]
    candidates.extend(tuple(sorted(pair)) for pair in itertools.combinations(unique, 2))
    return candidates


def _local_regime_reliability(
    records: list[OHLCVWindow],
    window: OHLCVWindow,
    *,
    direction: str,
    round_trip_cost_bps: float,
    min_overlap: int = 2,
    lookback: int = 160,
) -> dict[str, float]:
    if direction not in {"up", "down"} or not records:
        return {"support": 0.0, "hit_rate": 0.0, "avg_net_bps": 0.0}
    query_tokens = set(_regime_signature_from_window(window))
    candidates: list[tuple[int, float, float]] = []
    recent_records = records[-max(1, int(lookback)) :]
    for index, record in enumerate(recent_records):
        overlap = len(query_tokens.intersection(_regime_signature_from_window(record)))
        if overlap < min_overlap:
            continue
        net = _net_return_bps(
            predicted_direction=direction,
            actual_return_bps=record.future_return_bps,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        candidates.append((index, float(overlap), float(net)))
    if not candidates:
        return {"support": 0.0, "hit_rate": 0.0, "avg_net_bps": 0.0}
    span = max(1, len(recent_records))
    weighted_net = 0.0
    weighted_hits = 0.0
    total_weight = 0.0
    half_life = max(8.0, span / 3.0)
    for index, overlap, net in candidates:
        recency_weight = math.exp(-float(span - index - 1) / half_life)
        overlap_weight = 1.0 + 0.18 * max(0.0, overlap - float(min_overlap))
        weight = recency_weight * overlap_weight
        weighted_net += net * weight
        weighted_hits += (1.0 if net > 0.0 else 0.0) * weight
        total_weight += weight
    denominator = max(total_weight, 1e-12)
    return {
        "support": float(len(candidates)),
        "hit_rate": float(weighted_hits / denominator),
        "avg_net_bps": float(weighted_net / denominator),
    }


def _flat_adaptive_signal(reason: str) -> dict[str, float | int | str]:
    return {
        "direction": "flat",
        "expected_return_bps": 0.0,
        "edge_bps": 0.0,
        "confidence": 0.0,
        "stability": 0.0,
        "support": 0,
        "relationships": 0,
        "reason": reason,
    }


def _adaptive_split_index(
    records: list[OHLCVWindow],
    *,
    validation_holdout: float,
    min_test_support: int,
) -> int:
    return _adaptive_split_index_from_length(
        len(records),
        validation_holdout=validation_holdout,
        min_test_support=min_test_support,
    )


def _adaptive_split_index_from_length(
    length: int,
    *,
    validation_holdout: float,
    min_test_support: int,
) -> int:
    holdout = max(int(round(length * max(0.05, min(0.80, validation_holdout)))), int(min_test_support))
    holdout = min(max(holdout, int(min_test_support)), max(1, length - 1))
    return length - holdout


def _record_matches_tokens(window: OHLCVWindow, tokens: tuple[str, ...]) -> bool:
    signature = set(_regime_signature_from_window(window))
    return all(token in signature for token in tokens)


def _recency_weighted_mean_return(records: list[OHLCVWindow]) -> float:
    if not records:
        return 0.0
    half_life = max(6.0, len(records) / 3.0)
    weights = [math.exp(-float(len(records) - index - 1) / half_life) for index, _ in enumerate(records)]
    denominator = max(sum(weights), 1e-12)
    return float(
        sum(float(record.future_return_bps) * weight for record, weight in zip(records, weights, strict=False))
        / denominator
    )


def _recency_weighted_mean_indexed(records: list[tuple[int, float]], *, max_index: int) -> float:
    if not records:
        return 0.0
    span = max(1, max_index - min(index for index, _ in records) + 1)
    half_life = max(6.0, span / 3.0)
    weights = [math.exp(-float(max_index - index) / half_life) for index, _ in records]
    denominator = max(sum(weights), 1e-12)
    return float(sum(value * weight for (_, value), weight in zip(records, weights, strict=False)) / denominator)


def _summarize_events(
    engine_name: str,
    events: list[EventMetric],
    symbol: str | None = None,
    timeframe: str | None = None,
    fold_index: int | None = None,
    fold_start: int | None = None,
) -> dict:
    if not events:
        payload = {
            "engine": engine_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "queries": 0,
            "direction_accuracy_at_1": 0.0,
            "direction_accuracy_at_3": 0.0,
            "mean_abs_return_error_bps": math.inf,
            "mean_abs_mfe_error_bps": math.inf,
            "mean_abs_mae_error_bps": math.inf,
            "mean_abs_future_vol_error_bps": math.inf,
            "large_move_precision": 0.0,
            "large_move_false_positive_rate": 0.0,
            "avg_position_size": 0.0,
            "avg_confidence": 0.0,
            "filtered_rate": 0.0,
            "signal_rate": 0.0,
            "active_direction_accuracy": 0.0,
            "active_avg_net_return_bps": 0.0,
            "active_avg_sized_net_return_bps": 0.0,
            "avg_net_return_bps": 0.0,
            "avg_sized_net_return_bps": 0.0,
            "profit_factor": 0.0,
            "sized_profit_factor": 0.0,
            "max_drawdown_bps": 0.0,
            "sized_max_drawdown_bps": 0.0,
            "hit_rate_after_costs": 0.0,
            "sized_hit_rate_after_costs": 0.0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
        }
        if fold_index is not None:
            payload["fold_index"] = int(fold_index)
        if fold_start is not None:
            payload["fold_start"] = int(fold_start)
        return payload
    latencies = sorted(event.latency_ms for event in events)
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
    signal_events = [event for event in events if event.predicted_direction != "flat"]
    payload = {
        "engine": engine_name,
        "queries": len(events),
        "direction_accuracy_at_1": statistics.mean(event.direction_at_1 for event in events),
        "direction_accuracy_at_3": statistics.mean(event.direction_at_3 for event in events),
        "mean_abs_return_error_bps": statistics.mean(event.abs_return_error_bps for event in events),
        "mean_abs_mfe_error_bps": statistics.mean(event.abs_mfe_error_bps for event in events),
        "mean_abs_mae_error_bps": statistics.mean(event.abs_mae_error_bps for event in events),
        "mean_abs_future_vol_error_bps": statistics.mean(event.abs_future_vol_error_bps for event in events),
        "large_move_precision": _safe_ratio(
            sum(event.large_move_true_positive for event in events),
            sum(event.predicted_large_move for event in events),
        ),
        "large_move_false_positive_rate": _safe_ratio(
            sum(event.large_move_false_positive for event in events),
            sum(1.0 for event in events if event.actual_large_move == 0.0),
        ),
        "avg_position_size": statistics.mean(event.position_size for event in events),
        "avg_confidence": statistics.mean(event.confidence for event in events),
        "filtered_rate": statistics.mean(event.filtered for event in events),
        "signal_rate": len(signal_events) / len(events),
        "active_direction_accuracy": (
            statistics.mean(event.direction_at_1 for event in signal_events) if signal_events else 0.0
        ),
        "active_avg_net_return_bps": (
            statistics.mean(event.net_return_bps for event in signal_events) if signal_events else 0.0
        ),
        "active_avg_sized_net_return_bps": (
            statistics.mean(event.sized_net_return_bps for event in signal_events) if signal_events else 0.0
        ),
        "avg_net_return_bps": statistics.mean(event.net_return_bps for event in events),
        "avg_sized_net_return_bps": statistics.mean(event.sized_net_return_bps for event in events),
        "profit_factor": _profit_factor(event.net_return_bps for event in events),
        "sized_profit_factor": _profit_factor(event.sized_net_return_bps for event in events),
        "max_drawdown_bps": _max_drawdown_bps(event.net_return_bps for event in events),
        "sized_max_drawdown_bps": _max_drawdown_bps(event.sized_net_return_bps for event in events),
        "hit_rate_after_costs": statistics.mean(1.0 if event.net_return_bps > 0 else 0.0 for event in events),
        "sized_hit_rate_after_costs": statistics.mean(1.0 if event.sized_net_return_bps > 0 else 0.0 for event in events),
        "avg_latency_ms": statistics.mean(event.latency_ms for event in events),
        "p95_latency_ms": latencies[p95_index],
    }
    if symbol is not None:
        payload["symbol"] = symbol
    if timeframe is not None:
        payload["timeframe"] = timeframe
    if fold_index is not None:
        payload["fold_index"] = int(fold_index)
    if fold_start is not None:
        payload["fold_start"] = int(fold_start)
    return payload


def _attach_slice_robustness(results: list[dict], by_market: list[dict]) -> None:
    by_engine: dict[str, list[dict]] = {}
    for item in by_market:
        if item.get("symbol") is None or item.get("timeframe") is None:
            continue
        if int(item.get("queries", 0)) <= 0:
            continue
        by_engine.setdefault(str(item["engine"]), []).append(item)
    for result in results:
        if result.get("skipped"):
            continue
        slices = by_engine.get(str(result.get("engine", "")), [])
        if not slices:
            result["market_slices"] = 0
            result["positive_market_slices"] = 0
            result["slice_positive_rate"] = 0.0
            result["worst_market_slice_sized_net_bps"] = 0.0
            result["median_market_slice_sized_net_bps"] = 0.0
            continue
        slice_returns = [float(item["avg_sized_net_return_bps"]) for item in slices]
        positive = sum(1 for value in slice_returns if value > 0.0)
        result["market_slices"] = len(slice_returns)
        result["positive_market_slices"] = int(positive)
        result["slice_positive_rate"] = float(positive / len(slice_returns))
        result["worst_market_slice_sized_net_bps"] = float(min(slice_returns))
        result["median_market_slice_sized_net_bps"] = float(statistics.median(slice_returns))


def _analogue_from_window(window: OHLCVWindow, text: str, score: float) -> AnalogueMatch:
    return AnalogueMatch(
        id=window.id,
        score=float(score),
        direction=window.direction,
        future_return_bps=float(window.future_return_bps),
        max_favorable_excursion_bps=float(window.max_favorable_excursion_bps),
        max_adverse_excursion_bps=float(window.max_adverse_excursion_bps),
        future_realized_vol_bps=float(window.future_realized_vol_bps),
        start_time=window.start_time,
        end_time=window.end_time,
        text=text,
        regime_signature=_regime_signature_from_window(window),
    )


def _calibrated_prediction(
    *,
    query_window: OHLCVWindow,
    analogues: list[AnalogueMatch],
    latency_ms: float,
    min_analogue_agreement: float,
    confidence_threshold: float,
    regime_filter: bool,
    large_move_bps: float,
    min_expected_edge_bps: float,
) -> Prediction:
    direction, direction_agreement = _weighted_direction_vote(analogues)
    if direction == "flat" or not analogues:
        return Prediction(
            direction="flat",
            expected_return_bps=0.0,
            latency_ms=latency_ms,
            analogues=analogues,
            confidence=direction_agreement,
            raw_direction=direction,
            filtered=True,
            filter_reason="flat_vote",
            analogue_agreement=direction_agreement,
        )

    selected = [match for match in analogues if match.direction == direction]
    expected_return = _weighted_mean_return(selected)
    regime_agreement = _regime_agreement(query_window, selected) if regime_filter else 1.0
    move_agreement = _move_agreement(direction, selected, large_move_bps=large_move_bps)
    confidence = float(direction_agreement * (0.45 + 0.55 * regime_agreement) * move_agreement)

    filter_reasons = []
    if direction_agreement < min_analogue_agreement:
        filter_reasons.append("low_analogue_agreement")
    if confidence < confidence_threshold:
        filter_reasons.append("low_confidence")
    if regime_filter and regime_agreement < 0.55:
        filter_reasons.append("regime_mismatch")
    if abs(expected_return) < min_expected_edge_bps:
        filter_reasons.append("low_expected_edge")

    if filter_reasons:
        return Prediction(
            direction="flat",
            expected_return_bps=0.0,
            latency_ms=latency_ms,
            analogues=analogues,
            confidence=confidence,
            raw_direction=direction,
            filtered=True,
            filter_reason=",".join(filter_reasons),
            analogue_agreement=direction_agreement,
            regime_agreement=regime_agreement,
        )

    return Prediction(
        direction=direction,
        expected_return_bps=expected_return,
        latency_ms=latency_ms,
        analogues=analogues,
        confidence=confidence,
        raw_direction=direction,
        analogue_agreement=direction_agreement,
        regime_agreement=regime_agreement,
    )


def _weighted_direction_vote(analogues: list[AnalogueMatch]) -> tuple[str, float]:
    if not analogues:
        return "flat", 0.0
    weights = _rank_weights(analogues)
    totals: dict[str, float] = {"up": 0.0, "down": 0.0, "flat": 0.0}
    for match, weight in zip(analogues, weights, strict=False):
        totals[match.direction] = totals.get(match.direction, 0.0) + weight
    direction = max(totals, key=totals.get)
    denominator = max(sum(weights), 1e-12)
    return direction, float(totals[direction] / denominator)


def _weighted_direction_support(direction: str, analogues: list[AnalogueMatch]) -> float:
    if not analogues:
        return 0.0
    weights = _rank_weights(analogues)
    numerator = sum(
        weight
        for match, weight in zip(analogues, weights, strict=False)
        if match.direction == direction
    )
    return float(numerator / max(sum(weights), 1e-12))


def _weighted_mean_return(analogues: list[AnalogueMatch]) -> float:
    if not analogues:
        return 0.0
    weights = _rank_weights(analogues)
    denominator = max(sum(weights), 1e-12)
    return float(sum(match.future_return_bps * weight for match, weight in zip(analogues, weights, strict=False)) / denominator)


def _rank_weights(analogues: list[AnalogueMatch]) -> list[float]:
    return [
        (1.0 / (rank + 1.0)) * max(0.05, float(match.score))
        for rank, match in enumerate(analogues)
    ]


def _move_agreement(direction: str, analogues: list[AnalogueMatch], *, large_move_bps: float) -> float:
    if not analogues:
        return 0.0
    if direction == "flat":
        return 1.0
    threshold = max(float(large_move_bps), 1e-12)
    strong = [
        match
        for match in analogues
        if abs(float(match.future_return_bps)) >= threshold and match.direction == direction
    ]
    return float(max(0.35, len(strong) / len(analogues)))


def _regime_agreement(query_window: OHLCVWindow, analogues: list[AnalogueMatch]) -> float:
    query_signature = set(_regime_signature_from_window(query_window))
    if not query_signature or not analogues:
        return 1.0
    scores = []
    for match in analogues:
        match_signature = set(match.regime_signature)
        if not match_signature:
            scores.append(0.0)
        else:
            scores.append(len(query_signature & match_signature) / len(query_signature))
    return float(statistics.mean(scores)) if scores else 0.0


def _regime_signature_from_window(window: OHLCVWindow) -> tuple[str, ...]:
    return tuple(
        f"{key}={window.features[key]}"
        for key in REGIME_FEATURE_KEYS
        if key in window.features
    )


def _regime_signature_from_metadata(metadata: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        f"{key}={metadata[key]}"
        for key in REGIME_FEATURE_KEYS
        if key in metadata and metadata[key] is not None
    )


def _window_dtw_series(window: OHLCVWindow) -> np.ndarray:
    closes = np.asarray([bar.close for bar in window.bars], dtype=np.float64)
    volumes = np.asarray([bar.volume for bar in window.bars], dtype=np.float64)
    returns = np.diff(np.log(np.maximum(closes, 1e-12)), prepend=np.log(max(float(closes[0]), 1e-12))) * 10_000.0
    volume_ratio = volumes / max(float(np.mean(volumes)), 1e-12)
    stacked = np.column_stack([returns, volume_ratio])
    mean = stacked.mean(axis=0, keepdims=True)
    std = stacked.std(axis=0, keepdims=True)
    std = np.where(std <= 1e-12, 1.0, std)
    return ((stacked - mean) / std).astype(np.float32)


def _window_shape_vector(window: OHLCVWindow) -> np.ndarray:
    closes = np.asarray([bar.close for bar in window.bars], dtype=np.float64)
    highs = np.asarray([bar.high for bar in window.bars], dtype=np.float64)
    lows = np.asarray([bar.low for bar in window.bars], dtype=np.float64)
    volumes = np.asarray([bar.volume for bar in window.bars], dtype=np.float64)
    log_closes = np.log(np.maximum(closes, 1e-12))
    returns = np.diff(log_closes, prepend=log_closes[0]) * 10_000.0
    ranges = (highs - lows) / np.maximum(closes, 1e-12) * 10_000.0
    volume_ratio = volumes / max(float(np.mean(volumes)), 1e-12)
    stacked = np.column_stack([returns, ranges, volume_ratio])
    mean = stacked.mean(axis=0, keepdims=True)
    std = stacked.std(axis=0, keepdims=True)
    std = np.where(std <= 1e-12, 1.0, std)
    return ((stacked - mean) / std).reshape(-1).astype(np.float32)


def _dtw_distance(left: np.ndarray, right: np.ndarray) -> float:
    n = left.shape[0]
    m = right.shape[0]
    previous = np.full(m + 1, np.inf, dtype=np.float64)
    current = np.full(m + 1, np.inf, dtype=np.float64)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current[0] = np.inf
        li = left[i - 1]
        for j in range(1, m + 1):
            cost = float(np.linalg.norm(li - right[j - 1]))
            current[j] = cost + min(previous[j], current[j - 1], previous[j - 1])
        previous, current = current, previous
    return float(previous[m] / max(n, m))


def _window_metadata(window: OHLCVWindow) -> dict[str, str | int | float]:
    metadata: dict[str, str | int | float] = {
        "window_id": window.id,
        "symbol": window.symbol,
        "timeframe": window.timeframe,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "direction": window.direction,
        "future_return_bps": float(window.future_return_bps),
        "max_favorable_excursion_bps": float(window.max_favorable_excursion_bps),
        "max_adverse_excursion_bps": float(window.max_adverse_excursion_bps),
        "future_realized_vol_bps": float(window.future_realized_vol_bps),
        "future_max_drawdown_bps": float(window.future_max_drawdown_bps),
        "index": int(window.index),
    }
    for key in REGIME_FEATURE_KEYS:
        if key in window.features:
            metadata[key] = str(window.features[key])
    return metadata


def _analogue_sample(engine_name: str, window: OHLCVWindow, prediction: Prediction) -> dict:
    return {
        "engine": engine_name,
        "query": {
            "id": window.id,
            "symbol": window.symbol,
            "timeframe": window.timeframe,
            "start_time": window.start_time,
            "end_time": window.end_time,
            "direction": window.direction,
            "future_return_bps": float(window.future_return_bps),
            "max_favorable_excursion_bps": float(window.max_favorable_excursion_bps),
            "max_adverse_excursion_bps": float(window.max_adverse_excursion_bps),
            "future_realized_vol_bps": float(window.future_realized_vol_bps),
            "text": window_to_text(window, include_outcome=False),
        },
        "prediction": {
            "direction": prediction.direction,
            "raw_direction": prediction.raw_direction,
            "expected_return_bps": float(prediction.expected_return_bps),
            "confidence": float(prediction.confidence),
            "filtered": bool(prediction.filtered),
            "filter_reason": prediction.filter_reason,
            "analogue_agreement": float(prediction.analogue_agreement),
            "regime_agreement": float(prediction.regime_agreement),
            "latency_ms": float(prediction.latency_ms),
        },
        "analogues": [asdict(match) for match in prediction.analogues[:5]],
    }


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return float(numerator / denominator)


def _recent_mean(values: list[float], *, lookback: int) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values[-max(1, int(lookback)) :]))


def _profit_factor(values: Iterable[float]) -> float:
    items = list(values)
    gross_profit = sum(value for value in items if value > 0.0)
    gross_loss = abs(sum(value for value in items if value < 0.0))
    if gross_loss <= 1e-12:
        return math.inf if gross_profit > 0.0 else 0.0
    return float(gross_profit / gross_loss)


def _max_drawdown_bps(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return float(max_drawdown)


def _position_size(
    prediction: Prediction,
    *,
    large_move_bps: float,
    mode: str,
) -> float:
    if prediction.direction == "flat":
        return 0.0
    if mode == "fixed":
        return 1.0
    if mode != "confidence":
        raise ValueError(f"Unknown position sizing mode: {mode}")
    direction_agreement = min(float(prediction.confidence), _direction_agreement(prediction))
    move_strength = min(1.0, abs(prediction.expected_return_bps) / max(float(large_move_bps), 1e-12))
    return float(max(0.0, min(1.0, 0.35 * move_strength + 0.65 * direction_agreement)))


def _direction_agreement(prediction: Prediction) -> float:
    if not prediction.analogues:
        return 1.0 if prediction.direction != "flat" else 0.0
    return _direction_agreement_from_analogues(prediction.direction, prediction.analogues)


def _direction_agreement_from_analogues(direction: str, analogues: list[AnalogueMatch]) -> float:
    if not analogues:
        return 0.0
    matching = sum(1 for match in analogues if match.direction == direction)
    return float(matching / len(analogues))


if __name__ == "__main__":
    raise SystemExit(main())
