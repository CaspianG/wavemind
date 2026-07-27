from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from benchmarks.crypto_bybit_capitulation_benchmark import (
    ANALOGUE_FEATURES,
)
from benchmarks.crypto_capitulation_analogue_benchmark import (
    AnalogueConfig,
    _knn_probabilities,
    evaluate_analogue_memory,
    run_analogue_transfer_benchmark,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def test_knn_probability_uses_nearest_outcomes() -> None:
    history = np.asarray([[0.0], [1.0], [10.0], [11.0]])
    labels = np.asarray([0.0, 0.0, 1.0, 1.0])
    queries = np.asarray([[0.2], [10.2]])

    probability = _knn_probabilities(
        history,
        labels,
        queries,
        neighbors=2,
    )

    assert probability[0] < 0.5
    assert probability[1] > 0.5


def test_analogue_memory_uses_only_matured_training_assets() -> None:
    training = _rows(("AAAUSDT", "BBBUSDT"), flip=False)
    holdout = _rows(("CCCUSDT", "DDDUSDT"), flip=False)
    result = evaluate_analogue_memory(
        training,
        holdout,
        config=AnalogueConfig(confidence_margin=0.0),
    )

    evaluated = [
        audit
        for audit in result["fold_audits"]
        if audit["status"] == "evaluated"
    ]
    assert evaluated
    assert result["summary"]["signals"] > 0
    assert {event["symbol"] for event in result["events"]} <= {
        "CCCUSDT",
        "DDDUSDT",
    }


def test_transfer_keeps_asset_sets_disjoint_and_selects_an_ablation() -> None:
    development = _rows(("AAAUSDT", "BBBUSDT"), flip=False)
    holdout = _rows(("CCCUSDT", "DDDUSDT"), flip=False)
    payload = run_analogue_transfer_benchmark(
        development,
        holdout,
        development_provenance={"dataset_sha256": "dev"},
        holdout_provenance={"dataset_sha256": "holdout"},
        configs=(AnalogueConfig(confidence_margin=0.0),),
    )

    assert payload["development_assets"] == ["AAAUSDT", "BBBUSDT"]
    assert payload["holdout_assets"] == ["CCCUSDT", "DDDUSDT"]
    assert payload["selected_config"]["neighbors"] == 15
    if payload["selection_underpowered"]:
        assert payload["selected_config"]["field_weight"] == 0.0


def _rows(symbols: tuple[str, ...], *, flip: bool) -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    start = _timestamp("2023-01-01")
    end = _timestamp("2026-07-27")
    timestamp = start
    index = 0
    while timestamp < end:
        for symbol_index, symbol in enumerate(symbols):
            event = index % 19 == symbol_index
            direction = (index // 19 + symbol_index) % 2 == 0
            if flip:
                direction = not direction
            features = {
                name: float((index + offset) % 17)
                for offset, name in enumerate(ANALOGUE_FEATURES)
            }
            features["return_12"] = -1000.0 if event else 100.0
            features["oi_change_1"] = -500.0 if event else 100.0
            features["deceleration"] = 100.0
            row = FeatureRow(
                symbol=symbol,
                timestamp=timestamp,
                target_timestamp=timestamp + 24 * 60 * 60,
                fold_index=-1,
                features=features,
                future_return_bps=100.0 if direction else -100.0,
            )
            rows.append(replace(row))
        timestamp += 24 * 60 * 60
        index += 1
    return rows


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
