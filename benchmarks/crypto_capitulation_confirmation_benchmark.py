from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_capitulation_coverage_benchmark import (  # noqa: E402
    _admitted_70,
    _collapse_signals,
)
from benchmarks.crypto_capitulation_field_benchmark import (  # noqa: E402
    _independent_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)


CACHE_SCHEMA = "wavemind.crypto.capitulation-confirmation.v1"
FOLD_BOUNDARIES = (
    ("2023-07-01", "2023-10-01"),
    ("2023-10-01", "2024-01-01"),
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-15"),
    ("2024-10-15", "2025-01-15"),
    ("2025-01-15", "2025-04-15"),
    ("2025-04-15", "2025-07-15"),
    ("2025-07-15", "2025-10-15"),
    ("2025-10-15", "2026-01-15"),
    ("2026-01-15", "2026-04-15"),
    ("2026-04-15", "2026-07-01"),
)
DEVELOPMENT_FOLDS = (0, 1, 2, 3, 4)
FINAL_FOLDS = (5, 6, 7, 8, 9, 10, 11)


@dataclass(frozen=True)
class ConfirmationConfig:
    return_quantile: float
    oi_quantile: float
    confirmation: str

    def __post_init__(self) -> None:
        if not 0.0 < self.return_quantile < 0.5:
            raise ValueError("return_quantile must be between 0 and 0.5")
        if not 0.0 < self.oi_quantile <= 0.5:
            raise ValueError("oi_quantile must be above 0 and at most 0.5")
        if self.confirmation not in {
            "none",
            "green_4h",
            "green_12h",
            "green_flow",
            "green_absorption",
            "decelerating_selloff",
        }:
            raise ValueError("unsupported confirmation")


def load_confirmation_rows(
    bundle_paths: Sequence[str | Path],
    *,
    cache_path: str | Path | None = None,
) -> list[FeatureRow]:
    bundles = [Path(path) for path in bundle_paths]
    if not bundles:
        raise ValueError("bundle_paths must not be empty")
    fingerprints = {str(path.resolve()): _sha256(path) for path in bundles}
    cache = Path(cache_path) if cache_path is not None else None
    if cache is not None and cache.exists():
        payload = _read_gzip_json(cache)
        if (
            payload.get("schema") == CACHE_SCHEMA
            and payload.get("fingerprints") == fingerprints
        ):
            return [_feature_row(row) for row in payload["rows"]]

    start = _timestamp("2023-01-01")
    end = _timestamp("2026-07-03")
    rows: list[FeatureRow] = []
    seen: set[str] = set()
    for path in bundles:
        bundle = load_bundle(path)
        if bundle.symbol in seen:
            raise ValueError(f"duplicate bundle for {bundle.symbol}")
        seen.add(bundle.symbol)
        cropped = replace(
            bundle,
            bars=tuple(
                row for row in bundle.bars if start <= row.close_timestamp <= end
            ),
            intraday_bars=(),
            metrics=tuple(
                row for row in bundle.metrics if start <= row.timestamp <= end
            ),
            funding=tuple(
                row for row in bundle.funding if start <= row.timestamp <= end
            ),
            premium=tuple(
                row
                for row in bundle.premium
                if start <= row.close_timestamp <= end
            ),
            book_depth=(),
        )
        rows.extend(
            build_feature_rows(
                cropped,
                horizon=6,
                lookback=180,
                include_microstructure=False,
                include_intraday=False,
                extended_features=False,
            )
        )
    ordered = sorted(rows, key=lambda row: (row.timestamp, row.symbol))
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        _write_gzip_json(
            cache,
            {
                "schema": CACHE_SCHEMA,
                "fingerprints": fingerprints,
                "rows": [asdict(row) for row in ordered],
            },
        )
    return ordered


def candidate_configs() -> list[ConfirmationConfig]:
    return [
        ConfirmationConfig(return_quantile, oi_quantile, confirmation)
        for return_quantile in (0.01, 0.02, 0.03, 0.05)
        for oi_quantile in (0.10, 0.20, 0.30, 0.50)
        for confirmation in (
            "none",
            "green_4h",
            "green_12h",
            "green_flow",
            "green_absorption",
            "decelerating_selloff",
        )
    ]


