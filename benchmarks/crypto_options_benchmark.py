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
from benchmarks.crypto_bvol_benchmark import (  # noqa: E402
    COMPARE_ENGINES,
    _engine_row,
    _full_summary,
)
from benchmarks.crypto_deribit_options import (  # noqa: E402
    OPTIONS_FEATURES,
    add_options_features,
    load_options_dataset,
)
from benchmarks.crypto_derivatives_field_benchmark import (  # noqa: E402
    INTRADAY_PATH_FEATURES,
    FeatureRow,
    build_feature_rows,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    BASE_FEATURES,
    add_multiyear_market_features,
    assign_calendar_folds,
    run_multiyear_benchmark,
)


def run_options_comparison(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    base_feature_names: Sequence[str],
    calibration_timestamps: int = 720,
) -> dict[str, Any]:
    baseline = run_multiyear_benchmark(
        rows,
        horizon_seconds=horizon_seconds,
        calibration_timestamps=calibration_timestamps,
        feature_names=base_feature_names,
        include_lightgbm=True,
    )
    treatment = run_multiyear_benchmark(
        rows,
        horizon_seconds=horizon_seconds,
        calibration_timestamps=calibration_timestamps,
        feature_names=tuple(base_feature_names) + OPTIONS_FEATURES,
        include_lightgbm=True,
    )
    baseline_events = baseline.pop("events")
    treatment_events = treatment.pop("events")
    full_coverage = []
    policy = []
    for engine in COMPARE_ENGINES:
        baseline_all = _full_summary(baseline_events, engine=engine)
        options_all = _full_summary(treatment_events, engine=engine)
        baseline_final = _full_summary(
            baseline_events, engine=engine, fold_index=4
        )
        options_final = _full_summary(
            treatment_events, engine=engine, fold_index=4
        )
        if (
            baseline_all["signals"] != options_all["signals"]
            or baseline_final["signals"] != options_final["signals"]
        ):
            raise ValueError(f"Control and options coverage differ for {engine}")
        full_coverage.append(
            {
                "engine": engine,
                "all_signals": baseline_all["signals"],
                "final_signals": baseline_final["signals"],
                "control_all": baseline_all["accuracy"],
                "options_all": options_all["accuracy"],
                "delta_all": _difference(
                    options_all["accuracy"], baseline_all["accuracy"]
                ),
                "control_final": baseline_final["accuracy"],
                "options_final": options_final["accuracy"],
                "delta_final": _difference(
                    options_final["accuracy"], baseline_final["accuracy"]
                ),
                "options_worst_final_asset": options_final[
                    "worst_symbol_accuracy"
                ],
                "options_final_wilson_low_95": options_final["wilson_low_95"],
            }
        )
        control_all = _engine_row(baseline["summaries"], engine)
        selected_all = _engine_row(treatment["summaries"], engine)
        control_final = _engine_row(baseline["final_holdout_2026_h1"], engine)
        selected_final = _engine_row(
            treatment["final_holdout_2026_h1"], engine
        )
        policy.append(
            {
                "engine": engine,
                "control_all": control_all["accuracy"],
                "options_all": selected_all["accuracy"],
                "control_final": control_final["accuracy"],
                "options_final": selected_final["accuracy"],
                "options_final_signals": selected_final["selected_signals"],
            }
        )
    return {
        "methodology": {
            "protocol": (
                "Control and Deribit options treatment use identical BTC/ETH "
                "rows and calendar folds. Three deterministic trade samples "
                "per UTC day are fingerprinted and become visible only at the "
                "next UTC midnight."
            ),
            "selection": (
                "Thresholds use past folds only; 2026-H1 remains the final holdout."
            ),
            "features": list(OPTIONS_FEATURES),
            "rows": len(rows),
            "assets": sorted({row.symbol for row in rows}),
        },
        "full_coverage_comparison": full_coverage,
        "policy_comparison": policy,
        "control": baseline,
        "options": treatment,
        "admitted_70": treatment["admitted_70"],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Deribit Options Evidence Transfer Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        f"- rows: {payload['methodology']['rows']};",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        f"- admitted at 70%: {', '.join(payload['admitted_70']) or 'none'}.",
        "",
        "## Full Coverage",
        "",
        "| engine | signals | control all/final | options all/final | delta all/final | options worst final asset |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["full_coverage_comparison"]:
        lines.append(
            f"| {row['engine']} | {row['all_signals']} | "
            f"{_rate(row['control_all'])} / {_rate(row['control_final'])} | "
            f"{_rate(row['options_all'])} / {_rate(row['options_final'])} | "
            f"{_signed_rate(row['delta_all'])} / "
            f"{_signed_rate(row['delta_final'])} | "
            f"{_rate(row['options_worst_final_asset'])} |"
        )
    lines.extend(
        [
            "",
            "## Past-Selected Policy",
            "",
            "| engine | control all/final | options all/final | options final signals |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["policy_comparison"]:
        lines.append(
            f"| {row['engine']} | {_rate(row['control_all'])} / "
            f"{_rate(row['control_final'])} | {_rate(row['options_all'])} / "
            f"{_rate(row['options_final'])} | {row['options_final_signals']} |"
        )
    lines.extend(
        [
            "",
            "The options sample is admitted only if it transfers to the untouched "
            "period and every asset slice. It is a deterministic sample of the "
            "historical tape, not a claim of complete exchange volume.",
            "",
        ]
    )
    return "\n".join(lines)


def _difference(left: Any, right: Any) -> float | None:
    return None if left is None or right is None else float(left) - float(right)


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def _signed_rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):+.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict control-vs-Deribit-options transfer benchmark."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--options", type=Path, required=True)
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
        rows_by_symbol[bundle.symbol] = build_feature_rows(
            bundle,
            horizon=args.horizon_bars,
            lookback=180,
            include_microstructure=False,
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
            }
        )
    if set(rows_by_symbol) != {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("BTCUSDT and ETHUSDT futures bundles are required")
    market_rows = assign_calendar_folds(
        add_multiyear_market_features(rows_by_symbol)
    )
    dataset = load_options_dataset(args.options)
    rows = add_options_features(market_rows, dataset)
    payload = run_options_comparison(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        base_feature_names=BASE_FEATURES + INTRADAY_PATH_FEATURES,
        calibration_timestamps=args.calibration_timestamps,
    )
    payload["data_audit"] = {
        "futures": data_audit,
        "options_summaries": len(dataset.summaries),
        "options_missing_days": len(dataset.missing_days),
        "options_sample_count_per_window": dataset.sample_count,
        "options_sample_windows": list(dataset.sample_windows),
        "options_source_endpoint": dataset.source_endpoint,
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
