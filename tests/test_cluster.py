import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import ClusterNode, build_cluster_plan


def run_cli(*args):
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "wavemind", *args],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def test_cluster_plan_places_replicas_on_distinct_nodes():
    nodes = [
        ClusterNode(id="node-a", address="10.0.0.1:8000"),
        ClusterNode(id="node-b", address="10.0.0.2:8000"),
        ClusterNode(id="node-c", address="10.0.0.3:8000"),
    ]
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(64)],
        nodes=nodes,
        replication_factor=2,
    )

    assert len(plan.placements) == 64
    assert all(len(set(placement.replicas)) == 2 for placement in plan.placements)
    assert set(plan.node_load) == {"node-a", "node-b", "node-c"}
    assert sum(plan.primary_load.values()) == 64
    assert not plan.warnings


def test_cluster_plan_survives_single_node_loss_with_replication():
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(20)],
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=2,
    )

    loss = plan.simulate_node_loss("node-a")

    assert loss["availability_ratio"] == 1.0
    assert loss["unavailable_namespaces"] == 0


def test_cluster_plan_prefers_distinct_zones_and_reports_quorum():
    nodes = [
        ClusterNode(id="node-a", address="10.0.0.1:8000", zone="zone-a"),
        ClusterNode(id="node-b", address="10.0.0.2:8000", zone="zone-b"),
        ClusterNode(id="node-c", address="10.0.0.3:8000", zone="zone-c"),
        ClusterNode(id="node-d", address="10.0.0.4:8000", zone="zone-a"),
    ]
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(128)],
        nodes=nodes,
        replication_factor=3,
    )
    zones_by_id = {node.id: node.zone for node in nodes}

    assert all(
        len({zones_by_id[node_id] for node_id in placement.replicas}) == 3
        for placement in plan.placements
    )
    quorum = plan.quorum_report()
    assert quorum["write_quorum"] == 2
    assert quorum["read_quorum"] == 1
    assert quorum["node_loss_min_availability"] == 1.0
    assert quorum["zone_loss_min_availability"] == 1.0


def test_cluster_plan_rejects_impossible_replication():
    with pytest.raises(ValueError, match="replication_factor"):
        build_cluster_plan(
            namespaces=["tenant:a"],
            nodes=["node-a"],
            replication_factor=2,
        )


def test_cluster_plan_emits_kubernetes_statefulset_manifest():
    plan = build_cluster_plan(
        namespaces=["tenant:a"],
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=2,
    )
    manifest = plan.kubernetes_manifest(image="wavemind:test", storage_size="5Gi")

    assert manifest["kind"] == "StatefulSet"
    assert manifest["spec"]["replicas"] == 3
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "wavemind:test"
    assert {"name": "WAVEMIND_REPLICATION_FACTOR", "value": "2"} in container["env"]


def test_cli_cluster_plan_outputs_json():
    result = run_cli(
        "cluster-plan",
        "--namespace-count",
        "4",
        "--node",
        "node-a=10.0.0.1:8000",
        "--node",
        "node-b=10.0.0.2:8000",
        "--replication-factor",
        "2",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["replication_factor"] == 2
    assert len(payload["placements"]) == 4
    assert set(payload["node_load"]) == {"node-a", "node-b"}
