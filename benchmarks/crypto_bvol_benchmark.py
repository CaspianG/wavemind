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
from benchmarks.crypto_accuracy_gate import (  # noqa: E402
    _wilson_low,
    collapse_overlapping_events,
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


COMPARE_ENGINES = (
    "LightGBM direction",
    "Tabular ensemble direction",
    "WaveField-gated Logistic direction",
    "Calibrated WaveField-gated Logistic direction",
    "WaveField outcome direction",
    "WaveField regime memory direction",
)


def run_bvol_comparison(
    rows: Sequence[FeatureRow],
    *,
    horizon_seconds: int,
    base_feature_names: Sequence[str],
    calibration_timestamps: int = 1620,
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
        feature_names=tuple(base_feature_names) + BVOL_FEATURES,
        include_lightgbm=True,
    )
    baseline_events = baseline.pop("events")
    treatment_events = treatment.pop("events")
    full_coverage_comparison = [
        _full_comparison_row(
            engine,
            baseline_events=baseline_events,
            treatment_events=treatment_events,
        )
        for engine in COMPARE_ENGINES
    ]
    policy_comparison = [
        _comparison_row(engine, baseline=baseline, treatment=treatment)
        for engine in COMPARE_ENGINES
    ]
    return {
        "methodology": {
            "protocol": (
                "Control and BVOL treatment use identical BTC/ETH rows and calendar folds. "
                "Each BVOL daily close becomes visible only at 00:00 UTC on the next day."
            ),
            "selection": "Model thresholds use past folds only; 2026-H1 remains the final holdout.",
            "features": list(BVOL_FEATURES),
            "rows": len(rows),
            "assets": sorted({row.symbol for row in rows}),
        },
        "full_coverage_comparison": full_coverage_comparison,
        "policy_comparison": policy_comparison,
        "baseline": baseline,
        "bvol": treatment,
        "admitted_70": treatment["admitted_70"],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Binance Options BVOL Transfer Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        f"- rows: {payload['methodology']['rows']};",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        f"- admitted at 70%: {', '.join(payload['admitted_70']) or 'none'}.",
        "",
        "## Full-Coverage Control vs BVOL",
        "",
        "| engine | all signals | control all | BVOL all | delta | final signals | control 2026-H1 | BVOL 2026-H1 | delta | BVOL worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["full_coverage_comparison"]:
        lines.append(
            f"| {row['engine']} | {row['all_signals']} | {_rate(row['baseline_all'])} | "
            f"{_rate(row['bvol_all'])} | {_signed_rate(row['delta_all'])} | "
            f"{row['final_signals']} | {_rate(row['baseline_final'])} | "
            f"{_rate(row['bvol_final'])} | {_signed_rate(row['delta_final'])} | "
            f"{_rate(row['bvol_worst_final_asset'])} |"
        )
    lines.extend(
        [
            "",
            "## Past-Selected Policy",
            "",
            "| engine | control all | BVOL all | delta | control 2026-H1 | BVOL 2026-H1 | delta |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["policy_comparison"]:
        lines.append(
            f"| {row['engine']} | {_rate(row['baseline_all'])} | {_rate(row['bvol_all'])} | "
            f"{_signed_rate(row['delta_all'])} | {_rate(row['baseline_final'])} | "
            f"{_rate(row['bvol_final'])} | {_signed_rate(row['delta_final'])} |"
        )
    lines.extend(
        [
            "",
            "BVOL is retained as predictive evidence only if gains transfer to the untouched final period.",
            "",
        ]
    )
    return "\n".join(lines)


def _full_comparison_row(
    engine: str,
    *,
    baseline_events: Sequence[Mapping[str, Any]],
    treatment_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline_all = _full_summary(baseline_events, engine=engine)
    treatment_all = _full_summary(treatment_events, engine=engine)
    baseline_final = _full_summary(baseline_events, engine=engine, fold_index=4)
    treatment_final = _full_summary(treatment_events, engine=engine, fold_index=4)
    if (
        baseline_all["signals"] != treatment_all["signals"]
        or baseline_final["signals"] != treatment_final["signals"]
    ):
        raise ValueError(f"Control and BVOL coverage differ for {engine}")
    return {
        "engine": engine,
        "all_signals": baseline_all["signals"],
        "baseline_all": baseline_all["accuracy"],
        "bvol_all": treatment_all["accuracy"],
        "delta_all": _difference(treatment_all["accuracy"], baseline_all["accuracy"]),
        "final_signals": baseline_final["signals"],
        "baseline_final": baseline_final["accuracy"],
        "bvol_final": treatment_final["accuracy"],
        "delta_final": _difference(
            treatment_final["accuracy"],
            baseline_final["accuracy"],
        ),
        "bvol_worst_final_asset": treatment_final["worst_symbol_accuracy"],
        "bvol_final_wilson_low_95": treatment_final["wilson_low_95"],
    }


def _full_summary(
    events: Sequence[Mapping[str, Any]],
    *,
    engine: str,
    fold_index: int | None = None,
) -> dict[str, Any]:
    selected = collapse_overlapping_events(
        row
        for row in events
        if row["engine"] == engine
        and (fold_index is None or int(row["fold_index"]) == fold_index)
    )
    hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in selected)
    by_symbol = []
    for symbol in sorted({str(row["symbol"]) for row in selected}):
        rows = [row for row in selected if str(row["symbol"]) == symbol]
        symbol_hits = sum(int(float(row["direction_hit"]) >= 0.5) for row in rows)
        by_symbol.append(
            {
                "symbol": symbol,
                "signals": len(rows),
                "accuracy": symbol_hits / len(rows),
            }
        )
    return {
        "signals": len(selected),
        "accuracy": hits / len(selected) if selected else None,
        "wilson_low_95": _wilson_low(hits, len(selected)) if selected else None,
        "worst_symbol_accuracy": min(
            (row["accuracy"] for row in by_symbol),
            default=None,
        ),
    }


def _comparison_row(
    engine: str,
    *,
    baseline: Mapping[str, Any],
    treatment: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_all = _engine_row(baseline["summaries"], engine)
    treatment_all = _engine_row(treatment["summaries"], engine)
    baseline_final = _engine_row(baseline["final_holdout_2026_h1"], engine)
    treatment_final = _engine_row(treatment["final_holdout_2026_h1"], engine)
    return {
        "engine": engine,
        "baseline_all": baseline_all["accuracy"],
        "bvol_all": treatment_all["accuracy"],
        "delta_all": _difference(treatment_all["accuracy"], baseline_all["accuracy"]),
        "baseline_final": baseline_final["accuracy"],
        "bvol_final": treatment_final["accuracy"],
        "delta_final": _difference(
            treatment_final["accuracy"],
            baseline_final["accuracy"],
        ),
        "bvol_worst_final_asset": treatment_final["worst_symbol_accuracy"],
        "bvol_final_signals": treatment_final["selected_signals"],
    }


def _engine_row(rows: Sequence[Mapping[str, Any]], engine: str) -> Mapping[str, Any]:
    try:
        return next(row for row in rows if row["engine"] == engine)
    except StopIteration as exc:
        raise ValueError(f"Missing benchmark engine: {engine}") from exc


def _difference(left: Any, right: Any) -> float | None:
    return None if left is None or right is None else float(left) - float(right)


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def _signed_rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):+.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict control-vs-BVOL transfer benchmark on Binance archives."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--bvol", type=Path, required=True)
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--include-intraday", action="store_true")
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
            include_intraday=args.include_intraday,
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
    market_rows = assign_calendar_folds(add_multiyear_market_features(rows_by_symbol))
    dataset = load_bvol_dataset(args.bvol)
    rows = add_bvol_features(market_rows, dataset)
    base_features = (
        BASE_FEATURES + INTRADAY_PATH_FEATURES
        if args.include_intraday
        else BASE_FEATURES
    )
    payload = run_bvol_comparison(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        base_feature_names=base_features,
        calibration_timestamps=args.calibration_timestamps,
    )
    payload["data_audit"] = {
        "futures": data_audit,
        "bvol_summaries": len(dataset.summaries),
        "bvol_source_files": len(dataset.source_files),
        "bvol_missing_source_files": len(dataset.missing_source_files),
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
