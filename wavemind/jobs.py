from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .core import QueryResult


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


def query_with_cache(
    memory: Any,
    cache: HotMemoryCache,
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
