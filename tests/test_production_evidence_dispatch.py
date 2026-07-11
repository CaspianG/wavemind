import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    build_production_evidence_dispatch_plan,
    render_dispatch_markdown,
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
        "WAVEMIND_SERVERLESS_NODES": (
            "https://wm-a.staging.internal,https://wm-b.staging.internal"
        ),
        "WAVEMIND_QDRANT_URL": "http://qdrant.staging.internal:6333",
        "WAVEMIND_QDRANT_URLS": (
            "http://qdrant-a.staging.internal:6333,"
            "http://qdrant-b.staging.internal:6333"
        ),
        "WAVEMIND_PGVECTOR_DSNS": ",".join(
            f"postgresql://user:pass@postgres-{index}.staging.internal:5432/wavemind"
            for index in range(4)
        ),
        "WAVEMIND_FAISS_IVFPQ_PATH": str(tmp_path / "wavemind-faiss-ivfpq-50m.faiss"),
        "WAVEMIND_FAISS_IVFPQ_FREE_GB": "8",
        "WAVEMIND_API_KEY": "test-key",
    }


def test_dispatch_plan_reports_blocked_jobs_without_remote_prerequisites():
    root = Path(__file__).resolve().parents[1]
    payload = build_production_evidence_dispatch_plan(root, env={})

    assert payload["schema"] == "wavemind.production_evidence_dispatch.v1"
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["total_jobs"] == 8
    assert payload["summary"]["blocked_by_preflight_count"] == 4
    assert payload["summary"]["ready_to_dispatch_count"] == 0
    assert payload["summary"]["complete_count"] == 4

    by_id = {row["id"]: row for row in payload["jobs"]}
    assert by_id["external_http_cluster"]["workflow"] == "external-http-cluster-load.yml"
    assert by_id["external_http_cluster"]["status"] == "complete"
    assert by_id["external_http_cluster"]["input_bindings"]["nodes"] == (
        "$WAVEMIND_CLUSTER_NODES"
    )
    assert '-f commit_results="false"' in by_id["external_http_cluster"][
        "safe_launch_command"
    ]
    assert '-f commit_results="true"' in by_id["external_http_cluster"][
        "publish_launch_command"
    ]
    assert by_id["hundred_million_remote_load"]["inputs"]["size"] == "100000000"
    assert by_id["hundred_million_remote_load"]["workflow"] == (
        "production-streaming-load.yml"
    )


def test_dispatch_plan_becomes_ready_with_prerequisites_without_leaking_secret_values(
    tmp_path,
):
    root = Path(__file__).resolve().parents[1]
    env = _ready_env(tmp_path)
    payload = build_production_evidence_dispatch_plan(
        root,
        env=env,
        runner_label="self-hosted-xxl",
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["overall_status"] == "ready_to_dispatch"
    assert payload["summary"]["ready_to_dispatch_count"] == 4
    assert payload["summary"]["blocked_by_preflight_count"] == 0
    assert payload["summary"]["complete_count"] == 4
    assert payload["summary"]["runner_label"] == "self-hosted-xxl"

    assert "test-key" not in serialized
    assert "postgresql://user:pass@" not in serialized
    assert "qdrant.staging.internal" not in serialized

    by_id = {row["id"]: row for row in payload["jobs"]}
    qdrant = by_id["qdrant_10m_service"]
    assert qdrant["inputs"]["qdrant_url"] == "$WAVEMIND_QDRANT_URL"
    assert qdrant["inputs"]["runner_label"] == "self-hosted-xxl"
    assert qdrant["inputs"]["runner_storage_root"] == "state/production-runs"
    assert qdrant["input_bindings"]["qdrant_url"] == "$WAVEMIND_QDRANT_URL"
    assert qdrant["required_secrets"] == ["WAVEMIND_QDRANT_API_KEY"]
    pgvector = by_id["pgvector_10m_service"]
    assert pgvector["inputs"]["pgvector_dsns"] == "$WAVEMIND_PGVECTOR_DSNS"
    assert pgvector["input_bindings"]["pgvector_dsns"] == "$WAVEMIND_PGVECTOR_DSNS"
    assert "pgvector_dsn" not in pgvector["inputs"]


def test_dispatch_markdown_lists_launch_and_promotion_commands(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = build_production_evidence_dispatch_plan(root, env=_ready_env(tmp_path))
    markdown = render_dispatch_markdown(payload)

    assert "# WaveMind Production Evidence Dispatch Plan" in markdown
    assert "Safe Launch Commands" in markdown
    assert "hundred_million_remote_load" in markdown
    assert "qdrant-sharded-service" in markdown
    assert "gh run download <run-id>" in markdown
    assert "ingest-production-evidence" in markdown


def test_cli_production_evidence_dispatch_writes_reports(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "dispatch.json"
    markdown = tmp_path / "dispatch.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-dispatch",
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
    assert payload["schema"] == "wavemind.production_evidence_dispatch.v1"
    assert "# WaveMind Production Evidence Dispatch Plan" in report


def test_cli_production_evidence_dispatch_can_fail_until_ready(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-dispatch",
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


def test_cli_production_evidence_dispatch_fail_gate_passes_when_ready(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(_ready_env(tmp_path))
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-dispatch",
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
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "ready_to_dispatch"
