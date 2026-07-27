from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_market_wave_benchmark import (  # noqa: E402
    MarketPanel,
    _admitted_70,
    load_market_panels,
    summarize_oracle,
    summarize_predictions,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


CACHE_SCHEMA = "wavemind.crypto.market-panels.v1"


@dataclass(frozen=True)
class AnalogueConfig:
    sequence_length: int
    neighbors: int
    memory_lookback: int = 540


class TemporalAnaloguePredictor:
    def __init__(
        self,
        all_panels: Sequence[MarketPanel],
        mature_panels: Sequence[MarketPanel],
        *,
        config: AnalogueConfig,
        seed: int,
    ) -> None:
        try:
            from sklearn.decomposition import PCA
            from sklearn.impute import SimpleImputer
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise RuntimeError(
                'Install the research extra: pip install -e ".[crypto-ml]"'
            ) from exc
        if len(mature_panels) < max(40, config.sequence_length * 3):
            raise ValueError("Insufficient mature panels for temporal analogues")

        self.config = config
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        mature_matrix = np.asarray(
            [panel.features for panel in mature_panels],
            dtype=float,
        )
        normalized = self.scaler.fit_transform(
            self.imputer.fit_transform(mature_matrix)
        )
        components = min(12, normalized.shape[0] - 1, normalized.shape[1])
        self.pca = PCA(n_components=components, random_state=seed)
        self.pca.fit(normalized)

        transformed = self._transform_panels(all_panels)
        panel_index = {
            panel.observed_at: index for index, panel in enumerate(all_panels)
        }
        sequences = []
        labels = []
        observed = []
        for panel in mature_panels[-config.memory_lookback :]:
            end = panel_index[panel.observed_at]
            sequence = _sequence_at(
                transformed,
                all_panels,
                end,
                length=config.sequence_length,
            )
            if sequence is None:
                continue
            sequences.append(sequence)
            labels.append(float(panel.market_up))
            observed.append(panel.observed_at)
        if len(sequences) < max(config.neighbors, 20):
            raise ValueError("Insufficient contiguous mature sequences")
        self.sequences = np.asarray(sequences, dtype=float)
        self.labels = np.asarray(labels, dtype=float)
        self.observed = np.asarray(observed, dtype=np.int64)
        self._fit_fields(seed=seed)

    def probabilities(
        self,
        all_panels: Sequence[MarketPanel],
        panel: MarketPanel,
    ) -> dict[str, float]:
        index = next(
            index
            for index, candidate in enumerate(all_panels)
            if candidate.observed_at == panel.observed_at
        )
        transformed = self._transform_panels(all_panels[: index + 1])
        query = _sequence_at(
            transformed,
            all_panels[: index + 1],
            index,
            length=self.config.sequence_length,
        )
        if query is None:
            raise ValueError("Current panel has no contiguous causal sequence")

        flat_distance = np.linalg.norm(
            self.sequences.reshape(len(self.sequences), -1)
            - query.reshape(1, -1),
            axis=1,
        )
        knn = _weighted_probability(
            flat_distance,
            self.labels,
            neighbors=self.config.neighbors,
        )

        candidate_count = min(
            len(self.sequences),
            max(self.config.neighbors * 4, 80),
        )
        candidates = np.argpartition(
            flat_distance,
            candidate_count - 1,
        )[:candidate_count]
        dtw_distance = np.full(len(self.sequences), np.inf, dtype=float)
        for candidate in candidates:
            dtw_distance[candidate] = _dtw_distance(
                query,
                self.sequences[candidate],
                band=2,
            )
        dtw = _weighted_probability(
            dtw_distance,
            self.labels,
            neighbors=self.config.neighbors,
        )

        pattern = self.projector.to_pattern(query.reshape(-1))
        field_score = (
            self.up_field.field_resonance(pattern)
            - self.down_field.field_resonance(pattern)
        )
        z_score = (field_score - self.field_center) / self.field_scale
        wavefield = 1.0 / (
            1.0 + math.exp(-float(np.clip(z_score, -30.0, 30.0)))
        )
        return {
            "knn": knn,
            "dtw": dtw,
            "wavefield": wavefield,
            "hybrid": 0.40 * knn + 0.35 * dtw + 0.25 * wavefield,
        }

    def _transform_panels(
        self,
        panels: Sequence[MarketPanel],
    ) -> np.ndarray:
        matrix = np.asarray([panel.features for panel in panels], dtype=float)
        normalized = self.scaler.transform(self.imputer.transform(matrix))
        return self.pca.transform(normalized)

    def _fit_fields(self, *, seed: int) -> None:
        flattened = self.sequences.reshape(len(self.sequences), -1)
        self.projector = FieldProjector(
            24,
            24,
            flattened.shape[1],
            seed=seed,
        )
        previous_state = np.random.get_state()
        np.random.seed(seed)
        try:
            self.up_field = WaveField(
                width=24,
                height=24,
                layers=4,
                decay=0.985,
                speed=0.12,
                nonlin=0.008,
            )
            self.down_field = WaveField(
                width=24,
                height=24,
                layers=4,
                decay=0.985,
                speed=0.12,
                nonlin=0.008,
            )
            up_count = max(int(np.sum(self.labels == 1.0)), 1)
            down_count = max(int(np.sum(self.labels == 0.0)), 1)
            for index, (vector, label) in enumerate(
                zip(flattened, self.labels, strict=True)
            ):
                recency = 0.20 + 0.80 * (index + 1) / len(flattened)
                field = self.up_field if label else self.down_field
                denominator = up_count if label else down_count
                field.feed(
                    self.projector.to_pattern(vector),
                    strength=recency * 500.0 / denominator,
                )
            self.up_field.evolve(4)
            self.down_field.evolve(4)
        finally:
            np.random.set_state(previous_state)

        scores = np.asarray(
            [
                self.up_field.field_resonance(
                    self.projector.to_pattern(vector)
                )
                - self.down_field.field_resonance(
                    self.projector.to_pattern(vector)
                )
                for vector in flattened
            ],
            dtype=float,
        )
        self.field_center = float(np.median(scores))
        self.field_scale = max(float(np.std(scores)), 1e-6)


def run_temporal_analogue_benchmark(
    panels: Sequence[MarketPanel],
    *,
    validation_fold: int = 1,
    test_folds: Sequence[int] = (2, 3, 4),
    sequence_lengths: Sequence[int] = (3, 7, 14),
    neighbor_counts: Sequence[int] = (15, 31),
    memory_lookback: int = 540,
    retrain_every: int = 7,
    seed: int = 2027,
) -> dict[str, Any]:
    ordered = sorted(panels, key=lambda panel: panel.observed_at)
    validation_candidates = []
    for sequence_length in sequence_lengths:
        for neighbors in neighbor_counts:
            config = AnalogueConfig(
                sequence_length=sequence_length,
                neighbors=neighbors,
                memory_lookback=memory_lookback,
            )
            predictions = _predict_folds(
                ordered,
                folds=(validation_fold,),
                config=config,
                retrain_every=retrain_every,
                seed=seed,
            )
            for engine in ("knn", "dtw", "wavefield", "hybrid"):
                validation_candidates.append(
                    {
                        "engine": engine,
                        "sequence_length": sequence_length,
                        "neighbors": neighbors,
                        "summary": summarize_predictions(
                            predictions,
                            engine=engine,
                        ),
                    }
                )

    selected = max(
        validation_candidates,
        key=lambda row: (
            float(row["summary"]["market_wilson_low_95"] or 0.0),
            float(row["summary"]["market_accuracy"] or 0.0),
            float(row["summary"]["asset_accuracy"] or 0.0),
        ),
    )
    final_config = AnalogueConfig(
        sequence_length=int(selected["sequence_length"]),
        neighbors=int(selected["neighbors"]),
        memory_lookback=memory_lookback,
    )
    final_predictions = _predict_folds(
        ordered,
        folds=test_folds,
        config=final_config,
        retrain_every=retrain_every,
        seed=seed,
    )
    final = summarize_predictions(
        final_predictions,
        engine=str(selected["engine"]),
    )
    return {
        "methodology": {
            "protocol": (
                f"Fold {validation_fold} selects one fixed temporal analogue "
                f"configuration; folds {list(test_folds)} are untouched."
            ),
            "causality": (
                "Only analogue outcomes with target_at strictly before the "
                "query observed_at enter memory."
            ),
            "engines": ["knn", "dtw", "wavefield", "hybrid"],
            "sampling": "one non-overlapping 24h cross-asset panel",
            "admission": (
                "At least 70% market and asset accuracy, market Wilson low at "
                "least 65%, and every final fold and asset at least 60%."
            ),
        },
        "panels": len(ordered),
        "validation_candidates": validation_candidates,
        "selected": {
            "engine": selected["engine"],
            "sequence_length": selected["sequence_length"],
            "neighbors": selected["neighbors"],
            "validation": selected["summary"],
        },
        "final_test": final,
        "oracle_market_factor_ceiling": summarize_oracle(final_predictions),
        "admitted_70": _admitted_70(final),
        "prediction_audit": {
            "rows": len(final_predictions),
            "all_training_targets_strictly_past": all(
                int(row["trained_through"]) < int(row["observed_at"])
                for row in final_predictions
            ),
        },
    }


def _predict_folds(
    panels: Sequence[MarketPanel],
    *,
    folds: Sequence[int],
    config: AnalogueConfig,
    retrain_every: int,
    seed: int,
) -> list[dict[str, Any]]:
    selected_folds = set(folds)
    predictions = []
    predictor: TemporalAnaloguePredictor | None = None
    trained_through = -1
    predictions_since_fit = retrain_every
    for panel in panels:
        if panel.fold_index not in selected_folds:
            continue
        mature = [
            prior
            for prior in panels
            if prior.target_at < panel.observed_at
        ][-config.memory_lookback :]
        latest_mature = mature[-1].target_at if mature else -1
        if (
            predictor is None
            or (
                predictions_since_fit >= retrain_every
                and latest_mature > trained_through
            )
        ):
            causal_context = [
                prior
                for prior in panels
                if prior.observed_at <= panel.observed_at
            ]
            predictor = TemporalAnaloguePredictor(
                causal_context,
                mature,
                config=config,
                seed=seed + panel.fold_index * 1009,
            )
            trained_through = latest_mature
            predictions_since_fit = 0
        causal_context = [
            prior
            for prior in panels
            if prior.observed_at <= panel.observed_at
        ]
        probabilities = predictor.probabilities(causal_context, panel)
        predictions.append(
            {
                "observed_at": panel.observed_at,
                "target_at": panel.target_at,
                "fold_index": panel.fold_index,
                "market_up": panel.market_up,
                "asset_outcomes": list(panel.asset_outcomes),
                "probabilities": probabilities,
                "history_panels": len(mature),
                "trained_through": trained_through,
            }
        )
        predictions_since_fit += 1
    return predictions


def save_panel_cache(
    path: str | Path,
    panels: Sequence[MarketPanel],
    source_audit: Mapping[str, Any],
) -> None:
    payload = {
        "schema": CACHE_SCHEMA,
        "source_audit": source_audit,
        "panels": [
            {
                "observed_at": panel.observed_at,
                "target_at": panel.target_at,
                "fold_index": panel.fold_index,
                "features": panel.features,
                "market_up": panel.market_up,
                "asset_outcomes": panel.asset_outcomes,
            }
            for panel in panels
        ],
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))


