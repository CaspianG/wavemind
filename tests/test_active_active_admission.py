import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_active_active_admission,
    render_active_active_admission_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _remote_region_env() -> dict[str, str]:
    return {
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS": ",".join(
            [
                "us=https://wm-us.staging.internal",
                "eu=https://wm-eu.staging.internal",
                "ap=https://wm-ap.staging.internal",
            ]
        ),
        "WAVEMIND_API_KEY": "test-key",
    }


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS",
        "WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON",
    ):
        env.pop(key, None)
    return env


def _write_remote_active_active_artifact(
    root: Path,
    *,
    regions: int = 3,
    namespaces: int = 16,
    p99_ms: float = 900.0,
) -> Path:
    artifact = root / "benchmarks" / "external_http_active_active_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": {
            "name": "local_http_active_active_smoke",
            "source": "external-regions",
            "deployment_id": "staging-active-active-001",
            "environment": "staging",
            "evidence_source": "github-actions-workflow",
            "region_count": regions,
            "region_ids": [f"region-{index:03d}" for index in range(regions)],
            "replicas_per_region": None,
            "namespace_prefix": "tenant:remote-active-active",
            "namespace_count": namespaces,
            "duration_ms": 1234.5,
        },
        "results": [
            {
                "engine": "WaveMind real HTTP active-active service-region sync",
                "region_count": regions,
                "namespaces": namespaces,
                "writes": regions * namespaces,
                "sync_cycles": 3,
                "pair_syncs": regions * (regions - 1) * namespaces,
                "cursor_count": regions * namespaces,
                "records_imported": regions * namespaces,
                "tombstones_imported": regions,
                "deleted_records": regions,
                "field_keys_exported": regions * namespaces,
                "final_noop_records_imported": 0,
                "final_noop_failed_pairs": 0,
                "convergence_rate": 1.0,
                "delete_suppression_rate": 1.0,
                "success_rate": 1.0,
                "failed_pairs": 0,
                "has_more_pairs": 0,
                "avg_sync_ms": 25.0,
                "p99_sync_ms": 75.0,
                "avg_operation_ms": 12.0,
                "p99_operation_ms": p99_ms,
                "slo_pass": True,
            }
        ],
    }
    artifact.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return artifact


def test_active_active_admission_blocks_without_external_region_evidence():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=False,
        env={},
    )

    assert payload["schema"] == "wavemind.active_active_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "external_active_active_evidence_required"
    assert payload["required_evidence"]["id"] == "external_http_active_active"
    assert payload["required_evidence"]["status"] == "action_required"
    assert payload["required_evidence"]["artifact"] == (
        "benchmarks/external_http_active_active_results.json"
    )
    assert "WAVEMIND_ACTIVE_ACTIVE_REGIONS" in payload["summary"]["missing_env"]
    assert any("strict_status=action_required" in item for item in payload["issues"])


def test_active_active_admission_admits_matching_remote_region_evidence(tmp_path):
    _write_remote_active_active_artifact(tmp_path)

    payload = evaluate_active_active_admission(
        tmp_path,
        min_regions=3,
        namespace_count=16,
        p99_slo_ms=1500.0,
        env=_remote_region_env(),
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["requested_evidence"]["status"] == "pass"
    assert payload["requested_evidence"]["min_regions"] == 3
    assert payload["requested_evidence"]["namespace_count"] == 16
    assert payload["requested_evidence"]["p99_slo_ms"] == 1500.0
    assert payload["issues"] == []


def test_active_active_admission_blocks_when_artifact_is_too_small_for_rollout(tmp_path):
    _write_remote_active_active_artifact(tmp_path, regions=3, namespaces=16, p99_ms=900.0)

    payload = evaluate_active_active_admission(
        tmp_path,
        min_regions=5,
        namespace_count=32,
        p99_slo_ms=500.0,
        allow_plan_only=False,
        env=_remote_region_env(),
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "fail"
    assert payload["requested_evidence"]["status"] == "fail"
    assert "region_count must be >= 5" in payload["requested_evidence"]["issues"]
    assert "namespace_count must be >= 32" in payload["requested_evidence"]["issues"]
    assert "p99_operation_ms above SLO" in payload["requested_evidence"]["issues"]
    assert any("requested_evidence_status=fail" in item for item in payload["issues"])


def test_active_active_admission_allows_plan_only_reporting():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "action_required"
    assert payload["summary"]["preflight_status"] == "action_required"
    assert payload["next_actions"]


def test_active_active_admission_markdown_documents_claim_boundary():
    payload = evaluate_active_active_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )
    markdown = render_active_active_admission_markdown(payload)

    assert "# WaveMind Active-Active Admission" in markdown
    assert "remote multi-region active-active" in markdown
    assert "benchmarks/external_http_active_active_results.json" in markdown
    assert "Local loopback profiles" in markdown
    assert "Requested Evidence" in markdown


def test_active_active_admission_cli_writes_artifacts(tmp_path):
    output = tmp_path / "active-active.json"
    markdown_output = tmp_path / "active-active.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "active-active-admission",
            "--root",
            str(PROJECT_ROOT),
            "--allow-plan-only",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "plan_only"
    assert file_payload["schema"] == "wavemind.active_active_admission.v1"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Active-Active Admission"
    )


def test_active_active_admission_cli_fail_on_blocked_exits_nonzero(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "active-active-admission",
            "--root",
            str(PROJECT_ROOT),
            "--fail-on-blocked",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
