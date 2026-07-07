import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_production_evidence_bundle,
    render_bundle_markdown,
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
        "WAVEMIND_PGVECTOR_DSN": "postgresql://user:pass@postgres.staging.internal:5432/wavemind",
        "WAVEMIND_FAISS_IVFPQ_PATH": str(tmp_path / "wavemind-faiss-ivfpq-50m.faiss"),
        "WAVEMIND_FAISS_IVFPQ_FREE_GB": "8",
        "WAVEMIND_API_KEY": "test-key",
    }


def test_production_evidence_bundle_keeps_claims_limited_without_remote_artifacts():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env={})

    assert payload["schema"] == "wavemind.production_evidence_bundle.v1"
    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["strict_overall_status"] == "action_required"
    assert payload["summary"]["production_readiness_status"] == "pass"
    assert payload["summary"]["artifact_audit_status"] == "pass"
    assert payload["summary"]["next_action_count"] == 8

    claims = {row["claim"]: row for row in payload["claim_boundaries"]}
    assert claims["Core library/API readiness"]["status"] == "unlocked"
    assert claims["Remote service-node cluster SLO"]["status"] == "locked"
    assert claims["10M-100M service-backed production scale"]["status"] == "locked"


def test_production_evidence_bundle_uses_preflight_for_next_actions(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env=_ready_env(tmp_path))

    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["preflight_overall_status"] == "ready"
    assert payload["summary"]["preflight_ready_count"] == 8

    by_id = {row["id"]: row for row in payload["next_actions"]}
    assert by_id["external_http_cluster"]["preflight_status"] == "ready"
    assert by_id["external_http_cluster"]["missing_env"] == []
    assert "-f batch_query_size=24" in by_id["external_http_cluster"]["command"]
    assert by_id["hundred_million_remote_load"]["preflight_status"] == "ready"


def test_production_evidence_bundle_markdown_lists_claim_boundaries():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env={})
    markdown = render_bundle_markdown(payload)

    assert "# WaveMind Production Evidence Bundle" in markdown
    assert "Claim Boundaries" in markdown
    assert "Remote multi-region active-active convergence" in markdown
    assert "Next Actions" in markdown


def test_cli_production_evidence_bundle_writes_reports(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "bundle.json"
    markdown = tmp_path / "bundle.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-bundle",
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

    assert "claim_status: claims_limited" in result.stdout
    assert payload["schema"] == "wavemind.production_evidence_bundle.v1"
    assert "# WaveMind Production Evidence Bundle" in report


def test_cli_production_evidence_bundle_strict_exits_nonzero():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-bundle",
            "--root",
            str(project_root),
            "--strict",
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
    assert payload["claim_status"] == "claims_limited"