def load_panel_cache(
    path: str | Path,
) -> tuple[list[MarketPanel], dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema") != CACHE_SCHEMA:
        raise ValueError("Unsupported market-panel cache schema")
    panels = [
        MarketPanel(
            observed_at=int(row["observed_at"]),
            target_at=int(row["target_at"]),
            fold_index=int(row["fold_index"]),
            features=tuple(float(value) for value in row["features"]),
            market_up=bool(row["market_up"]),
            asset_outcomes=tuple(
                (str(symbol), bool(actual_up))
                for symbol, actual_up in row["asset_outcomes"]
            ),
        )
        for row in payload["panels"]
    ]
    return panels, dict(payload["source_audit"])


def _sequence_at(
    transformed: np.ndarray,
    panels: Sequence[MarketPanel],
    end: int,
    *,
    length: int,
) -> np.ndarray | None:
    if end < 0 or end >= len(panels):
        return None
    start = max(0, end - length + 1)
    for index in range(start + 1, end + 1):
        if (
            panels[index].observed_at - panels[index - 1].observed_at
            > 36 * 60 * 60
        ):
            start = index
    sequence = np.asarray(transformed[start : end + 1], dtype=float)
    if not len(sequence):
        return None
    if len(sequence) < length:
        padding = np.repeat(
            sequence[:1],
            length - len(sequence),
            axis=0,
        )
        sequence = np.vstack((padding, sequence))
    return sequence


def _dtw_distance(
    left: np.ndarray,
    right: np.ndarray,
    *,
    band: int,
) -> float:
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    if not len(left) or not len(right):
        return math.inf
    width = max(int(band), abs(len(left) - len(right)))
    previous = np.full(len(right) + 1, np.inf, dtype=float)
    previous[0] = 0.0
    for left_index in range(1, len(left) + 1):
        current = np.full(len(right) + 1, np.inf, dtype=float)
        start = max(1, left_index - width)
        stop = min(len(right), left_index + width)
        for right_index in range(start, stop + 1):
            cost = float(
                np.linalg.norm(
                    left[left_index - 1] - right[right_index - 1]
                )
            )
            current[right_index] = cost + min(
                current[right_index - 1],
                previous[right_index],
                previous[right_index - 1],
            )
        previous = current
    return float(previous[len(right)] / max(len(left), len(right)))


def _weighted_probability(
    distances: np.ndarray,
    labels: np.ndarray,
    *,
    neighbors: int,
) -> float:
    finite = np.flatnonzero(np.isfinite(distances))
    if not len(finite):
        return 0.5
    count = min(int(neighbors), len(finite))
    selected_local = np.argpartition(
        distances[finite],
        count - 1,
    )[:count]
    selected = finite[selected_local]
    scale = max(float(np.median(distances[selected])), 1e-9)
    weights = np.exp(-distances[selected] / scale)
    return float(
        np.dot(weights, labels[selected]) / max(float(np.sum(weights)), 1e-9)
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    selected = payload["selected"]
    final = payload["final_test"]
    lines = [
        "# Causal Temporal Analogue Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        (
            f"- selected: `{selected['engine']}`, sequence "
            f"{selected['sequence_length']}d, {selected['neighbors']} neighbours;"
        ),
        f"- final market accuracy: {_percent(final['market_accuracy'])};",
        f"- final market Wilson low: {_percent(final['market_wilson_low_95'])};",
        f"- final asset accuracy: {_percent(final['asset_accuracy'])};",
        f"- worst final fold: {_percent(final['worst_fold_accuracy'])};",
        f"- worst final asset: {_percent(final['worst_asset_accuracy'])};",
        f"- admitted at 70%: {'yes' if payload['admitted_70'] else 'no'}.",
        "",
        "## Validation Selection",
        "",
        "| engine | sequence | neighbours | market accuracy | asset accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["validation_candidates"]:
        summary = row["summary"]
        lines.append(
            f"| {row['engine']} | {row['sequence_length']}d | "
            f"{row['neighbors']} | {_percent(summary['market_accuracy'])} | "
            f"{_percent(summary['asset_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## Final Folds",
            "",
            "| fold | asset signals | accuracy |",
            "|---:|---:|---:|",
        ]
    )
    for row in final["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            (
                "Configuration selection sees validation only. DTW, k-NN, and "
                "WaveField share the same causal sequences and mature labels."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _percent(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * float(value):.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Causal temporal analogue market-memory benchmark."
    )
    parser.add_argument("--bundles", type=Path, nargs="*")
    parser.add_argument("--panel-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.panel_cache.exists():
        panels, source_audit = load_panel_cache(args.panel_cache)
    else:
        if not args.bundles:
            parser.error("--bundles are required when --panel-cache is absent")
        panels, source_audit = load_market_panels(args.bundles)
        save_panel_cache(args.panel_cache, panels, source_audit)
    payload = run_temporal_analogue_benchmark(panels)
    payload["source_audit"] = source_audit
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
