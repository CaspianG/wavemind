from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_asset_normalized_field_transfer_benchmark import (  # noqa: E402
    PreparedRows,
    _fit_extra_trees,
    _iso,
    candidate_indices,
    load_protocol,
    load_row_cache,
    matured_target_indices,
    prepare_rows,
)
from benchmarks.crypto_capitulation_analogue_benchmark import (  # noqa: E402
    _field_probabilities,
)
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    _summarize_slices,
    load_confirmation_rows,
)
from benchmarks.crypto_decelerating_capitulation_transfer_benchmark import (  # noqa: E402
    evaluate_strict_gate,
    fingerprint_files,
    summarize_market_dependence,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


DEFAULT_PROTOCOL = (
    PROJECT_ROOT
    / "benchmarks"
    / "protocols"
    / "binance_dynamic_field_transfer_v1.json"
)


def run_dynamic_field_transfer(
    training_rows: Sequence[FeatureRow],
    holdout_rows: Sequence[FeatureRow],
    *,
    protocol: Mapping[str, Any],
    protocol_sha256: str,
) -> dict[str, Any]:
    training_symbols = sorted({row.symbol for row in training_rows})
    holdout_symbols = sorted({row.symbol for row in holdout_rows})
    _validate_asset_sets(
        training_symbols,
        holdout_symbols,
        expected_training=protocol.get("training_symbols"),
        expected_holdout=protocol.get("holdout_symbols"),
    )

    normalization_end = str(
        protocol["normalization"]["fit_period_end_exclusive"]
    )
    training = prepare_rows(
        training_rows,
        normalization_end=normalization_end,
    )
    holdout = prepare_rows(
        holdout_rows,
        normalization_end=normalization_end,
        expected_features=training.feature_names,
    )
    candidate = protocol["candidate_event"]
    initial_period = tuple(protocol["initial_training_period"])
    holdout_folds = [
        tuple(values) for values in protocol["holdout_folds"]
    ]
    tree_config = protocol["extra_trees_head"]
    threshold = float(protocol["joint_veto"]["minimum_up_probability"])
    seed = int(protocol["joint_veto"]["random_seed"])

    events: list[dict[str, Any]] = []
    fold_audits: list[dict[str, Any]] = []
    candidate_count = 0
    training_fingerprints: list[str] = []
    for fold_index, (start, end) in enumerate(holdout_folds):
        training_periods = [initial_period, *holdout_folds[:fold_index]]
        train_indices = _training_indices(
            training,
            training_periods,
            cutoff=str(start),
            return_quantile=float(candidate["return_quantile"]),
            oi_quantile=float(candidate["open_interest_quantile"]),
        )
        if len(train_indices) < int(protocol["minimum_training_events"]):
            raise ValueError(
                f"fold {fold_index} has only {len(train_indices)} matured "
                "training events"
            )
        labels = training.labels[train_indices]
        if len(set(labels)) < 2:
            raise ValueError(f"fold {fold_index} training labels are constant")

        query = candidate_indices(
            holdout,
            start=str(start),
            end=str(end),
            return_quantile=float(candidate["return_quantile"]),
            oi_quantile=float(candidate["open_interest_quantile"]),
        )
        candidate_count += len(query)
        model = _fit_extra_trees(
            training.normalized[train_indices],
            labels,
            training.timestamps[train_indices],
            tree_config,
        )
        tree_probability = model.predict_proba(
            holdout.normalized[query]
        )[:, 1]
        field_probability = _field_probabilities(
            training.normalized[train_indices],
            labels,
            holdout.normalized[query],
            seed=seed,
        )
        accepted = (tree_probability >= threshold) & (
            field_probability >= threshold
        )
        fold_events = [
            {
                "fold_index": fold_index,
                "symbol": str(holdout.symbols[index]),
                "timestamp": int(holdout.timestamps[index]),
                "timestamp_utc": _iso(int(holdout.timestamps[index])),
                "target_timestamp": int(
                    holdout.rows[int(index)].target_timestamp
                ),
                "target_timestamp_utc": _iso(
                    int(holdout.rows[int(index)].target_timestamp)
                ),
                "prediction": "up",
                "future_return_bps": float(
                    holdout.rows[int(index)].future_return_bps
                ),
                "direction_hit": bool(holdout.labels[index]),
                "tree_probability_up": float(tree_probability[position]),
                "field_probability_up": float(
                    field_probability[position]
                ),
                "joint_probability_floor": float(
                    min(
                        tree_probability[position],
                        field_probability[position],
                    )
                ),
            }
            for position, index in enumerate(query)
            if accepted[position]
        ]
        events.extend(fold_events)
        fingerprint = _training_fingerprint(
            training,
            train_indices,
        )
        training_fingerprints.append(fingerprint)
        fold_audits.append(
            {
                "fold_index": fold_index,
                "start": str(start),
                "end": str(end),
                "matured_training_events": len(train_indices),
                "training_fingerprint": fingerprint,
                "candidate_events": len(query),
                "signals": len(fold_events),
            }
        )

    summary = _summarize_slices(events)
    summary["candidate_events"] = candidate_count
    summary["candidate_acceptance"] = (
        len(events) / candidate_count if candidate_count else None
    )
    dependence = summarize_market_dependence(events)
    gate = evaluate_strict_gate(
        summary,
        dependence,
        protocol["strict_gate"],
    )
    return {
        "benchmark": "dynamic asset-disjoint WaveField transfer",
        "protocol": str(protocol["protocol"]),
        "protocol_sha256": protocol_sha256,
        "training_symbols": training_symbols,
        "holdout_symbols": holdout_symbols,
        "feature_names": list(training.feature_names),
        "candidate_event": dict(candidate),
        "extra_trees_head": dict(tree_config),
        "joint_veto": dict(protocol["joint_veto"]),
        "fold_audits": fold_audits,
        "training_fingerprints": training_fingerprints,
        "evaluation": {
            "summary": summary,
            "events": events,
        },
        "dependence_control": dependence,
        "strict_gate": gate,
    }


def _validate_asset_sets(
    training_symbols: Sequence[str],
    holdout_symbols: Sequence[str],
    *,
    expected_training: Sequence[str] | None,
    expected_holdout: Sequence[str] | None,
) -> None:
    overlap = sorted(set(training_symbols) & set(holdout_symbols))
    if overlap:
        raise ValueError(
            "training and holdout assets overlap: " + ", ".join(overlap)
        )
    if expected_training is not None and sorted(expected_training) != list(
        training_symbols
    ):
        raise ValueError("training symbols do not match the frozen protocol")
    if expected_holdout is not None and sorted(expected_holdout) != list(
        holdout_symbols
    ):
        raise ValueError("holdout symbols do not match the frozen protocol")


def _training_indices(
    prepared: PreparedRows,
    periods: Sequence[Sequence[str]],
    *,
    cutoff: str,
    return_quantile: float,
    oi_quantile: float,
) -> np.ndarray:
    parts = [
        candidate_indices(
            prepared,
            start=str(start),
            end=str(end),
            return_quantile=return_quantile,
            oi_quantile=oi_quantile,
        )
        for start, end in periods
    ]
    if not parts:
        return np.asarray([], dtype=int)
    combined = np.unique(np.concatenate(parts))
    matured = matured_target_indices(
        prepared,
        combined,
        cutoff=cutoff,
    )
    return np.asarray(
        sorted(
            matured,
            key=lambda index: (
                prepared.timestamps[index],
                str(prepared.symbols[index]),
            ),
        ),
        dtype=int,
    )


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


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload["evaluation"]["summary"]
    episodes = payload["dependence_control"]["market_episodes"]
    lines = [
        "# Dynamic Asset-Disjoint WaveField Transfer",
        "",
        (
            "The ExtraTrees event head and WaveField memory are rebuilt before "
            "each fold from outcomes that matured on training assets only."
        ),
        "",
        f"- training assets: {len(payload['training_symbols'])};",
        f"- unseen holdout assets: {len(payload['holdout_symbols'])};",
        (
            f"- signals: {summary['signals']} / "
            f"{summary['candidate_events']} candidates;"
        ),
        f"- accuracy: {_percent(summary['accuracy'])};",
        f"- Wilson low 95%: {_percent(summary['wilson_low_95'])};",
        (
            f"- market episodes: {episodes['observations']}, "
            f"accuracy {_percent(episodes['accuracy'])};"
        ),
        (
            "- strict 70% gate: "
            + ("**passed**" if payload["strict_gate"]["passed"] else "**rejected**")
            + "."
        ),
        "",
        "## Fold Stability",
        "",
        "| fold | signals | accuracy | Wilson low 95% |",
        "|---:|---:|---:|---:|",
    ]
    for row in summary["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            "## Asset Stability",
            "",
            "| asset | signals | accuracy | Wilson low 95% |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in summary["by_symbol"]:
        lines.append(
            f"| {row['symbol']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            (
                "No holdout labels are used to rebuild either model. A failed "
                "gate remains part of the report."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate dynamic WaveField transfer on unseen assets."
    )
    parser.add_argument("--training-cache", type=Path, required=True)
    parser.add_argument(
        "--holdout-bundle",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--holdout-cache", type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    protocol, protocol_sha256 = load_protocol(args.protocol)
    training_rows = load_row_cache(args.training_cache)
    holdout_rows = load_confirmation_rows(
        args.holdout_bundle,
        cache_path=args.holdout_cache,
    )
    payload = run_dynamic_field_transfer(
        training_rows,
        holdout_rows,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
    )
    payload["source_bundles"] = fingerprint_files(args.holdout_bundle)
    payload["training_cache"] = fingerprint_files([args.training_cache])[0]
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
        f"accuracy={_percent(summary['accuracy'])} "
        f"strict_gate={payload['strict_gate']['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
