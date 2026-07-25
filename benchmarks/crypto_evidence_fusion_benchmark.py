from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_binance_archive import load_bundle  # noqa: E402
from benchmarks.crypto_binance_bvol import (  # noqa: E402
    BVOL_FEATURES,
    add_bvol_features,
    load_bvol_dataset,
)
from benchmarks.crypto_binance_spot import (  # noqa: E402
    SPOT_FLOW_FEATURES,
    add_spot_flow_features,
    load_spot_dataset,
)
from benchmarks.crypto_bvol_benchmark import (  # noqa: E402
    COMPARE_ENGINES,
    _engine_row,
    _full_summary,
    _rate,
)
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    INTRADAY_PATH_FEATURES,
    MICROSTRUCTURE_FEATURES,
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_fred_macro import (  # noqa: E402
    MACRO_FEATURES,
    add_fred_macro_features,
    load_fred_dataset,
)
from benchmarks.crypto_coinmetrics_onchain import (  # noqa: E402
    ONCHAIN_FEATURES,
    add_onchain_features,
    load_onchain_dataset,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    BASE_FEATURES,
    add_multiyear_market_features,
    assign_calendar_folds,
    run_multiyear_benchmark,
)


VARIANT_ORDER = (
    "control",
    "depth",
    "bvol",
    "spot",
    "macro",
    "onchain",
    "fusion",
)


