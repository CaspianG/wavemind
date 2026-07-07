import json
import subprocess
import sys
from pathlib import Path

from benchmarks.production_evidence_gate import evaluate_production_evidence


def test_production_evidence_gate_tracks_strict_external_claims():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence(root)

    assert payload["schema"] == "wavemind.production_evidence.v1"
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["total_requirements"] == 8
    assert payload["summary"]["action_required_count"] >= 1

    by_id = {row["id"]: row for row in payload["requirements"]}
    assert by_id["external_http_cluster"]["status"] == "action_required"
    assert "real remote/staging/production" in " ".join(
        by_id["external_http_cluster"]["issues"]
    )
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
