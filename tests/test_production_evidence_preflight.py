import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_production_evidence_preflight,
    render_preflight_markdown,
)


def _ready_env(tmp_path):
    return {
        "WAVEMIND_CLUSTER_NODES": ",".join(
            [
                "node-a=https://wm-a.staging.internal",
                "node-b=https://wm-b.staging.internal",
                "node-c=https://wm-c.staging.internal",
                "node-d=https://wm-d.staging.internal",
            ]
        ),
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS": ",".join(
            [
                "us=https://wm-us.staging.internal",
                "eu=https://wm-eu.staging.internal",
                "ap=https://wm-ap.staging.internal",
            ]
        ),
        "WAVEMIND_SERVERLESS_NODES": "https://wm-a.staging.internal,https://wm-b.staging.internal",
        "WAVEMIND_QDRANT_URL": "http://qdrant.staging.internal:6333",
        "WAVEMIND_QDRANT_URLS": "http://qdrant-a.staging.internal:6333,http://qdrant-b.staging.internal:6333",
        "WAVEMIND_PGVECTOR_DSNS": ",".join(
            f"postgresql://user:pass@postgres-{index}.staging.internal:5432/wavemind"
            for index in range(4)
        ),
        "WAVEMIND_FAISS_IVFPQ_PATH": str(tmp_path / "wavemind-faiss-ivfpq-50m.faiss"),
        "WAVEMIND_FAISS_IVFPQ_FREE_GB": "8",
        "WAVEMIND_API_KEY": "test-key",
    }


def test_production_evidence_preflight_reports_missing_env():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_preflight(root, env={})

    assert payload["schema"] == "wavemind.production_evidence_preflight.v1"
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["total_checks"] == 8
    assert payload["summary"]["ready_count"] < 8

    by_id = {row["id"]: row for row in payload["checks"]}
    assert by_id["external_http_cluster"]["status"] == "action_required"
    assert "WAVEMIND_CLUSTER_NODES" in by_id["external_http_cluster"]["missing_env"]
    assert by_id["qdrant_10m_service"]["missing_env"] == ["WAVEMIND_QDRANT_URL"]
    assert by_id["faiss_ivfpq_50m"]["missing_env"] == ["WAVEMIND_FAISS_IVFPQ_PATH"]


def test_production_evidence_preflight_can_be_ready_with_real_prerequisites(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_preflight(root, env=_ready_env(tmp_path))

    assert payload["overall_status"] == "ready"
    assert payload["summary"]["ready_count"] == 8
    assert payload["summary"]["action_required_count"] == 0

    by_id = {row["id"]: row for row in payload["checks"]}
    assert by_id["external_http_active_active"]["missing_env"] == []
    assert by_id["pgvector_10m_service"]["missing_env"] == []
    assert "-f batch_query_size=24" in by_id["external_http_cluster"]["command"]
    assert by_id["hundred_million_remote_load"]["ready"] is True
    assert "production_streaming_load_qdrant_sharded_100m_results.json" in by_id[
        "hundred_million_remote_load"
    ]["command"]


def test_production_evidence_preflight_markdown_keeps_claim_boundary(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_preflight(root, env=_ready_env(tmp_path))
    markdown = render_preflight_markdown(payload)

    assert "# WaveMind Production Evidence Preflight" in markdown
    assert "not a substitute for" in markdown
    assert "50M FAISS IVF-PQ streaming load preflight" in markdown


def test_cli_production_evidence_preflight_writes_reports(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "preflight.json"
    markdown = tmp_path / "preflight.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-preflight",
            "--root",
            str(project_root),
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = markdown.read_text(encoding="utf-8")

    assert "status: action_required" in result.stdout
    assert payload["schema"] == "wavemind.production_evidence_preflight.v1"
    assert "# WaveMind Production Evidence Preflight" in report


def test_cli_production_evidence_preflight_can_fail_on_action_required(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-preflight",
            "--root",
            str(project_root),
            "--fail-on-action-required",
            "--json",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["overall_status"] == "action_required"
