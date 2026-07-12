import json
from pathlib import Path

import pytest

from wavemind.production_evidence_ingest import (
    ProductionEvidenceIngestError,
    discover_expected_artifacts,
    ingest_production_evidence_artifacts,
    refresh_commands,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _cluster_payload() -> dict:
    return {
        "scenario": {
            "name": "http_cluster_load",
            "node_count": 4,
            "node_ids": ["node-a", "node-b", "node-c", "node-d"],
            "node_addresses": [
                "https://wm-a.staging.internal",
                "https://wm-b.staging.internal",
                "https://wm-c.staging.internal",
                "https://wm-d.staging.internal",
            ],
            "deployment_id": "staging-cluster-20260708",
            "environment": "staging",
            "source": "github-actions-staging",
            "source_ref": "b" * 40,
            "workflow_run_id": "987654321",
            "workflow_run_url": (
                "https://github.com/CaspianG/wavemind/actions/runs/987654321"
            ),
            "namespace_count": 32,
            "memories_per_namespace": 8,
            "replication_factor": 3,
            "read_quorum": 1,
            "read_fanout": 1,
        },
        "results": [
            {
                "engine": "WaveMind external HTTP cluster load",
                "replication_factor": 3,
                "read_quorum": 1,
                "read_fanout": 1,
                "success_rate": 1.0,
                "write_success_rate": 1.0,
                "query_hit_rate": 1.0,
                "failover_hit_rate": 1.0,
                "delete_suppression_rate": 1.0,
                "repair_ok": True,
                "repair_repaired_total": 1,
                "slo_pass": True,
                "p99_operation_ms": 420.0,
                "batch_query": {
                    "success": True,
                    "individual_success": True,
                    "batch_success": True,
                    "batch_size": 24,
                    "individual_http_requests": 24,
                    "batch_http_requests": 1,
                    "request_reduction_ratio": 0.958,
                    "batch_p99_ms": 390.0,
                },
            }
        ],
    }


def _active_active_payload(*, environment: str = "staging", evidence_source: str = "github-actions-staging") -> dict:
    return {
        "scenario": {
            "name": "local_http_active_active_smoke",
            "source": "external-regions",
            "deployment_id": "staging-regions-20260708",
            "environment": environment,
            "evidence_source": evidence_source,
            "region_count": 3,
            "namespace_count": 16,
        },
        "results": [
            {
                "engine": "WaveMind real HTTP active-active service-region sync",
                "convergence_rate": 1.0,
                "delete_suppression_rate": 1.0,
                "success_rate": 1.0,
                "failed_pairs": 0,
                "final_noop_records_imported": 0,
                "final_noop_failed_pairs": 0,
                "slo_pass": True,
                "p99_operation_ms": 780.0,
            }
        ],
    }


def _active_active_failure_payload() -> dict:
    return {
        "schema": "wavemind.remote_region_failure_drill.v1",
        "status": "pass",
        "deployment_id": "staging-regions-20260708",
        "environment": "staging",
        "source": "ssh-remote-production-lab",
        "failed_region": "eu",
        "region_count": 3,
        "namespace_prefix": "remote-region-failure",
        "namespace_count": 16,
        "physical_failure": {
            "stop": {"ok": True, "error": None},
            "start": {"ok": True, "error": None},
            "failure_observed": True,
            "health_recovered": True,
        },
        "phase_statuses": {"seed": "pass", "outage": "pass", "recover": "pass"},
        "outage": {
            "unavailable_regions": ["eu"],
            "surviving_regions": ["us", "ap"],
        },
        "recover": {
            "sync": {
                "final_noop_records_imported": 0,
                "final_noop_tombstones_imported": 0,
            },
            "verification": {
                "convergence_rate": 1.0,
                "delete_suppression_rate": 1.0,
            },
        },
    }


def _serverless_payload() -> dict:
    return {
        "source": "knative-staging-us-east-eu-west",
        "node_mode": "external",
        "requests_per_second": 3200.0,
        "p99_request_ms": 44.0,
        "target_p99_ms": 100.0,
        "error_rate": 0.0,
        "max_error_rate": 0.01,
        "observed_slo_pass": True,
    }


def _streaming_payload() -> dict:
    return {
        "schema": "wavemind.production_streaming_load.v1",
        "generated_at": "2026-07-10T00:00:00Z",
        "source_ref": "a" * 40,
        "execution_id": "test-run-1",
        "execution_environment": "test-service",
        "evidence_source": "local-service",
        "workflow_run_id": None,
        "workflow_run_url": None,
        "scenario": {"name": "production_streaming_load_profile"},
        "results": [
            {
                "vectors": 100_000_000,
                "results": [
                    {
                        "engine": "Qdrant sharded service streaming",
                        "vectors": 100_000_000,
                        "target_recall_at_k": 0.97,
                        "p99_latency_ms": 82.5,
                        "cost_status": "valid_slo",
                    }
                ],
            }
        ],
    }


def test_ingest_accepts_remote_http_cluster_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    source = _write_json(artifact_dir / "http_cluster_load_results.json", _cluster_payload())

    manifest = ingest_production_evidence_artifacts(artifact_dir, output_root=output_root)

    destination = output_root / "benchmarks" / source.name
    assert destination.exists()
    assert manifest["schema"] == "wavemind.production_evidence_artifact_ingest.v1"
    assert manifest["ingested_count"] == 1
    assert manifest["ingested"][0]["requirement_id"] == "external_http_cluster"
    assert manifest["ingested"][0]["copied"] is True


def test_ingest_rejects_renamed_loopback_active_active_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    _write_json(
        artifact_dir / "external_http_active_active_results.json",
        _active_active_payload(environment="local-loopback", evidence_source="loopback-api-regions"),
    )

    with pytest.raises(ProductionEvidenceIngestError, match="loopback"):
        ingest_production_evidence_artifacts(artifact_dir, output_root=tmp_path / "checkout")


def test_ingest_requires_and_copies_remote_active_active_failure_drill(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    _write_json(
        artifact_dir / "external_http_active_active_results.json",
        _active_active_payload(),
    )
    with pytest.raises(ProductionEvidenceIngestError, match="failure drill"):
        ingest_production_evidence_artifacts(artifact_dir, output_root=output_root)

    _write_json(
        artifact_dir / "remote_active_active_failure_drill_results.json",
        _active_active_failure_payload(),
    )
    manifest = ingest_production_evidence_artifacts(artifact_dir, output_root=output_root)
    assert manifest["ingested_count"] == 1
    assert manifest["ingested"][0]["requirement_id"] == "external_http_active_active"
    assert manifest["ingested"][0]["dependencies"] == [
        "remote_active_active_failure_drill_results.json"
    ]
    assert (output_root / "benchmarks/remote_active_active_failure_drill_results.json").exists()


def test_ingest_accepts_remote_serverless_telemetry_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    _write_json(artifact_dir / "observed-telemetry.remote.json", _serverless_payload())

    manifest = ingest_production_evidence_artifacts(artifact_dir, output_root=output_root)

    destination = output_root / "deploy" / "serverless" / "observed-telemetry.remote.json"
    assert destination.exists()
    assert manifest["ingested"][0]["requirement_id"] == "serverless_remote_telemetry"
    assert "serverless" in manifest["ingested"][0]["description"]


def test_ingest_accepts_windows_utf8_bom_json(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    path = artifact_dir / "observed-telemetry.remote.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_serverless_payload(), indent=2), encoding="utf-8-sig")

    manifest = ingest_production_evidence_artifacts(artifact_dir, output_root=output_root, dry_run=True)

    assert manifest["ingested"][0]["requirement_id"] == "serverless_remote_telemetry"
    assert manifest["ingested"][0]["status"] == "pass"


def test_ingest_accepts_strict_100m_streaming_artifact_dry_run(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    source = _write_json(
        artifact_dir / "benchmarks" / "production_streaming_load_qdrant_sharded_100m_results.json",
        _streaming_payload(),
    )

    manifest = ingest_production_evidence_artifacts(artifact_dir, output_root=output_root, dry_run=True)

    assert discover_expected_artifacts(artifact_dir)[0][0] == source
    assert manifest["dry_run"] is True
    assert manifest["ingested"][0]["requirement_id"] == "hundred_million_remote_load"
    assert manifest["ingested"][0]["copied"] is False
    assert not (output_root / "benchmarks" / source.name).exists()


def test_ingest_refresh_commands_cover_claim_boundary_artifacts():
    commands = [" ".join(command) for command in refresh_commands()]

    assert any("benchmarks/production_evidence_gate.py" in command for command in commands)
    assert any("production-evidence-env" in command for command in commands)
    assert any("production-evidence-bundle" in command for command in commands)
    assert any("release-claims" in command for command in commands)
    assert any("scale-gap" in command for command in commands)
    assert any("production-admission" in command for command in commands)
    assert any("docs/data/leaderboard-status.json" in command for command in commands)
    status_indexes = [
        index
        for index, command in enumerate(commands)
        if "render_leaderboard_status.py" in command
    ]
    audit_index = next(
        index
        for index, command in enumerate(commands)
        if "validate_benchmark_artifacts.py" in command
    )
    assert len(status_indexes) == 2
    assert status_indexes[0] < audit_index < status_indexes[1]
