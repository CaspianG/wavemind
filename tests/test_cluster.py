import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import (
    ClusterNode,
    NamespaceMove,
    build_cluster_autoscale_plan,
    build_cluster_plan,
    build_cluster_rebalance_plan,
)


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


def test_cluster_plan_reports_placement_health():
    nodes = [
        ClusterNode(id="node-a", address="10.0.0.1:8000", zone="zone-a"),
        ClusterNode(id="node-b", address="10.0.0.2:8000", zone="zone-b"),
        ClusterNode(id="node-c", address="10.0.0.3:8000", zone="zone-c"),
        ClusterNode(id="node-d", address="10.0.0.4:8000", zone="zone-d"),
    ]
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(512)],
        nodes=nodes,
        replication_factor=3,
    )

    health = plan.placement_health_report()
    payload = plan.as_dict()

    assert health["namespace_count"] == 512
    assert health["node_count"] == 4
    assert health["zone_count"] == 4
    assert health["failure_domain_count"] == 4
    assert health["distinct_replica_rate"] == 1.0
    assert health["zone_spread_rate"] == 1.0
    assert health["primary_load_skew"] <= 1.25
    assert health["replica_load_skew"] <= 1.25
    assert payload["placement_health"] == health


def test_cluster_plan_uses_nodes_as_failure_domains_without_zones():
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(64)],
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=2,
    )

    health = plan.placement_health_report()

    assert health["zone_count"] == 0
    assert health["failure_domain_count"] == 3
    assert health["distinct_replica_rate"] == 1.0
    assert health["zone_spread_rate"] == 1.0


def test_cluster_plan_reports_stable_scale_out_movement():
    namespaces = [f"tenant:{index}" for index in range(1024)]
    source = build_cluster_plan(
        namespaces=namespaces,
        nodes=[
            ClusterNode(id="node-a", address="node-a", zone="zone-a"),
            ClusterNode(id="node-b", address="node-b", zone="zone-b"),
            ClusterNode(id="node-c", address="node-c", zone="zone-c"),
            ClusterNode(id="node-d", address="node-d", zone="zone-d"),
        ],
        replication_factor=3,
    )
    target = build_cluster_plan(
        namespaces=namespaces,
        nodes=[
            ClusterNode(id="node-a", address="node-a", zone="zone-a"),
            ClusterNode(id="node-b", address="node-b", zone="zone-b"),
            ClusterNode(id="node-c", address="node-c", zone="zone-c"),
            ClusterNode(id="node-d", address="node-d", zone="zone-d"),
            ClusterNode(id="node-e", address="node-e", zone="zone-e"),
        ],
        replication_factor=3,
    )

    report = source.movement_report(target)

    assert report["shared_namespace_count"] == 1024
    assert report["new_node_count"] == 1
    assert report["removed_node_count"] == 0
    assert report["replica_set_moves"] > 0
    assert report["moved_to_new_node"] == report["replica_set_moves"]
    assert 0.0 < report["replica_set_movement_ratio"] < 0.75


def test_weighted_rendezvous_prefers_larger_nodes_without_duplicate_replicas():
    nodes = [
        ClusterNode(id="small-a", address="small-a", zone="zone-a", weight=1.0),
        ClusterNode(id="small-b", address="small-b", zone="zone-b", weight=1.0),
        ClusterNode(id="large", address="large", zone="zone-c", weight=4.0),
    ]
    plan = build_cluster_plan(
        namespaces=[f"tenant:{index}" for index in range(4000)],
        nodes=nodes,
        replication_factor=1,
    )
    health = plan.placement_health_report()
    primary_load = plan.primary_load

    assert primary_load["large"] > primary_load["small-a"] * 2.5
    assert primary_load["large"] > primary_load["small-b"] * 2.5
    assert health["distinct_replica_rate"] == 1.0
    assert health["max_primary_weight_error"] <= 0.12


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


