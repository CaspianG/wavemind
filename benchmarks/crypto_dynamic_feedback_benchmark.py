from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_bybit_capitulation_benchmark import (  # noqa: E402
    ALL_BYBIT_FOLDS,
    ANALOGUE_FEATURES,
    BYBIT_FOLD_BOUNDARIES,
    BybitInstrument,
    _percent,
    build_analogue_feature_rows,
    load_or_download_dataset,
)
from benchmarks.crypto_capitulation_coverage_benchmark import (  # noqa: E402
    _admitted_70,
    _collapse_signals,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


DEVELOPMENT_GROUPS = (
    (
        (
            "NEARUSDT",
            "SNXUSDT",
            "CRVUSDT",
            "KAVAUSDT",
            "IOTAUSDT",
            "ENJUSDT",
            "OPUSDT",
            "APTUSDT",
        ),
        "data/bybit-capitulation-transfer-v1.json.gz",
    ),
    (
        (
            "ADAUSDT",
            "LINKUSDT",
            "LTCUSDT",
            "BCHUSDT",
            "DOTUSDT",
            "XLMUSDT",
            "AVAXUSDT",
            "ETCUSDT",
        ),
        "data/bybit-capitulation-analogue-holdout-v1.json.gz",
    ),
    (
        (
            "ARBUSDT",
            "SUIUSDT",
            "INJUSDT",
            "LDOUSDT",
            "TRXUSDT",
            "DYDXUSDT",
            "YFIUSDT",
            "1000PEPEUSDT",
        ),
        "data/bybit-capitulation-replication2-v1.json.gz",
    ),
    (
        (
            "GALAUSDT",
            "APEUSDT",
            "CHZUSDT",
            "EGLDUSDT",
            "ICPUSDT",
            "RUNEUSDT",
            "FLOWUSDT",
            "NEOUSDT",
        ),
        "data/bybit-capitulation-replication3-v1.json.gz",
    ),
    (
        (
            "KSMUSDT",
            "WAVESUSDT",
            "ZILUSDT",
            "CELOUSDT",
            "ONTUSDT",
            "IOTXUSDT",
            "QTUMUSDT",
            "MASKUSDT",
        ),
        "data/bybit-capitulation-replication4-v1.json.gz",
    ),
)
FINAL_HOLDOUT_SYMBOLS = (
    "SUSHIUSDT",
    "1INCHUSDT",
    "KNCUSDT",
    "BLURUSDT",
    "STXUSDT",
    "MINAUSDT",
    "CFXUSDT",
    "AXSUSDT",
)


@dataclass(frozen=True)
class FeedbackConfig:
    half_life_days: float = 60.0
    prior_strength: float = 20.0
    reliability_gate: float = 0.10
    bucket: str = "trend"
    field_weight: float = 0.0

    def __post_init__(self) -> None:
        if self.half_life_days <= 0.0:
            raise ValueError("half_life_days must be positive")
        if self.prior_strength <= 0.0:
            raise ValueError("prior_strength must be positive")
        if not 0.0 <= self.reliability_gate < 0.5:
            raise ValueError("reliability_gate must be in [0, 0.5)")
        if self.bucket not in {"global", "direction", "trend"}:
            raise ValueError("unsupported bucket")
        if not 0.0 <= self.field_weight <= 1.0:
            raise ValueError("field_weight must be in [0, 1]")


@dataclass(frozen=True)
class AnalogueQuery:
    fold_index: int
    symbol: str
    timestamp: int
    target_timestamp: int
    probability_up: float
    actual_up: bool
    return_36: float

    @property
    def base_hit(self) -> bool:
        return (self.probability_up >= 0.5) == self.actual_up


BASE_NEIGHBORS = 63
BASE_CONFIDENCE_MARGIN = 0.30
RETURN_QUANTILE = 0.01
OI_QUANTILE = 0.20
PREDECLARED_FIELD_ABLATIONS = (
    FeedbackConfig(field_weight=0.0),
    FeedbackConfig(field_weight=0.15),
    FeedbackConfig(field_weight=0.30),
)


def generate_online_queries(
    training_rows: Sequence[FeatureRow],
    test_rows: Sequence[FeatureRow],
    *,
    include_matured_test_memory: bool,
) -> list[AnalogueQuery]:
    try:
        from sklearn.preprocessing import RobustScaler
    except ImportError as exc:
        raise RuntimeError(
            'Install the research extra: pip install -e ".[crypto-ml]"'
        ) from exc

    training = assign_calendar_folds(
        training_rows,
        boundaries=BYBIT_FOLD_BOUNDARIES,
    )
    testing = assign_calendar_folds(
        test_rows,
        boundaries=BYBIT_FOLD_BOUNDARIES,
    )
    output: list[AnalogueQuery] = []
    for fold in ALL_BYBIT_FOLDS:
        test = sorted(
            (row for row in testing if row.fold_index == fold),
            key=lambda row: (row.timestamp, row.symbol),
        )
        if not test:
            continue
        start = min(row.timestamp for row in test)
        history = [row for row in training if row.target_timestamp < start]
        if len(history) < 100:
            continue
        return_threshold = _quantile(
            history,
            "return_12",
            RETURN_QUANTILE,
        )
        oi_threshold = _quantile(
            history,
            "oi_change_1",
            OI_QUANTILE,
        )
        memory = _collapse_signals(
            [
                row
                for row in history
                if _candidate(row, return_threshold, oi_threshold)
            ]
        )
        candidates = _collapse_signals(
            [
                row
                for row in test
                if _candidate(row, return_threshold, oi_threshold)
            ]
        )
        if len(memory) < BASE_NEIGHBORS or not candidates:
            continue
        scaler = RobustScaler()
        scaler.fit(_matrix(memory))
        pending: list[FeatureRow] = []
        for timestamp in sorted({row.timestamp for row in candidates}):
            if include_matured_test_memory:
                matured = [
                    row for row in pending if row.target_timestamp < timestamp
                ]
                pending = [
                    row for row in pending if row.target_timestamp >= timestamp
                ]
                memory.extend(matured)
            group = [row for row in candidates if row.timestamp == timestamp]
            history_matrix = scaler.transform(_matrix(memory))
            query_matrix = scaler.transform(_matrix(group))
            labels = np.asarray(
                [row.future_return_bps > 0.0 for row in memory],
                dtype=float,
            )
            probabilities = _knn_probabilities(
                history_matrix,
                labels,
                query_matrix,
                neighbors=BASE_NEIGHBORS,
            )
            output.extend(
                AnalogueQuery(
                    fold_index=fold,
                    symbol=row.symbol,
                    timestamp=row.timestamp,
                    target_timestamp=row.target_timestamp,
                    probability_up=float(probabilities[index]),
                    actual_up=row.future_return_bps > 0.0,
                    return_36=float(row.features["return_36"]),
                )
                for index, row in enumerate(group)
            )
            if include_matured_test_memory:
                pending.extend(group)
    return sorted(output, key=lambda row: (row.timestamp, row.symbol))


def evaluate_feedback_router(
    calibration_queries: Sequence[AnalogueQuery],
    test_queries: Sequence[AnalogueQuery],
    *,
    config: FeedbackConfig,
    update_with_test: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    raw_events: list[dict[str, Any]] = []
    test_history: list[AnalogueQuery] = []
    for query in sorted(
        test_queries,
        key=lambda row: (row.timestamp, row.symbol),
    ):
        if (
            abs(query.probability_up - 0.5)
            < BASE_CONFIDENCE_MARGIN
        ):
            test_history.append(query)
            continue
        matured_calibration = [
            row
            for row in calibration_queries
            if row.target_timestamp < query.timestamp
        ]
        matured_test = (
            [
                row
                for row in test_history
                if row.target_timestamp < query.timestamp
            ]
            if update_with_test
            else []
        )
        history = _matching_bucket(
            matured_calibration + matured_test,
            query,
            config.bucket,
        )
        statistical, effective_samples = _decayed_accuracy(
            history,
            query_timestamp=query.timestamp,
            half_life_days=config.half_life_days,
            prior_strength=config.prior_strength,
        )
        field = (
            _field_reliability(
                history,
                query,
                half_life_days=config.half_life_days,
            )
            if config.field_weight > 0.0
            else 0.5
        )
        active_field_weight = (
            config.field_weight
            * min(1.0, effective_samples / 30.0)
        )
        reliability = (
            (1.0 - active_field_weight) * statistical
            + active_field_weight * field
        )
        raw_events.append(
            _event(
                query,
                predicted_up=query.probability_up >= 0.5,
                reliability=reliability,
                statistical_reliability=statistical,
                field_reliability=field,
                effective_samples=effective_samples,
            )
        )
        if abs(reliability - 0.5) >= config.reliability_gate:
            predicted_up = query.probability_up >= 0.5
            if reliability < 0.5:
                predicted_up = not predicted_up
            events.append(
                _event(
                    query,
                    predicted_up=predicted_up,
                    reliability=reliability,
                    statistical_reliability=statistical,
                    field_reliability=field,
                    effective_samples=effective_samples,
                )
            )
        test_history.append(query)
    return {
        "config": asdict(config),
        "summary": _summarize_slices(events),
        "raw_high_confidence": _summarize_slices(raw_events),
        "events": events,
    }


def run_dynamic_feedback_benchmark(
    development_rows: Sequence[FeatureRow],
    holdout_rows: Sequence[FeatureRow],
    *,
    development_provenance: Sequence[Mapping[str, Any]],
    holdout_provenance: Mapping[str, Any],
    configs: Sequence[FeedbackConfig] = PREDECLARED_FIELD_ABLATIONS,
) -> dict[str, Any]:
    development_assets = sorted({row.symbol for row in development_rows})
    holdout_assets = sorted({row.symbol for row in holdout_rows})
    if set(development_assets) & set(holdout_assets):
        raise ValueError("development and holdout assets overlap")
    development_queries = generate_online_queries(
        development_rows,
        development_rows,
        include_matured_test_memory=True,
    )
    development_results = [
        evaluate_feedback_router(
            (),
            development_queries,
            config=config,
            update_with_test=True,
        )
        for config in configs
    ]
    eligible = [
        result
        for result in development_results
        if int(result["summary"]["signals"]) >= 40
    ]
    if not eligible:
        raise ValueError("no feedback ablation has at least 40 signals")
    selected = max(eligible, key=_selection_key)
    selected_config = FeedbackConfig(**selected["config"])

    holdout_queries = generate_online_queries(
        development_rows,
        holdout_rows,
        include_matured_test_memory=True,
    )
    holdout_selected = evaluate_feedback_router(
        development_queries,
        holdout_queries,
        config=selected_config,
        update_with_test=True,
    )
    holdout_statistical = evaluate_feedback_router(
        development_queries,
        holdout_queries,
        config=FeedbackConfig(
            half_life_days=selected_config.half_life_days,
            prior_strength=selected_config.prior_strength,
            reliability_gate=selected_config.reliability_gate,
            bucket=selected_config.bucket,
            field_weight=0.0,
        ),
        update_with_test=True,
    )
    holdout_no_update = evaluate_feedback_router(
        development_queries,
        holdout_queries,
        config=selected_config,
        update_with_test=False,
    )
    summary = holdout_selected["summary"]
    return {
        "benchmark": "dynamic analogue reliability field transfer",
        "methodology": {
            "source": "official Bybit V5 public kline and open-interest API",
            "horizon": "24h from each completed 4h candle",
            "base_memory": {
                "return_quantile": RETURN_QUANTILE,
                "oi_quantile": OI_QUANTILE,
                "neighbors": BASE_NEIGHBORS,
                "confidence_margin": BASE_CONFIDENCE_MARGIN,
            },
            "selection": (
                "The statistical feedback policy was frozen after 40-asset "
                "development. Only WaveField blend weights 0, 0.15, and 0.30 "
                "were compared before the final holdout was downloaded."
            ),
            "causality": (
                "Every neighbour, feedback observation, and field update has a "
                "target timestamp strictly earlier than the query timestamp."
            ),
            "holdout_update": (
                "The main holdout path may learn from earlier holdout outcomes "
                "only after their 24h targets mature; a no-update control is "
                "reported separately."
            ),
            "fold_boundaries": [
                list(boundary) for boundary in BYBIT_FOLD_BOUNDARIES
            ],
        },
        "development_assets": development_assets,
        "holdout_assets": holdout_assets,
        "development_provenance": [dict(row) for row in development_provenance],
        "holdout_provenance": dict(holdout_provenance),
        "selected_config": asdict(selected_config),
        "development_selected": selected,
        "development_ablations": development_results,
        "asset_disjoint_holdout": holdout_selected,
        "holdout_statistical_control": holdout_statistical,
        "holdout_no_update_control": holdout_no_update,
        "aggregate_evidence_70": _aggregate_evidence_70(summary),
        "admitted_70": _admitted_70(summary),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    config = payload["selected_config"]
    lines = [
        "# Dynamic Analogue Reliability Field Transfer",
        "",
        (
            "A 40-asset causal development stream freezes a decayed reliability "
            "router before evaluation on eight new Bybit assets."
        ),
        "",
        f"- development assets: {len(payload['development_assets'])};",
        f"- holdout assets: {', '.join(payload['holdout_assets'])};",
        (
            f"- feedback: {config['half_life_days']:.0f}d half-life, "
            f"prior={config['prior_strength']:.0f}, "
            f"gate={config['reliability_gate']:.2f}, "
            f"bucket={config['bucket']}, "
            f"WaveField weight={config['field_weight']:.2f};"
        ),
        (
            "- holdout SHA-256: "
            f"`{payload['holdout_provenance']['dataset_sha256']}`."
        ),
        "",
        "| split / control | signals | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, result in (
        ("development selected", payload["development_selected"]),
        ("asset-disjoint holdout", payload["asset_disjoint_holdout"]),
        ("holdout statistical-only", payload["holdout_statistical_control"]),
        ("holdout without online updates", payload["holdout_no_update_control"]),
    ):
        summary = result["summary"]
        lines.append(
            f"| {label} | {summary['signals']} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} | "
            f"{_percent(summary['worst_supported_symbol_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            (
                "Aggregate 70% evidence: "
                + (
                    "**passed**"
                    if payload["aggregate_evidence_70"]
                    else "**rejected**"
                )
            ),
            "",
            (
                "Stable 70% admission: "
                + ("**passed**" if payload["admitted_70"] else "**rejected**")
            ),
            "",
            "## Development WaveField Ablation",
            "",
            "| field weight | signals | accuracy | Wilson low | worst fold | worst asset |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in payload["development_ablations"]:
        summary = result["summary"]
        lines.append(
            f"| {result['config']['field_weight']:.2f} | "
            f"{summary['signals']} | {_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} | "
            f"{_percent(summary['worst_supported_symbol_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## Holdout Folds",
            "",
            "| fold | signals | accuracy | Wilson low 95% |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in payload["asset_disjoint_holdout"]["summary"]["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            "## Holdout Assets",
            "",
            "| asset | signals | accuracy | Wilson low 95% |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["asset_disjoint_holdout"]["summary"]["by_symbol"]:
        lines.append(
            f"| {row['symbol']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def _matching_bucket(
    history: Sequence[AnalogueQuery],
    query: AnalogueQuery,
    bucket: str,
) -> list[AnalogueQuery]:
    if bucket == "global":
        return list(history)
    if bucket == "direction":
        predicted_up = query.probability_up >= 0.5
        return [
            row
            for row in history
            if (row.probability_up >= 0.5) == predicted_up
        ]
    trend_up = query.return_36 >= 0.0
    return [
        row for row in history if (row.return_36 >= 0.0) == trend_up
    ]


def _decayed_accuracy(
    history: Sequence[AnalogueQuery],
    *,
    query_timestamp: int,
    half_life_days: float,
    prior_strength: float,
) -> tuple[float, float]:
    if not history:
        return 0.5, 0.0
    half_life_seconds = half_life_days * 86_400.0
    weights = np.asarray(
        [
            0.5
            ** (
                (query_timestamp - row.target_timestamp)
                / half_life_seconds
            )
            for row in history
        ],
        dtype=float,
    )
    hits = np.asarray([row.base_hit for row in history], dtype=float)
    effective = float(np.sum(weights))
    accuracy = (
        float(np.sum(weights * hits)) + 0.5 * prior_strength
    ) / (effective + prior_strength)
    return accuracy, effective


def _field_reliability(
    history: Sequence[AnalogueQuery],
    query: AnalogueQuery,
    *,
    half_life_days: float,
) -> float:
    correct = sum(int(row.base_hit) for row in history)
    wrong = len(history) - correct
    if correct < 5 or wrong < 5:
        return 0.5
    projector = FieldProjector(18, 18, 4, seed=2027)
    previous_state = np.random.get_state()
    np.random.seed(2027)
    try:
        correct_field = WaveField(
            width=18,
            height=18,
            layers=3,
            decay=0.99,
            speed=0.10,
            nonlin=0.008,
        )
        wrong_field = WaveField(
            width=18,
            height=18,
            layers=3,
            decay=0.99,
            speed=0.10,
            nonlin=0.008,
        )
        half_life_seconds = half_life_days * 86_400.0
        correct_weight = 0.0
        wrong_weight = 0.0
        weighted: list[tuple[AnalogueQuery, float]] = []
        for row in history:
            weight = 0.5 ** (
                (query.timestamp - row.target_timestamp)
                / half_life_seconds
            )
            weighted.append((row, weight))
            if row.base_hit:
                correct_weight += weight
            else:
                wrong_weight += weight
        for row, weight in weighted:
            target = correct_field if row.base_hit else wrong_field
            denominator = correct_weight if row.base_hit else wrong_weight
            target.feed(
                projector.to_pattern(_feedback_vector(row)),
                strength=weight * 100.0 / max(denominator, 1e-9),
            )
        correct_field.evolve(2)
        wrong_field.evolve(2)
    finally:
        np.random.set_state(previous_state)
    pattern = projector.to_pattern(_feedback_vector(query))
    score = (
        correct_field.field_resonance(pattern)
        - wrong_field.field_resonance(pattern)
    )
    return float(1.0 / (1.0 + math.exp(-float(np.clip(score * 50.0, -30, 30)))))


def _feedback_vector(query: AnalogueQuery) -> np.ndarray:
    return np.asarray(
        [
            query.probability_up,
            abs(query.probability_up - 0.5) * 2.0,
            math.tanh(query.return_36 / 2_000.0),
            1.0 if query.probability_up >= 0.5 else -1.0,
        ],
        dtype=float,
    )


def _candidate(
    row: FeatureRow,
    return_threshold: float,
    oi_threshold: float,
) -> bool:
    return bool(
        float(row.features["return_12"]) <= return_threshold
        and float(row.features["oi_change_1"]) <= oi_threshold
    )


def _matrix(rows: Sequence[FeatureRow]) -> np.ndarray:
    return np.asarray(
        [
            [float(row.features[name]) for name in ANALOGUE_FEATURES]
            for row in rows
        ],
        dtype=float,
    )


def _knn_probabilities(
    history: np.ndarray,
    labels: np.ndarray,
    queries: np.ndarray,
    *,
    neighbors: int,
) -> np.ndarray:
    distance = np.mean(
        (queries[:, None, :] - history[None, :, :]) ** 2,
        axis=2,
    )
    count = min(neighbors, len(history))
    indices = np.argpartition(distance, count - 1, axis=1)[:, :count]
    selected_distance = np.take_along_axis(distance, indices, axis=1)
    weights = 1.0 / (np.sqrt(selected_distance) + 0.1)
    return np.sum(weights * labels[indices], axis=1) / np.sum(weights, axis=1)


def _event(
    query: AnalogueQuery,
    *,
    predicted_up: bool,
    reliability: float,
    statistical_reliability: float,
    field_reliability: float,
    effective_samples: float,
) -> dict[str, Any]:
    return {
        "fold_index": query.fold_index,
        "symbol": query.symbol,
        "timestamp": query.timestamp,
        "target_timestamp": query.target_timestamp,
        "probability_up": query.probability_up,
        "prediction": "up" if predicted_up else "down",
        "actual": "up" if query.actual_up else "down",
        "direction_hit": predicted_up == query.actual_up,
        "reliability": reliability,
        "statistical_reliability": statistical_reliability,
        "field_reliability": field_reliability,
        "effective_samples": effective_samples,
        "return_36": query.return_36,
    }


def _summarize_slices(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary = _summarize(events)
    by_fold = _group(events, "fold_index")
    by_symbol = _group(events, "symbol")
    supported_folds = [row for row in by_fold if int(row["signals"]) >= 5]
    supported_symbols = [row for row in by_symbol if int(row["signals"]) >= 5]
    return summary | {
        "by_fold": by_fold,
        "by_symbol": by_symbol,
        "worst_supported_fold_accuracy": min(
            (float(row["accuracy"]) for row in supported_folds),
            default=None,
        ),
        "worst_supported_symbol_accuracy": min(
            (float(row["accuracy"]) for row in supported_symbols),
            default=None,
        ),
    }


def _summarize(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    signals = len(events)
    hits = sum(int(event["direction_hit"]) for event in events)
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": hits / signals if signals else None,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def _group(
    events: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    return [
        {field: value}
        | _summarize([event for event in events if event[field] == value])
        for value in sorted({event[field] for event in events})
    ]


def _quantile(
    rows: Sequence[FeatureRow],
    feature: str,
    quantile: float,
) -> float:
    return float(
        np.quantile(
            [float(row.features[feature]) for row in rows],
            quantile,
        )
    )


def _selection_key(result: Mapping[str, Any]) -> tuple[float, float, float, int]:
    summary = result["summary"]
    return (
        float(summary["worst_supported_fold_accuracy"] or 0.0),
        float(summary["wilson_low_95"] or 0.0),
        float(summary["accuracy"] or 0.0),
        int(summary["signals"]),
    )


def _aggregate_evidence_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= 40
        and float(summary["accuracy"] or 0.0) >= 0.70
        and float(summary["wilson_low_95"] or 0.0) >= 0.65
    )


def load_development() -> tuple[list[BybitInstrument], list[dict[str, Any]]]:
    instruments: list[BybitInstrument] = []
    provenance: list[dict[str, Any]] = []
    for symbols, cache in DEVELOPMENT_GROUPS:
        rows, source = load_or_download_dataset(symbols, cache_path=cache)
        instruments.extend(rows)
        provenance.append(source)
    return instruments, provenance


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a dynamic analogue reliability field."
    )
    parser.add_argument(
        "--holdout-cache",
        type=Path,
        default=Path("data/bybit-dynamic-feedback-holdout-v1.json.gz"),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    development, development_provenance = load_development()
    holdout, holdout_provenance = load_or_download_dataset(
        FINAL_HOLDOUT_SYMBOLS,
        cache_path=args.holdout_cache,
        refresh=args.refresh,
    )
    payload = run_dynamic_feedback_benchmark(
        build_analogue_feature_rows(development),
        build_analogue_feature_rows(holdout),
        development_provenance=development_provenance,
        holdout_provenance=holdout_provenance,
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
    summary = payload["asset_disjoint_holdout"]["summary"]
    print(
        f"holdout accuracy={_percent(summary['accuracy'])} "
        f"signals={summary['signals']} "
        f"aggregate_70={payload['aggregate_evidence_70']} "
        f"admitted_70={payload['admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
