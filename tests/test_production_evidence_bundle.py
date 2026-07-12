import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    build_release_claims_manifest,
    build_scale_gap_manifest,
    evaluate_production_evidence_bundle,
    render_release_claims_markdown,
    render_bundle_markdown,
    render_scale_gap_markdown,
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
        "WAVEMIND_REMOTE_LAB_INVENTORY_JSON": json.dumps(_remote_inventory()),
        "WAVEMIND_REMOTE_SSH_PRIVATE_KEY": "test-private-key",
        "WAVEMIND_REMOTE_SSH_KNOWN_HOSTS": "test-known-hosts",
        "WAVEMIND_REMOTE_API_KEY": "test-remote-api-key",
        "WAVEMIND_REMOTE_POSTGRES_PASSWORD": "test-postgres-password",
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


def _remote_inventory():
    return {
        "schema": "wavemind.remote_production_lab.v1",
        "deployment_id": "wm-regions-2026-07",
        "environment": "staging",
        "source": "independent-cloud-vms",
        "image": "ghcr.io/caspiang/wavemind:sha-0123456789abcdef",
        "regions": [
            {
                "id": f"region-{index}",
                "ssh_host": f"wavemind-{index}",
                "public_url": f"https://wm-{index}.staging.internal",
                "region": f"region-{index}",
                "zone": f"zone-{index}",
                "provider": f"provider-{index}",
            }
            for index in range(3)
        ],
    }


def test_production_evidence_bundle_keeps_claims_limited_without_remote_artifacts():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env={})

    assert payload["schema"] == "wavemind.production_evidence_bundle.v1"
    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["strict_overall_status"] == "action_required"
    assert payload["summary"]["production_readiness_status"] == "pass"
    assert payload["summary"]["artifact_audit_status"] == "pass"
    assert payload["summary"]["production_scale_run_contract_status"] == "available"
    assert payload["summary"]["production_scale_run_profile_count"] == 5
    assert payload["summary"]["production_scale_run_target_memories_total"] == 180_000_000
    assert payload["summary"]["strict_pass_count"] == 5
    assert payload["summary"]["next_action_count"] == 3
    assert payload["production_scale_run_contract"]["status"] == "available"
    assert payload["production_scale_run_contract"]["profile_count"] == 5

    claims = {row["claim"]: row for row in payload["claim_boundaries"]}
    assert claims["Core library/API readiness"]["status"] == "unlocked"
    assert claims["Large-N production run contracts"]["status"] == "available"
    assert claims["Non-loopback Kubernetes service-node cluster SLO"]["status"] == "unlocked"
    assert claims["10M-100M service-backed production scale"]["status"] == "locked"


def test_production_evidence_bundle_uses_preflight_for_next_actions(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env=_ready_env(tmp_path))

    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["preflight_overall_status"] == "ready"
    assert payload["summary"]["preflight_ready_count"] == 8

    by_id = {row["id"]: row for row in payload["next_actions"]}
    assert "external_http_cluster" not in by_id
    assert by_id["hundred_million_remote_load"]["preflight_status"] == "ready"


def test_production_evidence_bundle_markdown_lists_claim_boundaries():
    root = Path(__file__).resolve().parents[1]
    payload = evaluate_production_evidence_bundle(root, env={})
    markdown = render_bundle_markdown(payload)

    assert "# WaveMind Production Evidence Bundle" in markdown
    assert "Claim Boundaries" in markdown
    assert "Remote multi-region active-active convergence" in markdown
    assert "Production Scale Run Contract" in markdown
    assert "qdrant-sharded-100m" in markdown
    assert "Next Actions" in markdown


def test_release_claims_manifest_allows_core_release_without_strict_claims():
    root = Path(__file__).resolve().parents[1]
    payload = build_release_claims_manifest(root, env={})

    assert payload["schema"] == "wavemind.release_claims.v1"
    assert payload["release_status"] == "core_release_ready"
    assert payload["claim_status"] == "claims_limited"
    assert payload["summary"]["production_readiness_status"] == "pass"
    assert payload["summary"]["artifact_audit_status"] == "pass"
    assert payload["summary"]["allowed_claim_count"] >= 1
    assert payload["summary"]["locked_claim_count"] >= 1

    allowed = {row["claim"]: row for row in payload["allowed_claims"]}
    locked = {row["claim"]: row for row in payload["locked_claims"]}
    assert allowed["Core library/API readiness"]["status"] == "unlocked"
    assert allowed["Large-N production run contracts"]["status"] == "available"
    assert locked["10M-100M service-backed production scale"]["status"] == "locked"
    assert payload["next_actions"]


