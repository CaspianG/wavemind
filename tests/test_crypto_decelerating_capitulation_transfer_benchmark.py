from __future__ import annotations

import pytest

from benchmarks.crypto_decelerating_capitulation_transfer_benchmark import (
    evaluate_strict_gate,
    fingerprint_files,
    run_frozen_transfer,
    summarize_market_dependence,
)


def _event(
    *,
    timestamp: int,
    symbol: str,
    future_return_bps: float,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "future_return_bps": future_return_bps,
    }


def test_market_dependence_collapses_days_and_nearby_episodes() -> None:
    events = [
        _event(timestamp=0, symbol="AAAUSDT", future_return_bps=100.0),
        _event(timestamp=0, symbol="BBBUSDT", future_return_bps=200.0),
        _event(timestamp=86_400, symbol="AAAUSDT", future_return_bps=-50.0),
        _event(timestamp=4 * 86_400, symbol="AAAUSDT", future_return_bps=25.0),
    ]

    summary = summarize_market_dependence(events)

    assert summary["market_blocks"]["observations"] == 3
    assert summary["market_blocks"]["hits"] == 2
    assert summary["market_episodes"]["observations"] == 2
    assert summary["market_episodes"]["hits"] == 2


def test_strict_gate_requires_every_predeclared_check() -> None:
    slice_row = {
        "signals": 10,
        "accuracy": 0.8,
        "wilson_low_95": 0.6,
    }
    summary = {
        "signals": 80,
        "accuracy": 0.8,
        "wilson_low_95": 0.7,
        "by_fold": [dict(slice_row, fold_index=index) for index in range(4)],
        "by_symbol": [
            dict(slice_row, symbol=f"ASSET{index}") for index in range(6)
        ],
    }
    dependence = {
        "market_episodes": {
            "observations": 20,
            "accuracy": 0.75,
            "wilson_low_95": 0.55,
        }
    }
    thresholds = {
        "minimum_signals": 40,
        "minimum_direction_accuracy": 0.7,
        "minimum_wilson_low_95": 0.65,
        "minimum_supported_folds": 4,
        "minimum_fold_support": 5,
        "minimum_supported_fold_accuracy": 0.65,
        "minimum_supported_assets": 6,
        "minimum_asset_support": 5,
        "minimum_supported_asset_accuracy": 0.6,
        "minimum_market_episodes": 15,
        "minimum_market_episode_accuracy": 0.65,
        "minimum_market_episode_wilson_low_95": 0.5,
    }

    accepted = evaluate_strict_gate(summary, dependence, thresholds)
    rejected = evaluate_strict_gate(
        summary,
        {
            "market_episodes": dependence["market_episodes"]
            | {"accuracy": 0.6}
        },
        thresholds,
    )

    assert accepted["passed"]
    assert not rejected["passed"]
    assert not rejected["checks"]["market_episode_accuracy"]


def test_frozen_transfer_rejects_a_different_asset_set() -> None:
    protocol = {
        "holdout_symbols": ["EXPECTEDUSDT"],
    }

    with pytest.raises(ValueError, match="holdout symbols"):
        run_frozen_transfer(
            [],
            protocol=protocol,
            protocol_sha256="abc",
        )


def test_fingerprint_files_is_content_bound_and_name_sorted(tmp_path) -> None:
    second = tmp_path / "b.json.gz"
    first = tmp_path / "a.json.gz"
    second.write_bytes(b"second")
    first.write_bytes(b"first")

    fingerprints = fingerprint_files([second, first])

    assert [row["name"] for row in fingerprints] == [
        "a.json.gz",
        "b.json.gz",
    ]
    assert fingerprints[0]["bytes"] == 5
    assert fingerprints[0]["sha256"] == (
        "a7937b64b8caa58f03721bb6bacf5c78"
        "cb235febe0e70b1b84cd99541461a08e"
    )
