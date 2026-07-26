from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    add_multiyear_market_features,
    assign_calendar_folds,
)
from wavemind.core import WaveField  # noqa: E402
from wavemind.encoders import FieldProjector  # noqa: E402


@dataclass(frozen=True)
class MarketPanel:
    observed_at: int
    target_at: int
    fold_index: int
    features: tuple[float, ...]
    market_up: bool
    asset_outcomes: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class RollingConfig:
    engine: str
    lookback: int
    logistic_c: float = 0.02


class MarketWavePredictor:
    def __init__(
        self,
        panels: Sequence[MarketPanel],
        *,
        logistic_c: float,
        seed: int,
    ) -> None:
        try:
            from sklearn.impute import SimpleImputer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise RuntimeError(
                'Install the research extra: pip install -e ".[crypto-ml]"'
            ) from exc
        if len(panels) < 40:
            raise ValueError("MarketWavePredictor requires at least 40 mature panels")

        matrix = np.asarray([panel.features for panel in panels], dtype=float)
        labels = np.asarray([panel.market_up for panel in panels], dtype=int)
        self.direct = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                C=logistic_c,
                max_iter=3000,
                class_weight="balanced",
                random_state=seed,
            ),
        )
        self.direct.fit(matrix, labels)

        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        normalized = self.scaler.fit_transform(self.imputer.fit_transform(matrix))
        self.projector = FieldProjector(24, 24, normalized.shape[1], seed=seed)
        self.up_field, self.down_field = _fit_market_fields(
            normalized,
            labels,
            projector=self.projector,
            seed=seed,
        )
        train_scores = np.asarray(
            [self._field_score(vector) for vector in normalized],
            dtype=float,
        )
        scale = float(np.std(train_scores))
        self.field_center = float(np.median(train_scores))
        self.field_scale = max(scale, 1e-6)

    def probabilities(self, features: Sequence[float]) -> dict[str, float]:
        row = np.asarray([features], dtype=float)
        direct = float(self.direct.predict_proba(row)[0, 1])
        normalized = self.scaler.transform(self.imputer.transform(row))[0]
        z_score = (self._field_score(normalized) - self.field_center) / self.field_scale
        field = 1.0 / (1.0 + math.exp(-float(np.clip(z_score, -30.0, 30.0))))
        return {
            "direct": direct,
            "wavefield": field,
            "hybrid": 0.65 * direct + 0.35 * field,
        }

    def _field_score(self, vector: np.ndarray) -> float:
        pattern = self.projector.to_pattern(vector)
        return float(
            self.up_field.field_resonance(pattern)
            - self.down_field.field_resonance(pattern)
        )


def load_market_panels(
    bundle_paths: Sequence[str | Path],
    *,
    horizon_bars: int = 6,
    lookback_bars: int = 180,
) -> tuple[list[MarketPanel], dict[str, Any]]:
    rows_by_symbol: dict[str, list[FeatureRow]] = {}
    source_audit = []
    for path in bundle_paths:
        bundle = load_bundle(path)
        if bundle.symbol in rows_by_symbol:
            raise ValueError(f"Duplicate bundle for {bundle.symbol}")
        rows = build_feature_rows(
            bundle,
            horizon=horizon_bars,
            lookback=lookback_bars,
            include_microstructure=False,
            include_intraday=True,
            extended_features=True,
        )
        if not rows:
            raise ValueError(f"{bundle.symbol}: no causal feature rows")
        rows_by_symbol[bundle.symbol] = rows
        source_audit.append(
            {
                "symbol": bundle.symbol,
                "bars": len(bundle.bars),
                "intraday_bars": len(bundle.intraday_bars),
                "metrics": len(bundle.metrics),
                "funding": len(bundle.funding),
                "premium": len(bundle.premium),
                "feature_rows": len(rows),
                "missing_required_sources": len(bundle.missing_source_files),
            }
        )

    enriched = assign_calendar_folds(add_multiyear_market_features(rows_by_symbol))
    by_timestamp: defaultdict[int, list[FeatureRow]] = defaultdict(list)
    for row in enriched:
        if row.fold_index >= 0:
            by_timestamp[row.timestamp].append(row)

    symbol_count = len(rows_by_symbol)
    complete = [
        rows
        for _, rows in sorted(by_timestamp.items())
        if len(rows) == symbol_count
    ]
    if not complete:
        raise ValueError("No complete cross-asset timestamps")
    feature_names = sorted(
        set.intersection(
            *(set(row.features) for rows in complete for row in rows)
        )
    )
    if not feature_names:
        raise ValueError("No common cross-asset features")

    panels = []
    last_observed = -10**18
    horizon_seconds = horizon_bars * 4 * 60 * 60
    for rows in complete:
        observed_at = rows[0].timestamp
        if observed_at - last_observed < horizon_seconds:
            continue
        last_observed = observed_at
        matrix = np.asarray(
            [
                [float(row.features[name]) for name in feature_names]
                for row in rows
            ],
            dtype=float,
        )
        aggregate = np.concatenate(
            (
                np.nanmean(matrix, axis=0),
                np.nanstd(matrix, axis=0),
                np.nanmedian(matrix, axis=0),
            )
        )
        future_returns = np.asarray(
            [row.future_return_bps for row in rows],
            dtype=float,
        )
        panels.append(
            MarketPanel(
                observed_at=observed_at,
                target_at=max(row.target_timestamp for row in rows),
                fold_index=rows[0].fold_index,
                features=tuple(float(value) for value in aggregate),
                market_up=bool(np.median(future_returns) > 0.0),
                asset_outcomes=tuple(
                    sorted(
                        (
                            row.symbol,
                            bool(row.future_return_bps > 0.0),
                        )
                        for row in rows
                    )
                ),
            )
        )
    return panels, {
        "sources": source_audit,
        "feature_names": feature_names,
        "aggregate_features": len(feature_names) * 3,
        "symbols": sorted(rows_by_symbol),
    }


