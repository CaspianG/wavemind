from __future__ import annotations

import json
from pathlib import Path

from benchmarks.verified_experience_benchmark import (
    DATASET_REVISION,
    DOMAINS,
    dataset_fingerprint,
    frozen_tasks,
    run_benchmark,
)
from wavemind.cli import main
from wavemind.verified_experience_admission import (
    evaluate_verified_experience_admission,
)


EXPECTED_FINGERPRINT = (
    "2799210395afba32d175cefbf99b0c2bce1041688237790f273230d72c51a4f0"
)


def test_frozen_verified_experience_split_is_balanced_and_stable() -> None:
    tasks = frozen_tasks()

    assert DATASET_REVISION == "verified-experience-stateful-v1-frozen-20260803"
    assert len(tasks) == 150
    assert {
        domain: sum(task.domain == domain for task in tasks) for domain in DOMAINS
    } == {domain: 50 for domain in DOMAINS}
    assert sum(task.experience_needed for task in tasks) == 120
    assert dataset_fingerprint(tasks) == EXPECTED_FINGERPRINT


def test_verified_experience_benchmark_passes_frozen_gates() -> None:
    source_sha = "1" * 40
    payload = run_benchmark(source_sha=source_sha)

    assert payload["status"] == "pass"
    assert payload["source_sha"] == source_sha
    assert payload["protocol"]["repeats"] == 5
    assert payload["training"]["capture_rate"] >= 0.99
    assert payload["metrics"]["task_success_uplift"] >= 0.10
    assert min(payload["metrics"]["domain_task_success_uplift"].values()) > 0.0
    assert payload["metrics"]["repeated_error_relative_reduction"] >= 0.50
    assert (
        payload["metrics"]["context_token_relative_reduction_vs_full_history"] >= 0.30
    )
    assert payload["metrics"]["unnecessary_intervention_rate"] <= 0.10
    assert payload["metrics"]["runtime_p95_ms"] <= 75.0
    assert payload["safety"] == {
        "unverified_auto_promotions": 0,
        "namespace_leakage": 0,
        "rollback_provenance_parity": 1.0,
    }


def test_verified_experience_admission_requires_exact_source_sha(
    tmp_path: Path,
) -> None:
    payload = run_benchmark(source_sha="2" * 40)
    artifact = tmp_path / "benchmarks" / "verified_experience_results.json"
    artifact.parent.mkdir()
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    admitted = evaluate_verified_experience_admission(
        tmp_path, expected_source_sha="2" * 40
    )
    blocked = evaluate_verified_experience_admission(
        tmp_path, expected_source_sha="3" * 40
    )

    assert admitted["status"] == "admitted"
    assert admitted["summary"]["blockers"] == []
    assert blocked["status"] == "blocked"
    assert blocked["summary"]["blockers"] == ["source-sha"]


def test_verified_experience_admission_cli_blocks_missing_artifact(
    tmp_path: Path,
) -> None:
    assert (
        main(
            [
                "verified-experience-admission",
                "--root",
                str(tmp_path),
                "--expected-source-sha",
                "5" * 40,
                "--fail-on-blocked",
            ]
        )
        == 2
    )
