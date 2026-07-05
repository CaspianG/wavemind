from __future__ import annotations

import time
import json
import hashlib
import shutil
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .core import QueryResult
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
class ReplicatedSnapshotJobReport:
    snapshot_path: Path
    verified: bool
    total_bytes: int
    nodes: tuple[str, ...]
    offsite_path: Path | None = None
    offsite_verified: bool = False
    archive_path: Path | None = None
    archive_verified: bool = False
    pruned_local: tuple[Path, ...] = ()
    pruned_offsite: tuple[Path, ...] = ()
    pruned_archives: tuple[Path, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.verified
            and (self.offsite_path is None or self.offsite_verified)
            and (self.archive_path is None or self.archive_verified)
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
            "pruned_local": [str(path) for path in self.pruned_local],
            "pruned_offsite": [str(path) for path in self.pruned_offsite],
            "pruned_archives": [str(path) for path in self.pruned_archives],
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
        if archive_destination is not None:
            archive = ReplicatedWaveMind.archive_snapshot(
                snapshot.snapshot_path,
                archive_destination,
            )
            archive_path = archive.archive_path
            archive_verified = archive.verified

        pruned_local: tuple[Path, ...] = ()
        pruned_offsite: tuple[Path, ...] = ()
        pruned_archives: tuple[Path, ...] = ()
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

        return ReplicatedSnapshotJobReport(
            snapshot_path=snapshot.snapshot_path,
            verified=verified,
            total_bytes=snapshot.total_bytes,
            nodes=snapshot.nodes,
            offsite_path=offsite_path,
            offsite_verified=offsite_verified,
            archive_path=archive_path,
            archive_verified=archive_verified,
            pruned_local=pruned_local,
            pruned_offsite=pruned_offsite,
            pruned_archives=pruned_archives,
        )


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
