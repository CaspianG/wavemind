import json
import subprocess
import sys
from pathlib import Path

import wavemind.remote_scale_lab as scale_lab
from wavemind.remote_scale_lab import (
    _control_socket,
    RemoteQdrantScaleInventory,
    RemoteScaleLabError,
    attest_remote_qdrant_scale_inventory,
    close_remote_qdrant_tunnels,
    deploy_remote_qdrant_scale_inventory,
    open_remote_qdrant_tunnels,
    render_qdrant_env,
    validate_remote_qdrant_scale_attestation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def inventory_payload(*, shard_count=8):
    regions = ("eu-west", "us-east", "ap-south", "eu-central")
    return {
        "schema": "wavemind.remote_qdrant_scale_lab.v1",
        "deployment_id": "wavemind-100m-staging",
        "environment": "staging",
        "source": "independent-cloud-vms",
        "image": "qdrant/qdrant:v1.18.2",
        "target_vectors": 100_000_000,
        "vector_dim": 128,
        "shards": [
            {
                "id": f"shard-{index}",
                "ssh_host": f"wm-qdrant-{index}",
                "region": regions[index % len(regions)],
                "zone": f"zone-{index}",
                "provider": f"provider-{index % len(regions)}",
                "qdrant_port": 6333,
            }
            for index in range(shard_count)
        ],
    }


def test_inventory_requires_real_eight_host_three_region_topology():
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())

    assert len(inventory.shards) == 8
    assert inventory.target_vectors == 100_000_000
    assert inventory.required_disk_per_shard_gb() >= 35
    assert inventory.estimated_application_storage_gb > 230

    too_small = inventory_payload(shard_count=7)
    try:
        RemoteQdrantScaleInventory.from_dict(too_small)
    except RemoteScaleLabError as exc:
        assert "eight shard hosts" in str(exc)
    else:
        raise AssertionError("seven-host inventory must be rejected")


def test_inventory_rejects_mutable_image_and_duplicate_hosts():
    payload = inventory_payload()
    payload["image"] = "qdrant/qdrant:latest"
    try:
        RemoteQdrantScaleInventory.from_dict(payload)
    except RemoteScaleLabError as exc:
        assert "exact Qdrant semver" in str(exc)
    else:
        raise AssertionError("mutable image must be rejected")

    payload = inventory_payload()
    payload["shards"][1]["ssh_host"] = payload["shards"][0]["ssh_host"]
    try:
        RemoteQdrantScaleInventory.from_dict(payload)
    except RemoteScaleLabError as exc:
        assert "unique ssh_host" in str(exc)
    else:
        raise AssertionError("duplicate host must be rejected")


def test_inventory_accepts_digest_pinned_image():
    payload = inventory_payload()
    payload["image"] = "qdrant/qdrant@sha256:" + "a" * 64

    inventory = RemoteQdrantScaleInventory.from_dict(payload)

    assert inventory.image == payload["image"]


def test_attestation_requires_unique_machines_and_capacity():
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())

    def runner(host, command):
        index = int(host.rsplit("-", 1)[1])
        stdout = (
            f"machine-{index}\thost-{index}\t4\t33554432\t52428800\t28.3.0\n"
        )
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    result = attest_remote_qdrant_scale_inventory(inventory, runner=runner)

    assert result["status"] == "pass"
    assert result["summary"]["ready_count"] == 8
    assert result["summary"]["unique_machine_count"] == 8
    assert result["summary"]["total_disk_free_gb"] == 400.0
    assert result["thresholds"]["required_total_disk_gb"] >= 280
    assert result["thresholds"]["min_memory_gb"] == 16.0
    assert validate_remote_qdrant_scale_attestation(result)["status"] == "pass"


def test_attestation_rejects_duplicate_machine_identity_and_low_disk():
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())

    def runner(host, command):
        stdout = "same-machine\thost\t4\t8388608\t1048576\t28.3.0\n"
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    result = attest_remote_qdrant_scale_inventory(inventory, runner=runner)

    assert result["status"] == "fail"
    assert all("duplicate_machine_identity" in row["issues"] for row in result["shards"])
    assert all("insufficient_disk" in row["issues"] for row in result["shards"])
    validation = validate_remote_qdrant_scale_attestation(result)
    assert validation["status"] == "fail"
    assert "remote scale attestation status must be pass" in validation["issues"]


def test_deployment_keeps_qdrant_loopback_only_and_does_not_serialize_key():
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())
    compose = (PROJECT_ROOT / "deploy" / "remote-scale" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    commands = []

    def runner(host, command):
        commands.append((host, command))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    payload = deploy_remote_qdrant_scale_inventory(
        inventory,
        compose_text=compose,
        api_key="super-secret-scale-key",
        runner=runner,
    )

    assert payload["status"] == "pass"
    assert "super-secret-scale-key" not in json.dumps(payload)
    assert '127.0.0.1:${QDRANT_PORT:-6333}:6333' in compose
    env_text = render_qdrant_env(
        inventory,
        inventory.shards[0],
        api_key="super-secret-scale-key",
    )
    assert "QDRANT_API_KEY" in env_text
    assert any("<STDIN:" in command for _, command in commands)
    assert all("super-secret-scale-key" not in command for _, command in commands)


def test_tunnels_require_strict_host_keys_and_hide_api_key(monkeypatch):
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())
    commands = []

    def runner(command):
        commands.append(list(command))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(scale_lab.urllib.request, "urlopen", lambda request, timeout: Response())
    payload = open_remote_qdrant_tunnels(
        inventory,
        api_key="super-secret-scale-key",
        runner=runner,
        probe_timeout_seconds=1,
    )

    assert payload["status"] == "pass"
    assert len(payload["urls"]) == 8
    assert payload["security"]["qdrant_publicly_exposed"] is False
    assert "super-secret-scale-key" not in json.dumps(payload)
    assert all("StrictHostKeyChecking=yes" in command for command in commands)
    assert all("ExitOnForwardFailure=yes" in command for command in commands)


def test_tunnel_cleanup_closes_every_persistent_control_socket(tmp_path):
    inventory = RemoteQdrantScaleInventory.from_dict(inventory_payload())
    commands = []
    for shard in inventory.shards:
        _control_socket(tmp_path, inventory, shard).touch()

    def runner(command):
        commands.append(list(command))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    payload = close_remote_qdrant_tunnels(
        inventory,
        control_dir=tmp_path,
        runner=runner,
    )

    assert payload["status"] == "pass"
    assert len(commands) == 8
    assert all("-O" in command and "exit" in command for command in commands)


def test_remote_scale_cli_plan_is_offline_and_claim_limited(tmp_path):
    inventory = tmp_path / "inventory.json"
    output = tmp_path / "plan.json"
    inventory.write_text(json.dumps(inventory_payload()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "deploy/remote-scale/remote_scale_lab.py",
            "plan",
            "--inventory",
            str(inventory),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["target_vectors"] == 100_000_000
    assert payload["shard_count"] == 8
    assert payload["claim_boundary"].startswith("Validated plan only")
