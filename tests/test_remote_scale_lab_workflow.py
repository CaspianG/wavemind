from pathlib import Path


def test_remote_scale_workflow_enforces_private_attested_100m_path():
    workflow = Path(".github/workflows/remote-qdrant-100m-lab.yml").read_text(
        encoding="utf-8"
    )

    assert "WAVEMIND_REMOTE_SCALE_INVENTORY_JSON" in workflow
    assert "WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY" in workflow
    assert "WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS" in workflow
    assert "WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY" in workflow
    assert "Attest eight independent shard machines and capacity" in workflow
    assert "Require durable self-hosted runner" in workflow
    assert "runner_label must start with self-hosted" in workflow
    assert "Open pinned SSH tunnels to private shards" in workflow
    assert "--sizes 100000000" in workflow
    assert "--queries 5000" in workflow
    assert "--target-recall 0.95" in workflow
    assert "--target-p99-ms 100" in workflow
    assert "--checkpoint-path" in workflow
    assert "ingest-production-evidence" in workflow
    assert "remote-qdrant-100m-checkpoint" in workflow
    assert "Close SSH tunnels" in workflow
    assert "close-tunnels" in workflow
    assert "StrictHostKeyChecking=no" not in workflow


def test_remote_scale_compose_never_exposes_qdrant_publicly():
    compose = Path("deploy/remote-scale/docker-compose.yml").read_text(encoding="utf-8")

    assert '127.0.0.1:${QDRANT_PORT:-6333}:6333' in compose
    assert '"0.0.0.0:' not in compose
    assert "QDRANT__SERVICE__API_KEY" in compose
