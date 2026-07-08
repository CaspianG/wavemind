from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

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
class DistributedQueryBatchResult:
    results: tuple[tuple[QueryResult, ...], ...]
    failed_nodes: tuple[dict[str, str], ...] = field(default_factory=tuple)
    read_quorum: int = 1
    query_http_requests: int = 0
    individual_query_http_requests: int = 0

    @property
    def ok(self) -> bool:
        return all(len(failures) == 0 for failures in self.failed_nodes)

    @property
    def request_reduction_ratio(self) -> float:
        if self.individual_query_http_requests <= 0:
            return 0.0
        return 1.0 - (
            float(self.query_http_requests)
            / float(self.individual_query_http_requests)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "items": [
                [result.text for result in item_results]
                for item_results in self.results
            ],
            "failed_nodes": [dict(failures) for failures in self.failed_nodes],
            "read_quorum": self.read_quorum,
            "query_http_requests": self.query_http_requests,
            "individual_query_http_requests": self.individual_query_http_requests,
            "request_reduction_ratio": self.request_reduction_ratio,
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
    tombstone_keys: int = 0
    tombstone_texts: int = 0
    tombstone_deleted: int = 0
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
            "tombstone_keys": self.tombstone_keys,
            "tombstone_texts": self.tombstone_texts,
            "tombstone_deleted": self.tombstone_deleted,
            "failed_nodes": dict(self.failed_nodes),
            "read_quorum": self.read_quorum,
            "write_quorum": self.write_quorum,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class _ServiceTombstoneState:
    keys: frozenset[str] = frozenset()
    texts: frozenset[str] = frozenset()


_SERVICE_TOMBSTONE_ACTION = "distributed_tombstone"


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
        trust_env: bool = False,
    ):
        self.api_key = api_key
        self.timeout = float(timeout)
        self.trust_env = bool(trust_env)
        self._opener = None if self.trust_env else build_opener(ProxyHandler({}))

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

    def query_batch(
        self,
        address: str,
        *,
        queries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {"queries": queries}
        response = self._request("POST", address, "/query/batch", payload)
        return {
            "count": int(response.get("count", 0)),
            "items": [
                {
                    "index": int(item.get("index", index)),
                    "text": item.get("text"),
                    "namespace": item.get("namespace"),
                    "results": [
                        _query_result_from_payload(result)
                        for result in item.get("results", [])
                    ],
                }
                for index, item in enumerate(response.get("items", []))
            ],
        }

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

    def export_namespace_state(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags: tuple[str, ...] = (),
        include_tombstones: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "namespace": namespace,
            "limit": int(limit),
            "include_expired": bool(include_expired),
            "tags": list(tags),
            "include_tombstones": bool(include_tombstones),
        }
        return self._request("POST", address, "/memories/export", payload)

    def log_tombstone(
        self,
        address: str,
        *,
        namespace: str,
        record_keys: tuple[str, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> int:
        payload = {
            "namespace": namespace,
            "record_keys": list(record_keys),
            "texts": list(texts),
        }
        response = self._request("POST", address, "/memories/tombstone", payload)
        return int(response["id"])

    def export_namespace_delta(
        self,
        address: str,
        *,
        namespace: str,
        since: float | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "namespace": namespace,
            "since": since,
            "limit": limit,
        }
        return self._request("POST", address, "/namespace-delta/export", payload)

    def import_namespace_delta(
        self,
        address: str,
        *,
        delta: dict[str, Any],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "delta": delta,
            "namespace": namespace,
        }
        return self._request("POST", address, "/namespace-delta/import", payload)

    def stats(self, address: str) -> dict[str, Any]:
        return self._request("GET", address, "/stats", None)

    def _request(
        self,
        method: str,
        address: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body = (
            None
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            _join_url(address, path),
            data=body,
            method=method,
            headers=headers,
        )
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            open_request = urlopen if self._opener is None else self._opener.open
            with open_request(request, timeout=self.timeout) as response:
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
        read_fanout: int | None = None,
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
        self.read_fanout = (
            self.replication_factor
            if read_fanout is None
            else int(read_fanout)
        )
        if self.write_quorum <= 0:
            raise ValueError("write_quorum must be positive")
        if self.read_quorum <= 0:
            raise ValueError("read_quorum must be positive")
        if self.read_fanout <= 0:
            raise ValueError("read_fanout must be positive")
        if self.write_quorum > self.replication_factor:
            raise ValueError("write_quorum cannot exceed replication_factor")
        if self.read_quorum > self.replication_factor:
            raise ValueError("read_quorum cannot exceed replication_factor")
        if self.read_fanout > self.replication_factor:
            raise ValueError("read_fanout cannot exceed replication_factor")
        if self.read_fanout < self.read_quorum:
            raise ValueError("read_fanout cannot be smaller than read_quorum")
        self.client = client or HTTPNamespaceShardClient()
        self._available = {node.id: True for node in self.nodes}
        self._node_by_id = {node.id: node for node in self.nodes}
        self._node_failures = {node.id: 0 for node in self.nodes}
        self._node_successes = {node.id: 0 for node in self.nodes}
        self._node_last_error: dict[str, str | None] = {
            node.id: None for node in self.nodes
        }

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
        write_nodes = []
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            write_nodes.append(node_id)

        def write_replica(node_id: str) -> tuple[str, int]:
            return (
                node_id,
                self.client.remember(
                    self._address(node_id),
                    text=text,
                    namespace=namespace,
                    tags=tuple(tags),
                    ttl_seconds=ttl_seconds,
                    metadata=metadata,
                    priority=priority,
                ),
            )

        with ThreadPoolExecutor(max_workers=max(1, len(write_nodes))) as pool:
            futures = {
                pool.submit(write_replica, node_id): node_id
                for node_id in write_nodes
            }
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    _, record_id = future.result()
                    writes[node_id] = record_id
                    self._mark_node_success(node_id)
                except Exception as exc:  # pragma: no cover - service boundary
                    self._mark_node_failure(node_id, exc)
                    failed[node_id] = str(exc)
        if len(writes) < self.write_quorum:
            raise DistributedWriteQuorumError(
                f"Write quorum {self.write_quorum} was not reached for "
                f"namespace {namespace!r}; successful writes: {len(writes)}; "
                f"failures: {failed}"
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
        read_node_ids = self._read_node_ids(placement)
        tombstones = self._tombstone_state(namespace, read_node_ids)
        successful_reads = 0
        failed: dict[str, str] = {}
        best_by_key: dict[tuple[str, str, tuple[str, ...]], QueryResult] = {}
        for node_id in read_node_ids:
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
                self._mark_node_success(node_id)
            except Exception as exc:  # pragma: no cover - service boundary
                self._mark_node_failure(node_id, exc)
                failed[node_id] = str(exc)
                continue
            for result in results:
                result_key = _query_result_key(result)
                if result_key in tombstones.keys or result.text in tombstones.texts:
                    continue
                key = (result.namespace, result_key, tuple(sorted(result.tags)))
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

    def query_batch(
        self,
        queries: list[dict[str, Any]],
    ) -> DistributedQueryBatchResult:
        if not queries:
            return DistributedQueryBatchResult(
                results=(),
                failed_nodes=(),
                read_quorum=self.read_quorum,
                query_http_requests=0,
                individual_query_http_requests=0,
            )

        normalized: list[dict[str, Any]] = []
        read_nodes_by_index: list[tuple[str, ...]] = []
        failed_by_index: list[dict[str, str]] = []
        tombstone_cache: dict[tuple[str, tuple[str, ...]], _ServiceTombstoneState] = {}
        best_by_index: list[dict[tuple[str, str, tuple[str, ...]], QueryResult]] = [
            {} for _ in queries
        ]
        successful_reads = [0 for _ in queries]
        by_node: dict[str, list[tuple[int, dict[str, Any]]]] = {}

        for index, raw_query in enumerate(queries):
            namespace = str(raw_query.get("namespace", "default"))
            text = str(raw_query["text"])
            query = {
                "text": text,
                "namespace": namespace,
                "top_k": int(raw_query.get("top_k", 3)),
                "tags": list(raw_query.get("tags", ())),
                "min_score": raw_query.get("min_score"),
            }
            normalized.append(query)
            placement = self.placement(namespace)
            read_node_ids = self._read_node_ids(placement)
            read_nodes_by_index.append(read_node_ids)
            failed: dict[str, str] = {}
            failed_by_index.append(failed)
            tombstone_key = (namespace, read_node_ids)
            if tombstone_key not in tombstone_cache:
                tombstone_cache[tombstone_key] = self._tombstone_state(
                    namespace,
                    read_node_ids,
                )
            for node_id in read_node_ids:
                if not self._available.get(node_id, False):
                    failed[node_id] = "node unavailable"
                    continue
                by_node.setdefault(node_id, []).append((index, query))

        query_http_requests = 0
        for node_id, node_queries in by_node.items():
            batch_payload = [query for _, query in node_queries]
            try:
                response = self.client.query_batch(
                    self._address(node_id),
                    queries=batch_payload,
                )
                query_http_requests += 1
                self._mark_node_success(node_id)
            except Exception as exc:  # pragma: no cover - service boundary
                self._mark_node_failure(node_id, exc)
                for original_index, _ in node_queries:
                    failed_by_index[original_index][node_id] = str(exc)
                continue

            seen_local_indexes: set[int] = set()
            for item in response.get("items", []):
                local_index = int(item.get("index", len(seen_local_indexes)))
                if local_index < 0 or local_index >= len(node_queries):
                    continue
                seen_local_indexes.add(local_index)
                original_index, query = node_queries[local_index]
                successful_reads[original_index] += 1
                namespace = str(query["namespace"])
                tombstones = tombstone_cache[(namespace, read_nodes_by_index[original_index])]
                for result in item.get("results", []):
                    result_key = _query_result_key(result)
                    if result_key in tombstones.keys or result.text in tombstones.texts:
                        continue
                    key = (result.namespace, result_key, tuple(sorted(result.tags)))
                    enriched = _with_node_metadata(result, node_id)
                    current = best_by_index[original_index].get(key)
                    if current is None or enriched.score > current.score:
                        best_by_index[original_index][key] = enriched
            missing_local_indexes = set(range(len(node_queries))) - seen_local_indexes
            for local_index in missing_local_indexes:
                original_index, _ = node_queries[local_index]
                failed_by_index[original_index][node_id] = "batch item missing"

        result_items: list[tuple[QueryResult, ...]] = []
        for index, query in enumerate(normalized):
            if successful_reads[index] < self.read_quorum:
                namespace = str(query["namespace"])
                raise DistributedReadQuorumError(
                    f"Read quorum {self.read_quorum} was not reached for "
                    f"batch query {index} in namespace {namespace!r}; "
                    f"successful reads: {successful_reads[index]}; "
                    f"failures: {failed_by_index[index]}"
                )
            top_k = int(query.get("top_k", 3))
            ordered = sorted(
                best_by_index[index].values(),
                key=lambda result: result.score,
                reverse=True,
            )[:top_k]
            result_items.append(tuple(ordered))

        individual_query_http_requests = sum(len(nodes) for nodes in read_nodes_by_index)
        return DistributedQueryBatchResult(
            results=tuple(result_items),
            failed_nodes=tuple(dict(failures) for failures in failed_by_index),
            read_quorum=self.read_quorum,
            query_http_requests=query_http_requests,
            individual_query_http_requests=individual_query_http_requests,
        )

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
        tombstone_keys, tombstone_texts = self._resolve_tombstone_targets(
            placement,
            namespace,
            id=id,
            text=text,
        )
        deletes: dict[str, int] = {}
        failed: dict[str, str] = {}
        delete_nodes = []
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            delete_nodes.append(node_id)

        def delete_replica(node_id: str) -> tuple[str, int]:
            deleted = self.client.forget(
                self._address(node_id),
                namespace=namespace,
                id=id,
                text=text,
            )
            self.client.log_tombstone(
                self._address(node_id),
                namespace=namespace,
                record_keys=tuple(sorted(tombstone_keys)),
                texts=tuple(sorted(tombstone_texts)),
            )
            return node_id, deleted

        with ThreadPoolExecutor(max_workers=max(1, len(delete_nodes))) as pool:
            futures = {
                pool.submit(delete_replica, node_id): node_id
                for node_id in delete_nodes
            }
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    _, deleted = future.result()
                    deletes[node_id] = deleted
                    self._mark_node_success(node_id)
                except Exception as exc:  # pragma: no cover - service boundary
                    self._mark_node_failure(node_id, exc)
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
        tombstone_keys: set[str] = set()
        tombstone_texts: set[str] = set()
        failed: dict[str, str] = {}
        available: list[str] = []
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                failed[node_id] = "node unavailable"
                continue
            try:
                exported_state = self.client.export_namespace_state(
                    self._address(node_id),
                    namespace=namespace,
                    limit=limit,
                    include_expired=include_expired,
                    tags=tuple(tags),
                )
                self._mark_node_success(node_id)
            except Exception as exc:  # pragma: no cover - service boundary
                self._mark_node_failure(node_id, exc)
                failed[node_id] = str(exc)
                continue
            available.append(node_id)
            exported = [dict(record) for record in exported_state.get("records", [])]
            for tombstone in exported_state.get("tombstones", []):
                raw_keys = tombstone.get("record_keys", [])
                raw_texts = tombstone.get("texts", [])
                if isinstance(raw_keys, list):
                    tombstone_keys.update(str(key) for key in raw_keys)
                if isinstance(raw_texts, list):
                    tombstone_texts.update(str(item) for item in raw_texts)
            keyed = {_record_key(record): record for record in exported}
            records_by_node[node_id] = keyed
            for key, record in keyed.items():
                key_string = _record_key_string_from_tuple(key)
                if key_string in tombstone_keys or str(record.get("text") or "") in tombstone_texts:
                    continue
                canonical.setdefault(key, record)

        if len(available) < self.read_quorum:
            raise DistributedReadQuorumError(
                f"Repair read quorum {self.read_quorum} was not reached for "
                f"namespace {namespace!r}; successful reads: {len(available)}; "
                f"failures: {failed}"
            )
        canonical = {
            key: record
            for key, record in canonical.items()
            if _record_key_string_from_tuple(key) not in tombstone_keys
            and str(record.get("text") or "") not in tombstone_texts
        }

        repaired: dict[str, int] = {}
        missing_before_repair: dict[str, int] = {}
        tombstone_deleted = 0
        for node_id in placement.replicas:
            if node_id not in records_by_node:
                continue
            for key, record in list(records_by_node[node_id].items()):
                key_string = _record_key_string_from_tuple(key)
                if key_string in tombstone_keys or str(record.get("text") or "") in tombstone_texts:
                    try:
                        tombstone_deleted += self.client.forget(
                            self._address(node_id),
                            namespace=namespace,
                            text=str(record["text"]),
                        )
                        self._mark_node_success(node_id)
                    except Exception as exc:  # pragma: no cover - service boundary
                        self._mark_node_failure(node_id, exc)
                        failed[node_id] = str(exc)
                    records_by_node[node_id].pop(key, None)
            missing = [
                record
                for key, record in canonical.items()
                if key not in records_by_node[node_id]
                and _record_key_string_from_tuple(key) not in tombstone_keys
                and str(record.get("text") or "") not in tombstone_texts
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
                    self._mark_node_success(node_id)
                except Exception as exc:  # pragma: no cover - service boundary
                    self._mark_node_failure(node_id, exc)
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
            tombstone_keys=len(tombstone_keys),
            tombstone_texts=len(tombstone_texts),
            tombstone_deleted=tombstone_deleted,
            failed_nodes=failed,
            read_quorum=self.read_quorum,
            write_quorum=self.write_quorum,
        )

    def stats(self) -> dict[str, object]:
        health = self.node_health()
        return {
            "nodes": len(self.nodes),
            "replication_factor": self.replication_factor,
            "write_quorum": self.write_quorum,
            "read_quorum": self.read_quorum,
            "read_fanout": self.read_fanout,
            "available_nodes": sum(1 for value in self._available.values() if value),
            "healthy_nodes": sum(
                1 for payload in health.values() if payload["status"] == "healthy"
            ),
            "degraded_nodes": sum(
                1 for payload in health.values() if payload["status"] == "degraded"
            ),
            "unavailable_nodes": sum(
                1 for payload in health.values() if payload["status"] == "unavailable"
            ),
            "node_health": health,
        }

    def node_health(self) -> dict[str, dict[str, object]]:
        """Return operator-facing health and circuit state for cluster nodes."""

        payload: dict[str, dict[str, object]] = {}
        for node in self.nodes:
            available = bool(self._available.get(node.id, False))
            last_error = self._node_last_error.get(node.id)
            if not available:
                status = "unavailable"
            elif last_error:
                status = "degraded"
            else:
                status = "healthy"
            payload[node.id] = {
                "id": node.id,
                "address": node.address,
                "zone": node.zone,
                "available": available,
                "status": status,
                "successes": int(self._node_successes.get(node.id, 0)),
                "failures": int(self._node_failures.get(node.id, 0)),
                "last_error": last_error,
            }
        return payload

    def probe_nodes(self) -> dict[str, dict[str, object]]:
        """Probe every available service node and return updated health state."""

        for node in self.nodes:
            if not self._available.get(node.id, False):
                continue
            try:
                self.client.stats(self._address(node.id))
                self._mark_node_success(node.id)
            except Exception as exc:  # pragma: no cover - service boundary
                self._mark_node_failure(node.id, exc)
        return self.node_health()

    def _address(self, node_id: str) -> str:
        return self._node_by_id[node_id].address

    def _read_node_ids(self, placement: NamespacePlacement) -> tuple[str, ...]:
        available = [
            node_id
            for node_id in placement.replicas
            if self._available.get(node_id, False)
        ]
        return tuple(available[: self.read_fanout])

    def _resolve_tombstone_targets(
        self,
        placement: NamespacePlacement,
        namespace: str,
        *,
        id: int | None,
        text: str | None,
    ) -> tuple[set[str], set[str]]:
        keys: set[str] = set()
        texts: set[str] = set()
        if text is not None:
            texts.add(text)
        if text is not None and id is None:
            return keys, texts
        for node_id in placement.replicas:
            if not self._available.get(node_id, False):
                continue
            try:
                state = self.client.export_namespace_state(
                    self._address(node_id),
                    namespace=namespace,
                    limit=10_000,
                    include_expired=True,
                    include_tombstones=False,
                )
                self._mark_node_success(node_id)
            except Exception as exc:
                self._mark_node_failure(node_id, exc)
                continue
            for record in state.get("records", []):
                record_id = record.get("id")
                record_text = str(record.get("text") or "")
                if (id is not None and int(record_id) == int(id)) or (
                    text is not None and record_text == text
                ):
                    keys.add(_record_key_string(record))
                    texts.add(record_text)
        return keys, texts

    def _tombstone_state(
        self,
        namespace: str,
        node_ids: tuple[str, ...],
    ) -> _ServiceTombstoneState:
        keys: set[str] = set()
        texts: set[str] = set()
        for node_id in node_ids:
            if not self._available.get(node_id, False):
                continue
            try:
                state = self.client.export_namespace_state(
                    self._address(node_id),
                    namespace=namespace,
                    limit=0,
                    include_tombstones=True,
                )
                self._mark_node_success(node_id)
            except Exception as exc:
                self._mark_node_failure(node_id, exc)
                continue
            for tombstone in state.get("tombstones", []):
                raw_keys = tombstone.get("record_keys", [])
                raw_texts = tombstone.get("texts", [])
                if isinstance(raw_keys, list):
                    keys.update(str(key) for key in raw_keys)
                if isinstance(raw_texts, list):
                    texts.update(str(item) for item in raw_texts)
        return _ServiceTombstoneState(keys=frozenset(keys), texts=frozenset(texts))

    def _mark_node_success(self, node_id: str) -> None:
        if node_id not in self._node_successes:
            return
        self._node_successes[node_id] += 1
        self._node_last_error[node_id] = None

    def _mark_node_failure(self, node_id: str, error: object) -> None:
        if node_id not in self._node_failures:
            return
        self._node_failures[node_id] += 1
        self._node_last_error[node_id] = str(error)


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


def _record_key_string(record: dict[str, Any]) -> str:
    return json.dumps(_record_key(record), ensure_ascii=False, sort_keys=True, default=str)


def _record_key_string_from_tuple(key: tuple[object, ...]) -> str:
    return json.dumps(key, ensure_ascii=False, sort_keys=True, default=str)


def _query_result_key(result: QueryResult) -> str:
    return _record_key_string(
        {
            "namespace": result.namespace,
            "text": result.text,
            "tags": list(result.tags),
            "metadata": result.metadata,
        }
    )