def run_evidence_fusion_comparison(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    base_feature_names: Sequence[str],
    calibration_timestamps: int = 720,
) -> dict[str, Any]:
    feature_sets = {
        "control": tuple(base_feature_names),
        "depth": tuple(base_feature_names) + MICROSTRUCTURE_FEATURES,
        "bvol": tuple(base_feature_names) + BVOL_FEATURES,
        "spot": tuple(base_feature_names) + SPOT_FLOW_FEATURES,
        "macro": tuple(base_feature_names) + MACRO_FEATURES,
        "onchain": tuple(base_feature_names) + ONCHAIN_FEATURES,
        "fusion": (
            tuple(base_feature_names)
            + MICROSTRUCTURE_FEATURES
            + BVOL_FEATURES
            + SPOT_FLOW_FEATURES
            + MACRO_FEATURES
            + ONCHAIN_FEATURES
        ),
    }
    results = {}
    events = {}
    for name in VARIANT_ORDER:
        result = run_multiyear_benchmark(
            rows,
            horizon_seconds=horizon_seconds,
            calibration_timestamps=calibration_timestamps,
            feature_names=feature_sets[name],
            include_lightgbm=True,
        )
        events[name] = result.pop("events")
        results[name] = result

    full_coverage = []
    policy = []
    for engine in COMPARE_ENGINES:
        all_summaries = {
            name: _full_summary(events[name], engine=engine)
            for name in VARIANT_ORDER
        }
        final_summaries = {
            name: _full_summary(events[name], engine=engine, fold_index=4)
            for name in VARIANT_ORDER
        }
        if len({row["signals"] for row in all_summaries.values()}) != 1:
            raise ValueError(f"Full-coverage signal counts differ for {engine}")
        if len({row["signals"] for row in final_summaries.values()}) != 1:
            raise ValueError(f"Final signal counts differ for {engine}")
        full_coverage.append(
            {
                "engine": engine,
                "all_signals": all_summaries["control"]["signals"],
                "final_signals": final_summaries["control"]["signals"],
                "variants": {
                    name: {
                        "all_accuracy": all_summaries[name]["accuracy"],
                        "final_accuracy": final_summaries[name]["accuracy"],
                        "final_worst_asset": final_summaries[name][
                            "worst_symbol_accuracy"
                        ],
                        "final_wilson_low_95": final_summaries[name]["wilson_low_95"],
                    }
                    for name in VARIANT_ORDER
                },
            }
        )
        policy.append(
            {
                "engine": engine,
                "variants": {
                    name: {
                        "all_accuracy": _engine_row(
                            results[name]["summaries"], engine
                        )["accuracy"],
                        "final_accuracy": _engine_row(
                            results[name]["final_holdout_2026_h1"], engine
                        )["accuracy"],
                        "final_signals": _engine_row(
                            results[name]["final_holdout_2026_h1"], engine
                        )["selected_signals"],
                    }
                    for name in VARIANT_ORDER
                },
            }
        )
    return {
        "methodology": {
            "protocol": (
                "Seven feature variants use identical BTC/ETH rows, calendar folds, "
                "model hyperparameters, and past-only threshold selection. All source "
                "joins are causal and 2026-H1 remains untouched until final evaluation."
            ),
            "rows": len(rows),
            "assets": sorted({row.symbol for row in rows}),
            "variants": {
                name: list(feature_sets[name])
                for name in VARIANT_ORDER
            },
        },
        "full_coverage_comparison": full_coverage,
        "policy_comparison": policy,
        "results": results,
        "fusion_admitted_70": results["fusion"]["admitted_70"],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Binance Causal Evidence Fusion Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        f"- rows: {payload['methodology']['rows']};",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        (
            "- fusion admitted at 70%: "
            f"{', '.join(payload['fusion_admitted_70']) or 'none'}."
        ),
        "",
        "## Full Coverage",
        "",
        "| engine | signals | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion worst final asset |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["full_coverage_comparison"]:
        variants = row["variants"]
        lines.append(
            f"| {row['engine']} | {row['all_signals']} | "
            f"{_pair(variants['control'])} | {_pair(variants['depth'])} | "
            f"{_pair(variants['bvol'])} | {_pair(variants['spot'])} | "
            f"{_pair(variants['macro'])} | {_pair(variants['onchain'])} | "
            f"{_pair(variants['fusion'])} | "
            f"{_rate(variants['fusion']['final_worst_asset'])} |"
        )
    lines.extend(
        [
            "",
            "## Past-Selected Policy",
            "",
            "| engine | control all/final | depth all/final | BVOL all/final | spot all/final | macro all/final | on-chain all/final | fusion all/final | fusion final signals |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["policy_comparison"]:
        variants = row["variants"]
        lines.append(
            f"| {row['engine']} | {_pair(variants['control'])} | "
            f"{_pair(variants['depth'])} | {_pair(variants['bvol'])} | "
            f"{_pair(variants['spot'])} | {_pair(variants['macro'])} | "
            f"{_pair(variants['onchain'])} | "
            f"{_pair(variants['fusion'])} | "
            f"{variants['fusion']['final_signals']} |"
        )
    lines.extend(
        [
            "",
            "Fusion is admitted only if the combined causal evidence transfers across "
            "the final period and every asset slice; development-only uplift is rejected.",
            "",
        ]
    )
    return "\n".join(lines)


def _pair(row: Mapping[str, Any]) -> str:
    return f"{_rate(row['all_accuracy'])} / {_rate(row['final_accuracy'])}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict multi-arm benchmark for causal crypto evidence fusion."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--bvol", type=Path, required=True)
    parser.add_argument("--spot", type=Path, required=True)
    parser.add_argument("--fred", type=Path, required=True)
    parser.add_argument("--onchain", type=Path, required=True)
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--calibration-timestamps", type=int, default=720)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    rows_by_symbol = {}
    data_audit = []
    for path in args.bundles:
        bundle = load_bundle(path)
        if bundle.symbol not in {"BTCUSDT", "ETHUSDT"}:
            continue
        if not bundle.book_depth:
            raise ValueError(f"{bundle.symbol}: verified book-depth data is required")
        rows_by_symbol[bundle.symbol] = build_feature_rows(
            bundle,
            horizon=args.horizon_bars,
            lookback=180,
            include_microstructure=True,
            include_intraday=True,
            extended_features=True,
        )
        data_audit.append(
            {
                "symbol": bundle.symbol,
                "bars": len(bundle.bars),
                "intraday_bars": len(bundle.intraday_bars),
                "metrics": len(bundle.metrics),
                "funding": len(bundle.funding),
                "premium": len(bundle.premium),
                "book_depth": len(bundle.book_depth),
                "missing_source_files": len(bundle.missing_source_files),
            }
        )
    if set(rows_by_symbol) != {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("BTCUSDT and ETHUSDT futures bundles are required")
    rows = assign_calendar_folds(add_multiyear_market_features(rows_by_symbol))
    spot = load_spot_dataset(args.spot)
    rows = add_spot_flow_features(rows, spot)
    bvol = load_bvol_dataset(args.bvol)
    rows = add_bvol_features(rows, bvol)
    fred = load_fred_dataset(args.fred)
    rows = add_fred_macro_features(rows, fred)
    onchain = load_onchain_dataset(args.onchain)
    rows = add_onchain_features(rows, onchain)
    payload = run_evidence_fusion_comparison(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        base_feature_names=BASE_FEATURES + INTRADAY_PATH_FEATURES,
        calibration_timestamps=args.calibration_timestamps,
    )
    payload["data_audit"] = {
        "futures": data_audit,
        "spot_bars": len(spot.bars),
        "spot_source_files": len(spot.source_files),
        "bvol_summaries": len(bvol.summaries),
        "bvol_source_files": len(bvol.source_files),
        "bvol_missing_source_files": len(bvol.missing_source_files),
        "fred_observations": len(fred.observations),
        "fred_source_urls": list(fred.source_urls),
        "fred_source_sha256": list(fred.source_sha256),
        "fred_publication_lag_days": fred.publication_lag_days,
        "onchain_observations": len(onchain.observations),
        "onchain_source_urls": list(onchain.source_urls),
        "onchain_source_sha256": list(onchain.source_sha256),
        "onchain_publication_lag_days": onchain.publication_lag_days,
        "onchain_availability_policy": (
            "Use source completion/status timestamps only when they fall within "
            "seven days of observation; otherwise use the configured lag."
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
