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
from benchmarks.crypto_binance_spot import (  # noqa: E402
    SPOT_FLOW_FEATURES,
    add_spot_flow_features,
    load_spot_dataset,
)
from benchmarks.crypto_bvol_benchmark import (  # noqa: E402
    COMPARE_ENGINES,
    _comparison_row,
    _full_comparison_row,
    _rate,
    _signed_rate,
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


def run_spot_flow_comparison(
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
        feature_names=tuple(base_feature_names) + SPOT_FLOW_FEATURES,
        include_lightgbm=True,
    )
    baseline_events = baseline.pop("events")
    treatment_events = treatment.pop("events")
    return {
        "methodology": {
            "protocol": (
                "Control and spot-flow treatment use identical BTC/ETH rows and "
                "calendar folds. Only completed checksum-verified Binance spot 5m "
                "candles at or before each futures decision timestamp are visible."
            ),
            "selection": (
                "Model thresholds use past folds only; 2026-H1 remains the final holdout."
            ),
            "features": list(SPOT_FLOW_FEATURES),
            "rows": len(rows),
            "assets": sorted({row.symbol for row in rows}),
        },
        "full_coverage_comparison": [
            _spot_keys(
                _full_comparison_row(
                    engine,
                    baseline_events=baseline_events,
                    treatment_events=treatment_events,
                )
            )
            for engine in COMPARE_ENGINES
        ],
        "policy_comparison": [
            _spot_keys(
                _comparison_row(engine, baseline=baseline, treatment=treatment)
            )
            for engine in COMPARE_ENGINES
        ],
        "baseline": baseline,
        "spot_flow": treatment,
        "admitted_70": treatment["admitted_70"],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Binance Spot-vs-Perpetual Flow Transfer Benchmark",
        "",
        str(payload["methodology"]["protocol"]),
        "",
        f"- rows: {payload['methodology']['rows']};",
        f"- assets: {', '.join(payload['methodology']['assets'])};",
        f"- admitted at 70%: {', '.join(payload['admitted_70']) or 'none'}.",
        "",
        "## Full-Coverage Control vs Spot Flow",
        "",
        "| engine | signals | control all | spot all | delta | final signals | control 2026-H1 | spot 2026-H1 | delta | spot worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["full_coverage_comparison"]:
        lines.append(
            f"| {row['engine']} | {row['all_signals']} | "
            f"{_rate(row['baseline_all'])} | {_rate(row['spot_all'])} | "
            f"{_signed_rate(row['delta_all'])} | {row['final_signals']} | "
            f"{_rate(row['baseline_final'])} | {_rate(row['spot_final'])} | "
            f"{_signed_rate(row['delta_final'])} | "
            f"{_rate(row['spot_worst_final_asset'])} |"
        )
    lines.extend(
        [
            "",
            "## Past-Selected Policy",
            "",
            "| engine | control all | spot all | delta | control 2026-H1 | spot 2026-H1 | delta |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["policy_comparison"]:
        lines.append(
            f"| {row['engine']} | {_rate(row['baseline_all'])} | "
            f"{_rate(row['spot_all'])} | {_signed_rate(row['delta_all'])} | "
            f"{_rate(row['baseline_final'])} | {_rate(row['spot_final'])} | "
            f"{_signed_rate(row['delta_final'])} |"
        )
    lines.extend(
        [
            "",
            "Spot flow is retained as predictive evidence only if gains transfer to "
            "the untouched final period without reducing coverage.",
            "",
        ]
    )
    return "\n".join(lines)


def _spot_keys(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key.replace("bvol_", "spot_"): value
        for key, value in row.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict control-vs-spot-flow transfer benchmark."
    )
    parser.add_argument("--bundles", type=Path, nargs="+", required=True)
    parser.add_argument("--spot", type=Path, required=True)
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
    spot = load_spot_dataset(args.spot)
    rows = add_spot_flow_features(market_rows, spot)
    payload = run_spot_flow_comparison(
        rows,
        horizon_seconds=args.horizon_bars * 4 * 60 * 60,
        base_feature_names=BASE_FEATURES + INTRADAY_PATH_FEATURES,
        calibration_timestamps=args.calibration_timestamps,
    )
    payload["data_audit"] = {
        "futures": data_audit,
        "spot_bars": len(spot.bars),
        "spot_source_files": len(spot.source_files),
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
