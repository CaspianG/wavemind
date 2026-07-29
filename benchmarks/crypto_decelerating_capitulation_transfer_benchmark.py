from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    ConfirmationConfig,
    evaluate_config,
    load_confirmation_rows,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)


DEFAULT_PROTOCOL = (
    PROJECT_ROOT
    / "benchmarks"
    / "protocols"
    / "binance_decelerating_capitulation_transfer_v3.json"
)


def run_frozen_transfer(
    rows: Sequence[FeatureRow],
    *,
    protocol: Mapping[str, Any],
    protocol_sha256: str,
) -> dict[str, Any]:
    expected_symbols = sorted(str(value) for value in protocol["holdout_symbols"])
    actual_symbols = sorted({row.symbol for row in rows})
    if actual_symbols != expected_symbols:
        raise ValueError(
            "holdout symbols do not match the frozen protocol: "
            f"expected={expected_symbols}, actual={actual_symbols}"
        )

    frozen_rule = protocol["frozen_rule"]
    config = ConfirmationConfig(
        return_quantile=float(frozen_rule["return_quantile"]),
        oi_quantile=float(frozen_rule["open_interest_quantile"]),
        confirmation=str(frozen_rule["confirmation"]),
    )
    boundaries = tuple(
        (str(start), str(end))
        for start, end in protocol["fold_boundaries"]
    )
    folded = assign_calendar_folds(rows, boundaries=boundaries)
    evaluation = evaluate_config(
        folded,
        config=config,
        folds=tuple(range(len(boundaries))),
    )
    dependence = summarize_market_dependence(evaluation["events"])
    gate = evaluate_strict_gate(
        evaluation["summary"],
        dependence,
        protocol["strict_gate"],
    )
    return {
        "benchmark": "frozen decelerating-capitulation asset transfer",
        "protocol": str(protocol["protocol"]),
        "protocol_sha256": protocol_sha256,
        "holdout_symbols": expected_symbols,
        "frozen_rule": dict(frozen_rule),
        "fold_boundaries": [list(value) for value in boundaries],
        "evaluation": evaluation,
        "dependence_control": dependence,
        "strict_gate": gate,
    }


