import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_serverless_admission,
    render_serverless_admission_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "WAVEMIND_SERVERLESS_NODES",
        "WAVEMIND_CLOUD_RUN_PROJECT_ID",
        "WAVEMIND_CLOUD_RUN_REGION",
        "WAVEMIND_CLOUD_RUN_SERVICE",
        "WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER",
        "WAVEMIND_GCP_SERVICE_ACCOUNT",
        "WAVEMIND_API_KEY",
    ):
        env.pop(name, None)
    return env


def _write_remote_serverless_telemetry(
    root: Path,
    *,
    requests_per_second: float = 4000.0,
    p99_request_ms: float = 120.0,
    configured_max_scale: int = 256,
    cold_start_total_ms: float = 900.0,
) -> Path:
    artifact = root / "deploy" / "serverless" / "observed-telemetry.remote.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "schema": "wavemind.managed_serverless_telemetry.v1",
                "generated_at": "2026-07-12T00:00:00Z",
                "source_ref": "a" * 40,
                "execution_id": "managed-serverless-test-1",
                "workflow_run_id": "29200000000",
                "workflow_run_url": "https://github.com/CaspianG/wavemind/actions/runs/29200000000",
                "evidence_source": "github-actions",
                "source": "github-actions-serverless-observed-telemetry",
                "node_mode": "external",
                "provider": "gcp-cloud-run",
                "service_id": "projects/test/locations/us-central1/services/wavemind",
                "deployment_revision": "wavemind-00042-abc",
                "region": "us-central1",
                "provider_control_plane_observed": True,
                "min_instances": 0,
                "capacity_method": "provider-observed",
                "horizontal_capacity_estimate": False,
                "cold_start_measured": True,
                "scale_out_measured": True,
                "scale_to_zero_observed": True,
                "requests": 2000,
                "successes": 2000,
                "provider_request_count": 2000,
                "measured_replicas": 8,
                "scale_out_seconds": 18.0,
                "max_scale_out_seconds": 60.0,
                "provider_metric_types": [
                    "request_count",
                    "request_latency",
                    "container_startup_latency",
                    "container_instance_count",
                ],
                "metric_window_start": "2026-07-12T00:00:00Z",
                "metric_window_end": "2026-07-12T00:10:00Z",
                "requests_per_second": requests_per_second,
                "p99_request_ms": p99_request_ms,
                "cold_start_total_ms": cold_start_total_ms,
                "error_rate": 0.0,
                "max_error_rate": 0.01,
                "configured_max_scale": configured_max_scale,
                "target_rps": requests_per_second,
                "target_p99_ms": p99_request_ms,
                "cold_start_budget_ms": cold_start_total_ms + 100.0,
                "observed_slo_pass": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return artifact


def test_serverless_admission_blocks_without_remote_telemetry():
    payload = evaluate_serverless_admission(
        PROJECT_ROOT,
        allow_plan_only=False,
        env={},
    )

    assert payload["schema"] == "wavemind.serverless_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "remote_serverless_telemetry_required"
    assert payload["required_evidence"]["id"] == "serverless_remote_telemetry"
    assert payload["required_evidence"]["status"] == "action_required"
    assert payload["required_evidence"]["artifact"] == (
        "deploy/serverless/observed-telemetry.remote.json"
    )
    assert "WAVEMIND_CLOUD_RUN_PROJECT_ID" in payload["summary"]["missing_env"]
    assert "WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER" in payload["summary"]["missing_env"]
    assert any("strict_status=action_required" in item for item in payload["issues"])


def test_serverless_admission_allows_plan_only_reporting():
    payload = evaluate_serverless_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "action_required"
    assert payload["summary"]["preflight_status"] == "action_required"
    assert payload["summary"]["requested_evidence_status"] == "action_required"
    assert payload["target_rps"] == 3200.0
    assert payload["target_p99_ms"] == 500.0
    assert payload["max_scale"] == 256


def test_serverless_admission_accepts_matching_requested_remote_telemetry(tmp_path):
    _write_remote_serverless_telemetry(tmp_path)

    payload = evaluate_serverless_admission(
        tmp_path,
        target_rps=3200.0,
        target_p99_ms=500.0,
        max_scale=256,
        cold_start_budget_ms=1500.0,
        env={},
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["requested_evidence"]["status"] == "pass"


def test_serverless_admission_blocks_remote_telemetry_below_requested_rps(tmp_path):
    _write_remote_serverless_telemetry(tmp_path, requests_per_second=1000.0)

    payload = evaluate_serverless_admission(
        tmp_path,
        target_rps=3200.0,
        target_p99_ms=500.0,
        max_scale=256,
        cold_start_budget_ms=1500.0,
        allow_plan_only=True,
        env={},
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "fail"
    assert any("requests_per_second must be >= 3200" in issue for issue in payload["issues"])


def test_serverless_admission_rejects_extrapolated_manual_telemetry(tmp_path):
    artifact = _write_remote_serverless_telemetry(tmp_path)
    telemetry = json.loads(artifact.read_text(encoding="utf-8"))
    telemetry["capacity_method"] = "extrapolated"
    telemetry["horizontal_capacity_estimate"] = True
    telemetry["cold_start_measured"] = False
    telemetry["scale_out_measured"] = False
    telemetry["scale_to_zero_observed"] = False
    artifact.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")

    payload = evaluate_serverless_admission(
        tmp_path,
        allow_plan_only=True,
        env={},
    )

    assert payload["admitted"] is False
    issues = payload["requested_evidence"]["issues"]
    assert "capacity_method must be provider-observed" in issues
    assert "horizontal_capacity_estimate must be false" in issues
    assert "cold_start_measured must be true" in issues
    assert "scale_out_measured must be true" in issues
    assert "scale_to_zero_observed must be true" in issues


def test_serverless_admission_markdown_documents_claim_boundary():
    payload = evaluate_serverless_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )
    markdown = render_serverless_admission_markdown(payload)

    assert "# WaveMind Serverless Admission" in markdown
    assert "managed/serverless production" in markdown
    assert "deploy/serverless/observed-telemetry.remote.json" in markdown
    assert "Loopback telemetry" in markdown
    assert "Requested Evidence" in markdown


def test_serverless_admission_cli_writes_artifacts(tmp_path):
    output = tmp_path / "serverless.json"
    markdown_output = tmp_path / "serverless.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "serverless-admission",
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
    assert file_payload["schema"] == "wavemind.serverless_admission.v1"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Serverless Admission"
    )


def test_serverless_admission_cli_fail_on_blocked_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "serverless-admission",
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
