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

    def as_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "replication_factor": self.replication_factor,
            "placements": [placement.as_dict() for placement in self.placements],
            "node_load": self.node_load,
            "primary_load": self.primary_load,
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
    if replication_factor == 1:
        warnings.append("replication_factor=1 does not survive node loss")
    if len(node_list) < 3:
        warnings.append("Use at least three nodes before calling this production HA")

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
            (_rendezvous_score(namespace, node) * node.weight, node.id)
            for node in nodes
        ),
        reverse=True,
    )
    replicas = tuple(node_id for _, node_id in scores[:replication_factor])
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
