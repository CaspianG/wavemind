from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_bybit_capitulation_benchmark import (  # noqa: E402
    BybitInstrument,
    build_analogue_feature_rows,
    load_or_download_dataset,
)
from benchmarks.crypto_capitulation_coverage_benchmark import (  # noqa: E402
    _admitted_70,
)
from benchmarks.crypto_dynamic_feedback_benchmark import (  # noqa: E402
    FeedbackConfig,
    _percent,
    evaluate_feedback_router,
    generate_online_queries,
    load_development,
)
from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402


EXPANDED_HOLDOUT_GROUPS = (
    (
        (
            "SUSHIUSDT",
            "1INCHUSDT",
            "KNCUSDT",
            "BLURUSDT",
            "STXUSDT",
            "MINAUSDT",
            "CFXUSDT",
            "AXSUSDT",
        ),
        "data/bybit-dynamic-feedback-holdout-v1.json.gz",
    ),
    (
        (
            "ALGOUSDT",
            "ATOMUSDT",
            "BNBUSDT",
            "DOGEUSDT",
            "FILUSDT",
            "MANAUSDT",
            "SOLUSDT",
            "XRPUSDT",
        ),
        "data/bybit-dynamic-feedback-replication1-v1.json.gz",
    ),
    (
        (
            "AAVEUSDT",
            "HBARUSDT",
            "SANDUSDT",
            "THETAUSDT",
            "UNIUSDT",
            "VETUSDT",
            "XTZUSDT",
            "ZECUSDT",
        ),
        "data/bybit-dynamic-feedback-replication2-v1.json.gz",
    ),
    (
        (
            "ARUSDT",
            "BATUSDT",
            "COMPUSDT",
            "DASHUSDT",
            "GMTUSDT",
            "LRCUSDT",
            "ROSEUSDT",
            "RSRUSDT",
        ),
        "data/bybit-dynamic-feedback-replication3-v1.json.gz",
    ),
    (
        (
            "COTIUSDT",
            "ENSUSDT",
            "GMXUSDT",
            "IMXUSDT",
            "JASMYUSDT",
            "LPTUSDT",
            "MAGICUSDT",
            "WOOUSDT",
        ),
        "data/bybit-dynamic-feedback-replication4-v1.json.gz",
    ),
)
FROZEN_CONFIG = FeedbackConfig(field_weight=0.0)
BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 20260727


def load_expanded_holdout(
    groups: Sequence[tuple[Sequence[str], str | Path]] = EXPANDED_HOLDOUT_GROUPS,
) -> tuple[list[BybitInstrument], list[dict[str, Any]], dict[str, int]]:
    instruments: list[BybitInstrument] = []
    provenance: list[dict[str, Any]] = []
    group_by_symbol: dict[str, int] = {}
    for group_index, (symbols, cache_path) in enumerate(groups):
        rows, source = load_or_download_dataset(
            symbols,
            cache_path=cache_path,
        )
        instruments.extend(rows)
        provenance.append(source)
        for symbol in symbols:
            if symbol in group_by_symbol:
                raise ValueError(f"duplicate holdout symbol: {symbol}")
            group_by_symbol[symbol] = group_index
    return instruments, provenance, group_by_symbol