def run_confirmation_benchmark(
    rows: Sequence[FeatureRow],
    *,
    configs: Sequence[ConfirmationConfig] | None = None,
) -> dict[str, Any]:
    folded = assign_calendar_folds(rows, boundaries=FOLD_BOUNDARIES)
    candidates = list(configs or candidate_configs())
    if not candidates:
        raise ValueError("configs must not be empty")
    development = [
        evaluate_config(folded, config=config, folds=DEVELOPMENT_FOLDS)
        for config in candidates
    ]
    eligible = [
        result
        for result in development
        if int(result["summary"]["signals"]) >= 60
        and all(int(row["signals"]) >= 8 for row in result["summary"]["by_fold"])
    ]
    if not eligible:
        raise ValueError("no development configuration has enough support")
    selected = max(eligible, key=_selection_key)
    selected_config = ConfirmationConfig(**selected["config"])
    final_selected = evaluate_config(
        folded,
        config=selected_config,
        folds=FINAL_FOLDS,
    )
    final_unconfirmed = evaluate_config(
        folded,
        config=replace(selected_config, confirmation="none"),
        folds=FINAL_FOLDS,
    )
    return {
        "benchmark": "causal post-capitulation confirmation transfer",
        "methodology": {
            "source": "official Binance USD-M futures archives",
            "horizon": "24h from each completed 4h candle",
            "development_folds": list(DEVELOPMENT_FOLDS),
            "final_folds": list(FINAL_FOLDS),
            "fold_boundaries": [list(boundary) for boundary in FOLD_BOUNDARIES],
            "selection": (
                "96 predeclared threshold/confirmation configurations are "
                "ranked only through 2024-10-14. Seven later folds are "
                "evaluated once with the selected configuration."
            ),
            "overlap_control": (
                "event conditions are checked on each closed 4h candle, then "
                "signals are collapsed to one per asset and 24h horizon"
            ),
        },
        "selected_config": asdict(selected_config),
        "development_selected": selected,
        "development_leaderboard": sorted(
            development,
            key=_selection_key,
            reverse=True,
        )[:10],
        "final_selected": final_selected,
        "final_unconfirmed": final_unconfirmed,
        "admitted_70": _admitted_70(final_selected["summary"]),
    }


