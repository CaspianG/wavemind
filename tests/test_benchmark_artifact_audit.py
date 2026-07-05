import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from benchmarks.render_benchmark_leaderboard import render_leaderboard
from benchmarks.render_benchmark_report import render_report
from benchmarks.validate_benchmark_artifacts import (
    BenchmarkArtifactError,
    validate_benchmark_artifacts,
)


def test_benchmark_artifact_audit_accepts_checked_in_artifacts():
    report = validate_benchmark_artifacts(max_age_days=3650)

    assert report["schema"] == "wavemind.benchmark_artifact_audit.v1"
    assert report["status"] == "pass"
    assert report["implemented_count"] > 0
    assert report["planned_count"] > 0
    assert report["errors"] == []


def test_benchmark_artifact_audit_rejects_stale_matrix(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    shutil.copytree(project_root / "benchmarks", tmp_path / "benchmarks")
    matrix_path = tmp_path / "benchmarks" / "benchmark_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["generated_at"] = "2026-01-01T00:00:00Z"
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "benchmarks" / "BENCHMARK_REPORT.md").write_text(
        render_report(tmp_path),
        encoding="utf-8",
    )
    (tmp_path / "benchmarks" / "BENCHMARK_LEADERBOARD.md").write_text(
        render_leaderboard(tmp_path),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkArtifactError) as exc:
        validate_benchmark_artifacts(
            tmp_path,
            max_age_days=8,
            now=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )

    assert "benchmark matrix is stale" in str(exc.value)
