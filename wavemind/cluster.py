from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class ClusterNode:
    id: str
    address: str
    zone: str | None = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Cluster node id must not be empty")
        if not self.address.strip():
            raise ValueError("Cluster node address must not be empty")
        if self.weight <= 0:
            raise ValueError("Cluster node weight must be positive")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NamespacePlacement:
    namespace: str
    primary: str
    replicas: tuple[str, ...]
    shard_key: str

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "primary": self.primary,
            "replicas": list(self.replicas),
            "shard_key": self.shard_key,
        }


@dataclass(frozen=True)
class ClusterPlan:
    nodes: tuple[ClusterNode, ...]
    replication_factor: int
    placements: tuple[NamespacePlacement, ...]
    warnings: tuple[str, ...] = ()

    @property
    def node_load(self) -> dict[str, int]:
        load = {node.id: 0 for node in self.nodes}
        for placement in self.placements:
            for node_id in placement.replicas:
                load[node_id] += 1
        return load

    @property
    def primary_load(self) -> dict[str, int]:
        load = {node.id: 0 for node in self.nodes}
        for placement in self.placements:
            load[placement.primary] += 1
        return load

    def simulate_node_loss(self, node_id: str) -> dict[str, object]:
        if node_id not in {node.id for node in self.nodes}:
            raise ValueError(f"Unknown cluster node: {node_id}")
        affected = [
            placement.namespace
            for placement in self.placements
            if node_id in placement.replicas
        ]
        unavailable = [
            placement.namespace
            for placement in self.placements
            if node_id in placement.replicas
            and not any(replica != node_id for replica in placement.replicas)
        ]
        total = len(self.placements)
        available_after_loss = total - len(unavailable)
        availability_ratio = 1.0 if total == 0 else available_after_loss / total
        return {
            "lost_node": node_id,
            "affected_namespaces": len(affected),
            "unavailable_namespaces": len(unavailable),
            "available_namespaces": available_after_loss,
            "availability_ratio": availability_ratio,
        }

    def simulate_zone_loss(self, zone: str) -> dict[str, object]:
        node_ids = {node.id for node in self.nodes if node.zone == zone}
        if not node_ids:
            raise ValueError(f"Unknown cluster zone: {zone}")
        affected = [
            placement.namespace
            for placement in self.placements
            if any(node_id in node_ids for node_id in placement.replicas)
        ]
        unavailable = [
            placement.namespace
            for placement in self.placements
            if any(node_id in node_ids for node_id in placement.replicas)
            and not any(replica not in node_ids for replica in placement.replicas)
        ]
        total = len(self.placements)
        available_after_loss = total - len(unavailable)
        availability_ratio = 1.0 if total == 0 else available_after_loss / total
        return {
            "lost_zone": zone,
            "lost_nodes": sorted(node_ids),
            "affected_namespaces": len(affected),
            "unavailable_namespaces": len(unavailable),
            "available_namespaces": available_after_loss,
            "availability_ratio": availability_ratio,
        }

    def quorum_report(self) -> dict[str, object]:
        zones = sorted({node.zone for node in self.nodes if node.zone})
        write_quorum = self.replication_factor // 2 + 1
        read_quorum = 1
        node_losses = [self.simulate_node_loss(node.id) for node in self.nodes]
        zone_losses = [self.simulate_zone_loss(zone) for zone in zones]
        min_node_availability = (
            min(float(loss["availability_ratio"]) for loss in node_losses)
            if node_losses
            else 1.0
        )
        min_zone_availability = (
            min(float(loss["availability_ratio"]) for loss in zone_losses)
            if zone_losses
            else None
        )
        return {
            "replication_factor": self.replication_factor,
            "read_quorum": read_quorum,
            "write_quorum": write_quorum,
            "node_loss_min_availability": min_node_availability,
            "zone_loss_min_availability": min_zone_availability,
            "zones": zones,
            "node_loss": node_losses,
            "zone_loss": zone_losses,
        }

    def kubernetes_manifest(
        self,
        image: str = "wavemind:latest",
        storage_size: str = "20Gi",
    ) -> dict[str, object]:
        replicas = len(self.nodes)
        return {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "wavemind"},
            "spec": {
                "serviceName": "wavemind",
                "replicas": replicas,
                "selector": {"matchLabels": {"app": "wavemind"}},
                "template": {
                    "metadata": {"labels": {"app": "wavemind"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "wavemind",
                                "image": image,
                                "ports": [{"containerPort": 8000, "name": "http"}],
                                "env": [
                                    {"name": "WAVEMIND_CLUSTER_MODE", "value": "namespace-sharded"},
                                    {"name": "WAVEMIND_REPLICATION_FACTOR", "value": str(self.replication_factor)},
                                ],
                                "volumeMounts": [{"name": "state", "mountPath": "/state"}],
                            }
                        ]
                    },
                },
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "state"},
                        "spec": {
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": storage_size}},
                        },
                    }
                ],
            },
        }

    def kubernetes_repair_cronjob(
        self,
        *,
        image: str = "wavemind:latest",
        schedule: str = "*/15 * * * *",
        name: str = "wavemind-cluster-repair",
        api_key_secret: str | None = None,
        api_key_secret_key: str = "api-key",
        repair_limit: int = 1000,
        include_expired: bool = False,
        tags: Iterable[str] = (),
    ) -> dict[str, object]:
        namespaces = [placement.namespace for placement in self.placements]
        if not namespaces:
            raise ValueError("repair CronJob requires at least one planned namespace")
        if repair_limit <= 0:
            raise ValueError("repair_limit must be positive")
        write_quorum = self.replication_factor // 2 + 1
        args = [
            "cluster-repair",
            "--replication-factor",
            str(self.replication_factor),
            "--write-quorum",
            str(write_quorum),
            "--read-quorum",
            "1",
            "--limit",
            str(int(repair_limit)),
            "--json",
        ]
        for node in self.nodes:
            args.extend(["--node", f"{node.id}={node.address}"])
        for namespace in namespaces:
            args.extend(["--namespace", namespace])
        for tag in tags:
            args.extend(["--tag", str(tag)])
        if include_expired:
            args.append("--include-expired")

        container: dict[str, object] = {
            "name": "cluster-repair",
            "image": image,
            "args": args,
        }
        if api_key_secret:
            container["env"] = [
                {
                    "name": "WAVEMIND_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": api_key_secret,
                            "key": api_key_secret_key,
                        }
                    },
                }
            ]

        labels = {
            "app.kubernetes.io/name": "wavemind",
            "app.kubernetes.io/component": "cluster-repair",
        }
        return {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {
                "name": name,
                "labels": labels,
            },
            "spec": {
                "schedule": schedule,
                "concurrencyPolicy": "Forbid",
                "successfulJobsHistoryLimit": 3,
                "failedJobsHistoryLimit": 3,
                "jobTemplate": {
                    "spec": {
                        "template": {
                            "metadata": {"labels": labels},
                            "spec": {
                                "restartPolicy": "OnFailure",
                                "containers": [container],
                            },
                        }
                    }
                },
            },
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "replication_factor": self.replication_factor,
            "placements": [placement.as_dict() for placement in self.placements],
            "node_load": self.node_load,
            "primary_load": self.primary_load,
            "quorum": self.quorum_report(),
            "warnings": list(self.warnings),
        }


