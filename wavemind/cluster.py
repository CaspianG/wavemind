from __future__ import annotations

import hashlib
import math
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

    def placement_health_report(self) -> dict[str, object]:
        namespace_count = len(self.placements)
        zone_by_node = {node.id: node.zone for node in self.nodes}
        failure_domain_by_node = {
            node.id: node.zone or node.id
            for node in self.nodes
        }
        zone_count = len({node.zone for node in self.nodes if node.zone})
        failure_domain_count = len(set(failure_domain_by_node.values()))
        max_distinct_zones = (
            min(self.replication_factor, failure_domain_count)
            if failure_domain_count
            else self.replication_factor
        )

        distinct_replica_count = 0
        zone_spread_count = 0
        for placement in self.placements:
            if len(set(placement.replicas)) == len(placement.replicas):
                distinct_replica_count += 1
            replica_domains = {
                failure_domain_by_node.get(node_id)
                for node_id in placement.replicas
                if failure_domain_by_node.get(node_id)
            }
            if len(replica_domains) >= max_distinct_zones:
                zone_spread_count += 1

        primary_load = self.primary_load
        replica_load = self.node_load
        primary_weight_error = _max_relative_weight_error(
            primary_load,
            self.nodes,
            total_assignments=namespace_count,
        )
        replica_weight_error = _max_relative_weight_error(
            replica_load,
            self.nodes,
            total_assignments=namespace_count * self.replication_factor,
        )
        return {
            "namespace_count": namespace_count,
            "node_count": len(self.nodes),
            "zone_count": zone_count,
            "failure_domain_count": failure_domain_count,
            "replication_factor": self.replication_factor,
            "distinct_replica_rate": (
                1.0 if namespace_count == 0 else distinct_replica_count / namespace_count
            ),
            "zone_spread_rate": (
                1.0 if namespace_count == 0 else zone_spread_count / namespace_count
            ),
            "primary_load_skew": _load_skew(primary_load),
            "replica_load_skew": _load_skew(replica_load),
            "max_primary_weight_error": primary_weight_error,
            "max_replica_weight_error": replica_weight_error,
        }

    def movement_report(self, target: "ClusterPlan") -> dict[str, object]:
        source_by_namespace = {
            placement.namespace: placement
            for placement in self.placements
        }
        target_by_namespace = {
            placement.namespace: placement
            for placement in target.placements
        }
        shared_namespaces = sorted(
            set(source_by_namespace).intersection(target_by_namespace)
        )
        added_namespaces = sorted(set(target_by_namespace) - set(source_by_namespace))
        removed_namespaces = sorted(set(source_by_namespace) - set(target_by_namespace))
        source_nodes = {node.id for node in self.nodes}
        target_nodes = {node.id for node in target.nodes}
        new_nodes = target_nodes - source_nodes
        removed_nodes = source_nodes - target_nodes

        primary_moves = 0
        replica_set_moves = 0
        moved_to_new_node = 0
        moved_off_removed_node = 0
        for namespace in shared_namespaces:
            source = source_by_namespace[namespace]
            destination = target_by_namespace[namespace]
            if source.primary != destination.primary:
                primary_moves += 1
            if source.replicas != destination.replicas:
                replica_set_moves += 1
                if any(node_id in new_nodes for node_id in destination.replicas):
                    moved_to_new_node += 1
                if any(node_id in removed_nodes for node_id in source.replicas):
                    moved_off_removed_node += 1

        shared_count = len(shared_namespaces)
        return {
            "source_node_count": len(self.nodes),
            "target_node_count": len(target.nodes),
            "source_namespace_count": len(source_by_namespace),
            "target_namespace_count": len(target_by_namespace),
            "shared_namespace_count": shared_count,
            "added_namespace_count": len(added_namespaces),
            "removed_namespace_count": len(removed_namespaces),
            "new_node_count": len(new_nodes),
            "removed_node_count": len(removed_nodes),
            "primary_moves": primary_moves,
            "replica_set_moves": replica_set_moves,
            "moved_to_new_node": moved_to_new_node,
            "moved_off_removed_node": moved_off_removed_node,
            "primary_movement_ratio": (
                0.0 if shared_count == 0 else primary_moves / shared_count
            ),
            "replica_set_movement_ratio": (
                0.0 if shared_count == 0 else replica_set_moves / shared_count
            ),
            "new_nodes": sorted(new_nodes),
            "removed_nodes": sorted(removed_nodes),
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
            "placement_health": self.placement_health_report(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class NamespaceMove:
    namespace: str
    from_primary: str
    to_primary: str
    from_replicas: tuple[str, ...]
    to_replicas: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "from_primary": self.from_primary,
            "to_primary": self.to_primary,
            "from_replicas": list(self.from_replicas),
            "to_replicas": list(self.to_replicas),
        }


@dataclass(frozen=True)
class NamespaceRebalanceBatch:
    index: int
    moves: tuple[NamespaceMove, ...]
    source_node_pressure: tuple[tuple[str, int], ...]
    target_node_pressure: tuple[tuple[str, int], ...]
    requires_checkpoint: bool = True
    requires_repair: bool = True
    requires_validation: bool = True

    @property
    def namespaces(self) -> tuple[str, ...]:
        return tuple(move.namespace for move in self.moves)

    @property
    def affected_from_nodes(self) -> tuple[str, ...]:
        return tuple(node for node, _count in self.source_node_pressure)

    @property
    def affected_to_nodes(self) -> tuple[str, ...]:
        return tuple(node for node, _count in self.target_node_pressure)

    @property
    def max_node_pressure(self) -> int:
        counts = [count for _node, count in self.source_node_pressure]
        counts.extend(count for _node, count in self.target_node_pressure)
        return max(counts, default=0)

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "move_count": len(self.moves),
            "namespaces": list(self.namespaces),
            "moves": [move.as_dict() for move in self.moves],
            "affected_from_nodes": list(self.affected_from_nodes),
            "affected_to_nodes": list(self.affected_to_nodes),
            "source_node_pressure": dict(self.source_node_pressure),
            "target_node_pressure": dict(self.target_node_pressure),
            "max_node_pressure": self.max_node_pressure,
            "requires_checkpoint": self.requires_checkpoint,
            "requires_repair": self.requires_repair,
            "requires_validation": self.requires_validation,
        }