def test_release_claims_markdown_lists_allowed_and_locked_claims():
    root = Path(__file__).resolve().parents[1]
    payload = build_release_claims_manifest(root, env={})
    markdown = render_release_claims_markdown(payload)

    assert "# WaveMind Release Claims" in markdown
    assert "Allowed Claims" in markdown
    assert "Locked Claims" in markdown
    assert "core_release_ready" in markdown
    assert "10M-100M service-backed production scale" in markdown


def test_scale_gap_manifest_tracks_large_n_proof_gaps():
    root = Path(__file__).resolve().parents[1]
    payload = build_scale_gap_manifest(root, env={})

    assert payload["schema"] == "wavemind.scale_gap.v1"
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["total_profiles"] == 5
    assert payload["summary"]["planned_target_memories"] == 180_000_000
    assert payload["summary"]["complete_count"] == 4
    assert payload["summary"]["proven_target_memories"] == 80_000_000
    assert payload["summary"]["nearest_baseline_max_memories"] >= 10_000_000

    gaps = {row["profile"]: row for row in payload["profile_gaps"]}
    assert set(gaps) == {
        "qdrant-10m",
        "qdrant-sharded-10m",
        "pgvector-10m",
        "faiss-ivfpq-50m",
        "qdrant-sharded-100m",
    }
    assert gaps["qdrant-10m"]["requirement_id"] == "qdrant_10m_service"
    assert gaps["qdrant-10m"]["output_artifact"].endswith(
        "production_streaming_load_qdrant_10m_results.json"
    )
    assert gaps["qdrant-10m"]["status"] == "complete"
    assert gaps["qdrant-10m"]["strict_status"] == "pass"
    assert gaps["qdrant-sharded-10m"]["status"] == "complete"
    assert gaps["qdrant-sharded-10m"]["strict_status"] == "pass"
    assert gaps["pgvector-10m"]["status"] == "complete"
    assert gaps["pgvector-10m"]["strict_status"] == "pass"
    assert gaps["qdrant-10m"]["nearest_baseline"]["vectors"] >= 1_000_000
    assert gaps["faiss-ivfpq-50m"]["nearest_baseline"]["vectors"] >= 10_000_000
    assert gaps["faiss-ivfpq-50m"]["target_gap_multiplier"] == 5.0
    assert gaps["faiss-ivfpq-50m"]["status"] == "complete"
    assert "WAVEMIND_QDRANT_URL" in gaps["qdrant-10m"]["missing_env"]
    assert gaps["qdrant-sharded-100m"]["status"] == "blocked_by_env"


def test_scale_gap_markdown_lists_profiles_and_commands():
    root = Path(__file__).resolve().parents[1]
    payload = build_scale_gap_manifest(root, env={})
    markdown = render_scale_gap_markdown(payload)

    assert "# WaveMind Scale Gap Matrix" in markdown
    assert "qdrant-sharded-100m" in markdown
    assert "production_streaming_load_qdrant_sharded_100m_results.json" in markdown
    assert "python benchmarks/production_streaming_load_benchmark.py" in markdown


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


def test_cli_release_claims_writes_reports_and_allows_core_release(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "release_claims.json"
    markdown = tmp_path / "release_claims.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "release-claims",
            "--root",
            str(project_root),
            "--write-artifacts",
            "--fail-on-blocked",
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

    assert "release_status: core_release_ready" in result.stdout
    assert payload["schema"] == "wavemind.release_claims.v1"
    assert payload["release_status"] == "core_release_ready"
    assert "# WaveMind Release Claims" in report


def test_cli_release_claims_strict_exits_nonzero():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "release-claims",
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
    assert payload["release_status"] == "core_release_ready"


def test_cli_scale_gap_writes_reports(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "scale_gap.json"
    markdown = tmp_path / "scale_gap.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "scale-gap",
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

    assert "overall_status: action_required" in result.stdout
    assert payload["schema"] == "wavemind.scale_gap.v1"
    assert "# WaveMind Scale Gap Matrix" in report


def test_cli_scale_gap_fail_on_action_required_exits_nonzero():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "scale-gap",
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
