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
from benchmarks.crypto_capitulation_field_benchmark import (  # noqa: E402
    _independent_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


DEVELOPMENT_SYMBOLS = (
    "NEARUSDT",
    "SNXUSDT",
    "CRVUSDT",
    "KAVAUSDT",
    "IOTAUSDT",
    "ENJUSDT",
    "OPUSDT",
    "APTUSDT",
)
HOLDOUT_SYMBOLS = (
    "ADAUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "DOTUSDT",
    "XLMUSDT",
    "AVAXUSDT",
    "ETCUSDT",
)


@dataclass(frozen=True)
class AnalogueConfig:
    return_quantile: float = 0.01
    oi_quantile: float = 0.20
    neighbors: int = 15
    confidence_margin: float = 0.25
    field_weight: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 < self.return_quantile < 0.5:
            raise ValueError("return_quantile must be between 0 and 0.5")
        if not 0.0 < self.oi_quantile <= 0.5:
            raise ValueError("oi_quantile must be above 0 and at most 0.5")
        if self.neighbors < 3:
            raise ValueError("neighbors must be at least 3")
        if not 0.0 <= self.confidence_margin < 0.5:
            raise ValueError("confidence_margin must be in [0, 0.5)")
        if not 0.0 <= self.field_weight <= 1.0:
            raise ValueError("field_weight must be in [0, 1]")


PREDECLARED_ABLATIONS = (
    AnalogueConfig(field_weight=0.0),
    AnalogueConfig(field_weight=0.15),
    AnalogueConfig(field_weight=0.30),
)


def run_analogue_transfer_benchmark(
    development_rows: Sequence[FeatureRow],
    holdout_rows: Sequence[FeatureRow],
    *,
    development_provenance: Mapping[str, Any],
    holdout_provenance: Mapping[str, Any],
    configs: Sequence[AnalogueConfig] = PREDECLARED_ABLATIONS,
) -> dict[str, Any]:
    development_assets = sorted({row.symbol for row in development_rows})
    holdout_assets = sorted({row.symbol for row in holdout_rows})
    overlap = sorted(set(development_assets) & set(holdout_assets))
    if overlap:
        raise ValueError("development and holdout assets overlap")
    if not configs:
        raise ValueError("configs must not be empty")

    development_results = [
        evaluate_analogue_memory(
            development_rows,
            development_rows,
            config=config,
        )
        for config in configs
    ]
    eligible = [
        result
        for result in development_results
        if int(result["summary"]["signals"]) >= 40
    ]
    selection_underpowered = not eligible
    if eligible:
        selected = max(eligible, key=_selection_key)
    else:
        selected = next(
            (
                result
                for result in development_results
                if float(result["config"]["field_weight"]) == 0.0
            ),
            development_results[0],
        )
    selected_config = AnalogueConfig(**selected["config"])
    holdout_selected = evaluate_analogue_memory(
        development_rows,
        holdout_rows,
        config=selected_config,
    )
    holdout_knn = evaluate_analogue_memory(
        development_rows,
        holdout_rows,
        config=AnalogueConfig(
            return_quantile=selected_config.return_quantile,
            oi_quantile=selected_config.oi_quantile,
            neighbors=selected_config.neighbors,
            confidence_margin=selected_config.confidence_margin,
            field_weight=0.0,
        ),
    )
    holdout_field = evaluate_analogue_memory(
        development_rows,
        holdout_rows,
        config=AnalogueConfig(
            return_quantile=selected_config.return_quantile,
            oi_quantile=selected_config.oi_quantile,
            neighbors=selected_config.neighbors,
            confidence_margin=selected_config.confidence_margin,
            field_weight=0.30,
        ),
    )
    summary = holdout_selected["summary"]
    return {
        "benchmark": "causal analogue-memory capitulation transfer",
        "methodology": {
            "source": "official Bybit V5 public kline and open-interest API",
            "horizon": "24h from each completed 4h candle",
            "selection": (
                "The event thresholds, local feature set, k, confidence "
                "margin, and three WaveField weights were fixed before the "
                "eight holdout assets were downloaded."
            ),
            "development_protocol": (
                "Each development fold is predicted only from outcomes that "
                "matured before that fold started."
            ),
            "holdout_protocol": (
                "Each holdout fold is predicted only from matured development-"
                "asset outcomes; holdout-asset labels never enter memory."
            ),
            "overlap_control": (
                "Candidate events are collapsed per asset until the 24h "
                "forecast horizon matures."
            ),
            "features": list(ANALOGUE_FEATURES),
            "fold_boundaries": [
                list(boundary) for boundary in BYBIT_FOLD_BOUNDARIES
            ],
        },
        "development_assets": development_assets,
        "holdout_assets": holdout_assets,
        "development_provenance": dict(development_provenance),
        "holdout_provenance": dict(holdout_provenance),
        "selected_config": asdict(selected_config),
        "development_selected": selected,
        "development_ablations": development_results,
        "selection_underpowered": selection_underpowered,
        "asset_disjoint_holdout": holdout_selected,
        "holdout_knn_control": holdout_knn,
        "holdout_wavefield_30": holdout_field,
        "aggregate_evidence_70": _aggregate_evidence_70(summary),
        "admitted_70": _admitted_70(summary),
    }


def evaluate_analogue_memory(
    training_rows: Sequence[FeatureRow],
    test_rows: Sequence[FeatureRow],
    *,
    config: AnalogueConfig,
) -> dict[str, Any]:
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
    events: list[dict[str, Any]] = []
    baseline_events: list[dict[str, Any]] = []
    fold_audits: list[dict[str, Any]] = []
    opportunities = 0
    candidate_opportunities = 0
    for fold in ALL_BYBIT_FOLDS:
        test = sorted(
            (row for row in testing if row.fold_index == fold),
            key=lambda row: (row.timestamp, row.symbol),
        )
        if not test:
            fold_audits.append(
                {
                    "fold_index": fold,
                    "status": "empty",
                    "signals": 0,
                }
            )
            continue
        start = min(row.timestamp for row in test)
        history = [row for row in training if row.target_timestamp < start]
        if len(history) < 100:
            fold_audits.append(
                {
                    "fold_index": fold,
                    "status": "insufficient_history",
                    "matured_history_rows": len(history),
                    "signals": 0,
                }
            )
            continue
        return_threshold = _quantile(
            history,
            "return_12",
            config.return_quantile,
        )
        oi_threshold = _quantile(
            history,
            "oi_change_1",
            config.oi_quantile,
        )
        history_candidates = _collapse_signals(
            [
                row
                for row in history
                if _candidate(row, return_threshold, oi_threshold)
            ]
        )
        test_candidates = _collapse_signals(
            [
                row
                for row in test
                if _candidate(row, return_threshold, oi_threshold)
            ]
        )
        independent_opportunities = len(_independent_rows(test))
        opportunities += independent_opportunities
        candidate_opportunities += len(test_candidates)
        if len(history_candidates) < config.neighbors or not test_candidates:
            fold_audits.append(
                {
                    "fold_index": fold,
                    "status": "insufficient_candidates",
                    "matured_history_rows": len(history),
                    "history_candidates": len(history_candidates),
                    "test_candidates": len(test_candidates),
                    "signals": 0,
                }
            )
            continue

        scaler = RobustScaler()
        history_matrix = scaler.fit_transform(
            _matrix(history_candidates)
        )
        test_matrix = scaler.transform(_matrix(test_candidates))
        labels = np.asarray(
            [row.future_return_bps > 0.0 for row in history_candidates],
            dtype=float,
        )
        knn_probability = _knn_probabilities(
            history_matrix,
            labels,
            test_matrix,
            neighbors=config.neighbors,
        )
        if config.field_weight > 0.0:
            field_probability = _field_probabilities(
                history_matrix,
                labels,
                test_matrix,
                seed=2027 + fold,
            )
        else:
            field_probability = np.full(len(test_candidates), 0.5)
        probability = (
            (1.0 - config.field_weight) * knn_probability
            + config.field_weight * field_probability
        )
        selected = (
            np.abs(probability - 0.5) >= config.confidence_margin
        )
        for index, row in enumerate(test_candidates):
            baseline_events.append(
                _event(
                    row,
                    fold=fold,
                    probability_up=1.0,
                    knn_probability_up=float(knn_probability[index]),
                    field_probability_up=float(field_probability[index]),
                    return_threshold=return_threshold,
                    oi_threshold=oi_threshold,
                )
            )
            if selected[index]:
                events.append(
                    _event(
                        row,
                        fold=fold,
                        probability_up=float(probability[index]),
                        knn_probability_up=float(knn_probability[index]),
                        field_probability_up=float(field_probability[index]),
                        return_threshold=return_threshold,
                        oi_threshold=oi_threshold,
                    )
                )
        fold_audits.append(
            {
                "fold_index": fold,
                "status": "evaluated",
                "matured_history_rows": len(history),
                "history_candidates": len(history_candidates),
                "test_candidates": len(test_candidates),
                "signals": int(np.sum(selected)),
                "return_threshold": return_threshold,
                "oi_threshold": oi_threshold,
            }
        )

    summary = _summarize_slices(events)
    baseline = _summarize_slices(baseline_events)
    for target in (summary, baseline):
        target["independent_opportunities"] = opportunities
        target["candidate_opportunities"] = candidate_opportunities
        target["coverage"] = (
            int(target["signals"]) / opportunities
            if opportunities
            else None
        )
        target["candidate_coverage"] = (
            int(target["signals"]) / candidate_opportunities
            if candidate_opportunities
            else None
        )
    return {
        "config": asdict(config),
        "summary": summary,
        "always_up_candidate_baseline": baseline,
        "fold_audits": fold_audits,
        "events": events,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    selected = payload["selected_config"]
    lines = [
        "# Causal Analogue-Memory Capitulation Transfer",
        "",
        (
            "A high-confidence local analogue policy is selected on eight "
            "Bybit assets, then evaluated without holdout-label updates on "
            "eight different assets."
        ),
        "",
        f"- development assets: {', '.join(payload['development_assets'])};",
        f"- holdout assets: {', '.join(payload['holdout_assets'])};",
        (
            f"- frozen memory: k={selected['neighbors']}, margin="
            f"{selected['confidence_margin']:.2f}, WaveField weight="
            f"{selected['field_weight']:.2f};"
        ),
        (
            "- development selection support: "
            + (
                "underpowered; deterministic kNN control retained;"
                if payload["selection_underpowered"]
                else "at least 40 signals;"
            )
        ),
        (
            "- development SHA-256: "
            f"`{payload['development_provenance']['dataset_sha256']}`;"
        ),
        (
            "- holdout SHA-256: "
            f"`{payload['holdout_provenance']['dataset_sha256']}`."
        ),
        "",
        "| split / ablation | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    rows = [
        ("development selected", payload["development_selected"]),
        ("asset-disjoint holdout", payload["asset_disjoint_holdout"]),
        ("holdout kNN control", payload["holdout_knn_control"]),
        ("holdout 30% WaveField", payload["holdout_wavefield_30"]),
    ]
    for label, result in rows:
        summary = result["summary"]
        lines.append(
            f"| {label} | {summary['signals']} | "
            f"{_percent(summary['coverage'])} | "
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
            "| field weight | signals | accuracy | Wilson low | worst fold |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for result in payload["development_ablations"]:
        summary = result["summary"]
        lines.append(
            f"| {result['config']['field_weight']:.2f} | "
            f"{summary['signals']} | {_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} |"
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
    lines.extend(
        [
            "",
            (
                "The holdout memory contains only matured development-asset "
                "outcomes. A high development score is not promoted unless it "
                "survives the asset-disjoint holdout and every stability gate."
            ),
            "",
        ]
    )
    return "\n".join(lines)


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


def _field_probabilities(
    history: np.ndarray,
    labels: np.ndarray,
    queries: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    positives = int(np.sum(labels == 1.0))
    negatives = int(np.sum(labels == 0.0))
    if positives < 5 or negatives < 5:
        return np.full(len(queries), 0.5)
    projector = FieldProjector(20, 20, history.shape[1], seed=seed)
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(
            width=20,
            height=20,
            layers=4,
            decay=0.99,
            speed=0.10,
            nonlin=0.008,
        )
        down_field = WaveField(
            width=20,
            height=20,
            layers=4,
            decay=0.99,
            speed=0.10,
            nonlin=0.008,
        )
        for index, (vector, label) in enumerate(
            zip(history, labels, strict=True)
        ):
            recency = 0.25 + 0.75 * (index + 1) / len(history)
            denominator = positives if label else negatives
            target = up_field if label else down_field
            target.feed(
                projector.to_pattern(vector),
                strength=recency * 250.0 / denominator,
            )
        up_field.evolve(3)
        down_field.evolve(3)
    finally:
        np.random.set_state(previous_state)

    history_scores = np.asarray(
        [
            _field_score(up_field, down_field, projector.to_pattern(vector))
            for vector in history
        ],
        dtype=float,
    )
    center = float(np.median(history_scores))
    scale = float(np.std(history_scores))
    if not math.isfinite(scale) or scale < 1e-9:
        return np.full(len(queries), 0.5)
    query_scores = np.asarray(
        [
            _field_score(up_field, down_field, projector.to_pattern(vector))
            for vector in queries
        ],
        dtype=float,
    )
    z_score = np.clip((query_scores - center) / scale, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z_score))


def _field_score(
    up_field: WaveField,
    down_field: WaveField,
    pattern: np.ndarray,
) -> float:
    return float(
        up_field.field_resonance(pattern)
        - down_field.field_resonance(pattern)
    )


def _event(
    row: FeatureRow,
    *,
    fold: int,
    probability_up: float,
    knn_probability_up: float,
    field_probability_up: float,
    return_threshold: float,
    oi_threshold: float,
) -> dict[str, Any]:
    actual_up = row.future_return_bps > 0.0
    predicted_up = probability_up >= 0.5
    return {
        "fold_index": fold,
        "symbol": row.symbol,
        "timestamp": row.timestamp,
        "target_timestamp": row.target_timestamp,
        "prediction": "up" if predicted_up else "down",
        "probability_up": probability_up,
        "knn_probability_up": knn_probability_up,
        "field_probability_up": field_probability_up,
        "future_return_bps": row.future_return_bps,
        "direction_hit": predicted_up == actual_up,
        "return_12": float(row.features["return_12"]),
        "oi_change_1": float(row.features["oi_change_1"]),
        "return_threshold": return_threshold,
        "oi_threshold": oi_threshold,
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


def _selection_key(
    result: Mapping[str, Any],
) -> tuple[int, float, float, float, int]:
    summary = result["summary"]
    return (
        int(int(summary["signals"]) >= 40),
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a causal analogue memory and transfer it to unseen assets."
        )
    )
    parser.add_argument(
        "--development-cache",
        type=Path,
        default=Path("data/bybit-capitulation-transfer-v1.json.gz"),
    )
    parser.add_argument(
        "--holdout-cache",
        type=Path,
        default=Path("data/bybit-capitulation-analogue-holdout-v1.json.gz"),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    development, development_provenance = load_or_download_dataset(
        DEVELOPMENT_SYMBOLS,
        cache_path=args.development_cache,
        refresh=args.refresh,
    )
    holdout, holdout_provenance = load_or_download_dataset(
        HOLDOUT_SYMBOLS,
        cache_path=args.holdout_cache,
        refresh=args.refresh,
    )
    _validate_assets(development, DEVELOPMENT_SYMBOLS)
    _validate_assets(holdout, HOLDOUT_SYMBOLS)
    payload = run_analogue_transfer_benchmark(
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


def _validate_assets(
    instruments: Sequence[BybitInstrument],
    expected: Sequence[str],
) -> None:
    actual = sorted(instrument.symbol for instrument in instruments)
    if actual != sorted(expected):
        raise ValueError(f"asset mismatch: expected {sorted(expected)}, got {actual}")


if __name__ == "__main__":
    raise SystemExit(main())
