from __future__ import annotations

from benchmarks.crypto_dynamic_feedback_benchmark import (
    AnalogueQuery,
    FeedbackConfig,
    _decayed_accuracy,
    _matching_bucket,
    evaluate_feedback_router,
)


def test_decayed_accuracy_uses_only_supplied_matured_history() -> None:
    history = [
        _query(timestamp=100, target=200, probability=0.9, actual=True),
        _query(timestamp=200, target=300, probability=0.9, actual=False),
    ]
    accuracy, support = _decayed_accuracy(
        history[:1],
        query_timestamp=400,
        half_life_days=60.0,
        prior_strength=2.0,
    )

    assert support > 0.0
    assert accuracy > 0.5


def test_trend_bucket_does_not_mix_opposite_regimes() -> None:
    query = _query(
        timestamp=500,
        target=600,
        probability=0.9,
        actual=True,
        return_36=-100.0,
    )
    history = [
        _query(
            timestamp=100,
            target=200,
            probability=0.9,
            actual=True,
            return_36=-50.0,
        ),
        _query(
            timestamp=200,
            target=300,
            probability=0.9,
            actual=False,
            return_36=50.0,
        ),
    ]

    matched = _matching_bucket(history, query, "trend")

    assert len(matched) == 1
    assert matched[0].return_36 < 0.0


def test_feedback_router_never_uses_unmatured_test_outcome() -> None:
    test = [
        _query(timestamp=100, target=300, probability=0.9, actual=False),
        _query(timestamp=200, target=400, probability=0.9, actual=True),
    ]
    result = evaluate_feedback_router(
        (),
        test,
        config=FeedbackConfig(
            prior_strength=2.0,
            reliability_gate=0.0,
        ),
        update_with_test=True,
    )

    assert result["events"][0]["effective_samples"] == 0.0
    assert result["events"][1]["effective_samples"] == 0.0


def test_low_confidence_outcome_still_trains_later_feedback() -> None:
    test = [
        _query(timestamp=100, target=150, probability=0.6, actual=True),
        _query(timestamp=200, target=300, probability=0.9, actual=True),
    ]
    result = evaluate_feedback_router(
        (),
        test,
        config=FeedbackConfig(
            prior_strength=2.0,
            reliability_gate=0.0,
        ),
        update_with_test=True,
    )

    assert len(result["events"]) == 1
    assert result["events"][0]["effective_samples"] > 0.0


def _query(
    *,
    timestamp: int,
    target: int,
    probability: float,
    actual: bool,
    return_36: float = -100.0,
) -> AnalogueQuery:
    return AnalogueQuery(
        fold_index=0,
        symbol="TESTUSDT",
        timestamp=timestamp,
        target_timestamp=target,
        probability_up=probability,
        actual_up=actual,
        return_36=return_36,
    )