@dataclass(frozen=True)
class ClusterRebalancePlan:
    status: str
    replication_factor: int
    read_quorum: int
    write_quorum: int
    move_count: int
    omitted_moves: int
    batch_size: int
    max_node_moves_per_batch: int | None
    drain_nodes: tuple[str, ...]
    batches: tuple[NamespaceRebalanceBatch, ...]
    warnings: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()

    @property
    def full_plan(self) -> bool:
        return self.omitted_moves == 0

    @property
    def estimated_steps(self) -> int:
        if not self.batches:
            return 0
        # checkpoint, move, repair, validation for every batch.
        return len(self.batches) * 4

    @property
    def max_batch_node_pressure(self) -> int:
        return max((batch.max_node_pressure for batch in self.batches), default=0)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "replication_factor": self.replication_factor,
            "read_quorum": self.read_quorum,
            "write_quorum": self.write_quorum,
            "move_count": self.move_count,
            "omitted_moves": self.omitted_moves,
            "full_plan": self.full_plan,
            "batch_size": self.batch_size,
            "batch_count": len(self.batches),
            "estimated_steps": self.estimated_steps,
            "max_node_moves_per_batch": self.max_node_moves_per_batch,
            "max_batch_node_pressure": self.max_batch_node_pressure,
            "drain_nodes": list(self.drain_nodes),
            "batches": [batch.as_dict() for batch in self.batches],
            "warnings": list(self.warnings),
            "actions": list(self.actions),
        }


