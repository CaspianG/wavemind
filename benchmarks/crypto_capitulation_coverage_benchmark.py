from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import defaultdict
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
from benchmarks.crypto_binance_liquidations import (  # noqa: E402
    LiquidationBar,
    add_liquidation_features,
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


CACHE_SCHEMA = "wavemind.crypto.capitulation-coverage.v1"
FOLD_BOUNDARIES = (
    ("2023-07-01", "2023-10-01"),
    ("2023-10-01", "2024-01-01"),
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-15"),
)
DEVELOPMENT_FOLDS = (0, 1, 2)
FINAL_FOLDS = (3, 4)


@dataclass(frozen=True)
class CoverageConfig:
    return_quantile: float
    oi_quantile: float
    liquidation_policy: str

    def __post_init__(self) -> None:
        if not 0.0 < self.return_quantile < 0.5:
            raise ValueError("return_quantile must be between 0 and 0.5")
        if not 0.0 < self.oi_quantile <= 0.5:
            raise ValueError("oi_quantile must be above 0 and at most 0.5")
        if self.liquidation_policy not in {
            "none",
            "current_sell",
            "rolling_sell",
            "rolling_burst",
            "rolling_sell_burst",
        }:
            raise ValueError("unsupported liquidation policy")


LEGACY_EVENT_CONFIG = CoverageConfig(0.01, 0.10, "none")


def load_coverage_rows(
    bundle_paths: Sequence[str | Path],
    liquidation_paths: Sequence[str | Path],
    *,
    cache_path: str | Path | None = None,
) -> list[FeatureRow]:
    bundles = [Path(path) for path in bundle_paths]
    liquidations = [Path(path) for path in liquidation_paths]
    if not bundles or len(bundles) != len(liquidations):
        raise ValueError("bundle and liquidation paths must be non-empty and paired")
    fingerprints = {
        str(path.resolve()): _sha256(path) for path in bundles + liquidations
    }
    cache = Path(cache_path) if cache_path is not None else None
    if cache is not None and cache.exists():
        payload = _read_gzip_json(cache)
        if (
            payload.get("schema") == CACHE_SCHEMA
            and payload.get("fingerprints") == fingerprints
        ):
            return [_feature_row(row) for row in payload["rows"]]

    start = _timestamp("2023-01-01")
    end = _timestamp("2024-10-17")
    output: list[FeatureRow] = []
    seen: set[str] = set()
    for bundle_path, liquidation_path in zip(
        bundles,
        liquidations,
        strict=True,
    ):
        bundle = load_bundle(bundle_path)
        symbol_key = bundle.symbol.removesuffix("USDT")
        liquidation = json.loads(liquidation_path.read_text(encoding="utf-8"))
        expected = f"{symbol_key}USD_PERP"
        if liquidation["symbol"] != expected:
            raise ValueError(
                f"{bundle.symbol} must be paired with {expected}, "
                f"not {liquidation['symbol']}"
            )
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
        base_rows = build_feature_rows(
            cropped,
            horizon=6,
            lookback=180,
            include_microstructure=False,
            include_intraday=False,
            extended_features=False,
        )
        bars = [LiquidationBar(**row) for row in liquidation["bars"]]
        output.extend(add_liquidation_features(base_rows, bars))

    ordered = sorted(output, key=lambda row: (row.timestamp, row.symbol))
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


def candidate_configs() -> list[CoverageConfig]:
    return [
        CoverageConfig(return_quantile, oi_quantile, policy)
        for return_quantile in (0.01, 0.02, 0.03, 0.05)
        for oi_quantile in (0.10, 0.20, 0.30, 0.50)
        for policy in (
            "none",
            "current_sell",
            "rolling_sell",
            "rolling_burst",
            "rolling_sell_burst",
        )
    ]


def run_coverage_benchmark(
    rows: Sequence[FeatureRow],
    *,
    configs: Sequence[CoverageConfig] | None = None,
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
        if int(result["summary"]["signals"]) >= 40
        and all(int(row["signals"]) >= 8 for row in result["summary"]["by_fold"])
    ]
    if not eligible:
        raise ValueError("no development configuration has enough support")
    selected = max(eligible, key=_selection_key)
    selected_config = CoverageConfig(**selected["config"])

    final_selected = evaluate_config(
        folded,
        config=selected_config,
        folds=FINAL_FOLDS,
    )
    final_legacy = evaluate_config(
        folded,
        config=LEGACY_EVENT_CONFIG,
        folds=FINAL_FOLDS,
    )
    leaderboard = sorted(development, key=_selection_key, reverse=True)[:10]
    return {
        "benchmark": "causal capitulation coverage transfer",
        "methodology": {
            "source": (
                "official Binance USD-M futures bundles and checksum-verified "
                "Binance COIN-M liquidation snapshots"
            ),
            "horizon": "24h from each completed 4h candle",
            "development_folds": list(DEVELOPMENT_FOLDS),
            "final_folds": list(FINAL_FOLDS),
            "fold_boundaries": [list(boundary) for boundary in FOLD_BOUNDARIES],
            "selection": (
                "80 predeclared configurations are ranked on development only. "
                "The final folds are evaluated once with the selected policy."
            ),
            "overlap_control": (
                "signals are detected first, then collapsed to at most one "
                "forecast per asset and 24h horizon"
            ),
            "admission_gate": {
                "min_accuracy": 0.70,
                "min_signals": 40,
                "min_wilson_low_95": 0.65,
                "min_supported_fold_accuracy": 0.65,
                "min_supported_symbol_accuracy": 0.65,
                "min_slice_support": 5,
            },
        },
        "selected_config": asdict(selected_config),
        "development_selected": selected,
        "development_leaderboard": leaderboard,
        "final_selected": final_selected,
        "final_legacy_event": final_legacy,
        "admitted_70": _admitted_70(final_selected["summary"]),
    }


def evaluate_config(
    rows: Sequence[FeatureRow],
    *,
    config: CoverageConfig,
    folds: Sequence[int],
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    opportunities = 0
    for fold in folds:
        test = sorted(
            (row for row in rows if row.fold_index == fold),
            key=lambda row: (row.timestamp, row.symbol),
        )
        if not test:
            raise ValueError(f"fold {fold} is empty")
        test_start = min(row.timestamp for row in test)
        history = [row for row in rows if row.target_timestamp < test_start]
        if not history:
            raise ValueError(f"fold {fold} has no matured history")
        return_threshold = _quantile(history, "return_12", config.return_quantile)
        oi_threshold = _quantile(history, "oi_change_1", config.oi_quantile)
        selected = _collapse_signals(
            [
                row
                for row in test
                if float(row.features["return_12"]) <= return_threshold
                and float(row.features["oi_change_1"]) <= oi_threshold
                and _liquidation_matches(row, config.liquidation_policy)
            ]
        )
        opportunities += len(_independent_rows(test))
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
                "independent_opportunities": len(_independent_rows(test)),
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
        "# Capitulation Coverage Transfer",
        "",
        (
            "A development-only search tests whether causal liquidation context "
            "can broaden the frozen return/open-interest rebound signal."
        ),
        "",
        "- source: " + str(payload["methodology"]["source"]) + ";",
        "- horizon: 24h from completed 4h candles;",
        "- final period: April 2024 through October 14, 2024;",
        (
            "- selected policy: return q"
            f"{selected['return_quantile']:.2f}, OI q"
            f"{selected['oi_quantile']:.2f}, "
            f"{selected['liquidation_policy']}."
        ),
        "",
        "| split | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("development selected", "development_selected"),
        ("final selected", "final_selected"),
        ("final legacy event", "final_legacy_event"),
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
            "| return q | OI q | liquidation policy | signals | accuracy | Wilson low | worst fold |",
            "|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for result in payload["development_leaderboard"]:
        config = result["config"]
        summary = result["summary"]
        lines.append(
            f"| {config['return_quantile']:.2f} | {config['oi_quantile']:.2f} | "
            f"{config['liquidation_policy']} | {summary['signals']} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            (
                "The final period is not part of configuration ranking. A positive "
                "average does not pass unless Wilson, fold, asset, and support "
                "checks also pass."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _selection_key(result: Mapping[str, Any]) -> tuple[float, float, float, int]:
    summary = result["summary"]
    return (
        float(summary["worst_supported_fold_accuracy"] or 0.0),
        float(summary["wilson_low_95"] or 0.0),
        float(summary["accuracy"] or 0.0),
        int(summary["signals"]),
    )


def _admitted_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= 40
        and float(summary["accuracy"] or 0.0) >= 0.70
        and float(summary["wilson_low_95"] or 0.0) >= 0.65
        and float(summary["worst_supported_fold_accuracy"] or 0.0) >= 0.65
        and float(summary["worst_supported_symbol_accuracy"] or 0.0) >= 0.65
    )


def _liquidation_matches(row: FeatureRow, policy: str) -> bool:
    features = row.features
    current_count = math.expm1(float(features["liquidation_log_count"]))
    rolling_count = math.expm1(
        float(features["liquidation_log_count_sum6"])
    )
    current_imbalance = float(features["liquidation_imbalance"])
    rolling_imbalance = float(features["liquidation_weighted_imbalance6"])
    rolling_burst = float(features["liquidation_quantity_z36_max6"])
    if policy == "none":
        return True
    if policy == "current_sell":
        return current_count >= 1.0 and current_imbalance <= -0.20
    if policy == "rolling_sell":
        return rolling_count >= 3.0 and rolling_imbalance <= -0.10
    if policy == "rolling_burst":
        return rolling_count >= 3.0 and rolling_burst >= 1.0
    return (
        rolling_count >= 3.0
        and rolling_burst >= 1.0
        and rolling_imbalance <= -0.10
    )


def _collapse_signals(rows: Sequence[FeatureRow]) -> list[FeatureRow]:
    next_allowed: defaultdict[str, int] = defaultdict(lambda: -1)
    output: list[FeatureRow] = []
    for row in sorted(rows, key=lambda item: (item.timestamp, item.symbol)):
        if row.timestamp < next_allowed[row.symbol]:
            continue
        output.append(row)
        next_allowed[row.symbol] = row.target_timestamp
    return output


def _event(
    row: FeatureRow,
    *,
    fold: int,
    config: CoverageConfig,
    return_threshold: float,
    oi_threshold: float,
) -> dict[str, Any]:
    features = row.features
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
        "return_12": float(features["return_12"]),
        "oi_change_1": float(features["oi_change_1"]),
        "liquidation_log_count_sum6": float(
            features["liquidation_log_count_sum6"]
        ),
        "liquidation_quantity_z36_max6": float(
            features["liquidation_quantity_z36_max6"]
        ),
        "liquidation_weighted_imbalance6": float(
            features["liquidation_weighted_imbalance6"]
        ),
        "return_threshold": return_threshold,
        "oi_threshold": oi_threshold,
        "liquidation_policy": config.liquidation_policy,
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
        description="Test causal liquidation context for capitulation coverage."
    )
    parser.add_argument("--bundle", type=Path, action="append", required=True)
    parser.add_argument(
        "--liquidation",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/capitulation-coverage-rows-v1.json.gz"),
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    rows = load_coverage_rows(
        args.bundle,
        args.liquidation,
        cache_path=args.cache,
    )
    payload = run_coverage_benchmark(rows)
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