def test_cluster_plan_emits_repair_cronjob_manifest():
    plan = build_cluster_plan(
        namespaces=["tenant:a", "tenant:b"],
        nodes=[
            ClusterNode(id="node-a", address="https://wm-a.internal", zone="zone-a"),
            ClusterNode(id="node-b", address="https://wm-b.internal", zone="zone-b"),
            ClusterNode(id="node-c", address="https://wm-c.internal", zone="zone-c"),
        ],
        replication_factor=3,
    )

    manifest = plan.kubernetes_repair_cronjob(
        image="wavemind:test",
        schedule="*/5 * * * *",
        api_key_secret="wavemind-api-key",
        repair_limit=250,
        include_expired=True,
        tags=("ops",),
    )

    assert manifest["kind"] == "CronJob"
    assert manifest["spec"]["schedule"] == "*/5 * * * *"
    pod_spec = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod_spec["restartPolicy"] == "OnFailure"
    container = pod_spec["containers"][0]
    assert container["image"] == "wavemind:test"
    assert container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "wavemind-api-key",
        "key": "api-key",
    }
    args = container["args"]
    assert args[:7] == [
        "cluster-repair",
        "--replication-factor",
        "3",
        "--write-quorum",
        "2",
        "--read-quorum",
        "1",
    ]
    assert ["--node", "node-a=https://wm-a.internal"] == args[args.index("--node") : args.index("--node") + 2]
    assert args.count("--namespace") == 2
    assert "tenant:a" in args
    assert "tenant:b" in args
    assert "--include-expired" in args
    assert ["--tag", "ops"] == args[args.index("--tag") : args.index("--tag") + 2]


def test_cluster_plan_repair_cronjob_requires_namespaces():
    plan = build_cluster_plan(
        namespaces=[],
        nodes=["node-a", "node-b"],
        replication_factor=2,
    )

    with pytest.raises(ValueError, match="at least one planned namespace"):
        plan.kubernetes_repair_cronjob()


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


def test_cli_cluster_plan_outputs_repair_cronjob():
    result = run_cli(
        "cluster-plan",
        "--namespace",
        "tenant:a",
        "--node",
        "node-a=https://wm-a.internal",
        "--node",
        "node-b=https://wm-b.internal",
        "--node",
        "node-c=https://wm-c.internal",
        "--replication-factor",
        "3",
        "--repair-cronjob",
        "--repair-schedule",
        "*/10 * * * *",
        "--repair-api-key-secret",
        "wavemind-api-key",
        "--repair-limit",
        "500",
        "--repair-tag",
        "ops",
        "--json",
    )
    payload = json.loads(result.stdout)
    cronjob = payload["repair_cronjob"]

    assert cronjob["kind"] == "CronJob"
    assert cronjob["spec"]["schedule"] == "*/10 * * * *"
    container = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert container["env"][0]["valueFrom"]["secretKeyRef"]["name"] == "wavemind-api-key"
    assert "--namespace" in container["args"]
    assert "tenant:a" in container["args"]
    assert "--tag" in container["args"]
    assert "ops" in container["args"]


def test_cluster_autoscale_plan_adds_nodes_and_plans_namespace_moves():
    plan = build_cluster_autoscale_plan(
        namespaces=[f"tenant:{index}" for index in range(128)],
        nodes=[
            ClusterNode(id="node-a", address="https://wm-a.internal", zone="zone-a"),
            ClusterNode(id="node-b", address="https://wm-b.internal", zone="zone-b"),
            ClusterNode(id="node-c", address="https://wm-c.internal", zone="zone-c"),
        ],
        replication_factor=3,
        target_memories=10_000_000,
        max_memories_per_node=1_000_000,
        headroom=0.70,
        node_prefix="wm",
        address_template="https://{node_id}.internal",
        zones=("zone-a", "zone-b", "zone-c"),
        max_moves=10,
    )
    payload = plan.as_dict()

    assert plan.status == "scale_required"
    assert plan.required_nodes >= 43
    assert plan.additional_nodes == plan.required_nodes - 3
    assert len(payload["target_nodes"]) == plan.required_nodes
    assert payload["target_nodes"][3]["id"] == "wm-1"
    assert payload["target_nodes"][3]["address"] == "https://wm-1.internal"
    assert plan.target_max_node_memories <= int(1_000_000 * 0.70)
    assert len(plan.moves) == 10
    assert plan.omitted_moves > 0
    assert any(f"Add {plan.additional_nodes} node" in action for action in plan.actions)