@dataclass(frozen=True)
class ClusterAutoscalePlan:
    status: str
    current_nodes: tuple[ClusterNode, ...]
    target_nodes: tuple[ClusterNode, ...]
    replication_factor: int
    namespace_count: int
    target_memories: int
    max_memories_per_node: int
    headroom: float
    required_nodes: int
    additional_nodes: int
    current_max_node_memories: int
    target_max_node_memories: int
    current_replica_skew: float
    target_replica_skew: float
    moves: tuple[NamespaceMove, ...]
    omitted_moves: int = 0
    warnings: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()

    def rebalance_plan(
        self,
        *,
        batch_size: int = 25,
        max_node_moves_per_batch: int | None = None,
        drain_nodes: Iterable[str] = (),
    ) -> ClusterRebalancePlan:
        return build_cluster_rebalance_plan(
            self.moves,
            replication_factor=self.replication_factor,
            batch_size=batch_size,
            max_node_moves_per_batch=max_node_moves_per_batch,
            drain_nodes=drain_nodes,
            omitted_moves=self.omitted_moves,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "current_nodes": [node.as_dict() for node in self.current_nodes],
            "target_nodes": [node.as_dict() for node in self.target_nodes],
            "replication_factor": self.replication_factor,
            "namespace_count": self.namespace_count,
            "target_memories": self.target_memories,
            "max_memories_per_node": self.max_memories_per_node,
            "headroom": self.headroom,
            "required_nodes": self.required_nodes,
            "additional_nodes": self.additional_nodes,
            "current_max_node_memories": self.current_max_node_memories,
            "target_max_node_memories": self.target_max_node_memories,
            "current_replica_skew": self.current_replica_skew,
            "target_replica_skew": self.target_replica_skew,
            "moves": [move.as_dict() for move in self.moves],
            "omitted_moves": self.omitted_moves,
            "warnings": list(self.warnings),
            "actions": list(self.actions),
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


def build_cluster_autoscale_plan(
    namespaces: Iterable[str],
    nodes: Iterable[ClusterNode | dict[str, object] | str],
    *,
    replication_factor: int = 3,
    target_memories: int,
    max_memories_per_node: int = 1_000_000,
    headroom: float = 0.70,
    node_prefix: str = "node",
    address_template: str = "http://{node_id}:8000",
    zones: Iterable[str] = (),
    max_moves: int = 100,
) -> ClusterAutoscalePlan:
    namespace_list = tuple(str(namespace) for namespace in namespaces)
    if not namespace_list:
        raise ValueError("At least one namespace is required")
    current_nodes = tuple(_coerce_node(node) for node in nodes)
    if not current_nodes:
        raise ValueError("At least one cluster node is required")
    if replication_factor <= 0:
        raise ValueError("replication_factor must be positive")
    if max_memories_per_node <= 0:
        raise ValueError("max_memories_per_node must be positive")
    if headroom <= 0 or headroom > 1:
        raise ValueError("headroom must be in (0, 1]")
    if max_moves < 0:
        raise ValueError("max_moves cannot be negative")

    target = max(0, int(target_memories))
    effective_capacity = max(1.0, float(max_memories_per_node) * float(headroom))
    required_nodes = max(
        int(replication_factor),
        math.ceil((target * int(replication_factor)) / effective_capacity),
    )
    required_nodes = max(required_nodes, len(current_nodes))
    target_nodes = _extend_nodes(
        current_nodes,
        required_nodes=required_nodes,
        node_prefix=node_prefix,
        address_template=address_template,
        zones=tuple(zones),
    )

    current_plan = build_cluster_plan(
        namespaces=namespace_list,
        nodes=current_nodes,
        replication_factor=min(replication_factor, len(current_nodes)),
    )
    target_plan = build_cluster_plan(
        namespaces=namespace_list,
        nodes=target_nodes,
        replication_factor=replication_factor,
    )
    current_memory_by_node = _estimated_node_memories(
        current_plan.node_load,
        namespace_count=len(namespace_list),
        target_memories=target,
    )
    target_memory_by_node = _estimated_node_memories(
        target_plan.node_load,
        namespace_count=len(namespace_list),
        target_memories=target,
    )
    current_max = max(current_memory_by_node.values(), default=0)
    target_max = max(target_memory_by_node.values(), default=0)
    while target_max > effective_capacity and len(target_nodes) < max(required_nodes * 4, required_nodes + 1):
        required_nodes += 1
        target_nodes = _extend_nodes(
            current_nodes,
            required_nodes=required_nodes,
            node_prefix=node_prefix,
            address_template=address_template,
            zones=tuple(zones),
        )
        target_plan = build_cluster_plan(
            namespaces=namespace_list,
            nodes=target_nodes,
            replication_factor=replication_factor,
        )
        target_memory_by_node = _estimated_node_memories(
            target_plan.node_load,
            namespace_count=len(namespace_list),
            target_memories=target,
        )
        target_max = max(target_memory_by_node.values(), default=0)
    current_skew = _load_skew(current_plan.node_load)
    target_skew = _load_skew(target_plan.node_load)

    current_by_namespace = {
        placement.namespace: placement for placement in current_plan.placements
    }
    target_by_namespace = {
        placement.namespace: placement for placement in target_plan.placements
    }
    all_moves = [
        NamespaceMove(
            namespace=namespace,
            from_primary=current_by_namespace[namespace].primary,
            to_primary=target_by_namespace[namespace].primary,
            from_replicas=current_by_namespace[namespace].replicas,
            to_replicas=target_by_namespace[namespace].replicas,
        )
        for namespace in namespace_list
        if current_by_namespace[namespace].primary != target_by_namespace[namespace].primary
        or current_by_namespace[namespace].replicas != target_by_namespace[namespace].replicas
    ]
    moves = tuple(all_moves[:max_moves])
    omitted_moves = max(0, len(all_moves) - len(moves))

    warnings: list[str] = []
    actions: list[str] = []
    additional_nodes = max(0, len(target_nodes) - len(current_nodes))
    if len(current_nodes) < replication_factor:
        warnings.append("current node count is below replication_factor")
    if current_max > effective_capacity:
        warnings.append("current placement exceeds per-node headroom")
    if additional_nodes:
        actions.append(f"Add {additional_nodes} node(s) before importing the target memory volume.")
    if all_moves:
        actions.append(
            f"Move or repair {len(all_moves)} namespace placement(s) after the new node set is available."
        )
    actions.append("Run external HTTP cluster load with failover and repair before raising production traffic.")

    if additional_nodes:
        status = "scale_required"
    elif current_max > effective_capacity or len(current_nodes) < replication_factor:
        status = "action_required"
    elif current_skew > 1.25:
        status = "rebalance_recommended"
    else:
        status = "ok"

    return ClusterAutoscalePlan(
        status=status,
        current_nodes=current_nodes,
        target_nodes=target_nodes,
        replication_factor=int(replication_factor),
        namespace_count=len(namespace_list),
        target_memories=target,
        max_memories_per_node=int(max_memories_per_node),
        headroom=float(headroom),
        required_nodes=len(target_nodes),
        additional_nodes=additional_nodes,
        current_max_node_memories=int(math.ceil(current_max)),
        target_max_node_memories=int(math.ceil(target_max)),
        current_replica_skew=round(current_skew, 6),
        target_replica_skew=round(target_skew, 6),
        moves=moves,
        omitted_moves=omitted_moves,
        warnings=tuple(dict.fromkeys(warnings)),
        actions=tuple(dict.fromkeys(actions)),
    )


def build_cluster_rebalance_plan(
    moves: Iterable[NamespaceMove | dict[str, object]],
    *,
    replication_factor: int,
    batch_size: int = 25,
    max_node_moves_per_batch: int | None = None,
    drain_nodes: Iterable[str] = (),
    omitted_moves: int = 0,
) -> ClusterRebalancePlan:
    if replication_factor <= 0:
        raise ValueError("replication_factor must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_node_moves_per_batch is not None and max_node_moves_per_batch <= 0:
        raise ValueError("max_node_moves_per_batch must be positive")
    if omitted_moves < 0:
        raise ValueError("omitted_moves cannot be negative")

    move_list = tuple(_coerce_namespace_move(move) for move in moves)
    drain_node_set = {str(node) for node in drain_nodes}
    warnings: list[str] = []
    actions: list[str] = []

    for move in move_list:
        if len(set(move.to_replicas)) != len(move.to_replicas):
            warnings.append(f"{move.namespace} target replicas contain duplicates")
        if len(move.to_replicas) < replication_factor:
            warnings.append(
                f"{move.namespace} target replicas below replication_factor={replication_factor}"
            )
        drained_targets = sorted(drain_node_set.intersection(move.to_replicas))
        if drained_targets:
            warnings.append(
                f"{move.namespace} targets drain node(s): {', '.join(drained_targets)}"
            )
        if move.to_primary not in move.to_replicas:
            warnings.append(f"{move.namespace} target primary is not in target replicas")

    if omitted_moves:
        warnings.append(
            f"{omitted_moves} move(s) omitted; rerun with a higher max_moves for a full rebalance plan"
        )

    batches: list[NamespaceRebalanceBatch] = []
    current: list[NamespaceMove] = []
    current_source_pressure: dict[str, int] = {}
    current_target_pressure: dict[str, int] = {}

    def would_exceed_pressure(move: NamespaceMove) -> bool:
        if max_node_moves_per_batch is None:
            return False
        source = dict(current_source_pressure)
        target = dict(current_target_pressure)
        for node_id in move.from_replicas:
            source[node_id] = source.get(node_id, 0) + 1
        for node_id in move.to_replicas:
            target[node_id] = target.get(node_id, 0) + 1
        max_pressure = max([*source.values(), *target.values(), 0])
        return max_pressure > max_node_moves_per_batch

    def append_to_current(move: NamespaceMove) -> None:
        current.append(move)
        for node_id in move.from_replicas:
            current_source_pressure[node_id] = current_source_pressure.get(node_id, 0) + 1
        for node_id in move.to_replicas:
            current_target_pressure[node_id] = current_target_pressure.get(node_id, 0) + 1

    def flush_current() -> None:
        if not current:
            return
        batches.append(
            NamespaceRebalanceBatch(
                index=len(batches) + 1,
                moves=tuple(current),
                source_node_pressure=tuple(sorted(current_source_pressure.items())),
                target_node_pressure=tuple(sorted(current_target_pressure.items())),
            )
        )
        current.clear()
        current_source_pressure.clear()
        current_target_pressure.clear()

    for move in move_list:
        if current and (len(current) >= batch_size or would_exceed_pressure(move)):
            flush_current()
        append_to_current(move)
    flush_current()

    if move_list:
        actions.extend(
            [
                f"Apply {len(batches)} rebalance batch(es) sequentially.",
                "Checkpoint source and target replicas before every batch.",
                "Run cluster-repair after every batch.",
                "Run quorum and HTTP cluster validation after every batch.",
            ]
        )
    else:
        actions.append("No namespace placement changes required.")
    if drain_node_set:
        actions.append("Keep drain nodes out of target replicas until final validation passes.")
    if omitted_moves:
        actions.append("Generate a full move list before executing production rebalance.")

    if warnings:
        status = "action_required"
    elif move_list:
        status = "ready"
    else:
        status = "ok"

    return ClusterRebalancePlan(
        status=status,
        replication_factor=int(replication_factor),
        read_quorum=1,
        write_quorum=int(replication_factor) // 2 + 1,
        move_count=len(move_list),
        omitted_moves=int(omitted_moves),
        batch_size=int(batch_size),
        max_node_moves_per_batch=(
            int(max_node_moves_per_batch)
            if max_node_moves_per_batch is not None
            else None
        ),
        drain_nodes=tuple(sorted(drain_node_set)),
        batches=tuple(batches),
        warnings=tuple(dict.fromkeys(warnings)),
        actions=tuple(dict.fromkeys(actions)),
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


def _coerce_namespace_move(move: NamespaceMove | dict[str, object]) -> NamespaceMove:
    if isinstance(move, NamespaceMove):
        return move
    return NamespaceMove(
        namespace=str(move["namespace"]),
        from_primary=str(move["from_primary"]),
        to_primary=str(move["to_primary"]),
        from_replicas=tuple(str(node_id) for node_id in move["from_replicas"]),
        to_replicas=tuple(str(node_id) for node_id in move["to_replicas"]),
    )


def _extend_nodes(
    current_nodes: tuple[ClusterNode, ...],
    *,
    required_nodes: int,
    node_prefix: str,
    address_template: str,
    zones: tuple[str, ...],
) -> tuple[ClusterNode, ...]:
    nodes = list(current_nodes)
    used_ids = {node.id for node in nodes}
    index = 0
    while len(nodes) < required_nodes:
        index += 1
        node_id = f"{node_prefix}-{index}"
        while node_id in used_ids:
            index += 1
            node_id = f"{node_prefix}-{index}"
        used_ids.add(node_id)
        zone = zones[(len(nodes)) % len(zones)] if zones else None
        nodes.append(
            ClusterNode(
                id=node_id,
                address=address_template.format(node_id=node_id, index=index),
                zone=zone,
            )
        )
    return tuple(nodes)


def _estimated_node_memories(
    node_load: dict[str, int],
    *,
    namespace_count: int,
    target_memories: int,
) -> dict[str, float]:
    if namespace_count <= 0:
        return {node_id: 0.0 for node_id in node_load}
    memories_per_namespace = float(target_memories) / float(namespace_count)
    return {
        node_id: load * memories_per_namespace
        for node_id, load in node_load.items()
    }


def _load_skew(node_load: dict[str, int]) -> float:
    if not node_load:
        return 1.0
    values = list(node_load.values())
    average = sum(values) / len(values) if values else 0.0
    if average <= 0:
        return 1.0
    return max(values) / average


def _max_relative_weight_error(
    observed_load: dict[str, int],
    nodes: tuple[ClusterNode, ...],
    *,
    total_assignments: int,
) -> float:
    if not nodes or total_assignments <= 0:
        return 0.0
    total_weight = sum(node.weight for node in nodes)
    if total_weight <= 0:
        return 0.0
    errors: list[float] = []
    for node in nodes:
        expected = float(total_assignments) * (node.weight / total_weight)
        observed = float(observed_load.get(node.id, 0))
        if expected <= 0:
            errors.append(0.0 if observed == 0 else 1.0)
        else:
            errors.append(abs(observed - expected) / expected)
    return max(errors, default=0.0)


def _place_namespace(
    namespace: str,
    nodes: tuple[ClusterNode, ...],
    replication_factor: int,
) -> NamespacePlacement:
    scores = sorted(
        (
            (_rendezvous_score(namespace, node), node.id, node.zone or "")
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
    raw = int.from_bytes(digest[:8], "big")
    # Weighted rendezvous hashing: weight / -log(u) is equivalent to selecting
    # the lowest exponential race time and gives selection probability
    # proportional to node.weight while keeping placement deterministic.
    u = (raw + 1) / float(2**64)
    return node.weight / (-math.log(u))
