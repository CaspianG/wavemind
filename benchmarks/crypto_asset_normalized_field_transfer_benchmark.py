from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_capitulation_analogue_benchmark import (  # noqa: E402
    _field_probabilities,
)
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    _feature_row,
    _summarize_slices,
    load_confirmation_rows,
)
from benchmarks.crypto_decelerating_capitulation_transfer_benchmark import (  # noqa: E402
    evaluate_strict_gate,
    fingerprint_files,
    render_markdown as render_simple_markdown,
    summarize_market_dependence,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


DEFAULT_PROTOCOL = (
    PROJECT_ROOT
    / "benchmarks"
    / "protocols"
    / "binance_asset_normalized_field_transfer_v1.json"
)
EXCLUDED_FEATURES = {
    "hour_cos",
    "hour_sin",
    "weekday_cos",
    "weekday_sin",
}


@dataclass(frozen=True)
class PreparedRows:
    rows: tuple[FeatureRow, ...]
    timestamps: np.ndarray
    symbols: np.ndarray
    labels: np.ndarray
    raw: np.ndarray
    normalized: np.ndarray
    feature_names: tuple[str, ...]


def run_frozen_field_transfer(
    development_rows: Sequence[FeatureRow],
    holdout_rows: Sequence[FeatureRow],
    *,
    protocol: Mapping[str, Any],
    protocol_sha256: str,
) -> dict[str, Any]:
    expected_holdout = sorted(str(value) for value in protocol["holdout_symbols"])
    actual_holdout = sorted({row.symbol for row in holdout_rows})
    if actual_holdout != expected_holdout:
        raise ValueError(
            "holdout symbols do not match the frozen protocol: "
            f"expected={expected_holdout}, actual={actual_holdout}"
        )

    normalization_end = str(
        protocol["normalization"]["fit_period_end_exclusive"]
    )
    development = prepare_rows(
        development_rows,
        normalization_end=normalization_end,
    )
    holdout = prepare_rows(
        holdout_rows,
        normalization_end=normalization_end,
        expected_features=development.feature_names,
    )
    training_start, training_end = protocol["development"]["training_period"]
    candidate = protocol["candidate_event"]
    train_indices = candidate_indices(
        development,
        start=str(training_start),
        end=str(training_end),
        return_quantile=float(candidate["return_quantile"]),
        oi_quantile=float(candidate["open_interest_quantile"]),
    )
    train_indices = matured_target_indices(
        development,
        train_indices,
        cutoff=str(training_end),
    )
    if len(train_indices) < 30:
        raise ValueError("frozen training set has fewer than 30 events")

    labels = development.labels[train_indices]
    model = _fit_extra_trees(
        development.normalized[train_indices],
        labels,
        development.timestamps[train_indices],
        protocol["extra_trees_head"],
    )

    query_indices: list[int] = []
    fold_indices: list[int] = []
    for fold_index, (start, end) in enumerate(protocol["holdout_folds"]):
        selected = candidate_indices(
            holdout,
            start=str(start),
            end=str(end),
            return_quantile=float(candidate["return_quantile"]),
            oi_quantile=float(candidate["open_interest_quantile"]),
        )
        query_indices.extend(int(index) for index in selected)
        fold_indices.extend([fold_index] * len(selected))
    query = np.asarray(query_indices, dtype=int)
    if not len(query):
        raise ValueError("holdout contains no candidate events")

    tree_probability = model.predict_proba(holdout.normalized[query])[:, 1]
    field_probability = _field_probabilities(
        development.normalized[train_indices],
        labels,
        holdout.normalized[query],
        seed=int(protocol["wavefield_veto"]["projector_seed"]),
    )
    tree_floor = float(
        protocol["extra_trees_head"]["minimum_up_probability"]
    )
    field_floor = float(
        protocol["wavefield_veto"]["minimum_up_probability"]
    )
    accepted = (tree_probability >= tree_floor) & (
        field_probability >= field_floor
    )
    events = [
        {
            "fold_index": int(fold_indices[position]),
            "symbol": holdout.rows[index].symbol,
            "timestamp": int(holdout.rows[index].timestamp),
            "timestamp_utc": _iso(holdout.rows[index].timestamp),
            "target_timestamp": int(holdout.rows[index].target_timestamp),
            "target_timestamp_utc": _iso(
                holdout.rows[index].target_timestamp
            ),
            "prediction": "up",
            "future_return_bps": float(
                holdout.rows[index].future_return_bps
            ),
            "direction_hit": bool(holdout.labels[index]),
            "tree_probability_up": float(tree_probability[position]),
            "field_probability_up": float(field_probability[position]),
        }
        for position, index in enumerate(query)
        if accepted[position]
    ]
    summary = _summarize_slices(events)
    summary["candidate_events"] = len(query)
    summary["candidate_acceptance"] = (
        len(events) / len(query) if len(query) else None
    )
    dependence = summarize_market_dependence(events)
    gate = evaluate_strict_gate(
        summary,
        dependence,
        protocol["strict_gate"],
    )
    return {
        "benchmark": "frozen asset-normalized WaveField transfer",
        "protocol": str(protocol["protocol"]),
        "protocol_sha256": protocol_sha256,
        "development_symbols": sorted({row.symbol for row in development_rows}),
        "holdout_symbols": expected_holdout,
        "training_events": len(train_indices),
        "training_fingerprint": _training_fingerprint(
            development,
            train_indices,
        ),
        "feature_names": list(development.feature_names),
        "candidate_event": dict(candidate),
        "extra_trees_head": dict(protocol["extra_trees_head"]),
        "wavefield_veto": dict(protocol["wavefield_veto"]),
        "evaluation": {
            "summary": summary,
            "events": events,
        },
        "dependence_control": dependence,
        "strict_gate": gate,
    }


def prepare_rows(
    rows: Sequence[FeatureRow],
    *,
    normalization_end: str,
    expected_features: Sequence[str] | None = None,
) -> PreparedRows:
    ordered = tuple(sorted(rows, key=lambda row: (row.timestamp, row.symbol)))
    if not ordered:
        raise ValueError("rows must not be empty")
    feature_names = tuple(
        sorted(set(ordered[0].features) - EXCLUDED_FEATURES)
    )
    if expected_features is not None and tuple(expected_features) != feature_names:
        raise ValueError("development and holdout feature schemas differ")
    for row in ordered:
        if set(row.features) - EXCLUDED_FEATURES != set(feature_names):
            raise ValueError("feature schema changes within the row set")

    timestamps = np.asarray([row.timestamp for row in ordered], dtype=np.int64)
    symbols = np.asarray([row.symbol for row in ordered], dtype=object)
    labels = np.asarray(
        [row.future_return_bps > 0.0 for row in ordered],
        dtype=float,
    )
    raw = np.asarray(
        [
            [float(row.features[name]) for name in feature_names]
            for row in ordered
        ],
        dtype=float,
    )
    cutoff = _timestamp(normalization_end)
    normalized = np.zeros_like(raw)
    for symbol in sorted(set(symbols)):
        symbol_indices = np.flatnonzero(symbols == symbol)
        calibration = symbol_indices[timestamps[symbol_indices] < cutoff]
        if len(calibration) < 100:
            raise ValueError(
                f"{symbol} has fewer than 100 normalization observations"
            )
        center = np.median(raw[calibration], axis=0)
        low = np.quantile(raw[calibration], 0.10, axis=0)
        high = np.quantile(raw[calibration], 0.90, axis=0)
        scale = np.where(high - low > 1e-6, high - low, 1.0)
        normalized[symbol_indices] = np.clip(
            (raw[symbol_indices] - center) / scale,
            -10.0,
            10.0,
        )
    return PreparedRows(
        rows=ordered,
        timestamps=timestamps,
        symbols=symbols,
        labels=labels,
        raw=raw,
        normalized=normalized,
        feature_names=feature_names,
    )


def candidate_indices(
    prepared: PreparedRows,
    *,
    start: str,
    end: str,
    return_quantile: float,
    oi_quantile: float,
) -> np.ndarray:
    start_timestamp = _timestamp(start)
    end_timestamp = _timestamp(end)
    return_column = prepared.feature_names.index("return_12")
    oi_column = prepared.feature_names.index("oi_change_1")
    candidates: list[int] = []
    for symbol in sorted(set(prepared.symbols)):
        symbol_indices = np.flatnonzero(prepared.symbols == symbol)
        history = symbol_indices[
            prepared.timestamps[symbol_indices] < start_timestamp
        ]
        if len(history) < 100:
            continue
        return_threshold = float(
            np.quantile(
                prepared.raw[history, return_column],
                return_quantile,
            )
        )
        oi_threshold = float(
            np.quantile(
                prepared.raw[history, oi_column],
                oi_quantile,
            )
        )
        test = symbol_indices[
            (prepared.timestamps[symbol_indices] >= start_timestamp)
            & (prepared.timestamps[symbol_indices] < end_timestamp)
            & (
                prepared.raw[symbol_indices, return_column]
                <= return_threshold
            )
            & (prepared.raw[symbol_indices, oi_column] <= oi_threshold)
        ]
        candidates.extend(int(index) for index in test)

    ordered = sorted(
        candidates,
        key=lambda index: (
            prepared.timestamps[index],
            str(prepared.symbols[index]),
        ),
    )
    collapsed: list[int] = []
    next_allowed: defaultdict[str, int] = defaultdict(lambda: -1)
    for index in ordered:
        symbol = str(prepared.symbols[index])
        timestamp = int(prepared.timestamps[index])
        if timestamp < next_allowed[symbol]:
            continue
        collapsed.append(index)
        next_allowed[symbol] = timestamp + 86_400
    return np.asarray(collapsed, dtype=int)


def matured_target_indices(
    prepared: PreparedRows,
    indices: Sequence[int],
    *,
    cutoff: str,
) -> np.ndarray:
    cutoff_timestamp = _timestamp(cutoff)
    return np.asarray(
        [
            int(index)
            for index in indices
            if prepared.rows[int(index)].target_timestamp < cutoff_timestamp
        ],
        dtype=int,
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    base = json.loads(json.dumps(payload))
    base["benchmark"] = "frozen asset-normalized WaveField transfer"
    markdown = render_simple_markdown(base)
    return markdown.replace(
        "# Frozen Decelerating-Capitulation Transfer",
        "# Frozen Asset-Normalized WaveField Transfer",
        1,
    ).replace(
        "This is a one-read asset-disjoint holdout.",
        "This is a one-read asset-and-time-disjoint WaveField holdout.",
        1,
    )


def load_row_cache(path: str | Path) -> list[FeatureRow]:
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload.get("rows"), list):
        raise ValueError("row cache does not contain a rows list")
    return [_feature_row(row) for row in payload["rows"]]


def load_protocol(path: str | Path) -> tuple[dict[str, Any], str]:
    content = Path(path).read_bytes()
    return json.loads(content), hashlib.sha256(content).hexdigest()


def _fit_extra_trees(
    matrix: np.ndarray,
    labels: np.ndarray,
    timestamps: np.ndarray,
    config: Mapping[str, Any],
) -> ExtraTreesClassifier:
    timestamp_counts: defaultdict[int, int] = defaultdict(int)
    for timestamp in timestamps:
        timestamp_counts[int(timestamp)] += 1
    sample_weight = np.asarray(
        [1.0 / timestamp_counts[int(timestamp)] for timestamp in timestamps],
        dtype=float,
    )
    model = ExtraTreesClassifier(
        n_estimators=int(config["estimators"]),
        min_samples_leaf=int(config["minimum_samples_leaf"]),
        max_features=float(config["maximum_features"]),
        class_weight=str(config["class_weight"]),
        random_state=int(config["random_seed"]),
        n_jobs=-1,
    )
    model.fit(matrix, labels, sample_weight=sample_weight)
    return model


def _training_fingerprint(
    prepared: PreparedRows,
    indices: np.ndarray,
) -> str:
    digest = hashlib.sha256()
    digest.update("\n".join(prepared.feature_names).encode("utf-8"))
    digest.update(prepared.normalized[indices].astype("<f8").tobytes())
    digest.update(prepared.labels[indices].astype("<f8").tobytes())
    digest.update(prepared.timestamps[indices].astype("<i8").tobytes())
    return digest.hexdigest()


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen asset-normalized WaveField protocol."
    )
    parser.add_argument(
        "--development-cache",
        type=Path,
        default=Path("data/capitulation-confirmation-rows-v1.json.gz"),
    )
    parser.add_argument("--holdout-bundle", type=Path, action="append", required=True)
    parser.add_argument("--holdout-cache", type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    protocol, protocol_sha256 = load_protocol(args.protocol)
    development_rows = load_row_cache(args.development_cache)
    holdout_rows = load_confirmation_rows(
        args.holdout_bundle,
        cache_path=args.holdout_cache,
    )
    payload = run_frozen_field_transfer(
        development_rows,
        holdout_rows,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
    )
    payload["source_bundles"] = fingerprint_files(args.holdout_bundle)
    payload["development_cache"] = fingerprint_files(
        [args.development_cache]
    )[0]
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    summary = payload["evaluation"]["summary"]
    print(
        f"signals={summary['signals']} "
        f"accuracy={summary['accuracy']:.1%} "
        f"strict_gate={payload['strict_gate']['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
