from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    ConfirmationConfig,
    FOLD_BOUNDARIES,
    _percent,
    evaluate_config,
    load_confirmation_rows,
)
from benchmarks.crypto_capitulation_coverage_benchmark import (  # noqa: E402
    _admitted_70,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)


# Frozen before evaluating the 16-asset transfer set.
FROZEN_TRANSFER_CONFIG = ConfirmationConfig(
    return_quantile=0.01,
    oi_quantile=0.10,
    confirmation="decelerating_selloff",
)
ALL_FOLDS = tuple(range(len(FOLD_BOUNDARIES)))


def run_asset_transfer_benchmark(
    development_rows: Sequence[FeatureRow],
    holdout_rows: Sequence[FeatureRow],
    *,
    config: ConfirmationConfig = FROZEN_TRANSFER_CONFIG,
) -> dict[str, Any]:
    development_assets = sorted({row.symbol for row in development_rows})
    holdout_assets = sorted({row.symbol for row in holdout_rows})
    overlap = sorted(set(development_assets) & set(holdout_assets))
    if overlap:
        raise ValueError(
            "development and holdout assets overlap: " + ", ".join(overlap)
        )
    development = evaluate_config(
        assign_calendar_folds(
            development_rows,
            boundaries=FOLD_BOUNDARIES,
        ),
        config=config,
        folds=ALL_FOLDS,
    )
    holdout = evaluate_config(
        assign_calendar_folds(
            holdout_rows,
            boundaries=FOLD_BOUNDARIES,
        ),
        config=config,
        folds=ALL_FOLDS,
    )
    unconfirmed = evaluate_config(
        assign_calendar_folds(
            holdout_rows,
            boundaries=FOLD_BOUNDARIES,
        ),
        config=ConfirmationConfig(
            config.return_quantile,
            config.oi_quantile,
            "none",
        ),
        folds=ALL_FOLDS,
    )
    return {
        "benchmark": "frozen post-capitulation asset transfer",
        "methodology": {
            "source": "official Binance USD-M futures archives",
            "horizon": "24h from each completed 4h candle",
            "fold_boundaries": [list(boundary) for boundary in FOLD_BOUNDARIES],
            "selection": (
                "The threshold and confirmation rule were frozen on 13 "
                "development assets before the 16 holdout assets were loaded."
            ),
            "overlap_control": (
                "event conditions are checked on each closed 4h candle, then "
                "signals are collapsed to one per asset and 24h horizon"
            ),
        },
        "frozen_config": asdict(config),
        "development_assets": development_assets,
        "holdout_assets": holdout_assets,
        "development": development,
        "asset_disjoint_holdout": holdout,
        "holdout_unconfirmed": unconfirmed,
        "aggregate_evidence_70": _aggregate_evidence_70(holdout["summary"]),
        "admitted_70": _admitted_70(holdout["summary"]),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    config = payload["frozen_config"]
    lines = [
        "# Frozen Post-Capitulation Asset Transfer",
        "",
        (
            "A 13-asset development result is transferred unchanged to 16 "
            "different Binance futures assets."
        ),
        "",
        "- source: official Binance USD-M futures archives;",
        "- horizon: 24h from completed 4h candles;",
        (
            "- frozen rule: return q"
            f"{config['return_quantile']:.2f}, OI q"
            f"{config['oi_quantile']:.2f}, {config['confirmation']};"
        ),
        "- period: July 2023 through June 2026.",
        "",
        "| split | assets | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key, assets_key in (
        ("development", "development", "development_assets"),
        (
            "asset-disjoint holdout",
            "asset_disjoint_holdout",
            "holdout_assets",
        ),
        ("holdout without confirmation", "holdout_unconfirmed", "holdout_assets"),
    ):
        summary = payload[key]["summary"]
        lines.append(
            f"| {label} | {len(payload[assets_key])} | {summary['signals']} | "
            f"{_percent(summary['coverage'])} | {_percent(summary['accuracy'])} | "
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
            "Stable 70% admission: "
            + ("**passed**" if payload["admitted_70"] else "**rejected**"),
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
            f"{_percent(row['accuracy'])} | {_percent(row['wilson_low_95'])} |"
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
            f"{_percent(row['accuracy'])} | {_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            (
                "The aggregate and stable gates are separate: a high average "
                "does not become a production claim when a supported time or "
                "asset slice remains below 65%."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _aggregate_evidence_70(summary: Mapping[str, Any]) -> bool:
    return bool(
        int(summary["signals"]) >= 40
        and float(summary["accuracy"] or 0.0) >= 0.70
        and float(summary["wilson_low_95"] or 0.0) >= 0.65
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transfer a frozen capitulation confirmation to new assets."
    )
    parser.add_argument(
        "--development-bundle",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--holdout-bundle",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--development-cache",
        type=Path,
        default=Path("data/capitulation-confirmation-rows-v1.json.gz"),
    )
    parser.add_argument(
        "--holdout-cache",
        type=Path,
        default=Path("data/capitulation-transfer-holdout-rows-v1.json.gz"),
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    development = load_confirmation_rows(
        args.development_bundle,
        cache_path=args.development_cache,
    )
    holdout = load_confirmation_rows(
        args.holdout_bundle,
        cache_path=args.holdout_cache,
    )
    payload = run_asset_transfer_benchmark(development, holdout)
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
        f"accuracy={_percent(summary['accuracy'])} "
        f"signals={summary['signals']} "
        f"aggregate_70={payload['aggregate_evidence_70']} "
        f"admitted_70={payload['admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
