from __future__ import annotations

from pathlib import Path

from wavemind.scientific_preflight import evaluate_scientific_memory_preflight


ROOT = Path(__file__).resolve().parents[1]


def test_preflight_is_action_required_without_official_inputs(tmp_path):
    payload = evaluate_scientific_memory_preflight(
        project_root=ROOT,
        protocol_path=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
        dataset_manifest_path=(
            ROOT / "benchmarks" / "evaluation_dataset_manifest_v1.json"
        ),
        run_dir=tmp_path / "runs",
        environment={},
        package_versions={},
        repository_state={"sha": "a" * 40, "clean": True},
    )

    assert payload["status"] == "action_required"
    assert payload["ready"] is False
    assert payload["checks"]["protocol"]["ready"] is True
    assert payload["checks"]["dataset_manifest"]["ready"] is True
    assert payload["checks"]["clean_exact_sha"]["ready"] is True
    assert payload["checks"]["real_baseline_packages"]["ready"] is False
    assert payload["checks"]["official_datasets"]["ready"] is False
    assert payload["checks"]["official_runners"]["ready"] is False
    assert payload["checks"]["longmemeval_v2_one_shot_unconsumed"]["ready"] is True


def test_preflight_blocks_dirty_worktree_even_with_exact_sha(tmp_path):
    payload = evaluate_scientific_memory_preflight(
        project_root=ROOT,
        protocol_path=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
        dataset_manifest_path=(
            ROOT / "benchmarks" / "evaluation_dataset_manifest_v1.json"
        ),
        run_dir=tmp_path,
        environment={},
        package_versions={},
        repository_state={"sha": "a" * 40, "clean": False},
    )

    check = payload["checks"]["clean_exact_sha"]
    assert check["ready"] is False
    assert check["issue"] == "worktree has uncommitted changes"
