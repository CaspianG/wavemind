from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    deleted_records: int = 0
    tombstone_keys: int = 0
    repaired_nodes: dict[str, int] = field(default_factory=dict)
    failed_nodes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplicatedDeltaImportReport:
    namespace: str
    imported_records: int = 0
    skipped_records: int = 0
    deleted_records: int = 0
    imported_tombstones: int = 0
    failed_nodes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplicatedSnapshotReport:
    snapshot_path: Path
    nodes: tuple[str, ...]
    total_bytes: int
    checksums: dict[str, str]
    skipped_nodes: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.skipped_nodes

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_path": str(self.snapshot_path),
            "nodes": list(self.nodes),
            "total_bytes": self.total_bytes,
            "checksums": dict(self.checksums),
            "skipped_nodes": dict(self.skipped_nodes),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ReplicatedRestoreReport:
    root_path: Path
    nodes: tuple[str, ...]
    restored_files: dict[str, Path]
    total_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_path": str(self.root_path),
            "nodes": list(self.nodes),
            "restored_files": {
                node_id: str(path)
                for node_id, path in self.restored_files.items()
            },
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True)
class TombstoneState:
    keys: frozenset[str] = frozenset()
    texts: frozenset[str] = frozenset()


_REPLICA_KEY = "_wavemind_replica_key"
_REPLICA_OPERATION_ID = "_wavemind_operation_id"
_REPLICA_UPDATED_AT = "_wavemind_replica_updated_at"
_TOMBSTONE_ACTION = "replicated_tombstone"


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
        prepared_kwargs = self._prepare_remember_kwargs(text, namespace, kwargs)
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                writes[node_id] = self._mind(node_id).remember(
                    text,
                    namespace=namespace,
                    **prepared_kwargs,
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
        tombstones = self._tombstone_state(namespace, placement)

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
                replica_key = self._result_replica_key(result)
                if replica_key in tombstones.keys or result.text in tombstones.texts:
                    continue
                key = (result.namespace, replica_key, tuple(sorted(result.tags)))
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
        keys, texts = self._resolve_forget_targets(placement, namespace, id=id, text=text)
        if text is not None:
            texts.add(text)
        operation_id = uuid.uuid4().hex
        deleted_at = time.time()
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                mind = self._mind(node_id)
                writes[node_id] = self._forget_records(
                    mind,
                    namespace=namespace,
                    keys=keys,
                    texts=texts,
                    id=id if not keys and not texts else None,
                )
                self._log_tombstone(
                    mind,
                    namespace=namespace,
                    keys=keys,
                    texts=texts,
                    operation_id=operation_id,
                    deleted_at=deleted_at,
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
        tombstones = self._tombstone_state(namespace, placement)
        source_node, source_records = self._source_records(namespace, placement, tombstones)
        if source_node is None:
            return ReplicatedRepairReport(
                namespace=namespace,
                source_node=None,
                copied_records=0,
                tombstone_keys=len(tombstones.keys),
                failed_nodes={
                    node_id: "no available source records"
                    for node_id in placement.replicas
                    if not self._available.get(node_id, False)
                },
            )

        repaired: dict[str, int] = {}
        failed: dict[str, str] = {}
        deleted_total = 0
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                target = self._mind(node_id)
                deleted_total += self._forget_records(
                    target,
                    namespace=namespace,
                    keys=set(tombstones.keys),
                    texts=set(tombstones.texts),
                )
                if node_id == source_node and source_records:
                    repaired[node_id] = 0
                    continue
                existing = {
                    self._record_replica_key(record)
                    for record in target.store.list(namespace=namespace, include_expired=False)
                    if self._record_replica_key(record) not in tombstones.keys
                    and record.text not in tombstones.texts
                }
                copied = 0
                for record in source_records:
                    if self._record_replica_key(record) in tombstones.keys:
                        continue
                    if record.text in tombstones.texts:
                        continue
                    if self._record_replica_key(record) in existing:
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
            deleted_records=deleted_total,
            tombstone_keys=len(tombstones.keys),
            repaired_nodes=repaired,
            failed_nodes=failed,
        )

    def export_namespace_delta(self, namespace: str = "default") -> dict[str, Any]:
        """Export active records and tombstones for active-active sync."""
        placement = self.placement(namespace)
        tombstones = self._tombstone_state(namespace, placement)
        _source_node, records = self._source_records(namespace, placement, tombstones)
        events = self._tombstone_events(namespace, placement)
        return {
            "format": "wavemind.namespace_delta.v1",
            "namespace": namespace,
            "created_at": time.time(),
            "replication_factor": self.replication_factor,
            "records": [self._record_to_delta(record) for record in records],
            "tombstones": events,
        }

    def import_namespace_delta(
        self,
        delta: dict[str, Any],
        namespace: str | None = None,
    ) -> ReplicatedDeltaImportReport:
        if delta.get("format") != "wavemind.namespace_delta.v1":
            raise ValueError("Unsupported replicated namespace delta format")
        target_namespace = namespace or str(delta["namespace"])
        placement = self.placement(target_namespace)
        available_replicas = self._available_replicas(placement)
        if len(available_replicas) < self.write_quorum:
            raise WriteQuorumError(
                f"Import quorum {self.write_quorum} cannot be reached for "
                f"namespace {target_namespace!r}; available replicas: {available_replicas}"
            )

        incoming_tombstones = self._delta_tombstone_state(delta)
        imported_records = 0
        skipped_records = 0
        deleted_records = 0
        imported_tombstones = 0
        failed: dict[str, str] = {}

        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                mind = self._mind(node_id)
                existing_tombstones = self._existing_tombstone_operation_ids(
                    mind,
                    target_namespace,
                )
                for event in delta.get("tombstones", []):
                    operation_id = str(event.get("operation_id", ""))
                    if operation_id and operation_id in existing_tombstones:
                        continue
                    keys = {str(key) for key in event.get("replica_keys", [])}
                    texts = {str(text) for text in event.get("texts", [])}
                    self._log_tombstone(
                        mind,
                        namespace=target_namespace,
                        keys=keys,
                        texts=texts,
                        operation_id=operation_id or uuid.uuid4().hex,
                        deleted_at=float(event.get("deleted_at", time.time())),
                    )
                    imported_tombstones += 1
                deleted_records += self._forget_records(
                    mind,
                    namespace=target_namespace,
                    keys=set(incoming_tombstones.keys),
                    texts=set(incoming_tombstones.texts),
                )

                existing = {
                    self._record_replica_key(record): record
                    for record in mind.store.list(
                        namespace=target_namespace,
                        include_expired=False,
                    )
                }
                local_tombstones = self._tombstone_state(target_namespace, placement)
                for record_payload in delta.get("records", []):
                    key = str(record_payload.get("replica_key", ""))
                    text = str(record_payload.get("text", ""))
                    if key in local_tombstones.keys or text in local_tombstones.texts:
                        skipped_records += 1
                        continue
                    if key in existing:
                        skipped_records += 1
                        continue
                    ttl_seconds = self._delta_remaining_ttl(record_payload)
                    if ttl_seconds == 0:
                        skipped_records += 1
                        continue
                    metadata = dict(record_payload.get("metadata") or {})
                    metadata.setdefault(_REPLICA_KEY, key)
                    metadata.setdefault(
                        _REPLICA_OPERATION_ID,
                        str(record_payload.get("operation_id") or uuid.uuid4().hex),
                    )
                    metadata.setdefault(
                        _REPLICA_UPDATED_AT,
                        float(record_payload.get("updated_at", time.time())),
                    )
                    mind.remember(
                        text,
                        namespace=target_namespace,
                        tags=tuple(record_payload.get("tags", [])),
                        ttl_seconds=ttl_seconds,
                        metadata=metadata,
                        priority=float(record_payload.get("priority", 1.0)),
                    )
                    imported_records += 1
            except Exception as exc:  # pragma: no cover - defensive store boundary
                failed[node_id] = str(exc)

        successful_writes = len(placement.replicas) - len(failed)
        if successful_writes < self.write_quorum:
            raise WriteQuorumError(
                f"Import quorum {self.write_quorum} was not reached for "
                f"namespace {target_namespace!r}; successful writes: {successful_writes}"
            )
        return ReplicatedDeltaImportReport(
            namespace=target_namespace,
            imported_records=imported_records,
            skipped_records=skipped_records,
            deleted_records=deleted_records,
            imported_tombstones=imported_tombstones,
            failed_nodes=failed,
        )

    def snapshot(
        self,
        destination: str | Path,
        *,
        prefix: str = "wavemind-replicated",
        keep_last: int | None = None,
        require_all: bool = True,
    ) -> ReplicatedSnapshotReport:
        """Create a checksummed snapshot of every replica SQLite store."""
        destination = Path(destination)
        if destination.suffix:
            raise ValueError("replicated snapshot destination must be a directory")
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        snapshot_path = destination / f"{prefix}-{timestamp}"
        if snapshot_path.exists():
            snapshot_path = destination / f"{prefix}-{timestamp}-{time.time_ns()}"
        snapshot_path.mkdir(parents=True)

        nodes_payload: list[dict[str, Any]] = []
        skipped: dict[str, str] = {}
        checksums: dict[str, str] = {}
        total_bytes = 0

        for node in self.nodes:
            node_id = node.id
            if not self._available.get(node_id, False):
                skipped[node_id] = "node unavailable"
                if require_all:
                    shutil.rmtree(snapshot_path, ignore_errors=True)
                    raise ReplicationError(
                        f"Cannot snapshot unavailable replica {node_id!r}"
                    )
                continue

            mind = self._mind(node_id)
            backup = getattr(mind.store, "backup", None)
            commit = getattr(mind.store, "commit", None)
            if not callable(backup):
                skipped[node_id] = "store does not support SQLite file backup"
                if require_all:
                    shutil.rmtree(snapshot_path, ignore_errors=True)
                    raise NotImplementedError(
                        "Replicated snapshots currently require SQLite-backed replicas"
                    )
                continue
            if callable(commit):
                commit()

            filename = f"{self._safe_node_dir(node_id)}.sqlite3"
            target = snapshot_path / filename
            backup(target)
            digest = self._sha256_file(target)
            size = target.stat().st_size
            checksums[node_id] = digest
            total_bytes += size
            stats = mind.stats()
            nodes_payload.append(
                {
                    "id": node.id,
                    "address": node.address,
                    "zone": node.zone,
                    "weight": node.weight,
                    "db_file": filename,
                    "sha256": digest,
                    "bytes": size,
                    "active_memories": stats.get("active_memories"),
                    "total_memories": stats.get("total_memories"),
                    "audit_events": stats.get("audit_events"),
                }
            )

        manifest = {
            "format": "wavemind.replicated_snapshot.v1",
            "created_at": time.time(),
            "replication_factor": self.replication_factor,
            "write_quorum": self.write_quorum,
            "read_quorum": self.read_quorum,
            "nodes": nodes_payload,
            "skipped_nodes": skipped,
            "total_bytes": total_bytes,
        }
        (snapshot_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if keep_last is not None:
            self._prune_snapshots(destination, prefix=prefix, keep_last=keep_last)

        return ReplicatedSnapshotReport(
            snapshot_path=snapshot_path,
            nodes=tuple(item["id"] for item in nodes_payload),
            total_bytes=total_bytes,
            checksums=checksums,
            skipped_nodes=skipped,
        )

    @staticmethod
    def verify_snapshot(snapshot_path: str | Path) -> dict[str, Any]:
        snapshot_path = Path(snapshot_path)
        manifest = ReplicatedWaveMind._read_snapshot_manifest(snapshot_path)
        failures: dict[str, str] = {}
        verified: dict[str, str] = {}
        total_bytes = 0
        for node in manifest.get("nodes", []):
            node_id = str(node["id"])
            db_file = snapshot_path / str(node["db_file"])
            if not db_file.exists():
                failures[node_id] = "snapshot database file is missing"
                continue
            actual = ReplicatedWaveMind._sha256_file(db_file)
            expected = str(node["sha256"])
            if actual != expected:
                failures[node_id] = "sha256 mismatch"
                continue
            verified[node_id] = actual
            total_bytes += db_file.stat().st_size
        return {
            "format": manifest["format"],
            "healthy": not failures,
            "snapshot_path": str(snapshot_path),
            "verified_nodes": verified,
            "failed_nodes": failures,
            "total_bytes": total_bytes,
        }

    @classmethod
    def restore_snapshot(
        cls,
        snapshot_path: str | Path,
        root_path: str | Path,
        *,
        overwrite: bool = False,
        **mind_kwargs: Any,
    ) -> tuple["ReplicatedWaveMind", ReplicatedRestoreReport]:
        snapshot_path = Path(snapshot_path)
        root_path = Path(root_path)
        health = cls.verify_snapshot(snapshot_path)
        if not health["healthy"]:
            raise ReplicationError(
                f"Snapshot verification failed: {health['failed_nodes']}"
            )
        if root_path.exists() and any(root_path.iterdir()):
            if not overwrite:
                raise FileExistsError(
                    f"Restore root already exists and is not empty: {root_path}"
                )
            shutil.rmtree(root_path)
        root_path.mkdir(parents=True, exist_ok=True)

        manifest = cls._read_snapshot_manifest(snapshot_path)
        restored_files: dict[str, Path] = {}
        total_bytes = 0
        nodes: list[ClusterNode] = []
        for node_payload in manifest["nodes"]:
            node = ClusterNode(
                id=str(node_payload["id"]),
                address=str(node_payload["address"]),
                zone=(
                    str(node_payload["zone"])
                    if node_payload.get("zone") is not None
                    else None
                ),
                weight=float(node_payload.get("weight", 1.0)),
            )
            nodes.append(node)
            target = root_path / cls._safe_node_dir(node.id) / "wavemind.sqlite3"
            target.parent.mkdir(parents=True, exist_ok=True)
            source = snapshot_path / str(node_payload["db_file"])
            shutil.copy2(source, target)
            restored_files[node.id] = target
            total_bytes += target.stat().st_size

        memory = cls(
            root_path=root_path,
            nodes=nodes,
            replication_factor=int(manifest["replication_factor"]),
            write_quorum=int(manifest["write_quorum"]),
            read_quorum=int(manifest["read_quorum"]),
            **mind_kwargs,
        )
        report = ReplicatedRestoreReport(
            root_path=root_path,
            nodes=tuple(node.id for node in nodes),
            restored_files=restored_files,
            total_bytes=total_bytes,
        )
        return memory, report

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
        tombstones: TombstoneState,
    ) -> tuple[str | None, list[MemoryRecord]]:
        source_node: str | None = None
        records_by_key: dict[str, MemoryRecord] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            records = self._mind(node_id).store.list(namespace=namespace, include_expired=False)
            if source_node is None and records:
                source_node = node_id
            for record in records:
                key = self._record_replica_key(record)
                if key in tombstones.keys or record.text in tombstones.texts:
                    continue
                current = records_by_key.get(key)
                if current is None or self._record_updated_at(record) > self._record_updated_at(current):
                    records_by_key[key] = record
                    source_node = node_id
        return source_node, list(records_by_key.values())

    @staticmethod
    def _record_updated_at(record: MemoryRecord) -> float:
        value = record.metadata.get(_REPLICA_UPDATED_AT, record.updated_at)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(record.updated_at)

    def _prepare_remember_kwargs(
        self,
        text: str,
        namespace: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = dict(kwargs)
        tags = tuple(prepared.get("tags") or ())
        metadata = dict(prepared.get("metadata") or {})
        replica_key = str(
            metadata.get(_REPLICA_KEY)
            or self._memory_key(namespace, text, tags, metadata)
        )
        metadata.setdefault(_REPLICA_KEY, replica_key)
        metadata.setdefault(_REPLICA_OPERATION_ID, uuid.uuid4().hex)
        metadata.setdefault(_REPLICA_UPDATED_AT, time.time())
        prepared["metadata"] = metadata
        return prepared

    def _resolve_forget_targets(
        self,
        placement: NamespacePlacement,
        namespace: str,
        *,
        id: int | None,
        text: str | None,
    ) -> tuple[set[str], set[str]]:
        keys: set[str] = set()
        texts: set[str] = set()
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            store = self._mind(node_id).store
            if id is not None:
                record = store.get(id)
                if record is not None and record.namespace == namespace:
                    keys.add(self._record_replica_key(record))
                    texts.add(record.text)
            if text is not None:
                for record in store.list(namespace=namespace, include_expired=True):
                    if record.text == text:
                        keys.add(self._record_replica_key(record))
                        texts.add(record.text)
        return keys, texts

    def _forget_records(
        self,
        mind: WaveMind,
        *,
        namespace: str,
        keys: set[str],
        texts: set[str],
        id: int | None = None,
    ) -> int:
        deleted = 0
        records = mind.store.list(namespace=namespace, include_expired=True)
        for record in records:
            record_key = self._record_replica_key(record)
            should_delete = (
                (keys and record_key in keys)
                or (texts and record.text in texts)
                or (id is not None and record.id == id)
            )
            if should_delete and record.id is not None:
                deleted += mind.forget(id=record.id, namespace=namespace)
        return deleted

    def _log_tombstone(
        self,
        mind: WaveMind,
        *,
        namespace: str,
        keys: set[str],
        texts: set[str],
        operation_id: str,
        deleted_at: float,
    ) -> None:
        mind.store.log_audit_event(
            _TOMBSTONE_ACTION,
            namespace=namespace,
            metadata={
                "replica_keys": sorted(keys),
                "texts": sorted(texts),
                "operation_id": operation_id,
                "deleted_at": float(deleted_at),
            },
        )

    def _tombstone_state(
        self,
        namespace: str,
        placement: NamespacePlacement,
    ) -> TombstoneState:
        keys: set[str] = set()
        texts: set[str] = set()
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            events = self._mind(node_id).store.list_audit_events(
                namespace=namespace,
                action=_TOMBSTONE_ACTION,
                limit=10_000,
            )
            for event in events:
                raw_keys = event.metadata.get("replica_keys", [])
                raw_texts = event.metadata.get("texts", [])
                if isinstance(raw_keys, list):
                    keys.update(str(key) for key in raw_keys)
                if isinstance(raw_texts, list):
                    texts.update(str(item) for item in raw_texts)
        return TombstoneState(keys=frozenset(keys), texts=frozenset(texts))

    def _tombstone_events(
        self,
        namespace: str,
        placement: NamespacePlacement,
    ) -> list[dict[str, Any]]:
        by_operation: dict[str, dict[str, Any]] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            events = self._mind(node_id).store.list_audit_events(
                namespace=namespace,
                action=_TOMBSTONE_ACTION,
                limit=10_000,
            )
            for event in events:
                operation_id = str(event.metadata.get("operation_id") or event.id or uuid.uuid4().hex)
                payload = by_operation.setdefault(
                    operation_id,
                    {
                        "operation_id": operation_id,
                        "deleted_at": float(event.metadata.get("deleted_at", event.created_at)),
                        "replica_keys": set(),
                        "texts": set(),
                    },
                )
                raw_keys = event.metadata.get("replica_keys", [])
                raw_texts = event.metadata.get("texts", [])
                if isinstance(raw_keys, list):
                    payload["replica_keys"].update(str(key) for key in raw_keys)
                if isinstance(raw_texts, list):
                    payload["texts"].update(str(text) for text in raw_texts)
        return [
            {
                "operation_id": payload["operation_id"],
                "deleted_at": payload["deleted_at"],
                "replica_keys": sorted(payload["replica_keys"]),
                "texts": sorted(payload["texts"]),
            }
            for payload in sorted(
                by_operation.values(),
                key=lambda item: (float(item["deleted_at"]), str(item["operation_id"])),
            )
        ]

    @staticmethod
    def _delta_tombstone_state(delta: dict[str, Any]) -> TombstoneState:
        keys: set[str] = set()
        texts: set[str] = set()
        for event in delta.get("tombstones", []):
            raw_keys = event.get("replica_keys", [])
            raw_texts = event.get("texts", [])
            if isinstance(raw_keys, list):
                keys.update(str(key) for key in raw_keys)
            if isinstance(raw_texts, list):
                texts.update(str(text) for text in raw_texts)
        return TombstoneState(keys=frozenset(keys), texts=frozenset(texts))

    @staticmethod
    def _existing_tombstone_operation_ids(mind: WaveMind, namespace: str) -> set[str]:
        operation_ids: set[str] = set()
        for event in mind.store.list_audit_events(
            namespace=namespace,
            action=_TOMBSTONE_ACTION,
            limit=10_000,
        ):
            operation_id = event.metadata.get("operation_id")
            if operation_id:
                operation_ids.add(str(operation_id))
        return operation_ids

    def _record_to_delta(self, record: MemoryRecord) -> dict[str, Any]:
        replica_key = self._record_replica_key(record)
        return {
            "replica_key": replica_key,
            "operation_id": str(record.metadata.get(_REPLICA_OPERATION_ID, "")),
            "text": record.text,
            "tags": list(record.tags),
            "metadata": dict(record.metadata),
            "priority": float(record.priority),
            "created_at": float(record.created_at),
            "updated_at": self._record_updated_at(record),
            "expires_at": record.expires_at,
        }

    @staticmethod
    def _delta_remaining_ttl(record_payload: dict[str, Any]) -> float | None:
        expires_at = record_payload.get("expires_at")
        if expires_at is None:
            return None
        remaining = float(expires_at) - time.time()
        return 0.0 if remaining <= 0 else remaining

    def _record_replica_key(self, record: MemoryRecord) -> str:
        value = record.metadata.get(_REPLICA_KEY)
        if isinstance(value, str) and value:
            return value
        return self._memory_key(
            record.namespace,
            record.text,
            record.tags,
            record.metadata,
        )

    def _result_replica_key(self, result: QueryResult) -> str:
        value = result.metadata.get(_REPLICA_KEY)
        if isinstance(value, str) and value:
            return value
        return self._memory_key(
            result.namespace,
            result.text,
            result.tags,
            result.metadata,
        )

    @staticmethod
    def _memory_key(
        namespace: str,
        text: str,
        tags: Iterable[str],
        metadata: dict[str, Any],
    ) -> str:
        public_metadata = {
            key: value
            for key, value in metadata.items()
            if not str(key).startswith("_wavemind_")
        }
        payload = {
            "namespace": namespace,
            "text": text,
            "tags": sorted(str(tag) for tag in tags),
            "metadata": public_metadata,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

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

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _read_snapshot_manifest(snapshot_path: Path) -> dict[str, Any]:
        manifest_path = snapshot_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Snapshot manifest does not exist: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "wavemind.replicated_snapshot.v1":
            raise ValueError("Unsupported replicated snapshot format")
        return manifest

    @staticmethod
    def _prune_snapshots(
        directory: Path,
        *,
        prefix: str,
        keep_last: int,
    ) -> list[Path]:
        keep_last = max(0, int(keep_last))
        snapshots = sorted(
            [
                path
                for path in directory.glob(f"{prefix}-*")
                if path.is_dir() and (path / "manifest.json").exists()
            ],
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        deleted: list[Path] = []
        for path in snapshots[keep_last:]:
            shutil.rmtree(path)
            deleted.append(path)
        return deleted
