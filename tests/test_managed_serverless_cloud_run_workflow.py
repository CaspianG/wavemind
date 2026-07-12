from pathlib import Path

import yaml


def test_managed_serverless_cloud_run_workflow_uses_oidc_and_provider_metrics():
    path = Path(".github/workflows/managed-serverless-cloud-run.yml")
    workflow = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)

    assert parsed["permissions"]["id-token"] == "write"
    assert "google-github-actions/auth@v3" in workflow
    assert "google-github-actions/setup-gcloud@v3" in workflow
    assert "WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER" in workflow
    assert "WAVEMIND_GCP_SERVICE_ACCOUNT" in workflow
    assert "idle_wait_seconds" in workflow
    assert 'test "$IDLE_WAIT_SECONDS" -ge 600' in workflow
    assert "cloud_run_evidence.py" in workflow
    assert "Wait for Cloud Monitoring metric visibility" in workflow
    assert workflow.index("WAVEMIND_METRIC_WINDOW_START") < workflow.index("sleep \"$IDLE_WAIT_SECONDS\"")
    assert workflow.index("sleep 180") < workflow.index("WAVEMIND_METRIC_WINDOW_END")
    assert "ingest-production-evidence" in workflow
    assert "--dry-run" in workflow
    assert "credentials_json" not in workflow
