import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from benchmarks.render_benchmark_leaderboard import render_leaderboard
from benchmarks.render_benchmark_report import render_report
from benchmarks.render_leaderboard_status import render_leaderboard_status
from benchmarks.validate_benchmark_artifacts import (
    BenchmarkArtifactError,
    validate_benchmark_artifacts,
)
from wavemind.evidence import attach_artifact_integrity, repository_commit


def _copy_bundle(tmp_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    shutil.copytree(
        project_root / "benchmarks",
        tmp_path / "benchmarks",
        ignore=shutil.ignore_patterns("data", ".field_memory_workdir", "__pycache__"),
    )
    (tmp_path / "docs" / "data").mkdir(parents=True)
    return project_root


def _write_rendered_bundle(root: Path, matrix: dict) -> None:
    matrix_path = root / "benchmarks" / "benchmark_matrix_results.json"
    matrix_path.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "benchmarks" / "BENCHMARK_REPORT.md").write_text(
        render_report(root),
        encoding="utf-8",
    )
    (root / "benchmarks" / "BENCHMARK_LEADERBOARD.md").write_text(
        render_leaderboard(root),
        encoding="utf-8",
    )
    (root / "docs" / "data" / "leaderboard-status.json").write_text(
        json.dumps(render_leaderboard_status(root), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_benchmark_artifact_audit_accepts_checked_in_artifacts():
    report = validate_benchmark_artifacts(max_age_days=0)

    assert report["schema"] == "wavemind.benchmark_artifact_audit.v1"
    assert report["status"] == "pass"
    assert report["claim_status"] == "historical"
    assert report["claim_eligible"] is False
    assert report["implemented_count"] > 0
    assert report["planned_count"] > 0
    assert report["errors"] == []


def test_benchmark_artifact_audit_rejects_stale_matrix(tmp_path):
    project_root = _copy_bundle(tmp_path)
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["generated_at"] = "2026-01-01T00:00:00Z"
    matrix["provenance"]["generated_at"] = matrix["generated_at"]
    matrix["provenance"]["claim_status"] = "current"
    matrix = attach_artifact_integrity(matrix)
    _write_rendered_bundle(tmp_path, matrix)

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(
            tmp_path,
            max_age_days=8,
            now=datetime(2026, 1, 15, tzinfo=timezone.utc),
            expected_source_sha=repository_commit(project_root),
            require_current=True,
        )

    assert "benchmark matrix is stale" in str(exc.value)


def test_benchmark_artifact_audit_accepts_stale_historical_matrix(tmp_path):
    project_root = _copy_bundle(tmp_path)
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["generated_at"] = "2026-01-01T00:00:00Z"
    matrix["provenance"]["generated_at"] = matrix["generated_at"]
    matrix["provenance"]["claim_status"] = "historical"
    matrix = attach_artifact_integrity(matrix)
    _write_rendered_bundle(tmp_path, matrix)

    report = validate_benchmark_artifacts(
        tmp_path,
        max_age_days=8,
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
        expected_source_sha=repository_commit(project_root),
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "historical"
    assert report["claim_eligible"] is False


def test_benchmark_artifact_audit_rejects_wrong_sha_current_claim(tmp_path):
    project_root = _copy_bundle(tmp_path)
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["source_ref"] = "0" * 40
    matrix["provenance"]["source_sha"] = "0" * 40
    matrix["provenance"]["claim_status"] = "current"
    matrix = attach_artifact_integrity(matrix)
    _write_rendered_bundle(tmp_path, matrix)

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(
            tmp_path,
            max_age_days=3650,
            expected_source_sha=repository_commit(project_root),
            require_current=True,
        )

    assert "source SHA is not in current history" in str(exc.value)


def test_benchmark_artifact_audit_rejects_tampered_payload(tmp_path):
    project_root = _copy_bundle(tmp_path)
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["benchmarks"][0]["status"] = "implemented-tampered"
    _write_rendered_bundle(tmp_path, matrix)

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(
            tmp_path,
            expected_source_sha=repository_commit(project_root),
        )

    assert "artifact payload digest mismatch" in str(exc.value)


def test_benchmark_artifact_audit_rejects_missing_manifest(tmp_path):
    project_root = _copy_bundle(tmp_path)
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["provenance"].pop("source_manifest")
    matrix = attach_artifact_integrity(matrix)
    _write_rendered_bundle(tmp_path, matrix)

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(
            tmp_path,
            expected_source_sha=repository_commit(project_root),
        )

    assert "source manifest is missing" in str(exc.value)


def test_benchmark_artifact_audit_rejects_unsynchronized_leaderboard_status(tmp_path):
    _copy_bundle(tmp_path)
    docs_data = tmp_path / "docs" / "data"
    docs_data.mkdir(parents=True)
    status = render_leaderboard_status(tmp_path)
    status["publishing_status"] = "stale"
    (docs_data / "leaderboard-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "benchmarks" / "BENCHMARK_REPORT.md").write_text(
        render_report(tmp_path),
        encoding="utf-8",
    )
    (tmp_path / "benchmarks" / "BENCHMARK_LEADERBOARD.md").write_text(
        render_leaderboard(tmp_path),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(tmp_path, max_age_days=3650)

    assert "leaderboard status is not synchronized" in str(exc.value)
