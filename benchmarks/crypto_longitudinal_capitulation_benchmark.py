from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_accuracy_gate import _wilson_low  # noqa: E402
from benchmarks.crypto_bybit_capitulation_benchmark import (  # noqa: E402
    HORIZONS,
    BybitInstrument,
    _percent,
    build_feature_rows,
    load_or_download_dataset,
)
from benchmarks.crypto_capitulation_asset_transfer_benchmark import (  # noqa: E402
    FROZEN_TRANSFER_CONFIG,
)
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    evaluate_config,
)
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)


PROTOCOL_PATH = PROJECT_ROOT / (
    "benchmarks/protocols/bybit_longitudinal_capitulation_v1.json"
)
DATASET_GROUPS = (
    (
        (
            "BTCUSDT",
            "ETHUSDT",
            "IOSTUSDT",
            "SHIB1000USDT",
            "ALICEUSDT",
            "C98USDT",
            "SLPUSDT",
            "CHRUSDT",
        ),
        "data/bybit-longitudinal-capitulation-part1-v1.json.gz",
    ),
    (
        (
            "STORJUSDT",
            "TLMUSDT",
            "YGGUSDT",
            "CROUSDT",
            "ANKRUSDT",
            "ILVUSDT",
            "ZENUSDT",
            "CVCUSDT",
        ),
        "data/bybit-longitudinal-capitulation-part2-v1.json.gz",
    ),
    (
        (
            "BICOUSDT",
            "GRTUSDT",
            "BSVUSDT",
            "DUSKUSDT",
            "XMRUSDT",
            "PEOPLEUSDT",
            "RVNUSDT",
            "HNTUSDT",
        ),
        "data/bybit-longitudinal-capitulation-part3-v1.json.gz",
    ),
)
LONGITUDINAL_FOLDS = (
    ("2022-01-01", "2022-04-01"),
    ("2022-04-01", "2022-07-01"),
    ("2022-07-01", "2022-10-01"),
    ("2022-10-01", "2023-01-01"),
    ("2023-01-01", "2023-04-01"),
    ("2023-04-01", "2023-07-01"),
    ("2023-07-01", "2023-10-01"),
    ("2023-10-01", "2024-01-01"),
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-01"),
    ("2024-10-01", "2025-01-01"),
    ("2025-01-01", "2025-04-01"),
    ("2025-04-01", "2025-07-01"),
    ("2025-07-01", "2025-10-01"),
    ("2025-10-01", "2026-01-01"),
    ("2026-01-01", "2026-04-01"),
    ("2026-04-01", "2026-07-01"),
    ("2026-07-01", "2026-07-27"),
)
MIN_EPISODE_SUPPORT = 40
MIN_SLICE_SUPPORT = 5


def load_longitudinal_dataset(
    *,
    protocol_path: str | Path = PROTOCOL_PATH,
) -> tuple[list[BybitInstrument], list[dict[str, Any]], dict[str, Any]]:
    protocol = json.loads(
        Path(protocol_path).read_text(encoding="utf-8")
    )
    instruments: list[BybitInstrument] = []
    provenance: list[dict[str, Any]] = []
    expected = set(protocol["symbols"])
    configured = {
        symbol
        for symbols, _ in DATASET_GROUPS
        for symbol in symbols
    }
    if configured != expected:
        raise ValueError("dataset groups do not match the frozen protocol")
    for symbols, cache_path in DATASET_GROUPS:
        rows, source = load_or_download_dataset(
            symbols,
            cache_path=cache_path,
            start=protocol["source"]["start"],
            end=protocol["source"]["end"],
        )
        instruments.extend(rows)
        provenance.append(source)
    if {row.symbol for row in instruments} != expected:
        raise ValueError("loaded symbols do not match the frozen protocol")
    return instruments, provenance, protocol