def run_replication_audit(
    development: Sequence[BybitInstrument],
    holdout: Sequence[BybitInstrument],
    *,
    development_provenance: Sequence[Mapping[str, Any]],
    holdout_provenance: Sequence[Mapping[str, Any]],
    group_by_symbol: Mapping[str, int],
) -> dict[str, Any]:
    development_assets = sorted(row.symbol for row in development)
    holdout_assets = sorted(row.symbol for row in holdout)
    overlap = set(development_assets) & set(holdout_assets)
    if overlap:
        raise ValueError(
            "development and holdout assets overlap: "
            + ", ".join(sorted(overlap))
        )

    development_rows = build_analogue_feature_rows(development)
    holdout_rows = build_analogue_feature_rows(holdout)
    development_queries = generate_online_queries(
        development_rows,
        development_rows,
        include_matured_test_memory=True,
    )
    holdout_queries = generate_online_queries(
        development_rows,
        holdout_rows,
        include_matured_test_memory=True,
    )
    online_feedback = evaluate_feedback_router(
        development_queries,
        holdout_queries,
        config=FROZEN_CONFIG,
        update_with_test=True,
    )
    frozen_feedback = evaluate_feedback_router(
        development_queries,
        holdout_queries,
        config=FROZEN_CONFIG,
        update_with_test=False,
    )

    online_audit = audit_policy(
        online_feedback,
        group_by_symbol=group_by_symbol,
    )
    frozen_audit = audit_policy(
        frozen_feedback,
        group_by_symbol=group_by_symbol,
    )
    return {
        "benchmark": "dynamic feedback expanded replication audit",
        "status": "exploratory expanded audit; not a preregistered confirmation",
        "methodology": {
            "source": "official Bybit V5 public kline and open-interest API",
            "horizon": "24h from each completed 4h candle",
            "development_assets": len(development_assets),
            "holdout_assets": len(holdout_assets),
            "asset_disjoint": True,
            "frozen_config": FROZEN_CONFIG.__dict__,
            "causality": (
                "Every analogue label and feedback outcome has a target "
                "timestamp strictly earlier than the current query timestamp."
            ),
            "dependence_audit": (
                "Signals are additionally grouped into UTC 24h market blocks. "
                "A deterministic cluster bootstrap resamples whole blocks, not "
                "individual correlated asset signals."
            ),
            "baseline": (
                "The same selected events are compared with always-up and raw "
                "analogue-direction predictions."
            ),
            "admission": {
                "minimum_signals": 80,
                "minimum_market_blocks": 20,
                "minimum_accuracy": 0.70,
                "minimum_wilson_low_95": 0.65,
                "minimum_block_bootstrap_low_95": 0.65,
                "minimum_supported_fold_accuracy": 0.65,
                "minimum_supported_symbol_accuracy": 0.65,
                "minimum_paired_edge_low_95_vs_always_up": 0.0,
            },
        },
        "development_assets": development_assets,
        "holdout_assets": holdout_assets,
        "development_query_count": len(development_queries),
        "holdout_query_count": len(holdout_queries),
        "development_provenance": [
            dict(row) for row in development_provenance
        ],
        "holdout_provenance": [dict(row) for row in holdout_provenance],
        "online_feedback": online_audit,
        "frozen_feedback": frozen_audit,
    }


def audit_policy(
    result: Mapping[str, Any],
    *,
    group_by_symbol: Mapping[str, int],
) -> dict[str, Any]:
    events = [dict(row) for row in result["events"]]
    same_event_baselines = {
        "always_up": summarize_predictions(
            events,
            lambda _: True,
        ),
        "raw_analogue": summarize_predictions(
            events,
            lambda row: float(row["probability_up"]) >= 0.5,
        ),
    }
    blocks = market_block_summary(events)
    always_up_events = [
        row | {"direction_hit": row["actual"] == "up"}
        for row in events
    ]
    paired_edge = paired_block_bootstrap(
        events,
        always_up_events,
    )
    group_summaries = [
        summarize_events(
            [
                row
                for row in events
                if group_by_symbol[row["symbol"]] == group_index
            ]
        )
        for group_index in sorted(set(group_by_symbol.values()))
    ]
    summary = dict(result["summary"])
    evidence_gate = bool(
        int(summary["signals"]) >= 80
        and len(blocks["blocks"]) >= 20
        and float(summary["accuracy"] or 0.0) >= 0.70
        and float(summary["wilson_low_95"] or 0.0) >= 0.65
        and float(blocks["bootstrap_low_95"] or 0.0) >= 0.65
        and float(summary["worst_supported_fold_accuracy"] or 0.0) >= 0.65
        and float(summary["worst_supported_symbol_accuracy"] or 0.0) >= 0.65
        and float(paired_edge["bootstrap_low_95"] or 0.0) > 0.0
    )
    return {
        "config": dict(result["config"]),
        "summary": summary,
        "market_blocks": blocks,
        "same_event_baselines": same_event_baselines,
        "paired_edge_vs_always_up": paired_edge,
        "replication_groups": group_summaries,
        "legacy_admitted_70": _admitted_70(summary),
        "dependence_aware_admitted_70": evidence_gate,
        "events": events,
    }


def summarize_predictions(
    events: Sequence[Mapping[str, Any]],
    prediction: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any]:
    hits = sum(
        prediction(row) == (row["actual"] == "up")
        for row in events
    )
    signals = len(events)
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": hits / signals if signals else None,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def summarize_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hits = sum(bool(row["direction_hit"]) for row in events)
    signals = len(events)
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": hits / signals if signals else None,
        "wilson_low_95": _wilson_low(hits, signals) if signals else None,
    }