def summarize_market_dependence(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    blocks: defaultdict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        blocks[int(event["timestamp"]) // 86_400].append(event)

    block_rows = [
        _dependence_row(day, block_events)
        for day, block_events in sorted(blocks.items())
    ]
    episodes: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    previous_day: int | None = None
    for day, block_events in sorted(blocks.items()):
        if previous_day is not None and day - previous_day > 2:
            episodes.append(current)
            current = []
        current.extend(block_events)
        previous_day = day
    if current:
        episodes.append(current)

    episode_rows = [
        _dependence_row(index, episode)
        for index, episode in enumerate(episodes)
    ]
    return {
        "market_blocks": _summarize_dependence_rows(block_rows),
        "market_episodes": _summarize_dependence_rows(episode_rows),
        "block_rows": block_rows,
        "episode_rows": episode_rows,
        "signals_per_episode": (
            len(events) / len(episode_rows) if episode_rows else None
        ),
    }


def evaluate_strict_gate(
    summary: Mapping[str, Any],
    dependence: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    supported_folds = [
        row
        for row in summary["by_fold"]
        if int(row["signals"]) >= int(gate["minimum_fold_support"])
    ]
    supported_assets = [
        row
        for row in summary["by_symbol"]
        if int(row["signals"]) >= int(gate["minimum_asset_support"])
    ]
    episodes = dependence["market_episodes"]
    checks = {
        "signals": int(summary["signals"]) >= int(gate["minimum_signals"]),
        "direction_accuracy": (
            float(summary["accuracy"] or 0.0)
            >= float(gate["minimum_direction_accuracy"])
        ),
        "wilson_low_95": (
            float(summary["wilson_low_95"] or 0.0)
            >= float(gate["minimum_wilson_low_95"])
        ),
        "supported_folds": (
            len(supported_folds) >= int(gate["minimum_supported_folds"])
        ),
        "supported_fold_accuracy": bool(supported_folds)
        and min(float(row["accuracy"]) for row in supported_folds)
        >= float(gate["minimum_supported_fold_accuracy"]),
        "supported_assets": (
            len(supported_assets) >= int(gate["minimum_supported_assets"])
        ),
        "supported_asset_accuracy": bool(supported_assets)
        and min(float(row["accuracy"]) for row in supported_assets)
        >= float(gate["minimum_supported_asset_accuracy"]),
        "market_episodes": (
            int(episodes["observations"])
            >= int(gate["minimum_market_episodes"])
        ),
        "market_episode_accuracy": (
            float(episodes["accuracy"] or 0.0)
            >= float(gate["minimum_market_episode_accuracy"])
        ),
        "market_episode_wilson_low_95": (
            float(episodes["wilson_low_95"] or 0.0)
            >= float(gate["minimum_market_episode_wilson_low_95"])
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": dict(gate),
        "supported_fold_count": len(supported_folds),
        "supported_asset_count": len(supported_assets),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload["evaluation"]["summary"]
    blocks = payload["dependence_control"]["market_blocks"]
    episodes = payload["dependence_control"]["market_episodes"]
    lines = [
        "# Frozen Decelerating-Capitulation Transfer",
        "",
        "This is a one-read asset-disjoint holdout. The protocol was committed "
        "before the eight holdout assets were downloaded or evaluated.",
        "",
        f"- protocol SHA-256: `{payload['protocol_sha256']}`;",
        "- assets: " + ", ".join(payload["holdout_symbols"]) + ";",
        "- prediction: rebound over the next 24 hours;",
        "- overlap: one signal per asset until the 24h target matures.",
        "",
        "| view | observations | accuracy | Wilson low 95% |",
        "|---|---:|---:|---:|",
        _summary_row("asset signals", summary, count_key="signals"),
        _summary_row("UTC market blocks", blocks),
        _summary_row("market episodes", episodes),
        "",
        "Strict 70% gate: "
        + ("**passed**" if payload["strict_gate"]["passed"] else "**rejected**"),
        "",
        "## Fold Stability",
        "",
        "| fold | signals | accuracy | Wilson low 95% |",
        "|---:|---:|---:|---:|",
    ]
    for row in summary["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            "## Asset Stability",
            "",
            "| asset | signals | accuracy | Wilson low 95% |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in summary["by_symbol"]:
        lines.append(
            f"| {row['symbol']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            "No threshold, asset, direction, fold, or gate is changed after "
            "the holdout is read. A failed gate remains part of the report.",
            "",
        ]
    )
    return "\n".join(lines)


def load_protocol(path: str | Path) -> tuple[dict[str, Any], str]:
    protocol_path = Path(path)
    content = protocol_path.read_bytes()
    return json.loads(content), hashlib.sha256(content).hexdigest()


def _dependence_row(
    group: int,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    returns = [float(event["future_return_bps"]) for event in events]
    return {
        "group": group,
        "signals": len(events),
        "symbols": sorted({str(event["symbol"]) for event in events}),
        "median_future_return_bps": median(returns),
        "direction_hit": median(returns) > 0.0,
    }


def _summarize_dependence_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    observations = len(rows)
    hits = sum(int(row["direction_hit"]) for row in rows)
    return {
        "observations": observations,
        "hits": hits,
        "accuracy": hits / observations if observations else None,
        "wilson_low_95": (
            _wilson_low(hits, observations) if observations else None
        ),
    }


def _summary_row(
    label: str,
    summary: Mapping[str, Any],
    *,
    count_key: str = "observations",
) -> str:
    return (
        f"| {label} | {summary[count_key]} | "
        f"{_percent(summary['accuracy'])} | "
        f"{_percent(summary['wilson_low_95'])} |"
    )


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen asset-disjoint rebound protocol."
    )
    parser.add_argument("--bundle", type=Path, action="append", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    protocol, protocol_sha256 = load_protocol(args.protocol)
    rows = load_confirmation_rows(args.bundle, cache_path=args.cache)
    payload = run_frozen_transfer(
        rows,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
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
    summary = payload["evaluation"]["summary"]
    print(
        f"signals={summary['signals']} "
        f"accuracy={_percent(summary['accuracy'])} "
        f"strict_gate={payload['strict_gate']['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
