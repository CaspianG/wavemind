from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.validate_goal4_quality_experiment import (
    Goal4QualityArtifactError,
    validate_goal4_quality_experiment,
)


def test_checked_in_goal4_failed_experiment_is_internally_consistent() -> None:
    report = validate_goal4_quality_experiment()

    assert report["status"] == "pass"
    assert report["experiment_status"] == "failed_experiment"
    assert report["errors"] == []


def test_goal4_validator_rejects_a_false_admission(tmp_path: Path) -> None:
    artifact = json.loads(
        Path("benchmarks/goal4_quality_experiment_results.json").read_text(
            encoding="utf-8"
        )
    )
    artifact["status"] = "admitted"
    target = tmp_path / "benchmarks"
    target.mkdir()
    (target / "goal4_quality_experiment_results.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )

    with pytest.raises(Goal4QualityArtifactError, match="status must remain"):
        validate_goal4_quality_experiment(tmp_path)


def test_goal4_validator_rejects_contradictory_uplift(tmp_path: Path) -> None:
    artifact = json.loads(
        Path("benchmarks/goal4_quality_experiment_results.json").read_text(
            encoding="utf-8"
        )
    )
    artifact["full451"]["task_success_uplift"] = 0.25
    target = tmp_path / "benchmarks"
    target.mkdir()
    (target / "goal4_quality_experiment_results.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )

    with pytest.raises(Goal4QualityArtifactError, match="uplift arithmetic"):
        validate_goal4_quality_experiment(tmp_path)