def market_block_summary(
    events: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    grouped = _market_blocks(events)
    block_rows = [
        {
            "market_block": block,
            "signals": len(rows),
            "accuracy": sum(bool(row["direction_hit"]) for row in rows)
            / len(rows),
        }
        for block, rows in sorted(grouped.items())
    ]
    accuracies = np.asarray(
        [float(row["accuracy"]) for row in block_rows],
        dtype=float,
    )
    low, high = _bootstrap_mean_interval(
        accuracies,
        samples=samples,
        seed=seed,
    )
    return {
        "block_hours": 24,
        "blocks": block_rows,
        "macro_accuracy": float(np.mean(accuracies)) if len(accuracies) else None,
        "bootstrap_low_95": low,
        "bootstrap_high_95": high,
    }


def paired_block_bootstrap(
    model_events: Sequence[Mapping[str, Any]],
    baseline_events: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if len(model_events) != len(baseline_events):
        raise ValueError("paired policies must have the same events")
    model_by_block = _market_blocks(model_events)
    baseline_by_block = _market_blocks(baseline_events)
    if model_by_block.keys() != baseline_by_block.keys():
        raise ValueError("paired policies must have the same market blocks")
    edge = np.asarray(
        [
            _event_accuracy(model_by_block[block])
            - _event_accuracy(baseline_by_block[block])
            for block in sorted(model_by_block)
        ],
        dtype=float,
    )
    low, high = _bootstrap_mean_interval(
        edge,
        samples=samples,
        seed=seed,
    )
    return {
        "market_blocks": len(edge),
        "macro_accuracy_edge": float(np.mean(edge)) if len(edge) else None,
        "bootstrap_low_95": low,
        "bootstrap_high_95": high,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Dynamic Feedback Expanded Replication Audit",
        "",
        "> Exploratory expanded audit, not a preregistered confirmation.",
        "",
        "## Result",
        "",
        (
            "| policy | signals | accuracy | Wilson low | market blocks | "
            "block-bootstrap low | always-up | paired edge low | admitted |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for label, key in (
        ("online feedback", "online_feedback"),
        ("frozen feedback", "frozen_feedback"),
    ):
        result = payload[key]
        summary = result["summary"]
        blocks = result["market_blocks"]
        baseline = result["same_event_baselines"]["always_up"]
        edge = result["paired_edge_vs_always_up"]
        lines.append(
            f"| {label} | {summary['signals']} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{len(blocks['blocks'])} | "
            f"{_percent(blocks['bootstrap_low_95'])} | "
            f"{_percent(baseline['accuracy'])} | "
            f"{_percent(edge['bootstrap_low_95'])} | "
            f"{'yes' if result['dependence_aware_admitted_70'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "The ordinary signal-level score is not sufficient because "
                "crypto assets co-move. The admission decision therefore "
                "requires a positive paired block-bootstrap edge over "
                "always-up, in addition to asset, fold, support, and Wilson "
                "gates."
            ),
            "",
            "## Reproduction",
            "",
            "```bash",
            (
                "python benchmarks/crypto_dynamic_feedback_replication_benchmark.py "
                "--output-json benchmarks/results/crypto/"
                "bybit_dynamic_feedback_replication.json "
                "--output-markdown benchmarks/results/crypto/"
                "bybit_dynamic_feedback_replication.md"
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _market_blocks(
    events: Sequence[Mapping[str, Any]],
) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in events:
        grouped[int(row["timestamp"]) // 86_400].append(row)
    return dict(grouped)


def _event_accuracy(events: Sequence[Mapping[str, Any]]) -> float:
    return sum(bool(row["direction_hit"]) for row in events) / len(events)


def _bootstrap_mean_interval(
    values: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    if not len(values):
        return None, None
    if samples <= 0:
        raise ValueError("samples must be positive")
    rng = np.random.default_rng(seed)
    indices = rng.integers(
        0,
        len(values),
        size=(samples, len(values)),
    )
    distribution = np.mean(values[indices], axis=1)
    return (
        float(np.quantile(distribution, 0.025)),
        float(np.quantile(distribution, 0.975)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the expanded dynamic-feedback replication."
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    development, development_provenance = load_development()
    holdout, holdout_provenance, group_by_symbol = load_expanded_holdout()
    payload = run_replication_audit(
        development,
        holdout,
        development_provenance=development_provenance,
        holdout_provenance=holdout_provenance,
        group_by_symbol=group_by_symbol,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    selected = payload["frozen_feedback"]
    summary = selected["summary"]
    print(
        f"frozen accuracy={_percent(summary['accuracy'])} "
        f"signals={summary['signals']} "
        f"market_blocks={len(selected['market_blocks']['blocks'])} "
        "dependence_aware_admitted_70="
        f"{selected['dependence_aware_admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
