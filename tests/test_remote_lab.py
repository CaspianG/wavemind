import json
import subprocess
from pathlib import Path

import pytest

from wavemind.remote_lab import (
    RemoteLabError,
    RemoteLabInventory,
    attest_remote_inventory,
    deploy_remote_inventory,
    load_remote_inventory,
    render_region_env,
)


def inventory_payload():
    return {
        "schema": "wavemind.remote_production_lab.v1",
        "deployment_id": "wm-prod-lab",
        "environment": "staging",
        "source": "ssh-remote-production-lab",
        "image": "ghcr.io/caspiang/wavemind:sha-1234567",
        "regions": [
            {
                "id": "eu-west",
                "ssh_host": "wm-eu",
                "public_url": "https://wm-eu.example.com",
                "region": "eu-west",
                "zone": "eu-west-a",
                "provider": "provider-a",
            },
            {
                "id": "us-east",
                "ssh_host": "wm-us",
                "public_url": "https://wm-us.example.com",
                "region": "us-east",
                "zone": "us-east-a",
                "provider": "provider-b",
            },
            {
                "id": "ap-south",
                "ssh_host": "wm-ap",
                "public_url": "https://wm-ap.example.com",
                "region": "ap-south",
                "zone": "ap-south-a",
                "provider": "provider-c",
            },
        ],
    }


def test_inventory_requires_three_unique_non_loopback_regions(tmp_path):
    payload = inventory_payload()
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    inventory = load_remote_inventory(path)
    assert len(inventory.regions) == 3
    assert inventory.active_active_manifest()["source"] == "ssh-remote-production-lab"

    payload["regions"][2]["ssh_host"] = "wm-us"
    with pytest.raises(RemoteLabError, match="unique ssh_host"):
        RemoteLabInventory.from_dict(payload)

    payload = inventory_payload()
    payload["regions"][0]["public_url"] = "http://127.0.0.1:8000"
    with pytest.raises(RemoteLabError, match="loopback"):
        RemoteLabInventory.from_dict(payload)

    payload = inventory_payload()
    payload["image"] = "ghcr.io/caspiang/wavemind:latest"
    with pytest.raises(RemoteLabError, match="immutable"):
        RemoteLabInventory.from_dict(payload)

    payload = inventory_payload()
    payload["regions"][0]["ssh_host"] = "-oProxyCommand=bad"
    with pytest.raises(RemoteLabError, match="invalid SSH host"):
        RemoteLabInventory.from_dict(payload)

    payload = inventory_payload()
    payload["regions"][0]["public_url"] = "https://user:secret@wm-eu.example.com"
    with pytest.raises(RemoteLabError, match="credentials"):
        RemoteLabInventory.from_dict(payload)


def test_attestation_hashes_machine_ids_and_rejects_duplicate_hosts():
    inventory = RemoteLabInventory.from_dict(inventory_payload())
    outputs = {
        "wm-eu": "machine-eu\thost-eu\t4\t8388608\t52428800\t28.3.0\n",
        "wm-us": "machine-us\thost-us\t4\t8388608\t52428800\t28.3.0\n",
        "wm-ap": "machine-ap\thost-ap\t4\t8388608\t52428800\t28.3.0\n",
    }

    def runner(host, command):
        assert "/etc/machine-id" in command
        return subprocess.CompletedProcess([], 0, stdout=outputs[host], stderr="")

    result = attest_remote_inventory(inventory, runner=runner)
    assert result["status"] == "pass"
    assert result["summary"]["unique_machine_count"] == 3
    serialized = json.dumps(result)
    assert "machine-eu" not in serialized
    assert all(len(row["machine_identity_sha256"]) == 64 for row in result["regions"])

    outputs["wm-ap"] = outputs["wm-us"].replace("host-us", "host-ap")
    duplicate = attest_remote_inventory(inventory, runner=runner)
    assert duplicate["status"] == "fail"
    assert any("duplicate_machine_identity" in row["issues"] for row in duplicate["regions"])


def test_attestation_enforces_capacity_and_redacts_errors():
    inventory = RemoteLabInventory.from_dict(inventory_payload())

    def runner(host, command):
        if host == "wm-eu":
            return subprocess.CompletedProcess([], 1, stdout="", stderr="token=super-secret failed")
        return subprocess.CompletedProcess(
            [], 0, stdout=f"machine-{host}\thost-{host}\t1\t1048576\t1048576\t28.3.0\n", stderr=""
        )

    result = attest_remote_inventory(inventory, runner=runner)
    assert result["status"] == "fail"
    assert "super-secret" not in json.dumps(result)
    assert "insufficient_cpu" in result["regions"][1]["issues"]
    assert "insufficient_memory" in result["regions"][1]["issues"]
    assert "insufficient_disk" in result["regions"][1]["issues"]


def test_region_env_quotes_secrets_without_exposing_them_in_deployment_result():
    inventory = RemoteLabInventory.from_dict(inventory_payload())
    env = render_region_env(
        inventory,
        inventory.regions[0],
        api_key="api secret ' value",
        postgres_password="db secret@host:/value",
    )
    assert 'WAVEMIND_API_KEY="api secret \' value"' in env
    assert 'POSTGRES_PASSWORD="db secret@host:/value"' in env
    assert 'POSTGRES_PASSWORD_URLENCODED="db%20secret%40host%3A%2Fvalue"' in env

    calls = []

    def runner(host, command):
        calls.append((host, command))
        return subprocess.CompletedProcess([], 0, stdout="{}", stderr="")

    result = deploy_remote_inventory(
        inventory,
        compose_text="services: {}\n",
        api_key="api secret ' value",
        postgres_password="db secret",
        runner=runner,
    )
    assert result["status"] == "pass"
    assert "api secret" not in json.dumps(result)
    assert "db secret" not in json.dumps(result)
    assert len(calls) == 12


def test_remote_compose_uses_all_production_backends():
    compose = Path("deploy/remote/docker-compose.yml").read_text(encoding="utf-8")
    assert "pgvector/pgvector:pg16" in compose
    assert "qdrant/qdrant:v1.18.2" in compose
    assert "redis:7.4-alpine" in compose
    assert "WAVEMIND_STORE: postgres" in compose
    assert "WAVEMIND_INDEX: qdrant" in compose
    assert "WAVEMIND_POSTGRES_DSN" in compose
    assert "WAVEMIND_QDRANT_URL" in compose
    assert "WAVEMIND_REDIS_URL" in compose
    assert "WAVEMIND_API_KEYS" in compose


def test_remote_lab_plan_cli_is_offline_and_secret_free(tmp_path):
    inventory = tmp_path / "inventory.json"
    output = tmp_path / "plan.json"
    inventory.write_text(json.dumps(inventory_payload()), encoding="utf-8")
    completed = subprocess.run(
        [
            "python",
            "deploy/remote/remote_lab.py",
            "plan",
            "--inventory",
            str(inventory),
            "--output",
            str(output),
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["region_count"] == 3
    assert "WAVEMIND_REMOTE_API_KEY" in payload["required_environment"]
