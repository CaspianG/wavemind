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
    assert payload["checks"]["official_runner_manifest"]["ready"] is True
    assert payload["checks"]["clean_exact_sha"]["ready"] is True
    assert payload["checks"]["real_baseline_packages"]["ready"] is False
    assert payload["checks"]["official_datasets"]["ready"] is False
    assert payload["checks"]["official_runners"]["ready"] is False
    assert payload["checks"]["official_credentials"]["ready"] is False
    assert (
        payload["checks"]["official_credentials"]["secret_values_recorded"]
        is False
    )
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


def test_preflight_records_credential_presence_without_secret_values(tmp_path):
    environment = {
        "OPENAI_API_KEY": "top-secret",
        "WAVEMIND_LONGMEMEVAL_READER_BASE_URL": "http://reader.invalid/v1",
        "WAVEMIND_LONGMEMEVAL_EMBEDDING_BASE_URL": "http://embed.invalid/v1",
    }
    payload = evaluate_scientific_memory_preflight(
        project_root=ROOT,
        protocol_path=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
        dataset_manifest_path=(
            ROOT / "benchmarks" / "evaluation_dataset_manifest_v1.json"
        ),
        run_dir=tmp_path,
        environment=environment,
        package_versions={},
        repository_state={"sha": "a" * 40, "clean": True},
    )

    credentials = payload["checks"]["official_credentials"]
    assert credentials["ready"] is True
    assert credentials["secret_values_recorded"] is False
    assert "top-secret" not in str(credentials)


def test_preflight_rejects_tampered_runner_manifest(tmp_path):
    source = ROOT / "benchmarks" / "scientific_official_runner_manifest_v1.json"
    payload = source.read_text(encoding="utf-8").replace(
        "HUST-AI-HYZ/MemoryAgentBench",
        "untrusted/MemoryAgentBench",
    )
    manifest = tmp_path / "runner-manifest.json"
    manifest.write_text(payload, encoding="utf-8")

    result = evaluate_scientific_memory_preflight(
        project_root=ROOT,
        protocol_path=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
        dataset_manifest_path=(
            ROOT / "benchmarks" / "evaluation_dataset_manifest_v1.json"
        ),
        runner_manifest_path=manifest,
        run_dir=tmp_path / "runs",
        environment={},
        package_versions={},
        repository_state={"sha": "a" * 40, "clean": True},
    )

    check = result["checks"]["official_runner_manifest"]
    assert check["ready"] is False
    assert "digest mismatch" in " ".join(check["issues"])
