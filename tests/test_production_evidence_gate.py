import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_production_admission,
    evaluate_production_evidence,
    render_production_admission_markdown,
)


def _write_100m_streaming_artifact(root: Path, *, engine: str) -> Path:
    artifact = root / "benchmarks" / "production_streaming_load_qdrant_sharded_100m_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "schema": "wavemind.production_streaming_load.v1",
                "generated_at": "2026-07-10T00:00:00Z",
                "source_ref": "a" * 40,
                "execution_id": "test-run-1",
                "execution_environment": "test-service",
                "evidence_source": "local-service",
                "workflow_run_id": None,
                "workflow_run_url": None,
                "results": [
                    {
                        "vectors": 100_000_000,
                        "results": [
                            {
                                "engine": engine,
                                "vectors": 100_000_000,
                                "recall_at_k": 0.97,
                                "target_recall_at_k": 0.95,
                                "p99_latency_ms": 88.0,
                                "cost_status": "valid_slo",
                                "shard_count": 8,
                                "collection_names": [
                                    f"wavemind_remote_100m_s{index:03d}"
                                    for index in range(8)
                                ],
                                "parallel_shard_upsert": True,
                                "routing": "point_id_minus_one_mod_shard_count",
                                "index_ready_all": True,
                                "index_readiness": [
                                    {
                                        "collection_name": f"wavemind_remote_100m_s{index:03d}",
                                        "expected_vectors": 12_500_000,
                                        "points_count": 12_500_000,
                                        "indexed_vectors_count": 12_500_000,
                                        "ready": True,
                                    }
                                    for index in range(8)
                                ],
                                "checkpoint_completed_batches": 10_000,
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_100m_attestation(root)
    return artifact


def _write_100m_attestation(root: Path) -> Path:
    artifact = root / "benchmarks" / "remote_qdrant_100m_attestation.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shards = [
        {
            "id": f"shard-{index}",
            "ssh_host": f"wm-qdrant-{index}",
            "region": ("eu", "us", "ap", "ca")[index % 4],
            "zone": f"zone-{index}",
            "provider": f"provider-{index % 4}",
            "reachable": True,
            "issues": [],
            "machine_identity_sha256": f"{index + 1:064x}",
            "cpu_count": 4,
            "memory_gb": 32.0,
            "disk_free_gb": 50.0,
            "docker_version": "28.3.0",
        }
        for index in range(8)
    ]
    artifact.write_text(
        json.dumps(
            {
                "schema": "wavemind.remote_qdrant_scale_attestation.v1",
                "status": "pass",
                "generated_at": "2026-07-10T00:00:00Z",
                "source_ref": "a" * 40,
                "execution_id": "test-run-1",
                "workflow_run_id": None,
                "workflow_run_url": None,
                "deployment_id": "wavemind-100m-staging",
                "environment": "staging",
                "source": "independent-cloud-vms",
                "target_vectors": 100_000_000,
                "vector_dim": 128,
                "thresholds": {
                    "min_shards": 8,
                    "min_regions": 3,
                    "min_cpu": 2,
                    "min_memory_gb": 16.0,
                    "min_disk_free_gb_per_shard": 35.0,
                    "required_total_disk_gb": 280.0,
                    "unique_machine_identity_required": True,
                },
                "summary": {
                    "shard_count": 8,
                    "region_count": 4,
                    "reachable_count": 8,
                    "ready_count": 8,
                    "unique_machine_count": 8,
                    "total_disk_free_gb": 400.0,
                },
                "shards": shards,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return artifact


def test_production_evidence_gate_tracks_strict_external_claims():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence(root)
    cluster_load = json.loads(
        (root / "benchmarks" / "http_cluster_load_results.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["schema"] == "wavemind.production_evidence.v1"
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["total_requirements"] == 8
    assert payload["summary"]["action_required_count"] >= 1

    by_id = {row["id"]: row for row in payload["requirements"]}
    assert by_id["external_http_cluster"]["status"] == "pass"
    assert by_id["external_http_cluster"]["issues"] == []
    evidence = by_id["external_http_cluster"]["evidence"]
    metrics = cluster_load["results"][0]
    assert f"query p99 {metrics['query_p99_ms']}" in evidence
    assert f"lifecycle batch p99 {metrics['lifecycle_batch_p99_ms']}" in evidence
    assert "-f batch_query_size=24" in by_id["external_http_cluster"]["command"]
    assert by_id["external_http_active_active"]["artifact"] == (
        "benchmarks/external_http_active_active_results.json"
    )
    assert by_id["serverless_remote_telemetry"]["artifact"] == (
        "deploy/serverless/observed-telemetry.remote.json"
    )
    assert by_id["qdrant_sharded_10m_service"]["artifact"] == (
        "benchmarks/production_streaming_load_qdrant_sharded_10m_results.json"
    )
    assert by_id["hundred_million_remote_load"]["artifact"] == (
        "benchmarks/production_streaming_load_qdrant_sharded_100m_results.json"
    )
    assert "remote-qdrant-100m-lab.yml" in by_id["hundred_million_remote_load"]["command"]
    assert "runner_label=self-hosted-large" in by_id[
        "hundred_million_remote_load"
    ]["command"]


def test_hundred_million_requirement_requires_sharded_qdrant_engine(tmp_path):
    _write_100m_streaming_artifact(
        tmp_path,
        engine="WaveMind faiss-ivfpq-persisted streaming",
    )

    payload = evaluate_production_evidence(tmp_path)
    row = {item["id"]: item for item in payload["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert row["status"] == "fail"
    assert any(
        "artifact must include engine Qdrant sharded service streaming" in issue
        for issue in row["issues"]
    )


def test_hundred_million_requirement_accepts_matching_sharded_qdrant_artifact(tmp_path):
    _write_100m_streaming_artifact(
        tmp_path,
        engine="Qdrant sharded service streaming",
    )

    payload = evaluate_production_evidence(tmp_path)
    row = {item["id"]: item for item in payload["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert row["status"] == "pass"
    assert row["issues"] == []
    assert "Qdrant sharded service streaming" in row["evidence"]
    assert "remote shards 8" in row["evidence"]


def test_hundred_million_requirement_rejects_benchmark_without_remote_attestation(tmp_path):
    _write_100m_streaming_artifact(
        tmp_path,
        engine="Qdrant sharded service streaming",
    )
    (tmp_path / "benchmarks" / "remote_qdrant_100m_attestation.json").unlink()

    payload = evaluate_production_evidence(tmp_path)
    row = {item["id"]: item for item in payload["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert row["status"] == "action_required"
    assert any("missing remote Qdrant 100M attestation" in issue for issue in row["issues"])


def test_hundred_million_requirement_rejects_unbound_attestation(tmp_path):
    _write_100m_streaming_artifact(
        tmp_path,
        engine="Qdrant sharded service streaming",
    )
    artifact = tmp_path / "benchmarks" / "remote_qdrant_100m_attestation.json"
    attestation = json.loads(artifact.read_text(encoding="utf-8"))
    attestation["execution_id"] = "different-run"
    artifact.write_text(json.dumps(attestation, indent=2), encoding="utf-8")

    payload = evaluate_production_evidence(tmp_path)
    row = {item["id"]: item for item in payload["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert row["status"] == "fail"
    assert "remote topology: execution_id must match benchmark execution_id" in row[
        "issues"
    ]


def test_hundred_million_requirement_rejects_under_sharded_benchmark(tmp_path):
    artifact = _write_100m_streaming_artifact(
        tmp_path,
        engine="Qdrant sharded service streaming",
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    row = payload["results"][0]["results"][0]
    row["shard_count"] = 4
    row["collection_names"] = row["collection_names"][:4]
    row["index_readiness"] = row["index_readiness"][:4]
    artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    evidence = evaluate_production_evidence(tmp_path)
    requirement = {item["id"]: item for item in evidence["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert requirement["status"] == "fail"
    assert "remote topology: benchmark shard_count must be >= 8" in requirement[
        "issues"
    ]
    assert any("point counts" in issue for issue in requirement["issues"])


def test_large_service_requirement_rejects_missing_provenance(tmp_path):
    artifact = _write_100m_streaming_artifact(
        tmp_path,
        engine="Qdrant sharded service streaming",
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload.pop("source_ref")
    artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    evidence = evaluate_production_evidence(tmp_path)
    row = {item["id"]: item for item in evidence["requirements"]}[
        "hundred_million_remote_load"
    ]

    assert row["status"] == "fail"
    assert any("source_ref" in issue for issue in row["issues"])


def test_production_evidence_gate_cli_writes_json_and_markdown(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "production_evidence_results.json"
    markdown = tmp_path / "PRODUCTION_EVIDENCE.md"

    result = subprocess.run(
        [
            sys.executable,
            "benchmarks/production_evidence_gate.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = markdown.read_text(encoding="utf-8")

    assert "action_required" in result.stdout
    assert payload["overall_status"] == "action_required"
    assert "# WaveMind Strict Production Evidence Gate" in report
    assert "100M remote load result" in report
    assert "Core readiness can pass without these artifacts" in report


def test_production_evidence_gate_strict_exits_nonzero(tmp_path):
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "benchmarks/production_evidence_gate.py",
            "--output",
            str(tmp_path / "evidence.json"),
            "--markdown-output",
            str(tmp_path / "evidence.md"),
            "--strict",
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 2
    assert "action_required" in result.stdout


def test_production_admission_blocks_100m_without_strict_artifact():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_admission(
        root,
        target_memories=100_000_000,
        engine="qdrant-sharded-service",
    )

    assert payload["schema"] == "wavemind.production_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "strict_evidence_required"

    row = payload["required_evidence"][0]
    assert row["profile"] == "qdrant-sharded-100m"
    assert row["requirement_id"] == "hundred_million_remote_load"
    assert row["strict_status"] == "action_required"
    assert row["artifact"] == (
        "benchmarks/production_streaming_load_qdrant_sharded_100m_results.json"
    )
    assert "100m" in row["command"].lower()
    assert payload["issues"]


def test_production_admission_blocks_wrong_engine_100m_artifact(tmp_path):
    _write_100m_streaming_artifact(
        tmp_path,
        engine="WaveMind faiss-ivfpq-persisted streaming",
    )

    payload = evaluate_production_admission(
        tmp_path,
        target_memories=100_000_000,
        engine="qdrant-sharded-service",
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    row = payload["required_evidence"][0]
    assert row["profile"] == "qdrant-sharded-100m"
    assert row["strict_status"] == "fail"
    assert any("artifact must include engine" in issue for issue in row["issues"])


def test_production_admission_plan_only_never_admits_production():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_admission(
        root,
        target_memories=100_000_000,
        engine="qdrant-sharded",
        allow_plan_only=True,
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert "Do not admit production traffic yet" in payload["next_actions"][0]


def test_production_admission_allows_small_targets_with_scale_guardrail():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_admission(
        root,
        target_memories=500_000,
        engine="numpy",
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["claim_boundary"] == "scale_plan_required"
    assert payload["required_evidence"] == []
    assert "Strict large-N admission is not required" in payload["warnings"][0]


def test_render_production_admission_markdown():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_admission(
        root,
        target_memories=100_000_000,
        engine="qdrant-sharded-service",
    )
    markdown = render_production_admission_markdown(payload)

    assert "# WaveMind Production Admission" in markdown
    assert "qdrant-sharded-100m" in markdown
    assert "hundred_million_remote_load" not in markdown
    assert "Keep the production claim locked" in markdown


def test_production_admission_cli_writes_json_and_markdown(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "production_admission_results.json"
    markdown = tmp_path / "PRODUCTION_ADMISSION.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-admission",
            "--root",
            str(project_root),
            "--target-memories",
            "100000000",
            "--engine",
            "qdrant-sharded-service",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = markdown.read_text(encoding="utf-8")

    assert "status: blocked" in result.stdout
    assert "admitted: false" in result.stdout
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert "# WaveMind Production Admission" in report
    assert "qdrant-sharded-100m" in report


def test_production_admission_cli_fail_on_blocked_exits_nonzero():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-admission",
            "--root",
            str(project_root),
            "--target-memories",
            "100000000",
            "--engine",
            "qdrant-sharded-service",
            "--fail-on-blocked",
            "--json",
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False


def test_serve_production_guard_blocks_before_uvicorn_start():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8999",
            "--require-production-admission",
            "--production-admission-root",
            str(project_root),
            "--production-target-memories",
            "100000000",
            "--production-engine",
            "qdrant-sharded-service",
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 2
    assert "production admission blocked" in result.stderr
    assert "qdrant-sharded-100m is not admitted" in result.stderr
    assert "Uvicorn running" not in result.stderr


def test_serve_production_guard_can_be_enabled_from_environment():
    project_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(project_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "WAVEMIND_REQUIRE_PRODUCTION_ADMISSION": "1",
        "WAVEMIND_PRODUCTION_ADMISSION_ROOT": str(project_root),
        "WAVEMIND_PRODUCTION_TARGET_MEMORIES": "100000000",
        "WAVEMIND_PRODUCTION_ENGINE": "qdrant-sharded-service",
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8998",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 2
    assert "production admission blocked" in result.stderr
    assert "target_memories=100000000" in result.stderr
