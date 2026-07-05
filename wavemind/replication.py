from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .cluster import ClusterNode, NamespacePlacement, build_cluster_plan
from .core import QueryResult, WaveMind
from .storage import MemoryRecord


class ReplicationError(RuntimeError):
    """Base class for replicated WaveMind runtime errors."""


class WriteQuorumError(ReplicationError):
    """Raised when a replicated write cannot satisfy the configured quorum."""


class ReadQuorumError(ReplicationError):
    """Raised when a replicated read cannot satisfy the configured quorum."""


@dataclass(frozen=True)
class ReplicatedWriteResult:
    namespace: str
    primary_node: str
    primary_id: int | None
    writes: dict[str, int]
    failed_nodes: dict[str, str] = field(default_factory=dict)
    write_quorum: int = 1

    @property
    def ok(self) -> bool:
        return len(self.writes) >= self.write_quorum


@dataclass(frozen=True)
class ReplicatedRepairReport:
    namespace: str
    source_node: str | None
    copied_records: int
    repaired_nodes: dict[str, int] = field(default_factory=dict)
    failed_nodes: dict[str, str] = field(default_factory=dict)


class ReplicatedWaveMind:
    """Quorum-replicated namespace runtime over multiple WaveMind stores.

    This is a pragmatic local/service-mode replication layer: namespace
    placement is deterministic, each replica has its own durable SQLite or
    configured store, writes require a quorum, reads merge available replicas,
    and recovered replicas can be repaired from healthy peers.
    """

    def __init__(
        self,
        root_path: str | Path,
        nodes: Iterable[ClusterNode | dict[str, object] | str],
        replication_factor: int = 3,
        write_quorum: int | None = None,
        read_quorum: int = 1,
        **mind_kwargs: Any,
    ):
        if "db_path" in mind_kwargs:
            raise ValueError("ReplicatedWaveMind manages db_path per replica")
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.replication_factor = int(replication_factor)
        self.write_quorum = (
            self.replication_factor // 2 + 1
            if write_quorum is None
            else int(write_quorum)
        )
        self.read_quorum = int(read_quorum)
        if self.write_quorum <= 0:
            raise ValueError("write_quorum must be positive")
        if self.read_quorum <= 0:
            raise ValueError("read_quorum must be positive")
        if self.write_quorum > self.replication_factor:
            raise ValueError("write_quorum cannot exceed replication_factor")
        if self.read_quorum > self.replication_factor:
            raise ValueError("read_quorum cannot exceed replication_factor")

        plan = build_cluster_plan(
            namespaces=[],
            nodes=nodes,
            replication_factor=self.replication_factor,
        )
        self.nodes = plan.nodes
        self.mind_kwargs = dict(mind_kwargs)
        self._available = {node.id: True for node in self.nodes}
        self._minds: dict[str, WaveMind] = {}

    def remember(
        self,
        text: str,
        namespace: str = "default",
        **kwargs: Any,
    ) -> ReplicatedWriteResult:
        placement = self.placement(namespace)
        available_replicas = self._available_replicas(placement)
        if len(available_replicas) < self.write_quorum:
            raise WriteQuorumError(
                f"Write quorum {self.write_quorum} cannot be reached for "
                f"namespace {namespace!r}; available replicas: {available_replicas}"
            )

        writes: dict[str, int] = {}
        failed: dict[str, str] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                writes[node_id] = self._mind(node_id).remember(
                    text,
                    namespace=namespace,
                    **kwargs,
                )
            except Exception as exc:  # pragma: no cover - defensive store boundary
                failed[node_id] = str(exc)

        if len(writes) < self.write_quorum:
            raise WriteQuorumError(
                f"Write quorum {self.write_quorum} was not reached for "
                f"namespace {namespace!r}; successful writes: {len(writes)}"
            )
        return ReplicatedWriteResult(
            namespace=namespace,
            primary_node=placement.primary,
            primary_id=writes.get(placement.primary),
            writes=writes,
            failed_nodes=failed,
            write_quorum=self.write_quorum,
        )

    def query(
        self,
        text: str,
        namespace: str = "default",
        top_k: int = 3,
        **kwargs: Any,
    ) -> list[QueryResult]:
        placement = self.placement(namespace)
        successful_reads = 0
        failed: dict[str, str] = {}
        best_by_key: dict[tuple[str, str, tuple[str, ...]], QueryResult] = {}

        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                results = self._mind(node_id).query(
                    text,
                    namespace=namespace,
                    top_k=top_k,
                    **kwargs,
                )
                successful_reads += 1
            except Exception as exc:  # pragma: no cover - defensive store boundary
                failed[node_id] = str(exc)
                continue

            for result in results:
                key = (result.namespace, result.text, tuple(sorted(result.tags)))
                current = best_by_key.get(key)
                if current is None or result.score > current.score:
                    best_by_key[key] = self._with_replica_metadata(result, node_id)

        if successful_reads < self.read_quorum:
            raise ReadQuorumError(
                f"Read quorum {self.read_quorum} was not reached for "
                f"namespace {namespace!r}; successful reads: {successful_reads}; "
                f"failures: {failed}"
            )

        merged = sorted(best_by_key.values(), key=lambda item: item.score, reverse=True)
        return merged[:top_k]

    def forget(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str = "default",
    ) -> ReplicatedWriteResult:
        if id is None and text is None:
            raise ValueError("forget requires id or text")
        placement = self.placement(namespace)
        available_replicas = self._available_replicas(placement)
        if len(available_replicas) < self.write_quorum:
            raise WriteQuorumError(
                f"Forget quorum {self.write_quorum} cannot be reached for "
                f"namespace {namespace!r}; available replicas: {available_replicas}"
            )

        writes: dict[str, int] = {}
        failed: dict[str, str] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                writes[node_id] = self._mind(node_id).forget(
                    id=id,
                    text=text,
                    namespace=namespace,
                )
            except Exception as exc:  # pragma: no cover - defensive store boundary
                failed[node_id] = str(exc)

        if len(writes) < self.write_quorum:
            raise WriteQuorumError(
                f"Forget quorum {self.write_quorum} was not reached for "
                f"namespace {namespace!r}; successful writes: {len(writes)}"
            )
        return ReplicatedWriteResult(
            namespace=namespace,
            primary_node=placement.primary,
            primary_id=writes.get(placement.primary),
            writes=writes,
            failed_nodes=failed,
            write_quorum=self.write_quorum,
        )

    def repair_namespace(self, namespace: str = "default") -> ReplicatedRepairReport:
        placement = self.placement(namespace)
        source_node, source_records = self._source_records(namespace, placement)
        if source_node is None:
            return ReplicatedRepairReport(
                namespace=namespace,
                source_node=None,
                copied_records=0,
                failed_nodes={
                    node_id: "no available source records"
                    for node_id in placement.replicas
                    if not self._available.get(node_id, False)
                },
            )

        repaired: dict[str, int] = {}
        failed: dict[str, str] = {}
        for node_id in placement.replicas:
            if node_id == source_node:
                continue
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                target = self._mind(node_id)
                existing = {
                    self._record_key(record)
                    for record in target.store.list(namespace=namespace, include_expired=False)
                }
                copied = 0
                for record in source_records:
                    if self._record_key(record) in existing:
                        continue
                    ttl_seconds = self._remaining_ttl(record)
                    if ttl_seconds == 0:
                        continue
                    target.remember(
                        record.text,
                        namespace=record.namespace,
                        tags=record.tags,
                        ttl_seconds=ttl_seconds,
                        metadata=record.metadata,
                        priority=record.priority,
                    )
                    copied += 1
                repaired[node_id] = copied
            except Exception as exc:  # pragma: no cover - defensive store boundary
                failed[node_id] = str(exc)

        return ReplicatedRepairReport(
            namespace=namespace,
            source_node=source_node,
            copied_records=sum(repaired.values()),
            repaired_nodes=repaired,
            failed_nodes=failed,
        )

    def placement(self, namespace: str = "default") -> NamespacePlacement:
        return build_cluster_plan(
            namespaces=[namespace],
            nodes=self.nodes,
            replication_factor=self.replication_factor,
        ).placements[0]

    def set_node_available(self, node_id: str, available: bool) -> None:
        if node_id not in {node.id for node in self.nodes}:
            raise ValueError(f"Unknown replicated node: {node_id}")
        self._available[node_id] = bool(available)

    def node_db_path(self, node_id: str) -> Path:
        if node_id not in {node.id for node in self.nodes}:
            raise ValueError(f"Unknown replicated node: {node_id}")
        return self.root_path / self._safe_node_dir(node_id) / "wavemind.sqlite3"

    def stats(self, namespace: str | None = None) -> dict[str, Any]:
        node_payloads = {}
        total_active = 0
        for node in self.nodes:
            node_stats: dict[str, Any] = {
                "available": self._available.get(node.id, False),
                "path": str(self.node_db_path(node.id)),
            }
            if node.id in self._minds:
                stats = self._minds[node.id].stats(namespace=namespace)
                node_stats.update(stats)
                total_active += int(stats["active_memories"])
            node_payloads[node.id] = node_stats
        return {
            "nodes": len(self.nodes),
            "available_nodes": sum(1 for available in self._available.values() if available),
            "replication_factor": self.replication_factor,
            "write_quorum": self.write_quorum,
            "read_quorum": self.read_quorum,
            "namespace": namespace,
            "replicated_active_memories": total_active,
            "node_stats": node_payloads,
        }

    def close(self) -> None:
        for mind in self._minds.values():
            mind.close()
        self._minds.clear()

    def __enter__(self) -> "ReplicatedWaveMind":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _mind(self, node_id: str) -> WaveMind:
        mind = self._minds.get(node_id)
        if mind is None:
            mind = WaveMind(db_path=self.node_db_path(node_id), **self.mind_kwargs)
            self._minds[node_id] = mind
        return mind

    def _available_replicas(self, placement: NamespacePlacement) -> list[str]:
        return [
            node_id
            for node_id in placement.replicas
            if self._available.get(node_id, False)
        ]

    def _source_records(
        self,
        namespace: str,
        placement: NamespacePlacement,
    ) -> tuple[str | None, list[MemoryRecord]]:
        best_node: str | None = None
        best_records: list[MemoryRecord] = []
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            records = self._mind(node_id).store.list(namespace=namespace, include_expired=False)
            if len(records) > len(best_records):
                best_node = node_id
                best_records = records
        return best_node, best_records

    @staticmethod
    def _record_key(record: MemoryRecord) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
        metadata = tuple(sorted((str(key), str(value)) for key, value in record.metadata.items()))
        return record.text, tuple(sorted(record.tags)), metadata

    @staticmethod
    def _remaining_ttl(record: MemoryRecord) -> float | None:
        if record.expires_at is None:
            return None
        remaining = record.expires_at - time.time()
        return 0.0 if remaining <= 0 else remaining

    @staticmethod
    def _with_replica_metadata(result: QueryResult, node_id: str) -> QueryResult:
        metadata = dict(result.metadata)
        metadata["_replica_node"] = node_id
        return QueryResult(
            id=result.id,
            text=result.text,
            score=result.score,
            vector_score=result.vector_score,
            field_score=result.field_score,
            graph_score=result.graph_score,
            namespace=result.namespace,
            tags=result.tags,
            metadata=metadata,
        )

    @staticmethod
    def _safe_node_dir(node_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_id).strip(".-")
        return safe or "node"
