from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import NormalDist
from typing import Any, Mapping, Sequence


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    if not p_values:
        return []
    checked = []
    for value in p_values:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("p-values must be between zero and one")
        checked.append(numeric)
    ordered = sorted(enumerate(checked), key=lambda item: item[1])
    adjusted = [0.0] * len(checked)
    running = 0.0
    total = len(checked)
    for rank, (index, value) in enumerate(ordered):
        candidate = min(1.0, (total - rank) * value)
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def binary_sample_size(
    *,
    baseline_rate: float,
    minimum_detectable_effect: float,
    alpha: float,
    power: float,
) -> int:
    baseline = float(baseline_rate)
    effect = float(minimum_detectable_effect)
    if not 0.0 < baseline < 1.0:
        raise ValueError("baseline_rate must be between zero and one")
    if not 0.0 < effect < 1.0 - baseline:
        raise ValueError("minimum_detectable_effect exceeds metric headroom")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    if not 0.0 < power < 1.0:
        raise ValueError("power must be between zero and one")
    alternative = baseline + effect
    pooled = (baseline + alternative) / 2.0
    z_alpha = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    z_power = NormalDist().inv_cdf(power)
    numerator = (
        z_alpha * math.sqrt(2.0 * pooled * (1.0 - pooled))
        + z_power
        * math.sqrt(baseline * (1.0 - baseline) + alternative * (1.0 - alternative))
    ) ** 2
    return math.ceil(numerator / (effect**2))


def plan_primary_metrics(
    specifications: Sequence[Mapping[str, Any]],
    *,
    familywise_alpha: float = 0.05,
    power: float = 0.80,
) -> list[dict[str, Any]]:
    if not specifications:
        raise ValueError("at least one primary metric specification is required")
    corrected_alpha = float(familywise_alpha) / len(specifications)
    plans = []
    for specification in specifications:
        metric_id = str(specification.get("id", ""))
        cluster_unit = str(specification.get("cluster_unit", ""))
        if not metric_id or not cluster_unit:
            raise ValueError("each primary metric requires id and cluster_unit")
        baseline = float(specification["baseline_rate"])
        effect = float(specification["minimum_detectable_effect"])
        plans.append(
            {
                "id": metric_id,
                "cluster_unit": cluster_unit,
                "baseline_rate": baseline,
                "minimum_detectable_effect": effect,
                "target_rate": baseline + effect,
                "familywise_alpha": float(familywise_alpha),
                "per_comparison_alpha": corrected_alpha,
                "power": float(power),
                "required_independent_clusters": binary_sample_size(
                    baseline_rate=baseline,
                    minimum_detectable_effect=effect,
                    alpha=corrected_alpha,
                    power=power,
                ),
                "method": "two-sided normal approximation; conservative independent-cluster plan",
            }
        )
    return plans


def paired_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    cluster_key: str,
    baseline_key: str,
    treatment_key: str,
    repeats: int = 2000,
    seed: int = 17,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    if repeats < 100:
        raise ValueError("paired cluster bootstrap requires at least 100 repeats")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if (
            cluster_key not in row
            or baseline_key not in row
            or treatment_key not in row
        ):
            raise ValueError("paired bootstrap row is missing a mandatory field")
        cluster = str(row[cluster_key])
        if not cluster:
            raise ValueError("paired bootstrap cluster id is empty")
        difference = float(row[treatment_key]) - float(row[baseline_key])
        clusters[cluster].append(difference)
    if len(clusters) < 2:
        raise ValueError("paired cluster bootstrap requires at least two clusters")
    cluster_means = {
        cluster: sum(values) / len(values) for cluster, values in clusters.items()
    }
    cluster_ids = sorted(cluster_means)
    observed = sum(cluster_means.values()) / len(cluster_means)
    rng = random.Random(seed)
    samples = []
    for _ in range(repeats):
        selected = [rng.choice(cluster_ids) for _ in cluster_ids]
        samples.append(sum(cluster_means[item] for item in selected) / len(selected))
    samples.sort()
    alpha = 1.0 - confidence_level
    lower_index = max(0, math.floor((alpha / 2.0) * repeats))
    upper_index = min(repeats - 1, math.ceil((1.0 - alpha / 2.0) * repeats) - 1)
    return {
        "paired": True,
        "cluster_key": cluster_key,
        "cluster_count": len(cluster_ids),
        "row_count": len(rows),
        "repeats": repeats,
        "seed": seed,
        "confidence_level": confidence_level,
        "mean_difference": observed,
        "ci_lower": samples[lower_index],
        "ci_upper": samples[upper_index],
    }
