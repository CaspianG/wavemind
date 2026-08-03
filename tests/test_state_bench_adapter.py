from __future__ import annotations

import json
from pathlib import Path

from benchmarks.verified_experience_benchmark import _runtime, _train
from wavemind.integrations.state_bench import (
    STATE_BENCH_DOMAINS,
    WaveMindStateBenchLearningAdapter,
    build_state_bench_adapter_artifact,
    validate_state_bench_training_root,
)


def _write_official_shape(root: Path, *, count: int = 100) -> None:
    for domain in STATE_BENCH_DOMAINS:
        folder = root / domain
        folder.mkdir(parents=True)
        for index in range(count):
            (folder / f"trajectory-{index:03d}.json").write_text(
                json.dumps(
                    {
                        "conversation": [
                            {"role": "user", "content": f"{domain} task {index}"},
                            {"role": "assistant", "content": "completed"},
                        ]
                    }
                ),
                encoding="utf-8",
            )


def test_state_bench_adapter_is_read_only_and_returns_strings(tmp_path: Path) -> None:
    namespace = "state-bench-adapter"
    runtime = _runtime(tmp_path / "adapter.sqlite3", namespace)
    _train(runtime, namespace)
    adapter = WaveMindStateBenchLearningAdapter(
        runtime,
        namespace=namespace,
        domain="travel",
    )

    before = runtime.snapshot(namespace=namespace)
    learnings = adapter.retrieve_learnings(
        "Safely rebook this itinerary and verify the final reservation",
        top_k=3,
    )
    after = runtime.snapshot(namespace=namespace)

    assert learnings
    assert len(learnings) <= 3
    assert all(isinstance(item, str) and item for item in learnings)
    assert before == after
    runtime.store.close()


def test_state_bench_protocol_validator_requires_exact_train_split(
    tmp_path: Path,
) -> None:
    root = tmp_path / "train_task_trajectories"
    _write_official_shape(root)

    validation = validate_state_bench_training_root(root)
    artifact = build_state_bench_adapter_artifact(
        training_root=root,
        source_sha="4" * 40,
        upstream_sha="6" * 40,
    )

    assert validation.valid is True
    assert validation.file_counts == {domain: 100 for domain in STATE_BENCH_DOMAINS}
    assert len(validation.fingerprint_sha256) == 64
    assert artifact["status"] == "runner_ready"
    assert artifact["official_protocol"]["official_paid_model_run_performed"] is False
    assert artifact["official_protocol"]["repository_sha"] == "6" * 40
    assert "not an official STATE-Bench result" in artifact["claim_boundary"]


def test_state_bench_protocol_rejects_test_data_and_incomplete_split(
    tmp_path: Path,
) -> None:
    root = tmp_path / "test" / "task_trajectories"
    _write_official_shape(root, count=1)

    validation = validate_state_bench_training_root(root)

    assert validation.valid is False
    assert any("test data" in error for error in validation.errors)
    assert any("exactly 100" in error for error in validation.errors)
