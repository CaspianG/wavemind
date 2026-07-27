from __future__ import annotations

from dataclasses import replace

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
from benchmarks.crypto_longitudinal_capitulation_benchmark import (
    episode_admitted_70,
    market_episode_audit,
    unconditional_market_baseline,
)


def test_market_episode_audit_merges_cross_asset_event_cluster() -> None:
    events = [
        _event("AAA", 100, hit=True, fold=0),
        _event("BBB", 200, hit=True, fold=0),
        _event("CCC", 80_000, hit=False, fold=1),
        _event("DDD", 200_000, hit=True, fold=2),
    ]

    result = market_episode_audit(events)

    assert result["episodes"] == 2
    assert result["hits"] == 2
    assert result["accuracy"] == 1.0
    assert result["rows"][0]["asset_signals"] == 3


def test_unconditional_market_baseline_uses_one_daily_panel() -> None:
    template = FeatureRow(
        symbol="AAA",
        timestamp=0,
        target_timestamp=86_400,
        fold_index=0,
        features={},
        future_return_bps=100.0,
    )
    rows = [
        template,
        replace(template, symbol="BBB", future_return_bps=-10.0),
        replace(
            template,
            timestamp=86_400,
            target_timestamp=172_800,
            future_return_bps=-100.0,
        ),
        replace(
            template,
            symbol="BBB",
            timestamp=86_400,
            target_timestamp=172_800,
            future_return_bps=-20.0,
        ),
    ]

    result = unconditional_market_baseline(rows)

    assert result["independent_days"] == 2
    assert result["up_days"] == 1
    assert result["always_up_accuracy"] == 0.5


def test_episode_gate_rejects_insufficient_market_episodes() -> None:
    result = {
        "market_episode_audit": {
            "episodes": 39,
            "accuracy": 0.9,
            "wilson_low_95": 0.8,
            "worst_supported_fold_accuracy": 0.8,
        },
        "summary": {
            "worst_supported_symbol_accuracy": 0.8,
        },
    }

    assert not episode_admitted_70(result)


def _event(
    symbol: str,
    timestamp: int,
    *,
    hit: bool,
    fold: int,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "fold_index": fold,
        "direction_hit": hit,
    }
