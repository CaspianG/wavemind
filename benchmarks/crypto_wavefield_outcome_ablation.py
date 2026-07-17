from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import evaluate_accuracy_gate  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    CROSS_ASSET_FEATURES,
    DERIVATIVE_FEATURES,
    MICROSTRUCTURE_FEATURES,
    PRICE_FEATURES,
    FeatureRow,
    _events,
    _matrix,
    _summarize,
    add_cross_asset_features,
    assign_walk_forward_folds,
    build_feature_rows,
    render_markdown,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


FIELD_FEATURES = PRICE_FEATURES + DERIVATIVE_FEATURES + MICROSTRUCTURE_FEATURES + CROSS_ASSET_FEATURES


def run_wavefield_ablation(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    train_timestamps: int = 720,
    random_state: int = 1729,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for fold in sorted({row.fold_index for row in rows if row.fold_index >= 0}):
        test_rows = [row for row in rows if row.fold_index == fold]
        test_start = min(row.timestamp for row in test_rows)
        train_rows = [row for row in rows if row.target_timestamp < test_start]
        allowed = set(sorted({row.timestamp for row in train_rows})[-train_timestamps:])
        train_rows = [row for row in train_rows if row.timestamp in allowed]
        for symbol in sorted({row.symbol for row in test_rows}):
            train_symbol = [row for row in train_rows if row.symbol == symbol]
            test_symbol = [row for row in test_rows if row.symbol == symbol]
            unsigned, signed = _predict_symbol_fields(
                train_symbol,
                test_symbol,
                seed=random_state + fold * 101 + sum(map(ord, symbol)),
            )
            events.extend(
                _events(
                    "WaveMind unsigned outcome field ablation",
                    fold,
                    test_symbol,
                    unsigned,
                    horizon_seconds=horizon_seconds,
                )
            )
            events.extend(
                _events(
                    "WaveMind signed outcome field ablation",
                    fold,
                    test_symbol,
                    signed,
                    horizon_seconds=horizon_seconds,
                )
            )

    return {
        "methodology": {
            "data": "Binance USD-M official archive",
            "horizon": _horizon_label(horizon_seconds) + " from completed 4h candles",
            "training": f"rolling {train_timestamps}-timestamp window; target must mature before fold start",
            "model_scope": (
                "Direct wavemind.core.WaveField ablation. Unsigned uses separate up/down fields; "
                "signed uses one outcome-weighted field."
            ),
            "features": list(FIELD_FEATURES),
        },
        "summary": _summarize(events),
        "gate_75": evaluate_accuracy_gate(
            events,
            target_accuracy=0.75,
            min_wilson_low_95=0.65,
            min_fold_accuracy=0.65,
            min_slice_accuracy=0.65,
            thresholds_bps=(0.0, 25.0, 50.0, 100.0, 150.0, 200.0),
        ),
        "gate_80": evaluate_accuracy_gate(
            events,
            thresholds_bps=(0.0, 25.0, 50.0, 100.0, 150.0, 200.0),
        ),
        "events": events,
    }


def _predict_symbol_fields(
    train_rows: Sequence[FeatureRow],
    test_rows: Sequence[FeatureRow],
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    if len(train_rows) < 300:
        raise ValueError("WaveField ablation requires at least 300 matured training rows per symbol")
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    train_matrix = scaler.fit_transform(imputer.fit_transform(_matrix(train_rows, FIELD_FEATURES)))
    test_matrix = scaler.transform(imputer.transform(_matrix(test_rows, FIELD_FEATURES)))
    projector = FieldProjector(24, 24, len(FIELD_FEATURES), seed=seed)
    targets = np.asarray([row.future_return_bps for row in train_rows], dtype=float)
    scale = max(float(np.median(np.abs(targets))), 1.0)

    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(width=24, height=24, layers=4, decay=0.995, speed=0.10, nonlin=0.01)
        down_field = WaveField(width=24, height=24, layers=4, decay=0.995, speed=0.10, nonlin=0.01)
        signed_field = WaveField(width=24, height=24, layers=4, decay=0.995, speed=0.10, nonlin=0.01)
        up_count = max(1, int(np.sum(targets > 0.0)))
        down_count = max(1, int(np.sum(targets < 0.0)))
        for index, (vector, target) in enumerate(zip(train_matrix, targets, strict=True)):
            pattern = projector.to_pattern(vector)
            recency = 0.15 + 0.85 * (index + 1) / len(targets)
            magnitude = min(3.0, abs(float(target)) / scale)
            unsigned_strength = recency * (0.5 + 0.5 * magnitude) * 400.0
            selected = up_field if target > 0.0 else down_field
            selected.feed(
                pattern,
                strength=unsigned_strength / (up_count if target > 0.0 else down_count),
            )
            signed_field.feed(
                pattern,
                strength=recency * math.tanh(float(target) / scale) * 600.0 / len(targets),
            )
        up_field.evolve(4)
        down_field.evolve(4)
        signed_field.evolve(4)
    finally:
        np.random.set_state(previous_state)

    unsigned_scores = np.asarray(
        [
            up_field.field_resonance(projector.to_pattern(vector))
            - down_field.field_resonance(projector.to_pattern(vector))
            for vector in test_matrix
        ],
        dtype=float,
    )
    signed_state = np.mean(signed_field.state, axis=2)
    train_signed = np.asarray(
        [_signed_resonance(signed_state, projector.to_pattern(vector)) for vector in train_matrix],
        dtype=float,
    )
    test_signed = np.asarray(
        [_signed_resonance(signed_state, projector.to_pattern(vector)) for vector in test_matrix],
        dtype=float,
    )
    return _scores_to_probability(unsigned_scores, scale=80.0), _scores_to_probability(
        test_signed - float(np.median(train_signed)),
        scale=80.0,
    )


def _signed_resonance(state: np.ndarray, pattern: np.ndarray) -> float:
    denominator = float(np.linalg.norm(state) * np.linalg.norm(pattern)) + 1e-9
    return float(np.dot(state.ravel(), pattern.ravel()) / denominator)


def _scores_to_probability(scores: np.ndarray, *, scale: float) -> np.ndarray:
    values = np.clip(np.asarray(scores, dtype=float) * float(scale), -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-values))


def _horizon_label(horizon_seconds: int) -> str:
    days, remainder = divmod(int(horizon_seconds), 24 * 60 * 60)
    if remainder == 0:
        return "24h" if days == 1 else f"{days}d"
    return f"{horizon_seconds / 3600:g}h"


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct WaveField market-outcome ablation.")
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
        rows_by_symbol[bundle.symbol] = build_feature_rows(bundle, horizon=args.horizon_bars)
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
    payload = run_wavefield_ablation(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
    )
    events = payload.pop("events")
    payload["data_audit"] = data_audit
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