def evaluate_config(
    rows: Sequence[FeatureRow],
    *,
    config: ConfirmationConfig,
    folds: Sequence[int],
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    opportunities = 0
    audits: list[dict[str, Any]] = []
    for fold in folds:
        test = sorted(
            (row for row in rows if row.fold_index == fold),
            key=lambda row: (row.timestamp, row.symbol),
        )
        if not test:
            raise ValueError(f"fold {fold} is empty")
        start = min(row.timestamp for row in test)
        history = [row for row in rows if row.target_timestamp < start]
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
        selected = _collapse_signals(
            [
                row
                for row in test
                if float(row.features["return_12"]) <= return_threshold
                and float(row.features["oi_change_1"]) <= oi_threshold
                and _confirmation_matches(row, config.confirmation)
            ]
        )
        independent_opportunities = len(_independent_rows(test))
        opportunities += independent_opportunities
        events.extend(
            _event(
                row,
                fold=fold,
                config=config,
                return_threshold=return_threshold,
                oi_threshold=oi_threshold,
            )
            for row in selected
        )
        audits.append(
            {
                "fold_index": fold,
                "matured_history_rows": len(history),
                "independent_opportunities": independent_opportunities,
                "signals": len(selected),
                "return_threshold": return_threshold,
                "oi_threshold": oi_threshold,
            }
        )
    summary = _summarize_slices(events)
    summary["independent_opportunities"] = opportunities
    summary["coverage"] = (
        int(summary["signals"]) / opportunities if opportunities else None
    )
    return {
        "config": asdict(config),
        "summary": summary,
        "fold_audits": audits,
        "events": events,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    selected = payload["selected_config"]
    lines = [
        "# Post-Capitulation Confirmation Transfer",
        "",
        (
            "This benchmark tests whether waiting for a causal stabilization "
            "signal improves extreme return/open-interest rebounds."
        ),
        "",
        "- source: official Binance USD-M futures archives;",
        "- development cutoff: 2024-10-15;",
        "- final period: 2024-10-15 through 2026-06-30;",
        (
            "- selected: return q"
            f"{selected['return_quantile']:.2f}, OI q"
            f"{selected['oi_quantile']:.2f}, {selected['confirmation']}."
        ),
        "",
        "| split | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("development selected", "development_selected"),
        ("final selected", "final_selected"),
        ("final without confirmation", "final_unconfirmed"),
    ):
        summary = payload[key]["summary"]
        lines.append(
            f"| {label} | {summary['signals']} | "
            f"{_percent(summary['coverage'])} | {_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} | "
            f"{_percent(summary['worst_supported_symbol_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "70% admission: " + ("**passed**" if payload["admitted_70"] else "**rejected**"),
            "",
            "## Development Leaderboard",
            "",
            "| return q | OI q | confirmation | signals | accuracy | Wilson low | worst fold |",
            "|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for result in payload["development_leaderboard"]:
        config = result["config"]
        summary = result["summary"]
        lines.append(
            f"| {config['return_quantile']:.2f} | {config['oi_quantile']:.2f} | "
            f"{config['confirmation']} | {summary['signals']} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            (
                "The final folds are absent from configuration ranking. The "
                "admission gate still requires aggregate, Wilson, fold, asset, "
                "and support checks."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _confirmation_matches(row: FeatureRow, confirmation: str) -> bool:
    features = row.features
    return_1 = float(features["return_1"])
    return_3 = float(features["return_3"])
    taker = float(features["taker_imbalance"])
    if confirmation == "none":
        return True
    if confirmation == "green_4h":
        return return_1 > 0.0
    if confirmation == "green_12h":
        return return_3 > 0.0
    if confirmation == "green_flow":
        return return_1 > 0.0 and taker > 0.0
    if confirmation == "green_absorption":
        return return_1 > 0.0 and taker <= 0.0
    return return_1 > return_3 / 3.0


def _selection_key(result: Mapping[str, Any]) -> tuple[float, float, float, int]:
    summary = result["summary"]
    return (
        float(summary["worst_supported_fold_accuracy"] or 0.0),
        float(summary["wilson_low_95"] or 0.0),
        float(summary["accuracy"] or 0.0),
        int(summary["signals"]),
    )


def _event(
    row: FeatureRow,
    *,
    fold: int,
    config: ConfirmationConfig,
    return_threshold: float,
    oi_threshold: float,
) -> dict[str, Any]:
    return {
        "fold_index": fold,
        "symbol": row.symbol,
        "timestamp": row.timestamp,
        "timestamp_utc": _iso(row.timestamp),
        "target_timestamp": row.target_timestamp,
        "target_timestamp_utc": _iso(row.target_timestamp),
        "prediction": "up",
        "future_return_bps": row.future_return_bps,
        "direction_hit": row.future_return_bps > 0.0,
        "return_1": float(row.features["return_1"]),
        "return_3": float(row.features["return_3"]),
        "return_12": float(row.features["return_12"]),
        "oi_change_1": float(row.features["oi_change_1"]),
        "taker_imbalance": float(row.features["taker_imbalance"]),
        "return_threshold": return_threshold,
        "oi_threshold": oi_threshold,
        "confirmation": config.confirmation,
    }


def _summarize_slices(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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


def _feature_row(payload: Mapping[str, Any]) -> FeatureRow:
    return FeatureRow(
        symbol=str(payload["symbol"]),
        timestamp=int(payload["timestamp"]),
        target_timestamp=int(payload["target_timestamp"]),
        fold_index=int(payload.get("fold_index", -1)),
        features={
            str(key): float(value)
            for key, value in payload["features"].items()
        },
        future_return_bps=float(payload["future_return_bps"]),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, separators=(",", ":"))


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test causal confirmation after capitulation."
    )
    parser.add_argument("--bundle", type=Path, action="append", required=True)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/capitulation-confirmation-rows-v1.json.gz"),
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    rows = load_confirmation_rows(args.bundle, cache_path=args.cache)
    payload = run_confirmation_benchmark(rows)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    print(
        f"selected={payload['selected_config']} "
        f"accuracy={_percent(payload['final_selected']['summary']['accuracy'])} "
        f"signals={payload['final_selected']['summary']['signals']} "
        f"admitted_70={payload['admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