def build_cluster_plan(
    namespaces: Iterable[str],
    nodes: Iterable[ClusterNode | dict[str, object] | str],
    replication_factor: int = 2,
) -> ClusterPlan:
    node_list = tuple(_coerce_node(node) for node in nodes)
    if not node_list:
        raise ValueError("At least one cluster node is required")
    node_ids = [node.id for node in node_list]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("Cluster node ids must be unique")
    if replication_factor <= 0:
        raise ValueError("replication_factor must be positive")
    if replication_factor > len(node_list):
        raise ValueError("replication_factor cannot exceed node count")

    placements = tuple(
        _place_namespace(str(namespace), node_list, replication_factor)
        for namespace in namespaces
    )
    warnings: list[str] = []
    zones = {node.zone for node in node_list if node.zone}
    if replication_factor == 1:
        warnings.append("replication_factor=1 does not survive node loss")
    if len(node_list) < 3:
        warnings.append("Use at least three nodes before calling this production HA")
    if zones and replication_factor > len(zones):
        warnings.append("replication_factor exceeds available zones; zone loss can remove multiple replicas")

    return ClusterPlan(
        nodes=node_list,
        replication_factor=int(replication_factor),
        placements=placements,
        warnings=tuple(warnings),
    )


def _coerce_node(node: ClusterNode | dict[str, object] | str) -> ClusterNode:
    if isinstance(node, ClusterNode):
        return node
    if isinstance(node, str):
        return ClusterNode(id=node, address=node)
    return ClusterNode(
        id=str(node["id"]),
        address=str(node.get("address", node["id"])),
        zone=str(node["zone"]) if node.get("zone") is not None else None,
        weight=float(node.get("weight", 1.0)),
    )


def _place_namespace(
    namespace: str,
    nodes: tuple[ClusterNode, ...],
    replication_factor: int,
) -> NamespacePlacement:
    scores = sorted(
        (
            (_rendezvous_score(namespace, node) * node.weight, node.id, node.zone or "")
            for node in nodes
        ),
        reverse=True,
    )
    selected: list[str] = []
    selected_zones: set[str] = set()
    for _, node_id, zone in scores:
        if len(selected) >= replication_factor:
            break
        zone_key = zone or node_id
        if zone_key in selected_zones:
            continue
        selected.append(node_id)
        selected_zones.add(zone_key)
    if len(selected) < replication_factor:
        for _, node_id, _zone in scores:
            if len(selected) >= replication_factor:
                break
            if node_id not in selected:
                selected.append(node_id)
    replicas = tuple(selected)
    digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
    return NamespacePlacement(
        namespace=namespace,
        primary=replicas[0],
        replicas=replicas,
        shard_key=digest,
    )


def _rendezvous_score(namespace: str, node: ClusterNode) -> float:
    digest = hashlib.sha256(f"{namespace}|{node.id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)