def test_cluster_rebalance_plan_batches_moves_with_quorum_safety():
    autoscale = build_cluster_autoscale_plan(
        namespaces=[f"tenant:{index}" for index in range(64)],
        nodes=[
            ClusterNode(id="node-a", address="https://wm-a.internal", zone="zone-a"),
            ClusterNode(id="node-b", address="https://wm-b.internal", zone="zone-b"),
            ClusterNode(id="node-c", address="https://wm-c.internal", zone="zone-c"),
        ],
        replication_factor=3,
        target_memories=8_000_000,
        max_memories_per_node=1_000_000,
        headroom=0.70,
        node_prefix="wm",
        address_template="https://{node_id}.internal",
        zones=("zone-a", "zone-b", "zone-c"),
        max_moves=64,
    )

    rebalance = autoscale.rebalance_plan(batch_size=4, max_node_moves_per_batch=4)
    payload = rebalance.as_dict()

    assert rebalance.status == "ready"
    assert rebalance.write_quorum == 2
    assert rebalance.read_quorum == 1
    assert rebalance.full_plan
    assert rebalance.move_count == len(autoscale.moves)
    assert payload["batch_count"] >= 1
    assert payload["max_batch_node_pressure"] <= 4
    assert all(len(batch.moves) <= 4 for batch in rebalance.batches)
    assert all(batch.requires_checkpoint for batch in rebalance.batches)
    assert all(batch.requires_repair for batch in rebalance.batches)
    assert all(batch.requires_validation for batch in rebalance.batches)
    assert any("cluster-repair" in action for action in rebalance.actions)


def test_cluster_rebalance_plan_rejects_drain_node_targets():
    plan = build_cluster_rebalance_plan(
        [
            NamespaceMove(
                namespace="tenant:a",
                from_primary="node-a",
                to_primary="node-b",
                from_replicas=("node-a", "node-c"),
                to_replicas=("node-b", "node-drain"),
            )
        ],
        replication_factor=2,
        batch_size=10,
        drain_nodes=("node-drain",),
    )

    assert plan.status == "action_required"
    assert plan.write_quorum == 2
    assert plan.drain_nodes == ("node-drain",)
    assert any("targets drain node" in warning for warning in plan.warnings)
    assert any("drain nodes" in action for action in plan.actions)


def test_cluster_autoscale_plan_reports_ok_when_capacity_is_enough():
    plan = build_cluster_autoscale_plan(
        namespaces=[f"tenant:{index}" for index in range(32)],
        nodes=[
            ClusterNode(id="node-a", address="node-a", zone="zone-a"),
            ClusterNode(id="node-b", address="node-b", zone="zone-b"),
            ClusterNode(id="node-c", address="node-c", zone="zone-c"),
        ],
        replication_factor=3,
        target_memories=100_000,
        max_memories_per_node=1_000_000,
    )

    assert plan.status == "ok"
    assert plan.additional_nodes == 0
    assert not plan.warnings


def test_cli_cluster_autoscale_plan_outputs_json():
    result = run_cli(
        "cluster-autoscale-plan",
        "--namespace-count",
        "64",
        "--node",
        "node-a=https://wm-a.internal",
        "--node",
        "node-b=https://wm-b.internal",
        "--node",
        "node-c=https://wm-c.internal",
        "--replication-factor",
        "3",
        "--target-memories",
        "10000000",
        "--max-memories-per-node",
        "1000000",
        "--node-prefix",
        "wm",
        "--zone",
        "zone-a",
        "--zone",
        "zone-b",
        "--zone",
        "zone-c",
        "--max-moves",
        "5",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "scale_required"
    assert payload["required_nodes"] >= 43
    assert payload["additional_nodes"] == payload["required_nodes"] - 3
    assert len(payload["moves"]) == 5
    assert payload["omitted_moves"] > 0


def test_cli_cluster_autoscale_plan_outputs_rebalance_plan_json():
    result = run_cli(
        "cluster-autoscale-plan",
        "--namespace-count",
        "16",
        "--node",
        "node-a=https://wm-a.internal",
        "--node",
        "node-b=https://wm-b.internal",
        "--node",
        "node-c=https://wm-c.internal",
        "--replication-factor",
        "3",
        "--target-memories",
        "5000000",
        "--max-memories-per-node",
        "1000000",
        "--node-prefix",
        "wm",
        "--zone",
        "zone-a",
        "--zone",
        "zone-b",
        "--zone",
        "zone-c",
        "--max-moves",
        "16",
        "--rebalance-plan",
        "--rebalance-batch-size",
        "2",
        "--rebalance-max-node-moves-per-batch",
        "2",
        "--json",
    )
    payload = json.loads(result.stdout)
    rebalance = payload["rebalance_plan"]

    assert rebalance["status"] == "ready"
    assert rebalance["move_count"] == len(payload["moves"])
    assert rebalance["full_plan"]
    assert rebalance["batch_size"] == 2
    assert rebalance["max_batch_node_pressure"] <= 2
    assert rebalance["write_quorum"] == 2