def run_market_wave_benchmark(
    panels: Sequence[MarketPanel],
    *,
    validation_fold: int = 1,
    test_folds: Sequence[int] = (2, 3, 4),
    lookbacks: Sequence[int] = (90, 180, 360),
    logistic_c: float = 0.02,
    retrain_every: int = 7,
    seed: int = 2027,
) -> dict[str, Any]:
    ordered = sorted(panels, key=lambda panel: panel.observed_at)
    validation_candidates = []
    for lookback in lookbacks:
        predictions = _predict_folds(
            ordered,
            folds=(validation_fold,),
            lookback=lookback,
            logistic_c=logistic_c,
            retrain_every=retrain_every,
            seed=seed,
        )
        for engine in ("direct", "wavefield", "hybrid"):
            summary = summarize_predictions(predictions, engine=engine)
            validation_candidates.append(
                {
                    "engine": engine,
                    "lookback": lookback,
                    "summary": summary,
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
    final_predictions = _predict_folds(
        ordered,
        folds=test_folds,
        lookback=int(selected["lookback"]),
        logistic_c=logistic_c,
        retrain_every=retrain_every,
        seed=seed,
    )
    final = summarize_predictions(
        final_predictions,
        engine=str(selected["engine"]),
    )
    oracle = summarize_oracle(final_predictions)
    admitted = _admitted_70(final)
    return {
        "methodology": {
            "protocol": (
                f"Fold {validation_fold} selects a fixed engine and memory lookback; "
                f"folds {list(test_folds)} are the untouched final test."
            ),
            "causality": (
                "A panel enters rolling memory only when target_at is strictly "
                "earlier than the forecast observed_at."
            ),
            "sampling": "one non-overlapping 24h panel across all assets",
            "engines": ["direct", "wavefield", "hybrid"],
            "admission": (
                "At least 70% market and asset direction accuracy, market Wilson "
                "low at least 65%, and every final fold and supported asset at "
                "least 60%."
            ),
        },
        "panels": len(ordered),
        "validation_candidates": validation_candidates,
        "selected": {
            "engine": selected["engine"],
            "lookback": selected["lookback"],
            "validation": selected["summary"],
        },
        "final_test": final,
        "oracle_market_factor_ceiling": oracle,
        "admitted_70": admitted,
        "predictions": final_predictions,
    }


def _predict_folds(
    panels: Sequence[MarketPanel],
    *,
    folds: Sequence[int],
    lookback: int,
    logistic_c: float,
    retrain_every: int,
    seed: int,
) -> list[dict[str, Any]]:
    selected_folds = set(folds)
    predictions = []
    predictor: MarketWavePredictor | None = None
    trained_through = -1
    predictions_since_fit = retrain_every
    for panel in panels:
        if panel.fold_index not in selected_folds:
            continue
        mature = [
            prior
            for prior in panels
            if prior.target_at < panel.observed_at
        ][-lookback:]
        latest_mature = mature[-1].target_at if mature else -1
        if (
            predictor is None
            or (
                predictions_since_fit >= retrain_every
                and latest_mature > trained_through
            )
        ):
            predictor = MarketWavePredictor(
                mature,
                logistic_c=logistic_c,
                seed=seed + panel.fold_index * 1009,
            )
            trained_through = latest_mature
            predictions_since_fit = 0
        probabilities = predictor.probabilities(panel.features)
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


def summarize_predictions(
    predictions: Sequence[Mapping[str, Any]],
    *,
    engine: str,
) -> dict[str, Any]:
    market_hits = []
    asset_hits: defaultdict[str, list[bool]] = defaultdict(list)
    fold_hits: defaultdict[int, list[bool]] = defaultdict(list)
    for row in predictions:
        predicted_up = float(row["probabilities"][engine]) >= 0.5
        market_hit = predicted_up == bool(row["market_up"])
        market_hits.append(market_hit)
        for symbol, actual_up in row["asset_outcomes"]:
            hit = predicted_up == bool(actual_up)
            asset_hits[str(symbol)].append(hit)
            fold_hits[int(row["fold_index"])].append(hit)
    market_count = len(market_hits)
    asset_count = sum(len(values) for values in asset_hits.values())
    market_correct = sum(market_hits)
    asset_correct = sum(sum(values) for values in asset_hits.values())
    return {
        "engine": engine,
        "market_panels": market_count,
        "market_accuracy": market_correct / market_count if market_count else None,
        "market_wilson_low_95": (
            _wilson_low(market_correct, market_count) if market_count else None
        ),
        "asset_signals": asset_count,
        "asset_accuracy": asset_correct / asset_count if asset_count else None,
        "by_fold": [
            {
                "fold_index": fold,
                "signals": len(values),
                "accuracy": sum(values) / len(values),
            }
            for fold, values in sorted(fold_hits.items())
        ],
        "by_asset": [
            {
                "symbol": symbol,
                "signals": len(values),
                "accuracy": sum(values) / len(values),
            }
            for symbol, values in sorted(asset_hits.items())
        ],
        "worst_fold_accuracy": min(
            (sum(values) / len(values) for values in fold_hits.values()),
            default=None,
        ),
        "worst_asset_accuracy": min(
            (sum(values) / len(values) for values in asset_hits.values()),
            default=None,
        ),
    }


def summarize_oracle(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hits = []
    for row in predictions:
        market_up = bool(row["market_up"])
        hits.extend(
            market_up == bool(actual_up)
            for _, actual_up in row["asset_outcomes"]
        )
    return {
        "description": (
            "Diagnostic only: asset direction when the future cross-asset market "
            "direction is known. This is not a tradable predictor."
        ),
        "asset_signals": len(hits),
        "asset_accuracy": sum(hits) / len(hits) if hits else None,
    }


def _admitted_70(summary: Mapping[str, Any]) -> bool:
    folds = summary["by_fold"]
    assets = [
        row for row in summary["by_asset"] if int(row["signals"]) >= 20
    ]
    return bool(
        int(summary["market_panels"]) >= 100
        and float(summary["market_accuracy"] or 0.0) >= 0.70
        and float(summary["market_wilson_low_95"] or 0.0) >= 0.65
        and float(summary["asset_accuracy"] or 0.0) >= 0.70
        and folds
        and all(float(row["accuracy"]) >= 0.60 for row in folds)
        and assets
        and all(float(row["accuracy"]) >= 0.60 for row in assets)
    )


def _fit_market_fields(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    projector: FieldProjector,
    seed: int,
) -> tuple[WaveField, WaveField]:
    previous_state = np.random.get_state()
    np.random.seed(seed)
    try:
        up_field = WaveField(
            width=24,
            height=24,
            layers=4,
            decay=0.985,
            speed=0.12,
            nonlin=0.008,
        )
        down_field = WaveField(
            width=24,
            height=24,
            layers=4,
            decay=0.985,
            speed=0.12,
            nonlin=0.008,
        )
        up_count = max(int(np.sum(labels == 1)), 1)
        down_count = max(int(np.sum(labels == 0)), 1)
        for index, (vector, label) in enumerate(
            zip(matrix, labels, strict=True)
        ):
            recency = 0.20 + 0.80 * (index + 1) / len(matrix)
            field = up_field if label else down_field
            denominator = up_count if label else down_count
            field.feed(
                projector.to_pattern(vector),
                strength=recency * 500.0 / denominator,
            )
        up_field.evolve(4)
        down_field.evolve(4)
        return up_field, down_field
    finally:
        np.random.set_state(previous_state)


def render_markdown(payload: Mapping[str, Any]) -> str:
    selected = payload["selected"]
    final = payload["final_test"]
    oracle = payload["oracle_market_factor_ceiling"]
    lines = [
        "# Causal Cross-Asset Market Wave Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        (
            f"- selected: `{selected['engine']}` with "
            f"{selected['lookback']}-panel rolling memory;"
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
        "| engine | lookback | market accuracy | Wilson low | asset accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["validation_candidates"]:
        summary = row["summary"]
        lines.append(
            f"| {row['engine']} | {row['lookback']} | "
            f"{_percent(summary['market_accuracy'])} | "
            f"{_percent(summary['market_wilson_low_95'])} | "
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
                "The future-market-factor oracle reaches "
                f"{_percent(oracle['asset_accuracy'])} asset accuracy. It is a "
                "diagnostic ceiling, not a predictor, because it uses the future "
                "cross-asset direction."
            ),
            "",
            (
                "The production claim remains rejected unless the fixed rolling "
                "policy clears every admission condition on the untouched folds."
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
        description="Causal rolling market-wave benchmark."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--lookback-bars", type=int, default=180)
    args = parser.parse_args()

    panels, source_audit = load_market_panels(
        args.bundles,
        horizon_bars=args.horizon_bars,
        lookback_bars=args.lookback_bars,
    )
    payload = run_market_wave_benchmark(panels)
    payload["source_audit"] = source_audit
    predictions = payload.pop("predictions")
    payload["prediction_audit"] = {
        "rows": len(predictions),
        "first_observed_at": predictions[0]["observed_at"],
        "last_observed_at": predictions[-1]["observed_at"],
        "all_training_targets_strictly_past": all(
            int(row["trained_through"]) < int(row["observed_at"])
            for row in predictions
        ),
    }
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
