from __future__ import annotations

import pytest

from wavemind.evaluation_statistics import (
    binary_sample_size,
    holm_adjust,
    paired_cluster_bootstrap,
    plan_primary_metrics,
)


def test_holm_adjust_preserves_ordered_step_down_constraints():
    adjusted = holm_adjust([0.01, 0.04, 0.03])
    assert adjusted == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([]) == []


def test_binary_sample_size_rejects_impossible_effect():
    with pytest.raises(ValueError, match="exceeds metric headroom"):
        binary_sample_size(
            baseline_rate=0.95,
            minimum_detectable_effect=0.10,
            alpha=0.05,
            power=0.80,
        )


def test_primary_metric_plan_declares_cluster_units_and_mde():
    plans = plan_primary_metrics(
        [
            {
                "id": "workflow-pass-at-1",
                "cluster_unit": "task",
                "baseline_rate": 0.35,
                "minimum_detectable_effect": 0.10,
            },
            {
                "id": "memory-answer-quality",
                "cluster_unit": "conversation",
                "baseline_rate": 0.45,
                "minimum_detectable_effect": 0.08,
            },
        ]
    )
    assert len(plans) == 2
    assert all(plan["required_independent_clusters"] > 0 for plan in plans)
    assert all(plan["per_comparison_alpha"] == 0.025 for plan in plans)


def test_paired_bootstrap_resamples_clusters_not_correlated_rows():
    rows = [
        {"conversation": "a", "baseline": 0.0, "treatment": 1.0},
        {"conversation": "a", "baseline": 0.0, "treatment": 1.0},
        {"conversation": "b", "baseline": 1.0, "treatment": 1.0},
        {"conversation": "c", "baseline": 1.0, "treatment": 0.0},
    ]
    first = paired_cluster_bootstrap(
        rows,
        cluster_key="conversation",
        baseline_key="baseline",
        treatment_key="treatment",
        repeats=500,
        seed=7,
    )
    second = paired_cluster_bootstrap(
        rows,
        cluster_key="conversation",
        baseline_key="baseline",
        treatment_key="treatment",
        repeats=500,
        seed=7,
    )
    assert first == second
    assert first["cluster_count"] == 3
    assert first["row_count"] == 4
    assert first["mean_difference"] == pytest.approx(0.0)


def test_paired_bootstrap_rejects_unpaired_or_unclustered_rows():
    with pytest.raises(ValueError, match="mandatory field"):
        paired_cluster_bootstrap(
            [{"cluster": "a", "baseline": 0.0}],
            cluster_key="cluster",
            baseline_key="baseline",
            treatment_key="treatment",
        )
    with pytest.raises(ValueError, match="at least two clusters"):
        paired_cluster_bootstrap(
            [{"cluster": "a", "baseline": 0.0, "treatment": 1.0}],
            cluster_key="cluster",
            baseline_key="baseline",
            treatment_key="treatment",
        )
