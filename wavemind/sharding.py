from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .cluster import ClusterNode, NamespacePlacement, build_cluster_plan
from .core import QueryResult, WaveMind


class NamespaceShardRouter:
    def __init__(self, root_path: str | Path, shard_count: int = 16):
        if shard_count <= 0:
            raise ValueError("shard_count must be positive")
        self.root_path = Path(root_path)
        self.shard_count = int(shard_count)
        self.root_path.mkdir(parents=True, exist_ok=True)

    def shard_for(self, namespace: str) -> int:
        digest = hashlib.sha256(namespace.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.shard_count

    def db_path(self, namespace: str) -> Path:
        return self.root_path / f"shard-{self.shard_for(namespace):04d}.sqlite3"

    def existing_shards(self) -> list[Path]:
        return sorted(self.root_path.glob("shard-*.sqlite3"))


class ShardedWaveMind:
    """Route namespaces across multiple local WaveMind SQLite databases."""

    def __init__(
        self,
        root_path: str | Path,
        shard_count: int = 16,
        **mind_kwargs: Any,
    ):
        if "db_path" in mind_kwargs:
            raise ValueError("ShardedWaveMind manages db_path per shard")
        self.router = NamespaceShardRouter(root_path=root_path, shard_count=shard_count)
        self.mind_kwargs = dict(mind_kwargs)
        self._minds: dict[Path, WaveMind] = {}

    def remember(
        self,
        text: str,
        namespace: str = "default",
        **kwargs: Any,
    ) -> int:
        return self._mind(namespace).remember(text, namespace=namespace, **kwargs)

    def query(
        self,
        text: str,
        namespace: str = "default",
        **kwargs: Any,
    ) -> list[QueryResult]:
        return self._mind(namespace).query(text, namespace=namespace, **kwargs)

    def forget(
        self,
        namespace: str = "default",
        **kwargs: Any,
    ) -> int:
        return self._mind(namespace).forget(namespace=namespace, **kwargs)

    def purge_expired(self) -> int:
        return sum(mind.purge_expired() for mind in self._all_minds())

    def stats(self, namespace: str | None = None) -> dict[str, Any]:
        if namespace is not None:
            payload = self._mind(namespace).stats(namespace=namespace)
            payload["shard"] = self.router.shard_for(namespace)
            payload["shards"] = self.router.shard_count
            return payload

        totals: dict[str, Any] = {
            "active_memories": 0,
            "expired_memories": 0,
            "total_memories": 0,
            "audit_events": 0,
            "shards": self.router.shard_count,
            "shard_files": 0,
        }
        for mind in self._all_minds():
            stats = mind.stats()
            totals["active_memories"] += int(stats["active_memories"])
            totals["expired_memories"] += int(stats["expired_memories"])
            totals["total_memories"] += int(stats["total_memories"])
            totals["audit_events"] += int(stats.get("audit_events", 0))
            totals["shard_files"] += 1
        return totals

    def save(self, backup_dir: str | Path) -> list[Path]:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for mind in self._all_minds():
            path = Path(mind.store.path)
            paths.append(mind.save(backup_dir / path.name))
        return [path for path in paths if path is not None]

    def close(self) -> None:
        for mind in self._minds.values():
            mind.close()
        self._minds.clear()

    def __enter__(self) -> "ShardedWaveMind":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _mind(self, namespace: str) -> WaveMind:
        path = self.router.db_path(namespace)
        mind = self._minds.get(path)
        if mind is None:
            mind = WaveMind(db_path=path, **self.mind_kwargs)
            self._minds[path] = mind
        return mind

    def _all_minds(self) -> list[WaveMind]:
        for path in self.router.existing_shards():
            if path not in self._minds:
                self._minds[path] = WaveMind(db_path=path, **self.mind_kwargs)
        return list(self._minds.values())


class DistributedShardError(RuntimeError):
    """Base class for service-backed shard routing failures."""


class DistributedWriteQuorumError(DistributedShardError):
    """Raised when a distributed write cannot reach the configured quorum."""


class DistributedReadQuorumError(DistributedShardError):
    """Raised when a distributed read cannot reach the configured quorum."""


@dataclass(frozen=True)
class DistributedWriteResult:
    namespace: str
    primary_node: str
    writes: dict[str, int]
    failed_nodes: dict[str, str] = field(default_factory=dict)
    write_quorum: int = 1

    @property
    def ok(self) -> bool:
        return len(self.writes) >= self.write_quorum

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "primary_node": self.primary_node,
            "writes": dict(self.writes),
            "failed_nodes": dict(self.failed_nodes),
            "write_quorum": self.write_quorum,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class DistributedForgetResult:
    namespace: str
    primary_node: str
    deletes: dict[str, int]
    failed_nodes: dict[str, str] = field(default_factory=dict)
    write_quorum: int = 1

    @property
    def ok(self) -> bool:
        return len(self.deletes) >= self.write_quorum

    @property
    def deleted(self) -> int:
        return sum(self.deletes.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "primary_node": self.primary_node,
            "deletes": dict(self.deletes),
            "deleted": self.deleted,
            "failed_nodes": dict(self.failed_nodes),
            "write_quorum": self.write_quorum,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class DistributedRepairReport:
    namespace: str
    replicas: tuple[str, ...]
    available_nodes: tuple[str, ...]
    canonical_records: int
    repaired: dict[str, int]
    missing_before_repair: dict[str, int]
    failed_nodes: dict[str, str] = field(default_factory=dict)
    read_quorum: int = 1
    write_quorum: int = 1

    @property
    def ok(self) -> bool:
        return len(self.available_nodes) >= self.read_quorum and not self.failed_nodes

    @property
    def repaired_total(self) -> int:
        return sum(self.repaired.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "replicas": list(self.replicas),
            "available_nodes": list(self.available_nodes),
            "canonical_records": self.canonical_records,
            "repaired": dict(self.repaired),
            "repaired_total": self.repaired_total,
            "missing_before_repair": dict(self.missing_before_repair),
            "failed_nodes": dict(self.failed_nodes),
            "read_quorum": self.read_quorum,
            "write_quorum": self.write_quorum,
            "ok": self.ok,
        }


class HTTPNamespaceShardClient:
    """Small HTTP client for WaveMind API nodes.

    It intentionally uses the standard library so service-mode sharding does not
    add a hard dependency on requests/httpx.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.timeout = float(timeout)

    def remember(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        tags: tuple[str, ...] = (),
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        priority: float = 1.0,
    ) -> int:
        payload = {
            "text": text,
            "namespace": namespace,
            "tags": list(tags),
            "ttl_seconds": ttl_seconds,
            "metadata": metadata or {},
            "priority": priority,
        }
        response = self._request("POST", address, "/remember", payload)
        return int(response["id"])

    def query(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        top_k: int = 3,
        tags: tuple[str, ...] = (),
        min_score: float | None = None,
    ) -> list[QueryResult]:
        payload = {
            "text": text,
            "namespace": namespace,
            "top_k": int(top_k),
            "tags": list(tags),
            "min_score": min_score,
        }
        response = self._request("POST", address, "/query", payload)
        return [_query_result_from_payload(item) for item in response.get("results", [])]

    def forget(
        self,
        address: str,
        *,
        namespace: str,
        id: int | None = None,
        text: str | None = None,
    ) -> int:
        payload = {
            "id": id,
            "text": text,
            "namespace": namespace,
        }
        response = self._request("DELETE", address, "/forget", payload)
        return int(response["deleted"])

    def export_namespace(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        payload = {
            "namespace": namespace,
            "limit": int(limit),
            "include_expired": bool(include_expired),
            "tags": list(tags),
        }
        response = self._request("POST", address, "/memories/export", payload)
        return [dict(record) for record in response.get("records", [])]

    def _request(
        self,
        method: str,
        address: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            _join_url(address, path),
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DistributedShardError(
                f"{method} {path} failed on {address}: HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise DistributedShardError(
                f"{method} {path} failed on {address}: {exc.reason}"
            ) from exc
        return json.loads(raw or "{}")


class DistributedShardedWaveMind:
    """Route namespaces across service-backed WaveMind API nodes.

    This is the service-mode counterpart to local `ShardedWaveMind`: namespace
    placement is rendezvous-hashed, writes go to the placement replicas with a
    write quorum, and reads merge results from available replicas.
    """

    def __init__(
        self,
        nodes: list[ClusterNode | dict[str, object] | str],
        *,
        replication_factor: int = 2,
        write_quorum: int | None = None,
        read_quorum: int = 1,
        client: HTTPNamespaceShardClient | Any | None = None,
    ):
        plan = build_cluster_plan(
            namespaces=[],
            nodes=nodes,
            replication_factor=replication_factor,
        )
        self.nodes = plan.nodes
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
        self.client = client or HTTPNamespaceShardClient()
        self._available = {node.id: True for node in self.nodes}
        self._node_by_id = {node.id: node for node in self.nodes}

    def placement(self, namespace: str = "default") -> NamespacePlacement:
        return build_cluster_plan(
            namespaces=[namespace],
            nodes=self.nodes,
            replication_factor=self.replication_factor,
        ).placements[0]

    def set_node_available(self, node_id: str, available: bool) -> None:
        if node_id not in self._available:
            raise ValueError(f"Unknown cluster node: {node_id}")
        self._available[node_id] = bool(available)

    def remember(
        self,
        text: str,
        namespace: str = "default",
        *,
        tags: list[str] | tuple[str, ...] = (),
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        priority: float = 1.0,
    ) -> DistributedWriteResult:
        placement = self.placement(namespace)
        writes: dict[str, int] = {}
        failed: dict[str, str] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                writes[node_id] = self.client.remember(
                    self._address(node_id),
                    text=text,
                    namespace=namespace,
                    tags=tuple(tags),
                    ttl_seconds=ttl_seconds,
                    metadata=metadata,
                    priority=priority,
                )
            except Exception as exc:  # pragma: no cover - service boundary
                failed[node_id] = str(exc)
        if len(writes) < self.write_quorum:
            raise DistributedWriteQuorumError(
                f"Write quorum {self.write_quorum} was not reached for "
                f"namespace {namespace!r}; successful writes: {len(writes)}"
            )
        return DistributedWriteResult(
            namespace=namespace,
            primary_node=placement.primary,
            writes=writes,
            failed_nodes=failed,
            write_quorum=self.write_quorum,
        )

    def query(
        self,
        text: str,
        namespace: str = "default",
        *,
        top_k: int = 3,
        tags: list[str] | tuple[str, ...] = (),
        min_score: float | None = None,
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
                results = self.client.query(
                    self._address(node_id),
                    text=text,
                    namespace=namespace,
                    top_k=top_k,
                    tags=tuple(tags),
                    min_score=min_score,
                )
                successful_reads += 1
            except Exception as exc:  # pragma: no cover - service boundary
                failed[node_id] = str(exc)
                continue
            for result in results:
                key = (result.namespace, result.text, tuple(sorted(result.tags)))
                current = best_by_key.get(key)
                enriched = _with_node_metadata(result, node_id)
                if current is None or enriched.score > current.score:
                    best_by_key[key] = enriched
        if successful_reads < self.read_quorum:
            raise DistributedReadQuorumError(
                f"Read quorum {self.read_quorum} was not reached for "
                f"namespace {namespace!r}; successful reads: {successful_reads}; "
                f"failures: {failed}"
            )
        return sorted(
            best_by_key.values(),
            key=lambda result: result.score,
            reverse=True,
        )[:top_k]

    def forget(
        self,
        *,
        namespace: str = "default",
        id: int | None = None,
        text: str | None = None,
    ) -> DistributedForgetResult:
        if id is None and text is None:
            raise ValueError("forget requires id or text")
        placement = self.placement(namespace)
        deletes: dict[str, int] = {}
        failed: dict[str, str] = {}
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                deletes[node_id] = self.client.forget(
                    self._address(node_id),
                    namespace=namespace,
                    id=id,
                    text=text,
                )
            except Exception as exc:  # pragma: no cover - service boundary
                failed[node_id] = str(exc)
        if len(deletes) < self.write_quorum:
            raise DistributedWriteQuorumError(
                f"Forget quorum {self.write_quorum} was not reached for "
                f"namespace {namespace!r}; successful writes: {len(deletes)}"
            )
        return DistributedForgetResult(
            namespace=namespace,
            primary_node=placement.primary,
            deletes=deletes,
            failed_nodes=failed,
            write_quorum=self.write_quorum,
        )

    def repair_namespace(
        self,
        namespace: str = "default",
        *,
        limit: int = 1000,
        include_expired: bool = False,
        tags: list[str] | tuple[str, ...] = (),
    ) -> DistributedRepairReport:
        placement = self.placement(namespace)
        records_by_node: dict[str, dict[tuple[object, ...], dict[str, Any]]] = {}
        canonical: dict[tuple[object, ...], dict[str, Any]] = {}
        failed: dict[str, str] = {}
        available: list[str] = []
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                exported = self.client.export_namespace(
                    self._address(node_id),
                    namespace=namespace,
                    limit=limit,
                    include_expired=include_expired,
                    tags=tuple(tags),
                )
            except Exception as exc:  # pragma: no cover - service boundary
                failed[node_id] = str(exc)
                continue
            available.append(node_id)
            keyed = {_record_key(record): record for record in exported}
            records_by_node[node_id] = keyed
            for key, record in keyed.items():
                canonical.setdefault(key, record)

        if len(available) < self.read_quorum:
            raise DistributedReadQuorumError(
                f"Repair read quorum {self.read_quorum} was not reached for "
                f"namespace {namespace!r}; successful reads: {len(available)}; "
                f"failures: {failed}"
            )

        repaired: dict[str, int] = {}
        missing_before_repair: dict[str, int] = {}
        for node_id in placement.replicas:
            if node_id not in records_by_node:
                continue
            missing = [
                record
                for key, record in canonical.items()
                if key not in records_by_node[node_id]
            ]
            missing_before_repair[node_id] = len(missing)
            if not missing:
                repaired[node_id] = 0
                continue
            writes = 0
            for record in missing:
                try:
                    self.client.remember(
                        self._address(node_id),
                        text=str(record["text"]),
                        namespace=namespace,
                        tags=tuple(record.get("tags") or ()),
                        ttl_seconds=None,
                        metadata=dict(record.get("metadata") or {}),
                        priority=float(record.get("priority", 1.0)),
                    )
                    writes += 1
                except Exception as exc:  # pragma: no cover - service boundary
                    failed[node_id] = str(exc)
                    break
            repaired[node_id] = writes

        return DistributedRepairReport(
            namespace=namespace,
            replicas=tuple(placement.replicas),
            available_nodes=tuple(available),
            canonical_records=len(canonical),
            repaired=repaired,
            missing_before_repair=missing_before_repair,
            failed_nodes=failed,
            read_quorum=self.read_quorum,
            write_quorum=self.write_quorum,
        )

    def stats(self) -> dict[str, object]:
        return {
            "nodes": len(self.nodes),
            "replication_factor": self.replication_factor,
            "write_quorum": self.write_quorum,
            "read_quorum": self.read_quorum,
            "available_nodes": sum(1 for value in self._available.values() if value),
        }

    def _address(self, node_id: str) -> str:
        return self._node_by_id[node_id].address


def _join_url(address: str, path: str) -> str:
    base = address.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return f"{base}/{path.lstrip('/')}"


def _query_result_from_payload(payload: dict[str, Any]) -> QueryResult:
    return QueryResult(
        id=int(payload["id"]),
        text=str(payload["text"]),
        score=float(payload["score"]),
        vector_score=float(payload.get("vector_score", 0.0)),
        field_score=float(payload.get("field_score", 0.0)),
        graph_score=float(payload.get("graph_score", 0.0)),
        namespace=str(payload["namespace"]),
        tags=tuple(payload.get("tags") or ()),
        metadata=dict(payload.get("metadata") or {}),
    )


def _with_node_metadata(result: QueryResult, node_id: str) -> QueryResult:
    metadata = dict(result.metadata)
    metadata.setdefault("_wavemind_node", node_id)
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


def _record_key(record: dict[str, Any]) -> tuple[object, ...]:
    metadata = json.dumps(
        dict(record.get("metadata") or {}),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return (
        str(record.get("namespace") or ""),
        str(record.get("text") or ""),
        tuple(sorted(str(tag) for tag in (record.get("tags") or ()))),
        metadata,
    )
