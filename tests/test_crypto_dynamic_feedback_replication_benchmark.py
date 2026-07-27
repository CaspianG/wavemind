from __future__ import annotations

from benchmarks.crypto_dynamic_feedback_replication_benchmark import (
    _bootstrap_mean_interval,
    audit_policy,
    market_block_summary,
    paired_block_bootstrap,
    summarize_predictions,
)


def test_market_block_summary_clusters_correlated_assets() -> None:
    events = [
        _event("AAA", 100, hit=True),
        _event("BBB", 200, hit=True),
        _event("CCC", 86_500, hit=False),
    ]

    result = market_block_summary(events, samples=200, seed=1)

    assert len(result["blocks"]) == 2
    assert result["macro_accuracy"] == 0.5


def test_paired_bootstrap_compares_the_same_market_blocks() -> None:
    model = [
        _event("AAA", 100, hit=True),
        _event("BBB", 86_500, hit=True),
    ]
    baseline = [
        _event("AAA", 100, hit=False),
        _event("BBB", 86_500, hit=False),
    ]

    result = paired_block_bootstrap(
        model,
        baseline,
        samples=200,
        seed=1,
    )

    assert result["market_blocks"] == 2
    assert result["bootstrap_low_95"] == 1.0


def test_same_event_baseline_uses_actual_direction() -> None:
    events = [
        _event("AAA", 100, hit=False, actual="up"),
        _event("BBB", 200, hit=True, actual="down"),
    ]

    result = summarize_predictions(events, lambda _: True)

    assert result["signals"] == 2
    assert result["hits"] == 1
    assert result["accuracy"] == 0.5


def test_audit_rejects_correlated_small_sample() -> None:
    events = [
        _event(f"S{i}", 100, hit=True, actual="up")
        for i in range(80)
    ]
    result = {
        "config": {},
        "summary": {
            "signals": 80,
            "hits": 80,
            "accuracy": 1.0,
            "wilson_low_95": 0.95,
            "worst_supported_fold_accuracy": 1.0,
            "worst_supported_symbol_accuracy": 1.0,
            "by_fold": [],
            "by_symbol": [],
        },
        "events": events,
    }

    audited = audit_policy(
        result,
        group_by_symbol={f"S{i}": 0 for i in range(80)},
    )

    assert not audited["dependence_aware_admitted_70"]
    assert len(audited["market_blocks"]["blocks"]) == 1


def test_bootstrap_requires_positive_sample_count() -> None:
    try:
        _bootstrap_mean_interval(
            __import__("numpy").asarray([1.0]),
            samples=0,
            seed=1,
        )
    except ValueError as exc:
        assert str(exc) == "samples must be positive"
    else:
        raise AssertionError("expected ValueError")


def _event(
    symbol: str,
    timestamp: int,
    *,
    hit: bool,
    actual: str = "down",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "actual": actual,
        "direction_hit": hit,
        "probability_up": 0.9,
    }