def run_longitudinal_benchmark(
    instruments: Sequence[BybitInstrument],
    *,
    provenance: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for label, horizon in HORIZONS.items():
        folded = assign_calendar_folds(
            build_feature_rows(instruments, horizon=horizon),
            boundaries=LONGITUDINAL_FOLDS,
        )
        evaluated = evaluate_config(
            folded,
            config=FROZEN_TRANSFER_CONFIG,
            folds=range(len(LONGITUDINAL_FOLDS)),
        )
        episode_audit = market_episode_audit(evaluated["events"])
        baseline = unconditional_market_baseline(folded)
        evaluated["market_episode_audit"] = episode_audit
        evaluated["unconditional_market_baseline"] = baseline
        evaluated["episode_uplift_vs_unconditional_up"] = (
            float(episode_audit["accuracy"])
            - float(baseline["always_up_accuracy"])
        )
        evaluated["episode_admitted_70"] = episode_admitted_70(
            evaluated,
        )
        results[label] = evaluated

    return {
        "benchmark": "preregistered longitudinal post-capitulation replication",
        "protocol": dict(protocol),
        "protocol_path": str(
            Path(PROTOCOL_PATH).relative_to(PROJECT_ROOT)
        ).replace("\\", "/"),
        "provenance": [dict(row) for row in provenance],
        "symbols": sorted(row.symbol for row in instruments),
        "fold_boundaries": [list(row) for row in LONGITUDINAL_FOLDS],
        "horizons": results,
        "primary_24h_episode_admitted_70": results["24h"][
            "episode_admitted_70"
        ],
        "all_horizons_episode_admitted_70": all(
            row["episode_admitted_70"] for row in results.values()
        ),
    }


def market_episode_audit(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda row: int(row["timestamp"]))
    utc_blocks: defaultdict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in ordered:
        utc_blocks[int(row["timestamp"]) // 86_400].append(row)

    episodes: list[list[Mapping[str, Any]]] = []
    for row in ordered:
        if (
            not episodes
            or int(row["timestamp"])
            - int(episodes[-1][-1]["timestamp"])
            > 86_400
        ):
            episodes.append([row])
        else:
            episodes[-1].append(row)

    episode_rows = [
        _episode_row(index, rows)
        for index, rows in enumerate(episodes)
    ]
    hits = sum(bool(row["direction_hit"]) for row in episode_rows)
    by_fold = _group_episode_rows(episode_rows, "fold_index")
    supported_folds = [
        row for row in by_fold if int(row["episodes"]) >= MIN_SLICE_SUPPORT
    ]
    block_accuracy = [
        sum(bool(row["direction_hit"]) for row in rows) / len(rows)
        for _, rows in sorted(utc_blocks.items())
    ]
    return {
        "episodes": len(episode_rows),
        "hits": hits,
        "accuracy": hits / len(episode_rows) if episode_rows else None,
        "wilson_low_95": (
            _wilson_low(hits, len(episode_rows)) if episode_rows else None
        ),
        "utc_market_blocks": len(utc_blocks),
        "utc_block_macro_signal_accuracy": (
            float(np.mean(block_accuracy)) if block_accuracy else None
        ),
        "by_fold": by_fold,
        "worst_supported_fold_accuracy": min(
            (
                float(row["accuracy"])
                for row in supported_folds
            ),
            default=None,
        ),
        "rows": episode_rows,
    }


def unconditional_market_baseline(
    rows: Sequence[Any],
) -> dict[str, Any]:
    by_day: defaultdict[int, list[Any]] = defaultdict(list)
    for row in rows:
        if int(row.fold_index) >= 0 and int(row.timestamp) % 86_400 == 0:
            by_day[int(row.timestamp) // 86_400].append(row)
    outcomes = [
        float(np.median([row.future_return_bps for row in group])) > 0.0
        for _, group in sorted(by_day.items())
        if group
    ]
    up_days = sum(outcomes)
    return {
        "independent_days": len(outcomes),
        "up_days": up_days,
        "always_up_accuracy": (
            up_days / len(outcomes) if outcomes else None
        ),
        "majority_class_accuracy": (
            max(up_days, len(outcomes) - up_days) / len(outcomes)
            if outcomes
            else None
        ),
    }


def episode_admitted_70(result: Mapping[str, Any]) -> bool:
    episode = result["market_episode_audit"]
    signal = result["summary"]
    return bool(
        int(episode["episodes"]) >= MIN_EPISODE_SUPPORT
        and float(episode["accuracy"] or 0.0) >= 0.70
        and float(episode["wilson_low_95"] or 0.0) >= 0.65
        and float(episode["worst_supported_fold_accuracy"] or 0.0) >= 0.65
        and float(signal["worst_supported_symbol_accuracy"] or 0.0) >= 0.65
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Preregistered Longitudinal Capitulation Replication",
        "",
        (
            "The frozen rebound rule is evaluated on 24 previously unused "
            "Bybit assets from 2021-03-15 through 2026-07-27. The protocol was "
            "committed before the dataset was downloaded."
        ),
        "",
        f"- protocol: `{payload['protocol_path']}`;",
        f"- assets: {len(payload['symbols'])};",
        "- source interval: completed 4h candles and causal 4h OI;",
        "",
        (
            "| horizon | asset signals | signal accuracy | market episodes | "
            "episode accuracy | episode Wilson low | unconditional up | "
            "episode uplift | admitted |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for label, result in payload["horizons"].items():
        signal = result["summary"]
        episode = result["market_episode_audit"]
        baseline = result["unconditional_market_baseline"]
        lines.append(
            f"| {label} | {signal['signals']} | "
            f"{_percent(signal['accuracy'])} | "
            f"{episode['episodes']} | "
            f"{_percent(episode['accuracy'])} | "
            f"{_percent(episode['wilson_low_95'])} | "
            f"{_percent(baseline['always_up_accuracy'])} | "
            f"{_percent(result['episode_uplift_vs_unconditional_up'])} | "
            f"{'yes' if result['episode_admitted_70'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## 24h Episode Folds",
            "",
            "| fold | episodes | accuracy | Wilson low 95% |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in payload["horizons"]["24h"]["market_episode_audit"]["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['episodes']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            (
                "The asset-signal count is not treated as an independent "
                "sample. Admission is decided on globally clustered market "
                "episodes and remains false whenever support, Wilson, time, "
                "or asset stability fails."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _episode_row(
    index: int,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    up_fraction = sum(
        bool(row["direction_hit"]) for row in rows
    ) / len(rows)
    fold_counts: defaultdict[int, int] = defaultdict(int)
    for row in rows:
        fold_counts[int(row["fold_index"])] += 1
    fold_index = max(
        sorted(fold_counts),
        key=lambda value: fold_counts[value],
    )
    return {
        "episode_index": index,
        "fold_index": fold_index,
        "start_timestamp": min(int(row["timestamp"]) for row in rows),
        "end_timestamp": max(int(row["timestamp"]) for row in rows),
        "asset_signals": len(rows),
        "asset_up_fraction": up_fraction,
        "direction_hit": up_fraction > 0.5,
    }


def _group_episode_rows(
    rows: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    output = []
    for value in sorted({int(row[field]) for row in rows}):
        selected = [row for row in rows if int(row[field]) == value]
        hits = sum(bool(row["direction_hit"]) for row in selected)
        output.append(
            {
                field: value,
                "episodes": len(selected),
                "hits": hits,
                "accuracy": hits / len(selected),
                "wilson_low_95": _wilson_low(hits, len(selected)),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the preregistered longitudinal Bybit replication."
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    instruments, provenance, protocol = load_longitudinal_dataset()
    payload = run_longitudinal_benchmark(
        instruments,
        provenance=provenance,
        protocol=protocol,
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
    primary = payload["horizons"]["24h"]
    episode = primary["market_episode_audit"]
    print(
        f"24h episodes={episode['episodes']} "
        f"accuracy={_percent(episode['accuracy'])} "
        f"Wilson={_percent(episode['wilson_low_95'])} "
        f"admitted={primary['episode_admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
