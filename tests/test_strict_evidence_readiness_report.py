import json
import subprocess
import sys
from pathlib import Path

from benchmarks.strict_evidence_readiness_report import (
    build_strict_evidence_readiness_report,
    render_strict_evidence_readiness_markdown,
)


def test_strict_evidence_readiness_joins_all_strict_requirements():
    project_root = Path(__file__).resolve().parents[1]
    payload = build_strict_evidence_readiness_report(project_root)

    assert payload["schema"] == "wavemind.strict_evidence_readiness.v1"
    assert payload["status"] == "pass"
    assert payload["readiness_status"] == "action_required"
    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["total_requirements"] == 8
    assert payload["summary"]["action_required_count"] == 8
    assert payload["summary"]["target_memories_total"] == 180_000_000
    assert payload["summary"]["check_counts"] == {"pass": 8}
    assert payload["summary"]["can_auto_run_now_count"] == 0
    assert payload["summary"]["blocker_counts"]["missing_env"] == 8

    by_id = {row["id"]: row for row in payload["requirements"]}
    assert set(by_id) == {
        "external_http_cluster",
        "external_http_active_active",
        "serverless_remote_telemetry",
        "qdrant_10m_service",
        "qdrant_sharded_10m_service",
        "pgvector_10m_service",
        "faiss_ivfpq_50m",
        "hundred_million_remote_load",
    }

    assert by_id["external_http_cluster"]["workflow"] == "external-http-cluster-load.yml"
    assert by_id["external_http_cluster"]["locked_claim"] == "Remote service-node cluster SLO"
    assert by_id["external_http_cluster"]["safe_dispatch_command"].endswith(
        '-f commit_results="false"'
    )
    assert by_id["external_http_cluster"]["download_command"].startswith("gh run download")
    assert by_id["external_http_cluster"]["ingest_command"].startswith(
        "wavemind ingest-production-evidence"
    )
    assert "production_evidence_gate.py" in by_id["external_http_cluster"][
        "strict_validation_command"
    ]

    qdrant_100m = by_id["hundred_million_remote_load"]
    assert qdrant_100m["target_memories"] == 100_000_000
    assert qdrant_100m["target_recall_at_k"] == 0.95
    assert qdrant_100m["target_p99_ms"] == 100.0
    assert qdrant_100m["locked_claim"] == "10M-100M service-backed production scale"
    assert '-f size="100000000"' in qdrant_100m["safe_dispatch_command"]
    assert qdrant_100m["can_auto_run_now"] is False

    serialized = json.dumps(payload, sort_keys=True)
    assert "ghp_" not in serialized
    assert "github_pat_" not in serialized
    assert "://user:pass@" not in serialized
    assert "sk-" not in serialized
    assert "Readiness report only" in payload["claim_boundary"]


def test_strict_evidence_readiness_markdown_lists_runbook_commands():
    project_root = Path(__file__).resolve().parents[1]
    payload = build_strict_evidence_readiness_report(project_root)
    markdown = render_strict_evidence_readiness_markdown(payload)

    assert "# WaveMind Strict Evidence Readiness" in markdown
    assert "It is a runbook, not" in markdown
    assert "hundred_million_remote_load" in markdown
    assert "gh workflow run production-streaming-load.yml" in markdown
    assert "gh run download <run-id>" in markdown
    assert "wavemind ingest-production-evidence" in markdown
    assert "production_evidence_gate.py" in markdown
    assert "does not unlock remote, 10M, 50M, 100M" in markdown


def test_cli_strict_evidence_readiness_report_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "strict.json"
    markdown = tmp_path / "strict.md"

    result = subprocess.run(
        [
            sys.executable,
            "benchmarks/strict_evidence_readiness_report.py",
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

    assert "strict evidence readiness: pass / action_required" in result.stdout
    assert payload["schema"] == "wavemind.strict_evidence_readiness.v1"
    assert "# WaveMind Strict Evidence Readiness" in report


def test_checked_in_strict_evidence_readiness_artifacts_are_present():
    payload = json.loads(
        Path("benchmarks/strict_evidence_readiness_results.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = Path("benchmarks/STRICT_EVIDENCE_READINESS.md").read_text(
        encoding="utf-8"
    )

    assert payload["schema"] == "wavemind.strict_evidence_readiness.v1"
    assert payload["status"] == "pass"
    assert payload["summary"]["target_memories_total"] == 180_000_000
    assert "Safe Dispatch Commands" in markdown
