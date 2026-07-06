from __future__ import annotations

import time
import json
import hashlib
import shutil
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .core import QueryResult
from .object_store import ObjectStoreArchive, ObjectStoreUploadReport, S3SnapshotStore
from .replication import ReplicatedWaveMind


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    size: int
    capacity: int

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return 0.0 if total == 0 else self.hits / total

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["hit_rate"] = self.hit_rate
        return payload


@dataclass
class _CacheEntry:
    value: list[QueryResult]
    expires_at: float


class HotMemoryCache:
    """Small in-process LRU cache for hot namespace/query pairs."""

    def __init__(self, capacity: int = 1024, ttl_seconds: float = 60.0):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.capacity = int(capacity)
        self.ttl_seconds = float(ttl_seconds)
        self._items: OrderedDict[tuple[object, ...], _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(
        self,
        namespace: str,
        query: str,
        *,
        top_k: int,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> list[QueryResult] | None:
        key = self._key(namespace, query, top_k=top_k, tags=tags, min_score=min_score)
        entry = self._items.get(key)
        now = time.time()
        if entry is None or entry.expires_at <= now:
            self._misses += 1
            if entry is not None:
                self._items.pop(key, None)
            return None
        self._hits += 1
        self._items.move_to_end(key)
        return list(entry.value)

    def put(
        self,
        namespace: str,
        query: str,
        value: list[QueryResult],
        *,
        top_k: int,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> None:
        key = self._key(namespace, query, top_k=top_k, tags=tags, min_score=min_score)
        self._items[key] = _CacheEntry(
            value=list(value),
            expires_at=time.time() + self.ttl_seconds,
        )
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
            self._evictions += 1

    def invalidate_namespace(self, namespace: str) -> int:
        keys = [key for key in self._items if key[0] == namespace]
        for key in keys:
            self._items.pop(key, None)
        return len(keys)

    def clear(self) -> None:
        self._items.clear()

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            size=len(self._items),
            capacity=self.capacity,
        )

    @staticmethod
    def _key(
        namespace: str,
        query: str,
        *,
        top_k: int,
        tags: Iterable[str] | None,
        min_score: float | None,
    ) -> tuple[object, ...]:
        return (
            namespace,
            query,
            int(top_k),
            tuple(sorted(tags or ())),
            None if min_score is None else float(min_score),
        )


class RedisHotMemoryCache:
    """Redis-backed cache for hot namespace/query pairs.

    The class accepts an existing Redis-like client so production deployments can
    reuse their connection pool while tests can pass a small fake client.
    """

    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "wavemind:hot",
        ttl_seconds: float = 60.0,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.client = client
        self.prefix = prefix.rstrip(":")
        self.ttl_seconds = float(ttl_seconds)
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        prefix: str = "wavemind:hot",
        ttl_seconds: float = 60.0,
    ) -> "RedisHotMemoryCache":
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                'Install Redis support with: pip install "wavemind[redis]"'
            ) from exc
        return cls(
            redis.Redis.from_url(url, decode_responses=True),
            prefix=prefix,
            ttl_seconds=ttl_seconds,
        )

    def get(
        self,
        namespace: str,
        query: str,
        *,
        top_k: int,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> list[QueryResult] | None:
        key = self._key(namespace, query, top_k=top_k, tags=tags, min_score=min_score)
        raw = self.client.get(key)
        if raw is None:
            self._misses += 1
            return None
        self._hits += 1
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(str(raw))
        return [
            QueryResult(
                id=int(item["id"]),
                text=str(item["text"]),
                score=float(item["score"]),
                vector_score=float(item["vector_score"]),
                field_score=float(item["field_score"]),
                graph_score=float(item.get("graph_score", 0.0)),
                namespace=str(item["namespace"]),
                tags=tuple(item.get("tags") or ()),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in payload
        ]

    def put(
        self,
        namespace: str,
        query: str,
        value: list[QueryResult],
        *,
        top_k: int,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> None:
        key = self._key(namespace, query, top_k=top_k, tags=tags, min_score=min_score)
        payload = [
            {
                "id": item.id,
                "text": item.text,
                "score": item.score,
                "vector_score": item.vector_score,
                "field_score": item.field_score,
                "graph_score": item.graph_score,
                "namespace": item.namespace,
                "tags": list(item.tags),
                "metadata": item.metadata,
            }
            for item in value
        ]
        self.client.set(
            key,
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=max(1, int(round(self.ttl_seconds))),
        )

    def invalidate_namespace(self, namespace: str) -> int:
        pattern = f"{self.prefix}:{namespace}:*"
        keys = list(self.client.scan_iter(match=pattern))
        if keys:
            self.client.delete(*keys)
        return len(keys)

    def clear(self) -> None:
        keys = list(self.client.scan_iter(match=f"{self.prefix}:*"))
        if keys:
            self.client.delete(*keys)

    def stats(self) -> CacheStats:
        size = 0
        try:
            size = sum(1 for _ in self.client.scan_iter(match=f"{self.prefix}:*"))
        except Exception:
            size = 0
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            size=size,
            capacity=0,
        )

    def _key(
        self,
        namespace: str,
        query: str,
        *,
        top_k: int,
        tags: Iterable[str] | None,
        min_score: float | None,
    ) -> str:
        tail = HotMemoryCache._key(
            namespace,
            query,
            top_k=top_k,
            tags=tags,
            min_score=min_score,
        )
        digest = hashlib.sha256(
            json.dumps(tail, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"{self.prefix}:{namespace}:{digest}"


def query_with_cache(
    memory: Any,
    cache: HotMemoryCache | RedisHotMemoryCache,
    text: str,
    *,
    namespace: str = "default",
    top_k: int = 3,
    tags: Iterable[str] | None = None,
    min_score: float | None = None,
) -> list[QueryResult]:
    cached = cache.get(
        namespace,
        text,
        top_k=top_k,
        tags=tags,
        min_score=min_score,
    )
    if cached is not None:
        return cached
    results = memory.query(
        text,
        namespace=namespace,
        top_k=top_k,
        tags=tags,
        min_score=min_score,
    )
    cache.put(
        namespace,
        text,
        results,
        top_k=top_k,
        tags=tags,
        min_score=min_score,
    )
    return results


@dataclass(frozen=True)
class MaintenanceReport:
    expired_purged: int = 0
    consolidated_steps: int = 0
    concepts_created: int = 0
    index_rebuilt: bool = False
    cache_invalidated: int = 0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CachePrewarmReport:
    scanned_events: int = 0
    candidates: int = 0
    warmed: int = 0
    skipped: int = 0
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned_events": self.scanned_events,
            "candidates": self.candidates,
            "warmed": self.warmed,
            "skipped": self.skipped,
            "errors": dict(self.errors),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class MemoryOSHotQuery:
    namespace: str
    query: str
    frequency: int
    last_seen: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryOSReport:
    namespace: str | None
    scanned_events: int
    hot_queries: tuple[MemoryOSHotQuery, ...] = ()
    expired_purged: int = 0
    consolidated_steps: int = 0
    concepts_created: int = 0
    concept_ids: tuple[int, ...] = ()
    priority_predictions: int = 0
    priority_boost_total: float = 0.0
    priority_boosted_ids: tuple[int, ...] = ()
    forgetting_demotions: int = 0
    forgetting_decay_total: float = 0.0
    forgetting_demoted_ids: tuple[int, ...] = ()
    index_rebuilt: bool = False
    cache_enabled: bool = False
    cache_invalidated: int = 0
    prewarm: CachePrewarmReport = field(default_factory=CachePrewarmReport)
    stats_before: dict[str, object] = field(default_factory=dict)
    stats_after: dict[str, object] = field(default_factory=dict)
    actions: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        index_healthy = bool(self.stats_after.get("index_healthy", True))
        return index_healthy and self.prewarm.ok

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "scanned_events": self.scanned_events,
            "hot_queries": [query.as_dict() for query in self.hot_queries],
            "expired_purged": self.expired_purged,
            "consolidated_steps": self.consolidated_steps,
            "concepts_created": self.concepts_created,
            "concept_ids": list(self.concept_ids),
            "priority_predictions": self.priority_predictions,
            "priority_boost_total": self.priority_boost_total,
            "priority_boosted_ids": list(self.priority_boosted_ids),
            "forgetting_demotions": self.forgetting_demotions,
            "forgetting_decay_total": self.forgetting_decay_total,
            "forgetting_demoted_ids": list(self.forgetting_demoted_ids),
            "index_rebuilt": self.index_rebuilt,
            "cache_enabled": self.cache_enabled,
            "cache_invalidated": self.cache_invalidated,
            "prewarm": self.prewarm.as_dict(),
            "stats_before": dict(self.stats_before),
            "stats_after": dict(self.stats_after),
            "actions": list(self.actions),
            "recommendations": list(self.recommendations),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class DistributedRepairJobReport:
    namespaces: tuple[str, ...]
    repaired_total: int = 0
    tombstone_deleted: int = 0
    reports: dict[str, dict[str, object]] = field(default_factory=dict)
    failed_namespaces: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed_namespaces and all(
            bool(report.get("ok", False)) for report in self.reports.values()
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "namespaces": list(self.namespaces),
            "repaired_total": self.repaired_total,
            "tombstone_deleted": self.tombstone_deleted,
            "reports": dict(self.reports),
            "failed_namespaces": dict(self.failed_namespaces),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ReplicatedSnapshotJobReport:
    snapshot_path: Path
    verified: bool
    total_bytes: int
    nodes: tuple[str, ...]
    offsite_path: Path | None = None
    offsite_verified: bool = False
    archive_path: Path | None = None
    archive_verified: bool = False
    object_store_upload: ObjectStoreUploadReport | None = None
    pruned_local: tuple[Path, ...] = ()
    pruned_offsite: tuple[Path, ...] = ()
    pruned_archives: tuple[Path, ...] = ()
    pruned_object_store: tuple[ObjectStoreArchive, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.verified
            and (self.offsite_path is None or self.offsite_verified)
            and (self.archive_path is None or self.archive_verified)
            and (
                self.object_store_upload is None
                or self.object_store_upload.verified
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "snapshot_path": str(self.snapshot_path),
            "verified": self.verified,
            "total_bytes": self.total_bytes,
            "nodes": list(self.nodes),
            "offsite_path": str(self.offsite_path) if self.offsite_path else None,
            "offsite_verified": self.offsite_verified,
            "archive_path": str(self.archive_path) if self.archive_path else None,
            "archive_verified": self.archive_verified,
            "object_store_upload": (
                self.object_store_upload.as_dict()
                if self.object_store_upload is not None
                else None
            ),
            "object_store_verified": (
                self.object_store_upload.verified
                if self.object_store_upload is not None
                else False
            ),
            "pruned_local": [str(path) for path in self.pruned_local],
            "pruned_offsite": [str(path) for path in self.pruned_offsite],
            "pruned_archives": [str(path) for path in self.pruned_archives],
            "pruned_object_store": [
                archive.as_dict() for archive in self.pruned_object_store
            ],
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ReplicatedObjectStoreDrillReport:
    source: str
    selected_archive: ObjectStoreArchive
    downloaded_archive_path: Path
    downloaded_sha256: str
    download_matches_object: bool
    archive_verified: bool
    restore_root: Path
    restored_nodes: tuple[str, ...]
    restored_files: int
    restored_total_bytes: int
    namespace: str | None = None
    query: str | None = None
    expected_text: str | None = None
    primary_node_disabled: str | None = None
    recalled_after_primary_loss: bool | None = None
    expected_text_found: bool | None = None

    @property
    def ok(self) -> bool:
        query_ok = True
        if self.query is not None:
            query_ok = bool(self.recalled_after_primary_loss)
            if self.expected_text is not None:
                query_ok = query_ok and bool(self.expected_text_found)
        return (
            self.selected_archive.verified
            and self.download_matches_object
            and self.archive_verified
            and self.restored_files > 0
            and query_ok
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "selected_archive": self.selected_archive.as_dict(),
            "downloaded_archive_path": str(self.downloaded_archive_path),
            "downloaded_sha256": self.downloaded_sha256,
            "download_matches_object": self.download_matches_object,
            "archive_verified": self.archive_verified,
            "restore_root": str(self.restore_root),
            "restored_nodes": list(self.restored_nodes),
            "restored_files": self.restored_files,
            "restored_total_bytes": self.restored_total_bytes,
            "namespace": self.namespace,
            "query": self.query,
            "expected_text": self.expected_text,
            "primary_node_disabled": self.primary_node_disabled,
            "recalled_after_primary_loss": self.recalled_after_primary_loss,
            "expected_text_found": self.expected_text_found,
            "ok": self.ok,
        }


class ReplicatedSnapshotWorker:
    """One-shot replicated snapshot job for schedulers and CronJobs."""

    def __init__(self, memory: ReplicatedWaveMind):
        self.memory = memory

    def run_once(
        self,
        *,
        destination: str | Path,
        prefix: str = "wavemind-replicated",
        keep_last: int | None = None,
        require_all: bool = True,
        offsite_destination: str | Path | None = None,
        archive_destination: str | Path | None = None,
        object_store_destination: str | None = None,
        object_store: S3SnapshotStore | None = None,
        object_store_keep_last: int | None = None,
    ) -> ReplicatedSnapshotJobReport:
        local_destination = Path(destination)
        snapshot = self.memory.snapshot(
            local_destination,
            prefix=prefix,
            keep_last=None,
            require_all=require_all,
        )
        health = ReplicatedWaveMind.verify_snapshot(snapshot.snapshot_path)
        verified = bool(health["healthy"])
        offsite_path: Path | None = None
        offsite_verified = False
        if offsite_destination is not None:
            offsite_root = Path(offsite_destination)
            offsite_root.mkdir(parents=True, exist_ok=True)
            offsite_path = offsite_root / snapshot.snapshot_path.name
            if offsite_path.exists():
                shutil.rmtree(offsite_path)
            shutil.copytree(snapshot.snapshot_path, offsite_path)
            offsite_verified = bool(
                ReplicatedWaveMind.verify_snapshot(offsite_path)["healthy"]
            )

        archive_path: Path | None = None
        archive_verified = False
        if object_store_destination is not None and archive_destination is None:
            archive_destination = local_destination
        if archive_destination is not None:
            archive = ReplicatedWaveMind.archive_snapshot(
                snapshot.snapshot_path,
                archive_destination,
            )
            archive_path = archive.archive_path
            archive_verified = archive.verified

        object_store_upload: ObjectStoreUploadReport | None = None
        if object_store_destination is not None:
            if archive_path is None:
                raise RuntimeError("object-store upload requires a snapshot archive")
            object_store = object_store or S3SnapshotStore.from_uri(
                object_store_destination
            )
            object_store_upload = object_store.upload_archive(archive_path)

        pruned_local: tuple[Path, ...] = ()
        pruned_offsite: tuple[Path, ...] = ()
        pruned_archives: tuple[Path, ...] = ()
        pruned_object_store: tuple[ObjectStoreArchive, ...] = ()
        if keep_last is not None:
            pruned_local = tuple(
                ReplicatedWaveMind.prune_snapshots(
                    local_destination,
                    prefix=prefix,
                    keep_last=keep_last,
                )
            )
            if offsite_destination is not None:
                pruned_offsite = tuple(
                    ReplicatedWaveMind.prune_snapshots(
                        offsite_destination,
                        prefix=prefix,
                        keep_last=keep_last,
                    )
                )
            if archive_destination is not None:
                archive_root = Path(archive_destination)
                if archive_root.name.endswith(".tar.gz") or archive_root.suffix == ".tgz":
                    archive_root = archive_root.parent
                pruned_archives = tuple(
                    ReplicatedWaveMind.prune_snapshot_archives(
                        archive_root,
                        prefix=prefix,
                        keep_last=keep_last,
                    )
                )
        if object_store is not None and object_store_keep_last is not None:
            pruned_object_store = object_store.prune_archives(
                keep_last=object_store_keep_last
            )

        return ReplicatedSnapshotJobReport(
            snapshot_path=snapshot.snapshot_path,
            verified=verified,
            total_bytes=snapshot.total_bytes,
            nodes=snapshot.nodes,
            offsite_path=offsite_path,
            offsite_verified=offsite_verified,
            archive_path=archive_path,
            archive_verified=archive_verified,
            object_store_upload=object_store_upload,
            pruned_local=pruned_local,
            pruned_offsite=pruned_offsite,
            pruned_archives=pruned_archives,
            pruned_object_store=pruned_object_store,
        )


class ReplicatedObjectStoreDrillWorker:
    """Restore and verify the newest or exact object-store snapshot archive."""

    def __init__(self, object_store: S3SnapshotStore):
        self.object_store = object_store

    def run_once(
        self,
        *,
        source: str,
        destination: str | Path,
        latest: bool | None = None,
        download_destination: str | Path | None = None,
        overwrite: bool = False,
        namespace: str | None = None,
        query: str | None = None,
        expected_text: str | None = None,
        top_k: int = 1,
        disable_primary: bool = True,
        **mind_kwargs: Any,
    ) -> ReplicatedObjectStoreDrillReport:
        use_latest = latest if latest is not None else not _looks_like_archive(source)
        if use_latest:
            selected = self.object_store.latest_archive()
            if selected is None:
                raise RuntimeError(f"no snapshot archives found under {source}")
        else:
            selected = self.object_store.describe_archive(source)

        download_root = Path(download_destination) if download_destination else (
            Path(destination).parent / "object-store-downloads"
        )
        downloaded = self.object_store.download_archive(selected.uri, download_root)
        downloaded_sha256 = _sha256_file(downloaded)
        download_matches_object = (
            bool(selected.sha256) and downloaded_sha256 == selected.sha256
        )
        archive_health = ReplicatedWaveMind.verify_snapshot_archive(downloaded)
        archive_verified = bool(archive_health["healthy"])

        restored = None
        try:
            restored, restore = ReplicatedWaveMind.restore_snapshot_archive(
                downloaded,
                destination,
                overwrite=overwrite,
                **mind_kwargs,
            )
            primary_node: str | None = None
            recalled: bool | None = None
            expected_found: bool | None = None
            if query is not None:
                query_namespace = namespace or "default"
                if disable_primary:
                    placement = restored.placement(query_namespace)
                    primary_node = placement.primary
                    restored.set_node_available(primary_node, False)
                results = restored.query(
                    query,
                    namespace=query_namespace,
                    top_k=top_k,
                )
                recalled = bool(results)
                if expected_text is not None:
                    expected_found = any(result.text == expected_text for result in results)
            return ReplicatedObjectStoreDrillReport(
                source=source,
                selected_archive=selected,
                downloaded_archive_path=downloaded,
                downloaded_sha256=downloaded_sha256,
                download_matches_object=download_matches_object,
                archive_verified=archive_verified,
                restore_root=restore.root_path,
                restored_nodes=restore.nodes,
                restored_files=len(restore.restored_files),
                restored_total_bytes=restore.total_bytes,
                namespace=namespace,
                query=query,
                expected_text=expected_text,
                primary_node_disabled=primary_node,
                recalled_after_primary_loss=recalled,
                expected_text_found=expected_found,
            )
        finally:
            if restored is not None:
                restored.close()


class MemoryMaintenanceWorker:
    """Deterministic maintenance worker for scheduled jobs or external queues."""

    def __init__(self, memory: Any, cache: HotMemoryCache | None = None):
        self.memory = memory
        self.cache = cache

    def run_once(
        self,
        *,
        namespace: str | None = None,
        consolidate_steps: int = 0,
        consolidate_concepts: bool = False,
        rebuild_unhealthy_index: bool = True,
    ) -> MaintenanceReport:
        expired = int(self.memory.purge_expired())
        if consolidate_steps > 0 and hasattr(self.memory, "consolidate"):
            self.memory.consolidate(steps=consolidate_steps)
        concepts: list[dict[str, object]] = []
        if consolidate_concepts and hasattr(self.memory, "consolidate_concepts"):
            concepts = self.memory.consolidate_concepts(namespace=namespace)
        rebuilt = False
        if rebuild_unhealthy_index and hasattr(self.memory, "ensure_index_health"):
            before = self.memory.index_health()
            self.memory.ensure_index_health(rebuild=True)
            rebuilt = not bool(before.get("healthy"))
        invalidated = 0
        if self.cache is not None and (expired or concepts):
            if namespace is not None:
                invalidated = self.cache.invalidate_namespace(namespace)
            else:
                invalidated = self.cache.stats().size
                self.cache.clear()
        return MaintenanceReport(
            expired_purged=expired,
            consolidated_steps=max(0, int(consolidate_steps)),
            concepts_created=len(concepts),
            index_rebuilt=rebuilt,
            cache_invalidated=invalidated,
        )


class CachePrewarmWorker:
    """Warm hot query cache from audited query events."""

    def __init__(self, memory: Any, cache: HotMemoryCache | RedisHotMemoryCache):
        self.memory = memory
        self.cache = cache

    def run_once(
        self,
        *,
        namespace: str | None = None,
        audit_limit: int = 256,
        max_queries: int = 32,
        min_frequency: int = 1,
        top_k: int = 3,
        min_score: float | None = None,
    ) -> CachePrewarmReport:
        if not hasattr(self.memory, "audit_events"):
            raise TypeError("memory object must expose audit_events()")
        events = self.memory.audit_events(
            namespace=namespace,
            action="query",
            limit=max(0, int(audit_limit)),
        )
        counts: OrderedDict[tuple[str, str], int] = OrderedDict()
        for event in events:
            event_namespace = event.namespace or namespace or "default"
            query = str((event.metadata or {}).get("query") or "").strip()
            if not query:
                continue
            key = (event_namespace, query)
            counts[key] = counts.get(key, 0) + 1

        ordered = sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
        candidates = [
            (key, frequency)
            for key, frequency in ordered
            if frequency >= max(1, int(min_frequency))
        ][: max(0, int(max_queries))]

        warmed = 0
        skipped = 0
        errors: dict[str, str] = {}
        for (event_namespace, query), _frequency in candidates:
            existing = self.cache.get(
                event_namespace,
                query,
                top_k=top_k,
                min_score=min_score,
            )
            if existing is not None:
                skipped += 1
                continue
            try:
                results = self.memory.query(
                    query,
                    namespace=event_namespace,
                    top_k=top_k,
                    min_score=min_score,
                )
                self.cache.put(
                    event_namespace,
                    query,
                    results,
                    top_k=top_k,
                    min_score=min_score,
                )
                warmed += 1
            except Exception as exc:  # pragma: no cover - defensive job boundary
                errors[f"{event_namespace}:{query}"] = str(exc)

        return CachePrewarmReport(
            scanned_events=len(events),
            candidates=len(candidates),
            warmed=warmed,
            skipped=skipped,
            errors=errors,
        )


class MemoryOSWorker:
    """One-shot adaptive memory worker for production schedulers.

    The worker turns query audit events into concrete maintenance actions:
    expired-memory cleanup, optional field/concept consolidation, hot-query cache
    prewarming, index repair, and operator-facing recommendations.
    """

    def __init__(
        self,
        memory: Any,
        cache: HotMemoryCache | RedisHotMemoryCache | None = None,
    ):
        self.memory = memory
        self.cache = cache

    def run_once(
        self,
        *,
        namespace: str | None = None,
        audit_limit: int = 512,
        max_hot_queries: int = 32,
        min_frequency: int = 2,
        top_k: int = 3,
        min_score: float | None = None,
        consolidate_steps: int = 10,
        consolidate_concepts: bool = True,
        concept_seed_text: str | None = None,
        min_concept_energy: float = 0.02,
        min_concept_size: int = 2,
        max_concepts: int = 3,
        concept_priority: float = 6.0,
        predict_priorities: bool = True,
        max_priority_predictions: int = 16,
        priority_boost_per_hit: float = 0.05,
        max_priority_boost: float = 0.5,
        adaptive_forgetting: bool = True,
        forgetting_min_age_seconds: float = 7 * 24 * 60 * 60,
        forgetting_max_memories: int = 32,
        forgetting_max_access_count: int = 0,
        forgetting_priority_decay: float = 0.10,
        forgetting_min_priority: float = 0.0,
        rebuild_unhealthy_index: bool = True,
        memory_pressure_threshold: int = 50_000,
    ) -> MemoryOSReport:
        stats_before = self._stats(namespace)
        events = self._query_events(namespace=namespace, limit=audit_limit)
        hot_queries = self._hot_queries(
            events,
            max_hot_queries=max_hot_queries,
            min_frequency=min_frequency,
        )
        actions: list[str] = []

        expired = 0
        if hasattr(self.memory, "purge_expired"):
            expired = int(self.memory.purge_expired())
            if expired:
                actions.append("purge_expired")

        steps = max(0, int(consolidate_steps))
        if steps and hasattr(self.memory, "consolidate"):
            self.memory.consolidate(steps=steps)
            actions.append("consolidate_field")

        concepts: list[dict[str, object]] = []
        seed_text = concept_seed_text
        if seed_text is None and hot_queries:
            seed_text = hot_queries[0].query
        if consolidate_concepts and hasattr(self.memory, "consolidate_concepts"):
            concepts = self.memory.consolidate_concepts(
                namespace=namespace,
                seed_text=seed_text,
                min_energy=min_concept_energy,
                min_size=min_concept_size,
                max_concepts=max_concepts,
                priority=concept_priority,
            )
            if concepts:
                actions.append("consolidate_concepts")
        concept_ids = tuple(
            int(concept["id"])
            for concept in concepts
            if concept.get("id") is not None
        )

        boosted_ids: tuple[int, ...] = ()
        priority_boost_total = 0.0
        if predict_priorities and hot_queries:
            boosted_ids, priority_boost_total = self._predict_priorities(
                hot_queries,
                top_k=top_k,
                min_score=min_score,
                max_predictions=max_priority_predictions,
                boost_per_hit=priority_boost_per_hit,
                max_boost=max_priority_boost,
            )
            if boosted_ids:
                actions.append("predict_priority")

        demoted_ids: tuple[int, ...] = ()
        forgetting_decay_total = 0.0
        if adaptive_forgetting:
            demoted_ids, forgetting_decay_total = self._adaptive_forgetting(
                namespace=namespace,
                protected_ids=set(boosted_ids) | set(concept_ids),
                min_age_seconds=forgetting_min_age_seconds,
                max_memories=forgetting_max_memories,
                max_access_count=forgetting_max_access_count,
                priority_decay=forgetting_priority_decay,
                min_priority=forgetting_min_priority,
            )
            if demoted_ids:
                actions.append("adaptive_forgetting")

        index_rebuilt = False
        if rebuild_unhealthy_index and hasattr(self.memory, "index_health"):
            before_health = self.memory.index_health()
            if not bool(before_health.get("healthy", True)) and hasattr(
                self.memory, "ensure_index_health"
            ):
                self.memory.ensure_index_health(rebuild=True)
                index_rebuilt = True
                actions.append("rebuild_index")

        invalidated = 0
        if self.cache is not None and (expired or concepts or boosted_ids or demoted_ids):
            if namespace is not None:
                invalidated = self.cache.invalidate_namespace(namespace)
            else:
                invalidated = self.cache.stats().size
                self.cache.clear()
            if invalidated:
                actions.append("invalidate_cache")

        if self.cache is not None:
            prewarm = CachePrewarmWorker(self.memory, self.cache).run_once(
                namespace=namespace,
                audit_limit=audit_limit,
                max_queries=max_hot_queries,
                min_frequency=min_frequency,
                top_k=top_k,
                min_score=min_score,
            )
            if prewarm.warmed:
                actions.append("prewarm_cache")
        else:
            prewarm = CachePrewarmReport(
                scanned_events=len(events),
                candidates=len(hot_queries),
                skipped=len(hot_queries),
            )

        stats_after = self._stats(namespace)
        recommendations = self._recommendations(
            namespace=namespace,
            hot_queries=hot_queries,
            prewarm=prewarm,
            stats_after=stats_after,
            memory_pressure_threshold=memory_pressure_threshold,
        )
        report = MemoryOSReport(
            namespace=namespace,
            scanned_events=len(events),
            hot_queries=tuple(hot_queries),
            expired_purged=expired,
            consolidated_steps=steps,
            concepts_created=len(concepts),
            concept_ids=concept_ids,
            priority_predictions=len(boosted_ids),
            priority_boost_total=priority_boost_total,
            priority_boosted_ids=boosted_ids,
            forgetting_demotions=len(demoted_ids),
            forgetting_decay_total=forgetting_decay_total,
            forgetting_demoted_ids=demoted_ids,
            index_rebuilt=index_rebuilt,
            cache_enabled=self.cache is not None,
            cache_invalidated=invalidated,
            prewarm=prewarm,
            stats_before=stats_before,
            stats_after=stats_after,
            actions=tuple(dict.fromkeys(actions)),
            recommendations=tuple(recommendations),
        )
        self._log_report(report)
        return report

    def _query_events(self, *, namespace: str | None, limit: int) -> list[Any]:
        if not hasattr(self.memory, "audit_events"):
            return []
        return list(
            self.memory.audit_events(
                namespace=namespace,
                action="query",
                limit=max(0, int(limit)),
            )
        )

    def _hot_queries(
        self,
        events: Iterable[Any],
        *,
        max_hot_queries: int,
        min_frequency: int,
    ) -> list[MemoryOSHotQuery]:
        counts: OrderedDict[tuple[str, str], int] = OrderedDict()
        last_seen: dict[tuple[str, str], float] = {}
        for event in events:
            query = str((getattr(event, "metadata", {}) or {}).get("query") or "").strip()
            if not query:
                continue
            event_namespace = getattr(event, "namespace", None) or "default"
            key = (str(event_namespace), query)
            counts[key] = counts.get(key, 0) + 1
            last_seen[key] = max(float(getattr(event, "created_at", 0.0)), last_seen.get(key, 0.0))
        rows = [
            MemoryOSHotQuery(
                namespace=key[0],
                query=key[1],
                frequency=frequency,
                last_seen=last_seen.get(key, 0.0),
            )
            for key, frequency in counts.items()
            if frequency >= max(1, int(min_frequency))
        ]
        rows.sort(key=lambda row: (-row.frequency, -row.last_seen, row.namespace, row.query))
        return rows[: max(0, int(max_hot_queries))]

    def _stats(self, namespace: str | None) -> dict[str, object]:
        if not hasattr(self.memory, "stats"):
            return {}
        return dict(self.memory.stats(namespace=namespace))

    def _predict_priorities(
        self,
        hot_queries: list[MemoryOSHotQuery],
        *,
        top_k: int,
        min_score: float | None,
        max_predictions: int,
        boost_per_hit: float,
        max_boost: float,
    ) -> tuple[tuple[int, ...], float]:
        if not hasattr(self.memory, "query") or not hasattr(self.memory, "feedback"):
            return (), 0.0
        boosted: OrderedDict[int, float] = OrderedDict()
        now = time.time()
        for hot_query in hot_queries[: max(0, int(max_predictions))]:
            age_seconds = max(0.0, now - float(hot_query.last_seen or now))
            recency_weight = 1.0 / (1.0 + age_seconds / 86_400.0)
            strength = min(
                max(0.0, float(max_boost)),
                max(0.0, float(boost_per_hit)) * max(1, int(hot_query.frequency)) * recency_weight,
            )
            if strength <= 0.0:
                continue
            try:
                results = self.memory.query(
                    hot_query.query,
                    namespace=hot_query.namespace,
                    top_k=max(1, int(top_k)),
                    min_score=min_score,
                )
            except Exception:
                continue
            for result in results:
                memory_id = int(getattr(result, "id"))
                try:
                    accepted = bool(
                        self.memory.feedback(
                            memory_id,
                            useful=True,
                            strength=strength,
                        )
                    )
                except Exception:
                    accepted = False
                if accepted:
                    boosted[memory_id] = boosted.get(memory_id, 0.0) + strength
        return tuple(boosted.keys()), float(sum(boosted.values()))

    def _adaptive_forgetting(
        self,
        *,
        namespace: str | None,
        protected_ids: set[int],
        min_age_seconds: float,
        max_memories: int,
        max_access_count: int,
        priority_decay: float,
        min_priority: float,
    ) -> tuple[tuple[int, ...], float]:
        store = getattr(self.memory, "store", None)
        list_records = getattr(store, "list", None)
        if not callable(list_records) or not hasattr(self.memory, "feedback"):
            return (), 0.0
        decay = max(0.0, float(priority_decay))
        if decay <= 0.0 or max_memories <= 0:
            return (), 0.0
        now = time.time()
        try:
            records = list_records(namespace=namespace, include_expired=False)
        except Exception:
            return (), 0.0
        candidates = []
        for record in records:
            if record.id is None:
                continue
            memory_id = int(record.id)
            if memory_id in protected_ids:
                continue
            if "concept" in set(record.tags):
                continue
            if int(record.access_count) > int(max_access_count):
                continue
            if float(record.priority) <= float(min_priority):
                continue
            age_seconds = now - float(record.updated_at)
            if age_seconds < max(0.0, float(min_age_seconds)):
                continue
            candidates.append(record)
        candidates.sort(
            key=lambda record: (
                int(record.access_count),
                float(record.updated_at),
                float(record.priority),
                int(record.id or 0),
            )
        )
        demoted: OrderedDict[int, float] = OrderedDict()
        for record in candidates[: max(0, int(max_memories))]:
            memory_id = int(record.id)
            strength = min(decay, max(0.0, float(record.priority) - float(min_priority)))
            if strength <= 0.0:
                continue
            try:
                accepted = bool(
                    self.memory.feedback(
                        memory_id,
                        useful=False,
                        strength=strength,
                    )
                )
            except Exception:
                accepted = False
            if accepted:
                demoted[memory_id] = strength
        return tuple(demoted.keys()), float(sum(demoted.values()))

    def _recommendations(
        self,
        *,
        namespace: str | None,
        hot_queries: list[MemoryOSHotQuery],
        prewarm: CachePrewarmReport,
        stats_after: dict[str, object],
        memory_pressure_threshold: int,
    ) -> list[str]:
        recommendations: list[str] = []
        if hot_queries and self.cache is None:
            recommendations.append(
                "Enable RedisHotMemoryCache for shared hot-query prefetch across API workers."
            )
        if not hot_queries:
            recommendations.append(
                "Collect more audited query traffic before prewarming or consolidation decisions."
            )
        if self.cache is not None and hot_queries and prewarm.warmed == 0 and prewarm.skipped == 0:
            recommendations.append(
                "Inspect cache capacity and query audit filters; hot queries were found but none were warmed."
            )
        active = int(stats_after.get("active_memories", 0) or 0)
        if active >= int(memory_pressure_threshold):
            recommendations.append(
                "Move this namespace to a persisted ANN backend and sharded deployment before further growth."
            )
        if int(stats_after.get("expired_memories", 0) or 0) > 0:
            recommendations.append(
                "Schedule MemoryOSWorker more frequently; expired memories remain after this run."
            )
        if not bool(stats_after.get("index_healthy", True)):
            recommendations.append(
                "Index health is still failing after Memory OS; rebuild or replace the vector backend."
            )
        if namespace is None and active >= int(memory_pressure_threshold):
            recommendations.append(
                "Evaluate per-namespace placement and tenant sharding before cluster-wide hot spots form."
            )
        if not recommendations:
            recommendations.append("Memory OS run is healthy; keep the worker scheduled.")
        return recommendations

    def _log_report(self, report: MemoryOSReport) -> None:
        store = getattr(self.memory, "store", None)
        log_audit_event = getattr(store, "log_audit_event", None)
        if not callable(log_audit_event):
            return
        try:
            log_audit_event(
                "memory_os",
                namespace=report.namespace,
                metadata={
                    "hot_queries": len(report.hot_queries),
                    "expired_purged": report.expired_purged,
                    "concepts_created": report.concepts_created,
                    "priority_predictions": report.priority_predictions,
                    "priority_boost_total": report.priority_boost_total,
                    "forgetting_demotions": report.forgetting_demotions,
                    "forgetting_decay_total": report.forgetting_decay_total,
                    "prewarm_warmed": report.prewarm.warmed,
                    "index_rebuilt": report.index_rebuilt,
                    "actions": list(report.actions),
                    "ok": report.ok,
                },
            )
        except Exception:
            pass


class DistributedRepairWorker:
    """Run anti-entropy namespace repair for distributed memory runtimes."""

    def __init__(self, memory: Any):
        if not hasattr(memory, "repair_namespace"):
            raise TypeError("memory object must expose repair_namespace()")
        self.memory = memory

    def run_once(
        self,
        *,
        namespaces: Iterable[str],
        limit: int = 1000,
        include_expired: bool = False,
        tags: Iterable[str] | None = None,
        fail_fast: bool = False,
    ) -> DistributedRepairJobReport:
        requested = tuple(str(namespace) for namespace in namespaces)
        reports: dict[str, dict[str, object]] = {}
        failed: dict[str, str] = {}
        repaired_total = 0
        tombstone_deleted = 0
        for namespace in requested:
            try:
                report = self.memory.repair_namespace(
                    namespace,
                    limit=max(0, int(limit)),
                    include_expired=include_expired,
                    tags=tuple(tags or ()),
                )
            except Exception as exc:  # pragma: no cover - scheduler boundary
                failed[namespace] = str(exc)
                if fail_fast:
                    break
                continue
            payload = (
                report.as_dict()
                if hasattr(report, "as_dict")
                else dict(report)
            )
            reports[namespace] = payload
            repaired_total += int(
                payload.get("repaired_total", payload.get("copied_records", 0)) or 0
            )
            tombstone_deleted += int(
                payload.get("tombstone_deleted", payload.get("deleted_records", 0)) or 0
            )
        return DistributedRepairJobReport(
            namespaces=requested,
            repaired_total=repaired_total,
            tombstone_deleted=tombstone_deleted,
            reports=reports,
            failed_namespaces=failed,
        )


def _looks_like_archive(value: str) -> bool:
    return value.endswith(".tar.gz") or value.endswith(".tgz")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
