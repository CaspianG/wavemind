import json
from pathlib import Path

import pytest

from benchmarks.ingest_production_streaming_artifact import (
    ArtifactValidationError,
    discover_expected_artifacts,
    ingest_artifacts,
    refresh_commands,
    validate_artifact,
)


def _streaming_payload(
    *,
    engine: str = "Qdrant sharded service streaming",
    vectors: int = 100_000_000,
    recall: float = 0.97,
    p99_ms: float = 82.5,
    slo_status: str = "pass",
    cost_status: str = "valid_slo",
) -> dict:
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
                "vectors": vectors,
                "vector_dim": 128,
                "queries": 100,
                "top_k": 10,
                "results": [
                    {
                        "engine": engine,
                        "vectors": vectors,
                        "target_recall_at_k": recall,
                        "p99_latency_ms": p99_ms,
                        "avg_latency_ms": 50.0,
                        "queries": 100,
                        "slo_status": slo_status,
                        "cost_status": cost_status,
                    }
                ],
            }
        ],
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_ingest_accepts_strict_100m_sharded_qdrant_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    source = _write_json(
        artifact_dir / "benchmarks" / "production_streaming_load_qdrant_sharded_100m_results.json",
        _streaming_payload(),
    )

    manifest = ingest_artifacts(artifact_dir, output_root=output_root)

    destination = output_root / "benchmarks" / source.name
    assert destination.exists()
    assert json.loads(destination.read_text(encoding="utf-8"))["results"][0]["vectors"] == 100_000_000
    assert manifest["schema"] == "wavemind.production_streaming_artifact_ingest.v1"
    assert manifest["ingested"][0]["filename"] == source.name
    assert manifest["ingested"][0]["vectors"] == 100_000_000
    assert manifest["ingested"][0]["copied"] is True


def test_ingest_dry_run_validates_without_copying(tmp_path):
    artifact_dir = tmp_path / "artifact"
    output_root = tmp_path / "checkout"
    source = _write_json(
        artifact_dir / "production_streaming_load_pgvector_10m_results.json",
        _streaming_payload(engine="WaveMind pgvector streaming", vectors=10_000_000),
    )

    manifest = ingest_artifacts(artifact_dir, output_root=output_root, dry_run=True)

    assert manifest["dry_run"] is True
    assert manifest["ingested"][0]["filename"] == source.name
    assert manifest["ingested"][0]["copied"] is False
    assert not (output_root / "benchmarks" / source.name).exists()


def test_ingest_rejects_wrong_vectors_for_named_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    source = _write_json(
        artifact_dir / "production_streaming_load_qdrant_10m_results.json",
        _streaming_payload(engine="Qdrant service streaming", vectors=1_000_000),
    )

    with pytest.raises(ArtifactValidationError, match="expected 10000000 vectors"):
        validate_artifact(
            source,
            discover_expected_artifacts(artifact_dir)[0][1],
        )


def test_ingest_rejects_large_n_artifact_without_provenance(tmp_path):
    artifact_dir = tmp_path / "artifact"
    payload = _streaming_payload(
        engine="Qdrant service streaming",
        vectors=10_000_000,
    )
    payload.pop("source_ref")
    source = _write_json(
        artifact_dir / "production_streaming_load_qdrant_10m_results.json",
        payload,
    )

    with pytest.raises(ArtifactValidationError, match="source_ref"):
        validate_artifact(source, discover_expected_artifacts(artifact_dir)[0][1])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_recall_at_k", 0.90, "below"),
        ("p99_latency_ms", 150.0, "exceeds"),
        ("slo_status", "fail", "slo_status"),
        ("cost_status", "invalid", "cost_status"),
    ],
)
def test_ingest_rejects_non_production_slo_rows(tmp_path, field, value, message):
    artifact_dir = tmp_path / "artifact"
    payload = _streaming_payload(engine="WaveMind faiss-ivfpq-persisted streaming", vectors=50_000_000)
    payload["results"][0]["results"][0][field] = value
    source = _write_json(
        artifact_dir / "production_streaming_load_ivfpq_50m_results.json",
        payload,
    )

    with pytest.raises(ArtifactValidationError, match=message):
        validate_artifact(source, discover_expected_artifacts(artifact_dir)[0][1])


def test_ingest_ignores_smoke_and_requires_recognized_large_n_artifact(tmp_path):
    artifact_dir = tmp_path / "artifact"
    _write_json(
        artifact_dir / "production_streaming_load_qdrant_sharded_smoke_results.json",
        _streaming_payload(vectors=5_000),
    )

    assert discover_expected_artifacts(artifact_dir) == []
    with pytest.raises(ArtifactValidationError, match="no recognized production streaming result"):
        ingest_artifacts(artifact_dir, output_root=tmp_path / "checkout")


def test_refresh_commands_include_public_leaderboard_and_evidence_gates():
    commands = [" ".join(command) for command in refresh_commands()]

    assert any("benchmarks/benchmark_registry.py" in command for command in commands)
    assert any("benchmarks/render_benchmark_leaderboard.py" in command for command in commands)
    assert any("benchmarks/agent_impact_leaderboard.py" in command for command in commands)
    assert any("benchmarks/structured_memory_report.py" in command for command in commands)
    assert any("benchmarks/memory_os_intelligence_report.py" in command for command in commands)
    assert any("benchmarks/cluster_autoscale_report.py" in command for command in commands)
    assert any("benchmarks/cost_efficiency_leaderboard.py" in command for command in commands)
    assert any("benchmarks/render_benchmark_dashboard.py" in command for command in commands)
    assert any("benchmarks/production_readiness_gate.py" in command for command in commands)
    assert any("benchmarks/production_evidence_gate.py" in command for command in commands)
    assert any("benchmarks/render_leaderboard_status.py" in command for command in commands)
