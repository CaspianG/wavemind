from pathlib import Path


def test_remote_lab_workflow_requires_attestation_and_secret_backed_deploy():
    workflow = Path(".github/workflows/remote-production-lab.yml").read_text(
        encoding="utf-8"
    )
    assert "WAVEMIND_REMOTE_LAB_INVENTORY_JSON" in workflow
    assert "WAVEMIND_REMOTE_SSH_PRIVATE_KEY" in workflow
    assert "WAVEMIND_REMOTE_SSH_KNOWN_HOSTS" in workflow
    assert "WAVEMIND_REMOTE_API_KEY" in workflow
    assert "WAVEMIND_REMOTE_POSTGRES_PASSWORD" in workflow
    assert "remote_lab.py attest" in workflow
    assert "remote_lab.py deploy" in workflow
    assert "remote_lab.py probe" in workflow
    assert "local_http_active_active_smoke.py" in workflow
    assert "remote_lab.py failure-drill" in workflow
    assert "remote_active_active_failure_drill_results.json" in workflow
    assert "Resolve physical failure target" in workflow
    assert "steps.failure-target.outputs.failed_region" in workflow
    assert "ingest-production-evidence" in workflow
    assert "--dry-run" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "StrictHostKeyChecking=no" not in workflow


def test_remote_lab_docs_keep_deployment_and_evidence_claims_separate():
    readme = Path("deploy/remote/README.md").read_text(encoding="utf-8")
    inventory = Path("deploy/remote/inventory.example.json").read_text(encoding="utf-8")
    assert "at least three independently attested Linux hosts" in readme
    assert "Raw `/etc/machine-id` values are hashed" in readme
    assert "not active-active proof by themselves" in readme
    assert '"schema": "wavemind.remote_production_lab.v1"' in inventory
    assert inventory.count('"ssh_host"') == 3
    assert inventory.count('"public_url"') == 3


def test_full_check_runs_real_production_backend_compose_lifecycle():
    workflow = Path(".github/workflows/full-check.yml").read_text(encoding="utf-8")
    assert "docker build --build-arg INSTALL_PRODUCTION=true" in workflow
    assert "deploy/remote/docker-compose.yml up -d --wait" in workflow
    assert "production-query-after-restart.json" in workflow
    assert 'health["backend"] != "qdrant-cosine"' in workflow
    assert "select count(*) from wavemind_memories" in workflow
    assert "redis-cli dbsize" in workflow
    assert "deploy/remote/docker-compose.yml down -v" in workflow
