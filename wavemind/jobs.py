from __future__ import annotations

import time
import json
import hashlib
import math
import shutil
import uuid
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np

from .advisor import MemoryArchitectureAdvice, advise_memory_architecture
from .core import QueryResult
from .encoders import is_stopword_token, normalize_token
from .object_store import ObjectStoreArchive, ObjectStoreUploadReport, S3SnapshotStore
from .replication import NamespaceDeltaSyncReport, ReplicatedWaveMind, sync_namespace_delta
from .sharding import HTTPNamespaceShardClient


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


@dataclass
class _VectorCacheEntry:
    vector: np.ndarray
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


def query_vector_cache_key(encoder: Any) -> str:
    """Stable cache namespace for a query encoder.

    Query vectors are only reusable when the encoder implementation and vector
    dimensionality match. Model-backed encoders also include their model name.
    """

    cls = encoder.__class__
    parts = [
        f"{cls.__module__}.{cls.__qualname__}",
        f"dim={int(getattr(encoder, 'vector_dim', 0) or 0)}",
    ]
    model_name = getattr(encoder, "model_name", None)
    if model_name:
        parts.append(f"model={model_name}")
    return "|".join(parts)


class QueryVectorCache:
    """Small in-process LRU cache for encoded query vectors."""

    def __init__(self, capacity: int = 1024, ttl_seconds: float = 300.0):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.capacity = int(capacity)
        self.ttl_seconds = float(ttl_seconds)
        self._items: OrderedDict[tuple[str, str], _VectorCacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, encoder_key: str, text: str) -> np.ndarray | None:
        key = self._key(encoder_key, text)
        entry = self._items.get(key)
        now = time.time()
        if entry is None or entry.expires_at <= now:
            self._misses += 1
            if entry is not None:
                self._items.pop(key, None)
            return None
        self._hits += 1
        self._items.move_to_end(key)
        return np.asarray(entry.vector, dtype=np.float32).copy()

    def put(self, encoder_key: str, text: str, vector: np.ndarray) -> None:
        key = self._key(encoder_key, text)
        self._items[key] = _VectorCacheEntry(
            vector=np.asarray(vector, dtype=np.float32).copy(),
            expires_at=time.time() + self.ttl_seconds,
        )
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
            self._evictions += 1

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
    def _key(encoder_key: str, text: str) -> tuple[str, str]:
        return (str(encoder_key), str(text))


class RedisQueryVectorCache:
    """Redis-backed cache for encoded query vectors across API workers."""

    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "wavemind:qvec",
        ttl_seconds: float = 300.0,
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
        prefix: str = "wavemind:qvec",
        ttl_seconds: float = 300.0,
    ) -> "RedisQueryVectorCache":
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

    def get(self, encoder_key: str, text: str) -> np.ndarray | None:
        key = self._key(encoder_key, text)
        raw = self.client.get(key)
        if raw is None:
            self._misses += 1
            return None
        self._hits += 1
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(str(raw))
        return np.asarray(payload["vector"], dtype=np.float32)

    def put(self, encoder_key: str, text: str, vector: np.ndarray) -> None:
        key = self._key(encoder_key, text)
        payload = {
            "encoder": str(encoder_key),
            "vector": np.asarray(vector, dtype=np.float32).tolist(),
        }
        self.client.set(
            key,
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=max(1, int(round(self.ttl_seconds))),
        )

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

    def _key(self, encoder_key: str, text: str) -> str:
        tail = (str(encoder_key), str(text))
        digest = hashlib.sha256(
            json.dumps(tail, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"{self.prefix}:{digest}"


def _cached_query_vector(
    memory: Any,
    vector_cache: QueryVectorCache | RedisQueryVectorCache,
    text: str,
) -> np.ndarray:
    encoder_key = query_vector_cache_key(memory.encoder)
    query_vector = vector_cache.get(encoder_key, text)
    if query_vector is not None:
        return query_vector
    query_vector = memory.encoder.encode_vector(text)
    vector_cache.put(encoder_key, text, query_vector)
    return np.asarray(query_vector, dtype=np.float32)


def query_with_vector_cache(
    memory: Any,
    vector_cache: QueryVectorCache | RedisQueryVectorCache,
    text: str,
    *,
    namespace: str = "default",
    top_k: int = 3,
    tags: Iterable[str] | None = None,
    min_score: float | None = None,
) -> list[QueryResult]:
    query_vector = _cached_query_vector(memory, vector_cache, text)
    return memory.query(
        text,
        namespace=namespace,
        top_k=top_k,
        tags=tags,
        min_score=min_score,
        query_vector=query_vector,
    )


def query_with_cache(
    memory: Any,
    cache: HotMemoryCache | RedisHotMemoryCache,
    text: str,
    *,
    namespace: str = "default",
    top_k: int = 3,
    tags: Iterable[str] | None = None,
    min_score: float | None = None,
    vector_cache: QueryVectorCache | RedisQueryVectorCache | None = None,
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
    if vector_cache is None:
        results = memory.query(
            text,
            namespace=namespace,
            top_k=top_k,
            tags=tags,
            min_score=min_score,
        )
    else:
        results = query_with_vector_cache(
            memory,
            vector_cache,
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
class TransitionPrefetchEdge:
    namespace: str
    from_query: str
    to_query: str
    count: int
    probability: float
    last_seen: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PredictivePrefetchReport:
    scanned_hot_queries: int = 0
    generated_queries: int = 0
    warmed: int = 0
    skipped: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    queries: tuple[str, ...] = ()
    transition_queries: tuple[str, ...] = ()
    transition_edges: tuple[TransitionPrefetchEdge, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned_hot_queries": self.scanned_hot_queries,
            "generated_queries": self.generated_queries,
            "warmed": self.warmed,
            "skipped": self.skipped,
            "errors": dict(self.errors),
            "queries": list(self.queries),
            "transition_queries": list(self.transition_queries),
            "transition_edges": [edge.as_dict() for edge in self.transition_edges],
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
class MemoryOSLockReport:
    required: bool = False
    acquired: bool = False
    key: str | None = None
    owner: str | None = None
    ttl_seconds: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.required or self.acquired

    def as_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "acquired": self.acquired,
            "key": self.key,
            "owner": self.owner,
            "ttl_seconds": self.ttl_seconds,
            "reason": self.reason,
            "ok": self.ok,
        }


class RedisMemoryOSLock:
    """Small Redis-compatible single-flight lock for Memory OS workers."""

    def __init__(
        self,
        client: Any,
        *,
        key: str,
        ttl_seconds: int = 300,
        owner: str | None = None,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not key:
            raise ValueError("key must not be empty")
        self.client = client
        self.key = key
        self.ttl_seconds = int(ttl_seconds)
        self.owner = owner or str(uuid.uuid4())
        self.acquired = False

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        key: str,
        ttl_seconds: int = 300,
        owner: str | None = None,
    ) -> "RedisMemoryOSLock":
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                'Install Redis support with: pip install "wavemind[redis]"'
            ) from exc
        return cls(
            redis.Redis.from_url(url, decode_responses=True),
            key=key,
            ttl_seconds=ttl_seconds,
            owner=owner,
        )

    def acquire(self) -> bool:
        try:
            acquired = self.client.set(
                self.key,
                self.owner,
                ex=self.ttl_seconds,
                nx=True,
            )
        except TypeError:
            if self.client.get(self.key) is not None:
                acquired = False
            else:
                self.client.set(self.key, self.owner, ex=self.ttl_seconds)
                acquired = True
        self.acquired = bool(acquired)
        return self.acquired

    def release(self) -> bool:
        if not self.acquired:
            return False
        current = self.client.get(self.key)
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current != self.owner:
            self.acquired = False
            return False
        self.client.delete(self.key)
        self.acquired = False
        return True

    def report(self, *, required: bool, reason: str | None = None) -> MemoryOSLockReport:
        return MemoryOSLockReport(
            required=required,
            acquired=self.acquired,
            key=self.key,
            owner=self.owner,
            ttl_seconds=self.ttl_seconds,
            reason=reason,
        )

    @contextmanager
    def hold(self, *, required: bool = False) -> Iterator[MemoryOSLockReport]:
        acquired = self.acquire()
        if required and not acquired:
            yield self.report(required=True, reason="lock_already_held")
            return
        try:
            yield self.report(required=required)
        finally:
            if acquired:
                self.release()


@dataclass(frozen=True)
class MemoryOSImprovementSuggestion:
    id: str
    severity: str
    title: str
    rationale: str
    action: str
    evidence: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "rationale": self.rationale,
            "action": self.action,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class MemoryOSPolicyDecision:
    id: str
    status: str
    strategy: str
    rationale: str
    action: str
    evidence: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "strategy": self.strategy,
            "rationale": self.rationale,
            "action": self.action,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class MemoryOSPolicyManifest:
    status: str = "watch"
    namespace: str | None = None
    decisions: tuple[MemoryOSPolicyDecision, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "watch"}

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "namespace": self.namespace,
            "decision_count": len(self.decisions),
            "decision_ids": [decision.id for decision in self.decisions],
            "decisions": [decision.as_dict() for decision in self.decisions],
            "ok": self.ok,
        }


@dataclass(frozen=True)
class MemoryOSPolicyHistory:
    previous_runs: int = 0
    window: int = 5
    trend: str = "first_run"
    repeated_action_required_ids: tuple[str, ...] = ()
    repeated_architecture_required_ids: tuple[str, ...] = ()
    stable_ok_ids: tuple[str, ...] = ()
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def repeated_required_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.repeated_action_required_ids,
                    *self.repeated_architecture_required_ids,
                ]
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "previous_runs": self.previous_runs,
            "window": self.window,
            "trend": self.trend,
            "repeated_action_required_ids": list(self.repeated_action_required_ids),
            "repeated_architecture_required_ids": list(
                self.repeated_architecture_required_ids
            ),
            "repeated_required_ids": list(self.repeated_required_ids),
            "stable_ok_ids": list(self.stable_ok_ids),
            "status_counts": dict(self.status_counts),
        }


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
    predictive_prefetch: PredictivePrefetchReport = field(
        default_factory=PredictivePrefetchReport
    )
    stats_before: dict[str, object] = field(default_factory=dict)
    stats_after: dict[str, object] = field(default_factory=dict)
    architecture_advice: dict[str, object] = field(default_factory=dict)
    lock: MemoryOSLockReport = field(default_factory=MemoryOSLockReport)
    actions: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    suggestions: tuple[MemoryOSImprovementSuggestion, ...] = ()
    policy_manifest: MemoryOSPolicyManifest = field(
        default_factory=MemoryOSPolicyManifest
    )
    policy_history: MemoryOSPolicyHistory = field(
        default_factory=MemoryOSPolicyHistory
    )

    @property
    def ok(self) -> bool:
        index_healthy = bool(self.stats_after.get("index_healthy", True))
        return index_healthy and self.prewarm.ok and self.predictive_prefetch.ok and self.lock.ok

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
            "predictive_prefetch": self.predictive_prefetch.as_dict(),
            "stats_before": dict(self.stats_before),
            "stats_after": dict(self.stats_after),
            "architecture_advice": dict(self.architecture_advice),
            "lock": self.lock.as_dict(),
            "actions": list(self.actions),
            "recommendations": list(self.recommendations),
            "suggestions": [suggestion.as_dict() for suggestion in self.suggestions],
            "policy_manifest": self.policy_manifest.as_dict(),
            "policy_history": self.policy_history.as_dict(),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class MemoryOSScheduleTask:
    id: str
    title: str
    enabled: bool
    cadence_seconds: int
    worker_count: int
    timeout_seconds: int
    command: str
    reason: str
    priority: str = "normal"
    requires_shared_cache: bool = False
    requires_distributed_lock: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryOSSchedulePlan:
    status: str
    namespace: str | None
    deployment: str
    cache_mode: str
    effective_cache_mode: str
    target_memories: int
    namespace_count: int
    active_memories: int
    hot_query_count: int
    observed_p99_ms: float | None
    target_p99_ms: float
    target_qps: float
    worker_count: int
    tasks: tuple[MemoryOSScheduleTask, ...]
    required_infrastructure: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    architecture_advice: dict[str, object] = field(default_factory=dict)
    policy_manifest: MemoryOSPolicyManifest = field(
        default_factory=MemoryOSPolicyManifest
    )
    policy_history: MemoryOSPolicyHistory = field(
        default_factory=MemoryOSPolicyHistory
    )
    policy_escalation_ids: tuple[str, ...] = ()
    policy_auto_adjustments: tuple[str, ...] = ()

    @property
    def enabled_tasks(self) -> tuple[MemoryOSScheduleTask, ...]:
        return tuple(task for task in self.tasks if task.enabled)

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "watch", "architecture_required"}

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "namespace": self.namespace,
            "deployment": self.deployment,
            "cache_mode": self.cache_mode,
            "effective_cache_mode": self.effective_cache_mode,
            "target_memories": self.target_memories,
            "namespace_count": self.namespace_count,
            "active_memories": self.active_memories,
            "hot_query_count": self.hot_query_count,
            "observed_p99_ms": self.observed_p99_ms,
            "target_p99_ms": self.target_p99_ms,
            "target_qps": self.target_qps,
            "worker_count": self.worker_count,
            "required_infrastructure": list(self.required_infrastructure),
            "recommendations": list(self.recommendations),
            "architecture_advice": dict(self.architecture_advice),
            "policy_manifest": self.policy_manifest.as_dict(),
            "policy_history": self.policy_history.as_dict(),
            "policy_escalation_ids": list(self.policy_escalation_ids),
            "policy_auto_adjustments": list(self.policy_auto_adjustments),
            "tasks": [task.as_dict() for task in self.tasks],
            "enabled_task_ids": [task.id for task in self.enabled_tasks],
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


@dataclass(frozen=True)
class ActiveActivePairSyncReport:
    source_region: str
    target_region: str
    namespace: str
    from_cursor: float | None
    to_cursor: float | None
    exported_records: int = 0
    exported_tombstones: int = 0
    exported_field_keys: int = 0
    imported_records: int = 0
    skipped_records: int = 0
    deleted_records: int = 0
    imported_tombstones: int = 0
    has_more: bool = False
    failed_nodes: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and not self.failed_nodes

    def as_dict(self) -> dict[str, object]:
        return {
            "source_region": self.source_region,
            "target_region": self.target_region,
            "namespace": self.namespace,
            "from_cursor": self.from_cursor,
            "to_cursor": self.to_cursor,
            "exported_records": self.exported_records,
            "exported_tombstones": self.exported_tombstones,
            "exported_field_keys": self.exported_field_keys,
            "imported_records": self.imported_records,
            "skipped_records": self.skipped_records,
            "deleted_records": self.deleted_records,
            "imported_tombstones": self.imported_tombstones,
            "has_more": self.has_more,
            "failed_nodes": dict(self.failed_nodes),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ActiveActiveSyncJobReport:
    regions: tuple[str, ...]
    namespaces: tuple[str, ...]
    pair_reports: tuple[ActiveActivePairSyncReport, ...]
    duration_ms: float

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.pair_reports)

    @property
    def records_imported(self) -> int:
        return sum(report.imported_records for report in self.pair_reports)

    @property
    def tombstones_imported(self) -> int:
        return sum(report.imported_tombstones for report in self.pair_reports)

    @property
    def deleted_records(self) -> int:
        return sum(report.deleted_records for report in self.pair_reports)

    @property
    def exported_field_keys(self) -> int:
        return sum(report.exported_field_keys for report in self.pair_reports)

    @property
    def failed_pairs(self) -> int:
        return sum(1 for report in self.pair_reports if not report.ok)

    @property
    def has_more_pairs(self) -> int:
        return sum(1 for report in self.pair_reports if report.has_more)

    def as_dict(self) -> dict[str, object]:
        return {
            "regions": list(self.regions),
            "namespaces": list(self.namespaces),
            "pair_reports": [report.as_dict() for report in self.pair_reports],
            "records_imported": self.records_imported,
            "tombstones_imported": self.tombstones_imported,
            "deleted_records": self.deleted_records,
            "exported_field_keys": self.exported_field_keys,
            "failed_pairs": self.failed_pairs,
            "has_more_pairs": self.has_more_pairs,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
        }


class ActiveActiveSyncWorker:
    """Cursor-based mesh sync for independent active-active regions."""

    def __init__(
        self,
        regions: dict[str, ReplicatedWaveMind],
        *,
        cursors: dict[tuple[str, str, str], float] | None = None,
    ) -> None:
        if len(regions) < 2:
            raise ValueError("active-active sync requires at least two regions")
        names = tuple(str(name) for name in regions)
        if len(set(names)) != len(names):
            raise ValueError("region names must be unique")
        self.regions = {str(name): region for name, region in regions.items()}
        self.cursors: dict[tuple[str, str, str], float] = dict(cursors or {})

    def run_once(
        self,
        namespaces: Iterable[str],
        *,
        limit: int | None = None,
        bidirectional: bool = True,
        fail_fast: bool = False,
    ) -> ActiveActiveSyncJobReport:
        requested = tuple(dict.fromkeys(str(namespace) for namespace in namespaces))
        if not requested:
            raise ValueError("active-active sync requires at least one namespace")
        region_names = tuple(self.regions)
        pairs = self._pairs(region_names, bidirectional=bidirectional)
        started = time.perf_counter()
        reports: list[ActiveActivePairSyncReport] = []
        for namespace in requested:
            for source_name, target_name in pairs:
                report = self._sync_pair(
                    source_name,
                    target_name,
                    namespace,
                    limit=limit,
                )
                reports.append(report)
                if fail_fast and not report.ok:
                    return ActiveActiveSyncJobReport(
                        regions=region_names,
                        namespaces=requested,
                        pair_reports=tuple(reports),
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
        return ActiveActiveSyncJobReport(
            regions=region_names,
            namespaces=requested,
            pair_reports=tuple(reports),
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _sync_pair(
        self,
        source_name: str,
        target_name: str,
        namespace: str,
        *,
        limit: int | None,
    ) -> ActiveActivePairSyncReport:
        cursor_key = (source_name, target_name, namespace)
        since = self.cursors.get(cursor_key)
        started = time.perf_counter()
        try:
            report = sync_namespace_delta(
                self.regions[source_name],
                self.regions[target_name],
                namespace,
                since=since,
                limit=limit,
            )
        except Exception as exc:  # pragma: no cover - scheduler boundary
            return ActiveActivePairSyncReport(
                source_region=source_name,
                target_region=target_name,
                namespace=namespace,
                from_cursor=since,
                to_cursor=None,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        self.cursors[cursor_key] = report.to_cursor
        return _active_active_pair_report(
            source_name,
            target_name,
            report,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    @staticmethod
    def _pairs(region_names: tuple[str, ...], *, bidirectional: bool) -> tuple[tuple[str, str], ...]:
        if bidirectional:
            return tuple(
                (source, target)
                for source in region_names
                for target in region_names
                if source != target
            )
        first, *rest = region_names
        return tuple((first, target) for target in rest)


class HTTPActiveActiveSyncWorker:
    """Cursor-based active-active sync across WaveMind API service regions."""

    def __init__(
        self,
        regions: dict[str, str],
        *,
        client: HTTPNamespaceShardClient | Any | None = None,
        cursors: dict[tuple[str, str, str], float] | None = None,
    ) -> None:
        if len(regions) < 2:
            raise ValueError("HTTP active-active sync requires at least two regions")
        names = tuple(str(name) for name in regions)
        if len(set(names)) != len(names):
            raise ValueError("region names must be unique")
        self.regions = {str(name): str(address).rstrip("/") for name, address in regions.items()}
        self.client = client or HTTPNamespaceShardClient()
        self.cursors: dict[tuple[str, str, str], float] = dict(cursors or {})

    def run_once(
        self,
        namespaces: Iterable[str],
        *,
        limit: int | None = None,
        bidirectional: bool = True,
        fail_fast: bool = False,
    ) -> ActiveActiveSyncJobReport:
        requested = tuple(dict.fromkeys(str(namespace) for namespace in namespaces))
        if not requested:
            raise ValueError("HTTP active-active sync requires at least one namespace")
        region_names = tuple(self.regions)
        pairs = ActiveActiveSyncWorker._pairs(region_names, bidirectional=bidirectional)
        started = time.perf_counter()
        reports: list[ActiveActivePairSyncReport] = []
        for namespace in requested:
            for source_name, target_name in pairs:
                report = self._sync_pair(
                    source_name,
                    target_name,
                    namespace,
                    limit=limit,
                )
                reports.append(report)
                if fail_fast and not report.ok:
                    return ActiveActiveSyncJobReport(
                        regions=region_names,
                        namespaces=requested,
                        pair_reports=tuple(reports),
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
        return ActiveActiveSyncJobReport(
            regions=region_names,
            namespaces=requested,
            pair_reports=tuple(reports),
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _sync_pair(
        self,
        source_name: str,
        target_name: str,
        namespace: str,
        *,
        limit: int | None,
    ) -> ActiveActivePairSyncReport:
        cursor_key = (source_name, target_name, namespace)
        since = self.cursors.get(cursor_key)
        started = time.perf_counter()
        try:
            delta = self.client.export_namespace_delta(
                self.regions[source_name],
                namespace=namespace,
                since=since,
                limit=limit,
            )
            import_report = self.client.import_namespace_delta(
                self.regions[target_name],
                delta=delta,
                namespace=namespace,
            )
        except Exception as exc:  # pragma: no cover - service boundary
            return ActiveActivePairSyncReport(
                source_region=source_name,
                target_region=target_name,
                namespace=namespace,
                from_cursor=since,
                to_cursor=None,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        to_cursor = float(delta.get("cursor", since or time.time()))
        self.cursors[cursor_key] = to_cursor
        return _http_active_active_pair_report(
            source_name,
            target_name,
            namespace,
            delta,
            import_report,
            from_cursor=since,
            to_cursor=to_cursor,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )


def _active_active_pair_report(
    source_region: str,
    target_region: str,
    report: NamespaceDeltaSyncReport,
    *,
    duration_ms: float,
) -> ActiveActivePairSyncReport:
    return ActiveActivePairSyncReport(
        source_region=source_region,
        target_region=target_region,
        namespace=report.namespace,
        from_cursor=report.from_cursor,
        to_cursor=report.to_cursor,
        exported_records=report.exported_records,
        exported_tombstones=report.exported_tombstones,
        exported_field_keys=report.exported_field_keys,
        imported_records=report.imported_records,
        skipped_records=report.skipped_records,
        deleted_records=report.deleted_records,
        imported_tombstones=report.imported_tombstones,
        has_more=report.has_more,
        failed_nodes=dict(report.failed_nodes),
        duration_ms=duration_ms,
    )


def _http_active_active_pair_report(
    source_region: str,
    target_region: str,
    namespace: str,
    delta: dict[str, Any],
    import_report: dict[str, Any],
    *,
    from_cursor: float | None,
    to_cursor: float,
    duration_ms: float,
) -> ActiveActivePairSyncReport:
    field_state = delta.get("field_state") if isinstance(delta, dict) else {}
    exported_field_keys = 0
    if isinstance(field_state, dict):
        for bucket_name in ("positive", "negative", "tombstones"):
            bucket = field_state.get(bucket_name)
            if isinstance(bucket, dict):
                exported_field_keys += len(bucket)
    failed_nodes = dict(import_report.get("failed_nodes") or {})
    return ActiveActivePairSyncReport(
        source_region=source_region,
        target_region=target_region,
        namespace=namespace,
        from_cursor=from_cursor,
        to_cursor=to_cursor,
        exported_records=len(delta.get("records", []) or []),
        exported_tombstones=len(delta.get("tombstones", []) or []),
        exported_field_keys=exported_field_keys,
        imported_records=int(import_report.get("imported_records", 0)),
        skipped_records=int(import_report.get("skipped_records", 0)),
        deleted_records=int(import_report.get("deleted_records", 0)),
        imported_tombstones=int(import_report.get("imported_tombstones", 0)),
        has_more=bool(delta.get("has_more", False)),
        failed_nodes=failed_nodes,
        error=None if not failed_nodes else json.dumps(failed_nodes, sort_keys=True),
        duration_ms=duration_ms,
    )


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
        predictive_prefetch: bool = True,
        max_predictive_queries: int = 16,
        predictive_terms_per_hot_query: int = 3,
        transition_prefetch_window_seconds: float = 15 * 60,
        rebuild_unhealthy_index: bool = True,
        memory_pressure_threshold: int = 50_000,
        architecture_advice: bool = True,
        target_memories: int | None = None,
        target_p99_ms: float = 100.0,
        observed_p99_ms: float | None = None,
        namespace_count: int | None = None,
        node_count: int | None = None,
        replication_factor: int = 3,
        read_quorum: int = 1,
        read_fanout: int | None = None,
        target_qps: float = 100.0,
        deployment: str = "local",
        multimodal: bool = False,
        lock: RedisMemoryOSLock | None = None,
        lock_required: bool = False,
    ) -> MemoryOSReport:
        stats_before = self._stats(namespace)
        if lock is None and lock_required:
            report = MemoryOSReport(
                namespace=namespace,
                scanned_events=0,
                stats_before=stats_before,
                stats_after=stats_before,
                lock=MemoryOSLockReport(
                    required=True,
                    acquired=False,
                    reason="lock_required_without_lock",
                ),
                actions=("lock_skipped",),
                recommendations=(
                    "Configure --redis-url or pass a RedisMemoryOSLock before running Memory OS in production.",
                ),
            )
            self._log_report(report)
            return report

        lock_report = MemoryOSLockReport(required=False, acquired=False)
        if lock is not None:
            if not lock.acquire():
                report = MemoryOSReport(
                    namespace=namespace,
                    scanned_events=0,
                    stats_before=stats_before,
                    stats_after=stats_before,
                    lock=lock.report(required=lock_required, reason="lock_already_held"),
                    actions=("lock_skipped",),
                    recommendations=(
                        "Another Memory OS worker holds the namespace lock; retry after the lock TTL or the active run finishes.",
                    ),
                )
                self._log_report(report)
                return report
            lock_report = lock.report(required=lock_required)

        try:
            return self._run_once_locked(
                namespace=namespace,
                audit_limit=audit_limit,
                max_hot_queries=max_hot_queries,
                min_frequency=min_frequency,
                top_k=top_k,
                min_score=min_score,
                consolidate_steps=consolidate_steps,
                consolidate_concepts=consolidate_concepts,
                concept_seed_text=concept_seed_text,
                min_concept_energy=min_concept_energy,
                min_concept_size=min_concept_size,
                max_concepts=max_concepts,
                concept_priority=concept_priority,
                predict_priorities=predict_priorities,
                max_priority_predictions=max_priority_predictions,
                priority_boost_per_hit=priority_boost_per_hit,
                max_priority_boost=max_priority_boost,
                adaptive_forgetting=adaptive_forgetting,
                forgetting_min_age_seconds=forgetting_min_age_seconds,
                forgetting_max_memories=forgetting_max_memories,
                forgetting_max_access_count=forgetting_max_access_count,
                forgetting_priority_decay=forgetting_priority_decay,
                forgetting_min_priority=forgetting_min_priority,
                predictive_prefetch=predictive_prefetch,
                max_predictive_queries=max_predictive_queries,
                predictive_terms_per_hot_query=predictive_terms_per_hot_query,
                transition_prefetch_window_seconds=transition_prefetch_window_seconds,
                rebuild_unhealthy_index=rebuild_unhealthy_index,
                memory_pressure_threshold=memory_pressure_threshold,
                architecture_advice=architecture_advice,
                target_memories=target_memories,
                target_p99_ms=target_p99_ms,
                observed_p99_ms=observed_p99_ms,
                namespace_count=namespace_count,
                node_count=node_count,
                replication_factor=replication_factor,
                read_quorum=read_quorum,
                read_fanout=read_fanout,
                target_qps=target_qps,
                deployment=deployment,
                multimodal=multimodal,
                stats_before=stats_before,
                lock_report=lock_report,
            )
        finally:
            if lock is not None:
                lock.release()

    def _run_once_locked(
        self,
        *,
        namespace: str | None,
        audit_limit: int,
        max_hot_queries: int,
        min_frequency: int,
        top_k: int,
        min_score: float | None,
        consolidate_steps: int,
        consolidate_concepts: bool,
        concept_seed_text: str | None,
        min_concept_energy: float,
        min_concept_size: int,
        max_concepts: int,
        concept_priority: float,
        predict_priorities: bool,
        max_priority_predictions: int,
        priority_boost_per_hit: float,
        max_priority_boost: float,
        adaptive_forgetting: bool,
        forgetting_min_age_seconds: float,
        forgetting_max_memories: int,
        forgetting_max_access_count: int,
        forgetting_priority_decay: float,
        forgetting_min_priority: float,
        predictive_prefetch: bool,
        max_predictive_queries: int,
        predictive_terms_per_hot_query: int,
        transition_prefetch_window_seconds: float,
        rebuild_unhealthy_index: bool,
        memory_pressure_threshold: int,
        architecture_advice: bool,
        target_memories: int | None,
        target_p99_ms: float,
        observed_p99_ms: float | None,
        namespace_count: int | None,
        node_count: int | None,
        replication_factor: int,
        read_quorum: int,
        read_fanout: int | None,
        target_qps: float,
        deployment: str,
        multimodal: bool,
        stats_before: dict[str, object],
        lock_report: MemoryOSLockReport,
    ) -> MemoryOSReport:
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

        predictive = PredictivePrefetchReport(scanned_hot_queries=len(hot_queries))
        if predictive_prefetch and self.cache is not None and hot_queries:
            predictive = self._predictive_prefetch(
                hot_queries,
                events=events,
                top_k=top_k,
                min_score=min_score,
                max_queries=max_predictive_queries,
                terms_per_hot_query=predictive_terms_per_hot_query,
                transition_window_seconds=transition_prefetch_window_seconds,
            )
            if predictive.warmed:
                actions.append("predictive_prefetch")

        stats_after = self._stats(namespace)
        recommendations = self._recommendations(
            namespace=namespace,
            hot_queries=hot_queries,
            prewarm=prewarm,
            stats_after=stats_after,
            memory_pressure_threshold=memory_pressure_threshold,
        )
        architecture_payload: dict[str, object] = {}
        if architecture_advice:
            architecture = self._architecture_advice(
                stats_after=stats_after,
                namespace=namespace,
                target_memories=target_memories,
                target_p99_ms=target_p99_ms,
                observed_p99_ms=observed_p99_ms,
                namespace_count=namespace_count,
                node_count=node_count,
                replication_factor=replication_factor,
                read_quorum=read_quorum,
                read_fanout=read_fanout,
                target_qps=target_qps,
                deployment=deployment,
                multimodal=multimodal,
            )
            architecture_payload = architecture.as_dict()
            architecture_recommendations = self._architecture_recommendations(architecture)
            if architecture_recommendations:
                actions.append("advise_architecture")
                recommendations.extend(architecture_recommendations)
        suggestions = self._improvement_suggestions(
            namespace=namespace,
            hot_queries=hot_queries,
            prewarm=prewarm,
            predictive=predictive,
            stats_after=stats_after,
            memory_pressure_threshold=memory_pressure_threshold,
            cache_enabled=self.cache is not None,
            concepts_created=len(concepts),
            priority_predictions=len(boosted_ids),
            forgetting_demotions=len(demoted_ids),
            architecture_payload=architecture_payload,
        )
        policy_manifest = self._policy_manifest(
            namespace=namespace,
            hot_queries=hot_queries,
            prewarm=prewarm,
            predictive=predictive,
            stats_after=stats_after,
            memory_pressure_threshold=memory_pressure_threshold,
            cache_enabled=self.cache is not None,
            concepts_created=len(concepts),
            priority_predictions=len(boosted_ids),
            forgetting_demotions=len(demoted_ids),
            architecture_payload=architecture_payload,
            lock_report=lock_report,
            deployment=deployment,
        )
        policy_history = self._policy_history(
            namespace=namespace,
            current=policy_manifest,
            window=5,
        )
        history_suggestions = self._policy_history_suggestions(
            namespace=namespace,
            current=policy_manifest,
            history=policy_history,
        )
        if history_suggestions:
            actions.append("escalate_policy_history")
            recommendations.extend(
                self._policy_history_recommendations(
                    current=policy_manifest,
                    history=policy_history,
                )
            )
            suggestions = tuple([*suggestions, *history_suggestions])
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
            predictive_prefetch=predictive,
            stats_before=stats_before,
            stats_after=stats_after,
            architecture_advice=architecture_payload,
            lock=lock_report,
            actions=tuple(dict.fromkeys(actions)),
            recommendations=tuple(recommendations),
            suggestions=suggestions,
            policy_manifest=policy_manifest,
            policy_history=policy_history,
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

    def _predictive_prefetch(
        self,
        hot_queries: list[MemoryOSHotQuery],
        *,
        events: Iterable[Any],
        top_k: int,
        min_score: float | None,
        max_queries: int,
        terms_per_hot_query: int,
        transition_window_seconds: float,
    ) -> PredictivePrefetchReport:
        if self.cache is None or not hasattr(self.memory, "query"):
            return PredictivePrefetchReport(scanned_hot_queries=len(hot_queries))

        max_queries = max(0, int(max_queries))
        terms_per_hot_query = max(0, int(terms_per_hot_query))
        if max_queries <= 0:
            return PredictivePrefetchReport(scanned_hot_queries=len(hot_queries))

        planned: OrderedDict[tuple[str, str], None] = OrderedDict()
        errors: dict[str, str] = {}
        transition_edges = self._transition_edges(
            events,
            hot_queries,
            max_queries=max_queries,
            window_seconds=transition_window_seconds,
        )
        for edge in transition_edges:
            if len(planned) >= max_queries:
                break
            planned[(edge.namespace, edge.to_query)] = None
        for hot_query in hot_queries:
            if len(planned) >= max_queries:
                break
            try:
                results = self.memory.query(
                    hot_query.query,
                    namespace=hot_query.namespace,
                    top_k=max(1, int(top_k)),
                    min_score=min_score,
                )
            except Exception as exc:  # pragma: no cover - defensive job boundary
                errors[f"{hot_query.namespace}:{hot_query.query}"] = str(exc)
                continue
            for query in self._neighbor_queries(
                hot_query,
                results,
                terms_per_hot_query=terms_per_hot_query,
            ):
                if len(planned) >= max_queries:
                    break
                planned[(hot_query.namespace, query)] = None

        warmed = 0
        skipped = 0
        warmed_queries: list[str] = []
        for namespace, query in planned:
            existing = self.cache.get(
                namespace,
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
                    namespace=namespace,
                    top_k=max(1, int(top_k)),
                    min_score=min_score,
                )
                self.cache.put(
                    namespace,
                    query,
                    results,
                    top_k=top_k,
                    min_score=min_score,
                )
                warmed += 1
                warmed_queries.append(query)
            except Exception as exc:  # pragma: no cover - defensive job boundary
                errors[f"{namespace}:{query}"] = str(exc)

        return PredictivePrefetchReport(
            scanned_hot_queries=len(hot_queries),
            generated_queries=len(planned),
            warmed=warmed,
            skipped=skipped,
            errors=errors,
            queries=tuple(warmed_queries),
            transition_queries=tuple(edge.to_query for edge in transition_edges),
            transition_edges=transition_edges,
        )

    def _transition_edges(
        self,
        events: Iterable[Any],
        hot_queries: list[MemoryOSHotQuery],
        *,
        max_queries: int,
        window_seconds: float,
    ) -> tuple[TransitionPrefetchEdge, ...]:
        if max_queries <= 0 or window_seconds <= 0 or not hot_queries:
            return ()
        hot_keys = {(query.namespace, query.query) for query in hot_queries}
        ordered = sorted(
            events,
            key=lambda event: (
                float(getattr(event, "created_at", 0.0) or 0.0),
                int(getattr(event, "id", 0) or 0),
            ),
        )
        previous_by_namespace: dict[str, tuple[str, float]] = {}
        transition_counts: OrderedDict[tuple[str, str, str], int] = OrderedDict()
        totals_by_source: dict[tuple[str, str], int] = {}
        last_seen: dict[tuple[str, str, str], float] = {}
        for event in ordered:
            metadata = getattr(event, "metadata", {}) or {}
            query = str(metadata.get("query") or "").strip()
            if not query:
                continue
            namespace = str(getattr(event, "namespace", None) or "default")
            created_at = float(getattr(event, "created_at", 0.0) or 0.0)
            previous = previous_by_namespace.get(namespace)
            if previous is not None:
                previous_query, previous_at = previous
                elapsed = created_at - previous_at
                if (
                    previous_query != query
                    and 0.0 <= elapsed <= float(window_seconds)
                    and (namespace, previous_query) in hot_keys
                ):
                    source = (namespace, previous_query)
                    totals_by_source[source] = totals_by_source.get(source, 0) + 1
                    if (namespace, query) in hot_keys:
                        previous_by_namespace[namespace] = (query, created_at)
                        continue
                    key = (namespace, previous_query, query)
                    transition_counts[key] = transition_counts.get(key, 0) + 1
                    last_seen[key] = max(created_at, last_seen.get(key, 0.0))
            previous_by_namespace[namespace] = (query, created_at)
        edges = tuple(
            TransitionPrefetchEdge(
                namespace=namespace,
                from_query=from_query,
                to_query=to_query,
                count=count,
                probability=(
                    count / totals_by_source.get((namespace, from_query), count)
                    if count > 0
                    else 0.0
                ),
                last_seen=last_seen.get((namespace, from_query, to_query), 0.0),
            )
            for (namespace, from_query, to_query), count in transition_counts.items()
        )
        ordered_transitions = sorted(
            edges,
            key=lambda item: (
                -item.probability,
                -item.count,
                -item.last_seen,
                item.namespace,
                item.from_query,
                item.to_query,
            ),
        )
        return tuple(ordered_transitions[:max_queries])

    def _neighbor_queries(
        self,
        hot_query: MemoryOSHotQuery,
        results: Iterable[QueryResult],
        *,
        terms_per_hot_query: int,
    ) -> list[str]:
        base_tokens = self._query_tokens(hot_query.query)
        term_counts: OrderedDict[str, int] = OrderedDict()
        for result in results:
            for term in self._result_terms(result):
                if term in base_tokens:
                    continue
                term_counts[term] = term_counts.get(term, 0) + 1
        ordered_terms = sorted(
            term_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        queries: list[str] = []
        base = " ".join(base_tokens) or hot_query.query.strip()
        for term, _count in ordered_terms[:terms_per_hot_query]:
            queries.append(f"{base} {term}".strip())
        return queries

    def _query_tokens(self, text: str) -> tuple[str, ...]:
        tokens: list[str] = []
        for raw in str(text).split():
            token = normalize_token(raw)
            if not token or is_stopword_token(token):
                continue
            if token not in tokens:
                tokens.append(token)
        return tuple(tokens)

    def _result_terms(self, result: QueryResult) -> tuple[str, ...]:
        parts: list[str] = [result.text]
        parts.extend(str(tag) for tag in result.tags)
        for key, value in (result.metadata or {}).items():
            if key in {"source", "kind", "type", "topic", "category"}:
                parts.append(str(value))
        terms: list[str] = []
        for part in parts:
            for raw in str(part).replace("_", " ").replace("-", " ").split():
                token = normalize_token(raw)
                if len(token) < 3 or is_stopword_token(token):
                    continue
                if token not in terms:
                    terms.append(token)
        return tuple(terms)

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

    def _improvement_suggestions(
        self,
        *,
        namespace: str | None,
        hot_queries: list[MemoryOSHotQuery],
        prewarm: CachePrewarmReport,
        predictive: PredictivePrefetchReport,
        stats_after: dict[str, object],
        memory_pressure_threshold: int,
        cache_enabled: bool,
        concepts_created: int,
        priority_predictions: int,
        forgetting_demotions: int,
        architecture_payload: dict[str, object],
    ) -> tuple[MemoryOSImprovementSuggestion, ...]:
        suggestions: list[MemoryOSImprovementSuggestion] = []
        seen: set[str] = set()

        def add(
            id: str,
            severity: str,
            title: str,
            rationale: str,
            action: str,
            evidence: dict[str, object] | None = None,
        ) -> None:
            if id in seen:
                return
            seen.add(id)
            suggestions.append(
                MemoryOSImprovementSuggestion(
                    id=id,
                    severity=severity,
                    title=title,
                    rationale=rationale,
                    action=action,
                    evidence=evidence or {},
                )
            )

        active = int(stats_after.get("active_memories", 0) or 0)
        expired = int(stats_after.get("expired_memories", 0) or 0)
        index_healthy = bool(stats_after.get("index_healthy", True))
        namespace_label = namespace or "all namespaces"
        hot_count = len(hot_queries)

        if hot_queries and not cache_enabled:
            add(
                "shared-cache-required",
                "action_required",
                "Enable shared hot-query cache",
                "Audited hot queries exist, but this Memory OS run had no cache attached.",
                "Attach RedisHotMemoryCache for production workers so repeated recalls warm across API processes.",
                {
                    "namespace": namespace_label,
                    "hot_queries": hot_count,
                    "top_query": hot_queries[0].query,
                },
            )

        if not hot_queries:
            add(
                "query-audit-required",
                "watch",
                "Collect query audit traffic",
                "The worker cannot learn hot memories or follow-up query transitions without audited query events.",
                "Enable query audit in staging before relying on prewarm, priority prediction, or adaptive forgetting.",
                {"namespace": namespace_label, "scanned_events": prewarm.scanned_events},
            )

        if cache_enabled and hot_queries and prewarm.warmed == 0 and prewarm.skipped == 0:
            add(
                "prewarm-not-warming",
                "action_required",
                "Fix cache prewarm filters",
                "Hot queries were found, but no cache entries were warmed or skipped.",
                "Inspect cache capacity, namespace filters, min_frequency, and min_score before increasing worker cadence.",
                {
                    "namespace": namespace_label,
                    "hot_queries": hot_count,
                    "prewarm_candidates": prewarm.candidates,
                },
            )

        if active >= int(memory_pressure_threshold):
            add(
                "service-index-and-sharding",
                "architecture_required",
                "Move pressure-heavy memory to service index and sharding",
                "This namespace or cluster crossed the configured memory-pressure threshold.",
                "Use Qdrant, pgvector, or persisted FAISS for candidate generation and shard by namespace before further growth.",
                {
                    "namespace": namespace_label,
                    "active_memories": active,
                    "threshold": int(memory_pressure_threshold),
                },
            )

        if expired > 0:
            add(
                "expired-memory-leftover",
                "watch",
                "Increase expiry maintenance cadence",
                "Expired memories remain after the current Memory OS run.",
                "Run Memory OS maintenance more frequently or inspect TTL filters for this namespace.",
                {"namespace": namespace_label, "expired_memories": expired},
            )

        if not index_healthy:
            add(
                "index-health-repair",
                "architecture_required",
                "Repair unhealthy candidate index",
                "The source-of-truth memory count and candidate index are not in a healthy state.",
                "Run index-health and rebuild-index before serving production traffic.",
                {"namespace": namespace_label, "index_healthy": False},
            )

        if concepts_created:
            add(
                "review-consolidated-concepts",
                "watch",
                "Review newly consolidated concept memories",
                "Memory OS formed higher-level concept memories from active field clusters.",
                "Surface these concept memories in Studio/API review before promoting them to high-priority production context.",
                {"namespace": namespace_label, "concepts_created": concepts_created},
            )

        if predictive.generated_queries:
            add(
                "predictive-prefetch-active",
                "ok",
                "Keep predictive prefetch enabled",
                "Observed recall paths produced likely follow-up queries.",
                "Track predictive prefetch hit rate and keep transition edges in the benchmark artifact.",
                {
                    "namespace": namespace_label,
                    "generated_queries": predictive.generated_queries,
                    "warmed_queries": predictive.warmed,
                    "transition_queries": list(predictive.transition_queries),
                },
            )

        if priority_predictions:
            add(
                "priority-learning-active",
                "ok",
                "Keep usage-pattern priority learning enabled",
                "Hot audited queries produced deterministic priority boosts for recalled memories.",
                "Keep feedback and priority deltas in the Memory OS evidence artifact.",
                {
                    "namespace": namespace_label,
                    "priority_predictions": priority_predictions,
                },
            )

        if forgetting_demotions:
            add(
                "adaptive-forgetting-active",
                "ok",
                "Keep adaptive forgetting enabled",
                "Unused low-access memories were demoted before they could compete with hot context.",
                "Track demotion counts and stale-recall regressions in release evidence.",
                {"namespace": namespace_label, "forgetting_demotions": forgetting_demotions},
            )

        for item in architecture_payload.get("recommendations", []):
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "watch")
            if severity == "ok":
                continue
            rec_id = str(item.get("id") or "architecture")
            add(
                f"architecture:{rec_id}",
                severity,
                str(item.get("title") or rec_id),
                str(item.get("rationale") or "Architecture advisor raised a production recommendation."),
                str(item.get("action") or "Review architecture advisor output before scaling."),
                {
                    "namespace": namespace_label,
                    "source": "architecture_advisor",
                    "recommendation_id": rec_id,
                },
            )

        if not suggestions:
            add(
                "memory-os-steady-state",
                "ok",
                "Memory OS steady state",
                "The current worker run found no immediate memory-policy or architecture changes.",
                "Keep the worker scheduled and keep readiness artifacts fresh.",
                {"namespace": namespace_label, "active_memories": active},
            )

        return tuple(suggestions)

    def _policy_manifest(
        self,
        *,
        namespace: str | None,
        hot_queries: list[MemoryOSHotQuery],
        prewarm: CachePrewarmReport,
        predictive: PredictivePrefetchReport,
        stats_after: dict[str, object],
        memory_pressure_threshold: int,
        cache_enabled: bool,
        concepts_created: int,
        priority_predictions: int,
        forgetting_demotions: int,
        architecture_payload: dict[str, object],
        lock_report: MemoryOSLockReport,
        deployment: str,
    ) -> MemoryOSPolicyManifest:
        decisions: list[MemoryOSPolicyDecision] = []
        active = int(stats_after.get("active_memories", 0) or 0)
        hot_count = len(hot_queries)
        namespace_label = namespace or "all namespaces"
        production = deployment.lower() in {"production", "cluster", "serverless"}

        def add(
            id: str,
            status: str,
            strategy: str,
            rationale: str,
            action: str,
            evidence: dict[str, object] | None = None,
        ) -> None:
            decisions.append(
                MemoryOSPolicyDecision(
                    id=id,
                    status=status,
                    strategy=strategy,
                    rationale=rationale,
                    action=action,
                    evidence=evidence or {},
                )
            )

        if cache_enabled and (prewarm.warmed or predictive.warmed):
            add(
                "prefetch-policy",
                "ok",
                "hot-query-and-transition-prefetch",
                "Audited hot queries are being converted into warm cache entries and predicted follow-up recalls.",
                "Keep collecting prewarm hit rate, predictive hit rate, and transition edges in readiness artifacts.",
                {
                    "namespace": namespace_label,
                    "hot_queries": hot_count,
                    "prewarm_warmed": prewarm.warmed,
                    "predictive_generated": predictive.generated_queries,
                    "predictive_warmed": predictive.warmed,
                    "transition_edges": len(predictive.transition_edges),
                },
            )
        elif hot_queries and not cache_enabled:
            add(
                "prefetch-policy",
                "action_required",
                "attach-shared-hot-cache",
                "Hot query traffic exists, but this run had no shared cache to prewarm.",
                "Attach RedisHotMemoryCache before using Memory OS in multi-process production.",
                {"namespace": namespace_label, "hot_queries": hot_count},
            )
        else:
            add(
                "prefetch-policy",
                "watch",
                "collect-query-audit-first",
                "Memory OS needs audited query traffic before it can learn hot recalls.",
                "Run representative traffic with query audit enabled, then rerun Memory OS.",
                {"namespace": namespace_label, "scanned_events": prewarm.scanned_events},
            )

        if priority_predictions:
            add(
                "priority-policy",
                "ok",
                "usage-pattern-priority-boost",
                "Repeated recalls deterministically boosted memories that are likely to stay useful.",
                "Keep priority deltas in release evidence and cap per-run boosts to prevent runaway reinforcement.",
                {
                    "namespace": namespace_label,
                    "priority_predictions": priority_predictions,
                },
            )
        else:
            add(
                "priority-policy",
                "watch",
                "wait-for-hot-recall-signal",
                "No priority predictions fired in this run.",
                "Keep audit collection enabled and lower min_frequency only after checking false-positive recall.",
                {"namespace": namespace_label, "hot_queries": hot_count},
            )

        if forgetting_demotions:
            add(
                "forgetting-policy",
                "ok",
                "demote-cold-low-access-memories",
                "Cold memories were demoted before they could compete with fresh or reinforced context.",
                "Track stale-recall regressions and demotion counts in benchmark artifacts.",
                {
                    "namespace": namespace_label,
                    "forgetting_demotions": forgetting_demotions,
                },
            )
        elif active >= int(memory_pressure_threshold):
            add(
                "forgetting-policy",
                "action_required",
                "tighten-retention-under-pressure",
                "Memory pressure crossed the configured threshold, but this run did not demote stale records.",
                "Review TTLs, access-count thresholds, and protected ids before adding more data.",
                {
                    "namespace": namespace_label,
                    "active_memories": active,
                    "threshold": int(memory_pressure_threshold),
                },
            )
        else:
            add(
                "forgetting-policy",
                "watch",
                "observe-before-demoting",
                "Memory pressure is below threshold and no cold demotions were necessary.",
                "Keep adaptive forgetting scheduled and validate stale suppression in dynamic benchmarks.",
                {"namespace": namespace_label, "active_memories": active},
            )

        if concepts_created:
            add(
                "consolidation-policy",
                "ok",
                "promote-active-clusters-to-concepts",
                "The field graph produced higher-level concept memories from active clusters.",
                "Review new concept memories in Studio/API before assigning very high priority.",
                {"namespace": namespace_label, "concepts_created": concepts_created},
            )
        else:
            add(
                "consolidation-policy",
                "watch",
                "wait-for-stable-clusters",
                "No concept memories were created in this run.",
                "Keep consolidation enabled and require enough cluster energy before promoting abstractions.",
                {"namespace": namespace_label, "concepts_created": 0},
            )

        architecture_status = str(architecture_payload.get("status") or "watch")
        if architecture_status == "architecture_required":
            scale_strategy = "external-index-sharding-and-production-controls"
        elif architecture_status == "action_required":
            scale_strategy = "fix-production-gaps-before-growth"
        else:
            scale_strategy = "keep-current-scale-profile-under-observation"
        add(
            "scale-policy",
            architecture_status,
            scale_strategy,
            "Architecture advisor converted target load, namespace count, backend health, and deployment mode into scale guidance.",
            "Follow next_commands and keep scale-readiness artifacts current before raising release claims.",
            {
                "namespace": namespace_label,
                "active_memories": active,
                "target_memories": architecture_payload.get("target_memories"),
                "recommendation_ids": [
                    str(item.get("id"))
                    for item in architecture_payload.get("recommendations", [])
                    if isinstance(item, dict) and item.get("id") is not None
                ],
            },
        )

        if lock_report.required and not lock_report.acquired:
            coordination_status = "action_required"
            coordination_strategy = "do-not-overlap-memory-os-runs"
            coordination_rationale = "A required distributed lock was not acquired, so mutation should not proceed."
            coordination_action = "Fix lock ownership or retry after the current worker finishes."
        elif production and not lock_report.key:
            coordination_status = "action_required"
            coordination_strategy = "require-distributed-lock-in-production"
            coordination_rationale = "Production Memory OS workers need a distributed lock to avoid overlapping consolidation and forgetting."
            coordination_action = "Run Memory OS with RedisMemoryOSLock and --lock-required in production."
        else:
            coordination_status = "ok" if lock_report.ok else "watch"
            coordination_strategy = "single-writer-memory-os-cycle"
            coordination_rationale = "The current run has a safe coordination state for this deployment mode."
            coordination_action = "Keep one Memory OS writer per namespace window and use a shared lock for production workers."
        add(
            "coordination-policy",
            coordination_status,
            coordination_strategy,
            coordination_rationale,
            coordination_action,
            {
                "namespace": namespace_label,
                "deployment": deployment,
                "lock_required": lock_report.required,
                "lock_acquired": lock_report.acquired,
                "lock_key": lock_report.key,
                "cache_enabled": cache_enabled,
            },
        )

        severity_rank = {
            "ok": 0,
            "watch": 1,
            "action_required": 2,
            "architecture_required": 3,
        }
        status = max(
            (decision.status for decision in decisions),
            key=lambda item: severity_rank.get(item, 1),
            default="watch",
        )
        return MemoryOSPolicyManifest(
            status=status,
            namespace=namespace,
            decisions=tuple(decisions),
        )

    def _policy_history(
        self,
        *,
        namespace: str | None,
        current: MemoryOSPolicyManifest,
        window: int,
    ) -> MemoryOSPolicyHistory:
        events: list[Any] = []
        if hasattr(self.memory, "audit_events"):
            try:
                events = list(
                    self.memory.audit_events(
                        namespace=namespace,
                        action="memory_os",
                        limit=max(0, int(window)),
                    )
                )
            except Exception:
                events = []
        previous_by_id: dict[str, Counter[str]] = {}
        status_counts: Counter[str] = Counter()
        for decision in current.decisions:
            status_counts.update([decision.status])
        for event in events:
            metadata = getattr(event, "metadata", {}) or {}
            status_by_id = self._policy_status_by_id_from_metadata(metadata)
            for decision_id, status in status_by_id.items():
                previous_by_id.setdefault(decision_id, Counter()).update([status])
                status_counts.update([status])

        current_by_id = {decision.id: decision.status for decision in current.decisions}
        repeated_action = tuple(
            sorted(
                decision_id
                for decision_id, status in current_by_id.items()
                if status == "action_required"
                and previous_by_id.get(decision_id, Counter()).get("action_required", 0) > 0
            )
        )
        repeated_architecture = tuple(
            sorted(
                decision_id
                for decision_id, status in current_by_id.items()
                if status == "architecture_required"
                and previous_by_id.get(decision_id, Counter()).get("architecture_required", 0) > 0
            )
        )
        stable_ok = tuple(
            sorted(
                decision_id
                for decision_id, status in current_by_id.items()
                if status == "ok"
                and previous_by_id.get(decision_id, Counter()).get("ok", 0) > 0
            )
        )
        previous_required = any(
            count
            for counter in previous_by_id.values()
            for status, count in counter.items()
            if status in {"action_required", "architecture_required"}
        )
        current_required = any(
            status in {"action_required", "architecture_required"}
            for status in current_by_id.values()
        )
        if not events:
            trend = "first_run"
        elif repeated_architecture:
            trend = "repeated_architecture_required"
        elif repeated_action:
            trend = "repeated_action_required"
        elif previous_required and not current_required:
            trend = "improving"
        elif stable_ok:
            trend = "stable"
        else:
            trend = "watch"
        return MemoryOSPolicyHistory(
            previous_runs=len(events),
            window=max(0, int(window)),
            trend=trend,
            repeated_action_required_ids=repeated_action,
            repeated_architecture_required_ids=repeated_architecture,
            stable_ok_ids=stable_ok,
            status_counts=dict(sorted(status_counts.items())),
        )

    def _policy_status_by_id_from_metadata(
        self,
        metadata: dict[str, object],
    ) -> dict[str, str]:
        by_id = metadata.get("policy_decision_status_by_id")
        if isinstance(by_id, dict):
            return {
                str(decision_id): str(status)
                for decision_id, status in by_id.items()
                if decision_id is not None and status is not None
            }
        ids = metadata.get("policy_decision_ids")
        statuses = metadata.get("policy_decision_statuses")
        if isinstance(ids, list) and isinstance(statuses, list):
            return {
                str(decision_id): str(status)
                for decision_id, status in zip(ids, statuses)
                if decision_id is not None and status is not None
            }
        return {}

    def _policy_history_suggestions(
        self,
        *,
        namespace: str | None,
        current: MemoryOSPolicyManifest,
        history: MemoryOSPolicyHistory,
    ) -> tuple[MemoryOSImprovementSuggestion, ...]:
        if not history.repeated_required_ids:
            return ()
        namespace_label = namespace or "all namespaces"
        current_by_id = {decision.id: decision for decision in current.decisions}
        suggestions: list[MemoryOSImprovementSuggestion] = []
        for decision_id in history.repeated_required_ids:
            decision = current_by_id.get(decision_id)
            if decision is None:
                continue
            severity = (
                "architecture_required"
                if decision_id in history.repeated_architecture_required_ids
                else "action_required"
            )
            suggestions.append(
                MemoryOSImprovementSuggestion(
                    id=f"policy-history:{decision_id}",
                    severity=severity,
                    title=f"Resolve repeated {decision_id}",
                    rationale=(
                        "Memory OS saw the same required policy state in repeated "
                        "worker runs, so this is no longer a one-off maintenance signal."
                    ),
                    action=decision.action,
                    evidence={
                        "namespace": namespace_label,
                        "policy_id": decision_id,
                        "policy_status": decision.status,
                        "policy_strategy": decision.strategy,
                        "history_trend": history.trend,
                        "previous_runs": history.previous_runs,
                    },
                )
            )
        return tuple(suggestions)

    def _policy_history_recommendations(
        self,
        *,
        current: MemoryOSPolicyManifest,
        history: MemoryOSPolicyHistory,
    ) -> list[str]:
        if not history.repeated_required_ids:
            return []
        current_by_id = {decision.id: decision for decision in current.decisions}
        rows: list[str] = []
        for decision_id in history.repeated_required_ids:
            decision = current_by_id.get(decision_id)
            if decision is None:
                continue
            rows.append(
                "Memory OS policy history: "
                f"[{decision.status}] {decision_id} repeated across "
                f"{history.previous_runs + 1} runs - {decision.action}"
            )
        return rows

    def _architecture_advice(
        self,
        *,
        stats_after: dict[str, object],
        namespace: str | None,
        target_memories: int | None,
        target_p99_ms: float,
        observed_p99_ms: float | None,
        namespace_count: int | None,
        node_count: int | None,
        replication_factor: int,
        read_quorum: int,
        read_fanout: int | None,
        target_qps: float,
        deployment: str,
        multimodal: bool,
    ) -> MemoryArchitectureAdvice:
        return advise_memory_architecture(
            stats_after,
            namespace=namespace,
            target_memories=target_memories,
            target_p99_ms=target_p99_ms,
            observed_p99_ms=observed_p99_ms,
            namespace_count=namespace_count,
            node_count=node_count,
            replication_factor=replication_factor,
            read_quorum=read_quorum,
            read_fanout=read_fanout,
            target_qps=target_qps,
            deployment=deployment,
            multimodal=multimodal,
        )

    def _architecture_recommendations(
        self,
        advice: MemoryArchitectureAdvice,
    ) -> list[str]:
        rows = []
        for recommendation in advice.recommendations:
            if recommendation.severity == "ok":
                continue
            rows.append(
                "Architecture advisor: "
                f"[{recommendation.severity}] {recommendation.title} - "
                f"{recommendation.action}"
            )
        return rows

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
                    "predictive_prefetch_generated": report.predictive_prefetch.generated_queries,
                    "predictive_prefetch_warmed": report.predictive_prefetch.warmed,
                    "index_rebuilt": report.index_rebuilt,
                    "lock_required": report.lock.required,
                    "lock_acquired": report.lock.acquired,
                    "lock_key": report.lock.key,
                    "lock_reason": report.lock.reason,
                    "policy_status": report.policy_manifest.status,
                    "policy_decisions": len(report.policy_manifest.decisions),
                    "policy_decision_ids": [
                        decision.id for decision in report.policy_manifest.decisions
                    ],
                    "policy_decision_statuses": [
                        decision.status for decision in report.policy_manifest.decisions
                    ],
                    "policy_decision_status_by_id": {
                        decision.id: decision.status
                        for decision in report.policy_manifest.decisions
                    },
                    "policy_history_trend": report.policy_history.trend,
                    "policy_history_previous_runs": report.policy_history.previous_runs,
                    "policy_repeated_required_ids": list(
                        report.policy_history.repeated_required_ids
                    ),
                    "policy_history_escalations": len(
                        [
                            suggestion
                            for suggestion in report.suggestions
                            if suggestion.id.startswith("policy-history:")
                        ]
                    ),
                    "actions": list(report.actions),
                    "ok": report.ok,
                },
            )
        except Exception:
            pass


class MemoryOSScheduler:
    """Read-only Memory OS scheduler/preflight for production workers.

    The scheduler inspects current stats and query-audit traffic, then returns a
    concrete task plan for CronJobs, queue workers, or external orchestrators.
    It intentionally does not mutate memory state.
    """

    def __init__(self, memory: Any):
        self.memory = memory

    def plan(
        self,
        *,
        namespace: str | None = None,
        audit_limit: int = 512,
        max_hot_queries: int = 32,
        min_frequency: int = 2,
        top_k: int = 3,
        min_score: float | None = None,
        target_memories: int | None = None,
        namespace_count: int | None = None,
        node_count: int | None = None,
        replication_factor: int = 3,
        read_quorum: int = 1,
        read_fanout: int | None = None,
        target_qps: float = 100.0,
        target_p99_ms: float = 100.0,
        observed_p99_ms: float | None = None,
        deployment: str = "local",
        cache_mode: str = "auto",
        multimodal: bool = False,
        memory_pressure_threshold: int = 50_000,
    ) -> MemoryOSSchedulePlan:
        helper = MemoryOSWorker(self.memory)
        stats = helper._stats(namespace)
        events = helper._query_events(namespace=namespace, limit=audit_limit)
        hot_queries = helper._hot_queries(
            events,
            max_hot_queries=max_hot_queries,
            min_frequency=min_frequency,
        )
        active = int(stats.get("active_memories", 0) or 0)
        target = int(target_memories or active or 0)
        namespaces = int(namespace_count or stats.get("namespaces", 0) or (1 if namespace else 0) or 1)
        deployment_name = str(deployment or "local").lower()
        production_like = deployment_name in {"production", "prod", "staging"}
        qps = max(0.0, float(target_qps))
        p99_target = max(1.0, float(target_p99_ms))
        p99_observed = None if observed_p99_ms is None else max(0.0, float(observed_p99_ms))
        pressure = target >= int(memory_pressure_threshold) or active >= int(memory_pressure_threshold)
        shared_cache_needed = (
            production_like
            or pressure
            or qps >= 50.0
            or namespaces >= 32
            or len(hot_queries) >= max(4, int(max_hot_queries) // 2)
        )
        cache_requested = str(cache_mode or "auto").lower()
        if cache_requested not in {"auto", "disabled", "local", "redis"}:
            raise ValueError("cache_mode must be auto, disabled, local, or redis")
        effective_cache = (
            "redis"
            if cache_requested == "auto" and shared_cache_needed
            else "local"
            if cache_requested == "auto"
            else cache_requested
        )
        cache_enabled = effective_cache != "disabled"
        worker_count = self._worker_count(
            target_memories=target,
            namespace_count=namespaces,
            target_qps=qps,
            production_like=production_like,
        )
        lock_required = worker_count > 1 or production_like
        namespace_arg = f" --namespace {namespace}" if namespace else ""
        min_score_arg = "" if min_score is None else f" --min-score {float(min_score):g}"
        common_targets = (
            f" --target-memories {target}"
            f" --namespace-count {namespaces}"
            f" --deployment {deployment_name}"
            f" --target-qps {qps:g}"
            f" --target-p99-ms {p99_target:g}"
        )
        if node_count is not None:
            common_targets += f" --node-count {int(node_count)}"
        if multimodal:
            common_targets += " --multimodal"

        architecture = helper._architecture_advice(
            stats_after=stats,
            namespace=namespace,
            target_memories=target or None,
            target_p99_ms=p99_target,
            observed_p99_ms=p99_observed,
            namespace_count=namespaces,
            node_count=node_count,
            replication_factor=replication_factor,
            read_quorum=read_quorum,
            read_fanout=read_fanout,
            target_qps=qps,
            deployment=deployment_name,
            multimodal=multimodal,
        ).as_dict()

        policy_manifest = self._schedule_policy_manifest(
            helper=helper,
            namespace=namespace,
            events=events,
            hot_queries=hot_queries,
            stats=stats,
            memory_pressure_threshold=memory_pressure_threshold,
            cache_enabled=effective_cache == "redis",
            architecture=architecture,
            lock_required=lock_required,
            deployment=deployment_name,
        )
        policy_history = helper._policy_history(
            namespace=namespace,
            current=policy_manifest,
            window=5,
        )
        policy_escalation_ids = policy_history.repeated_required_ids
        policy_auto_adjustments: list[str] = []
        if (
            cache_requested == "auto"
            and effective_cache != "redis"
            and "prefetch-policy" in policy_escalation_ids
        ):
            effective_cache = "redis"
            cache_enabled = True
            shared_cache_needed = True
            policy_auto_adjustments.append("cache_mode:redis")
            policy_manifest = self._schedule_policy_manifest(
                helper=helper,
                namespace=namespace,
                events=events,
                hot_queries=hot_queries,
                stats=stats,
                memory_pressure_threshold=memory_pressure_threshold,
                cache_enabled=effective_cache == "redis",
                architecture=architecture,
                lock_required=lock_required,
                deployment=deployment_name,
            )
            policy_history = helper._policy_history(
                namespace=namespace,
                current=policy_manifest,
                window=5,
            )
        redis_arg = " --redis-url $WAVEMIND_REDIS_URL" if effective_cache == "redis" else ""
        lock_arg = " --lock-required" if lock_required else ""
        hot_policy_escalated = bool(policy_escalation_ids)
        scale_policy_escalated = any(
            item in policy_escalation_ids
            for item in ("scale-policy", "coordination-policy", "forgetting-policy")
        )

        hot_cadence = 15 if production_like and hot_queries else 60 if hot_queries else 300
        maintenance_cadence = 300 if pressure else 900 if production_like else 1800
        forgetting_cadence = 900 if pressure else 3600
        consolidation_cadence = 300 if hot_queries and pressure else 900 if hot_queries else 3600
        advice_cadence = 300 if architecture.get("status") == "architecture_required" else 1800
        if hot_policy_escalated and hot_queries:
            hot_cadence = min(hot_cadence, 30 if production_like else 45)
            consolidation_cadence = min(consolidation_cadence, 600)
        if scale_policy_escalated:
            maintenance_cadence = min(maintenance_cadence, 300)
            forgetting_cadence = min(forgetting_cadence, 600)
            advice_cadence = min(advice_cadence, 120)
        tasks = [
            self._task(
                "memory-os",
                "Adaptive Memory OS cycle",
                True,
                hot_cadence,
                worker_count,
                max(60, hot_cadence * 2),
                (
                    "wavemind memory-os"
                    f"{namespace_arg}{redis_arg}"
                    f"{lock_arg}"
                    f" --audit-limit {int(audit_limit)}"
                    f" --max-hot-queries {int(max_hot_queries)}"
                    f" --min-frequency {int(min_frequency)}"
                    f" --top-k {int(top_k)}{min_score_arg}{common_targets}"
                ),
                "Runs decay, hot-query learning, cache warming, predictive prefetch, consolidation, and advisor checks.",
                priority="critical" if production_like or hot_policy_escalated else "high",
                requires_shared_cache=effective_cache == "redis",
                requires_distributed_lock=lock_required,
            ),
            self._task(
                "cache-prewarm",
                "Hot query cache prewarm",
                bool(cache_enabled and hot_queries),
                hot_cadence,
                max(1, min(worker_count, 4)),
                max(30, hot_cadence * 2),
                (
                    "wavemind cache-prewarm"
                    f"{namespace_arg}{redis_arg}"
                    f" --audit-limit {int(audit_limit)}"
                    f" --max-queries {int(max_hot_queries)}"
                    f" --min-frequency {int(min_frequency)}"
                    f" --top-k {int(top_k)}{min_score_arg}"
                ),
                "Keeps repeated recall paths hot across API workers.",
                priority="critical"
                if "prefetch-policy" in policy_escalation_ids
                else "high" if hot_queries else "normal",
                requires_shared_cache=effective_cache == "redis",
                requires_distributed_lock=False,
            ),
            self._task(
                "predictive-prefetch",
                "Predictive neighbor prefetch",
                bool(cache_enabled and hot_queries),
                max(60, hot_cadence * 2),
                max(1, min(worker_count, 4)),
                120,
                (
                    "wavemind memory-os"
                    f"{namespace_arg}{redis_arg}"
                    f"{lock_arg}"
                    " --consolidate-steps 0 --no-consolidate-concepts"
                    " --no-adaptive-forgetting"
                    f" --audit-limit {int(audit_limit)}"
                    f" --max-hot-queries {int(max_hot_queries)}"
                    f" --min-frequency {int(min_frequency)}"
                    f" --top-k {int(top_k)}{min_score_arg}{common_targets}"
                ),
                "Warms likely follow-up queries from hot recall paths.",
                priority="high" if production_like else "normal",
                requires_shared_cache=effective_cache == "redis",
                requires_distributed_lock=production_like,
            ),
            self._task(
                "adaptive-forgetting",
                "Adaptive forgetting",
                active > 0 or target > 0,
                forgetting_cadence,
                1,
                300,
                (
                    "wavemind memory-os"
                    f"{namespace_arg}{redis_arg}"
                    f"{lock_arg}"
                    " --no-predictive-prefetch --no-predict-priorities"
                    " --consolidate-steps 0 --no-consolidate-concepts"
                    f"{common_targets}"
                ),
                "Demotes old unused memories before they compete with current context.",
                priority="critical"
                if "forgetting-policy" in policy_escalation_ids
                else "high" if pressure else "normal",
                requires_shared_cache=False,
                requires_distributed_lock=production_like,
            ),
            self._task(
                "consolidation",
                "Field and concept consolidation",
                active >= 2 or bool(hot_queries),
                consolidation_cadence,
                1,
                300,
                (
                    "wavemind memory-os"
                    f"{namespace_arg}{redis_arg}"
                    f"{lock_arg}"
                    " --no-predictive-prefetch --no-adaptive-forgetting"
                    f" --audit-limit {int(audit_limit)}"
                    f" --min-frequency {int(min_frequency)}{common_targets}"
                ),
                "Creates durable higher-level concept memories from active clusters.",
                priority="critical"
                if "consolidation-policy" in policy_escalation_ids
                else "high" if hot_queries else "normal",
                requires_shared_cache=False,
                requires_distributed_lock=True,
            ),
            self._task(
                "maintenance",
                "Expired memory and index maintenance",
                True,
                maintenance_cadence,
                1,
                300,
                f"wavemind maintenance{namespace_arg}",
                "Purges TTL-expired memories and repairs unhealthy local indexes.",
                priority="high" if not bool(stats.get("index_healthy", True)) else "normal",
                requires_shared_cache=False,
                requires_distributed_lock=production_like,
            ),
            self._task(
                "architecture-advice",
                "Architecture advisor preflight",
                True,
                advice_cadence,
                1,
                120,
                (
                    "wavemind advise"
                    f" --target-memories {target}"
                    f" --namespace-count {namespaces}"
                    f" --deployment {deployment_name}"
                    f" --replication-factor {int(replication_factor)}"
                    f" --read-quorum {int(read_quorum)}"
                    f" --target-qps {qps:g}"
                    f" --target-p99-ms {p99_target:g}"
                    " --json"
                ),
                "Keeps scale, sharding, cache, DR, observability, and multimodal readiness visible.",
                priority="critical"
                if architecture.get("status") == "architecture_required"
                or "scale-policy" in policy_escalation_ids
                else "normal",
                requires_shared_cache=False,
                requires_distributed_lock=False,
            ),
        ]

        infrastructure = self._required_infrastructure(
            effective_cache_mode=effective_cache,
            worker_count=worker_count,
            production_like=production_like,
        )
        recommendations = self._schedule_recommendations(
            hot_queries=hot_queries,
            effective_cache_mode=effective_cache,
            shared_cache_needed=shared_cache_needed,
            production_like=production_like,
            architecture=architecture,
            stats=stats,
            target_memories=target,
            observed_p99_ms=p99_observed,
            target_p99_ms=p99_target,
            policy_escalation_ids=policy_escalation_ids,
            policy_auto_adjustments=tuple(policy_auto_adjustments),
        )
        status = self._schedule_status(
            architecture=architecture,
            stats=stats,
            recommendations=recommendations,
            production_like=production_like,
            effective_cache_mode=effective_cache,
            shared_cache_needed=shared_cache_needed,
            policy_escalation_ids=policy_escalation_ids,
        )
        return MemoryOSSchedulePlan(
            status=status,
            namespace=namespace,
            deployment=deployment_name,
            cache_mode=cache_requested,
            effective_cache_mode=effective_cache,
            target_memories=target,
            namespace_count=namespaces,
            active_memories=active,
            hot_query_count=len(hot_queries),
            observed_p99_ms=p99_observed,
            target_p99_ms=p99_target,
            target_qps=qps,
            worker_count=worker_count,
            tasks=tuple(tasks),
            required_infrastructure=tuple(infrastructure),
            recommendations=tuple(recommendations),
            architecture_advice=architecture,
            policy_manifest=policy_manifest,
            policy_history=policy_history,
            policy_escalation_ids=policy_escalation_ids,
            policy_auto_adjustments=tuple(policy_auto_adjustments),
        )

    def _schedule_policy_manifest(
        self,
        *,
        helper: MemoryOSWorker,
        namespace: str | None,
        events: list[Any],
        hot_queries: list[MemoryOSHotQuery],
        stats: dict[str, object],
        memory_pressure_threshold: int,
        cache_enabled: bool,
        architecture: dict[str, object],
        lock_required: bool,
        deployment: str,
    ) -> MemoryOSPolicyManifest:
        planned_warmed = len(hot_queries) if cache_enabled and hot_queries else 0
        planned_predictive = 1 if cache_enabled and hot_queries else 0
        active = int(stats.get("active_memories", 0) or 0)
        pressure = active >= int(memory_pressure_threshold)
        return helper._policy_manifest(
            namespace=namespace,
            hot_queries=hot_queries,
            prewarm=CachePrewarmReport(
                scanned_events=len(events),
                candidates=len(hot_queries),
                warmed=planned_warmed,
            ),
            predictive=PredictivePrefetchReport(
                scanned_hot_queries=len(hot_queries),
                generated_queries=planned_predictive,
                warmed=planned_predictive,
            ),
            stats_after=stats,
            memory_pressure_threshold=memory_pressure_threshold,
            cache_enabled=cache_enabled,
            concepts_created=1 if hot_queries and active >= 2 else 0,
            priority_predictions=len(hot_queries),
            forgetting_demotions=1 if pressure else 0,
            architecture_payload=architecture,
            lock_report=MemoryOSLockReport(
                required=lock_required,
                acquired=lock_required,
                key="scheduler-preflight" if lock_required else None,
                reason="scheduler_preflight",
            ),
            deployment=deployment,
        )

    def _worker_count(
        self,
        *,
        target_memories: int,
        namespace_count: int,
        target_qps: float,
        production_like: bool,
    ) -> int:
        if not production_like and target_memories < 50_000 and target_qps <= 50:
            return 1
        by_qps = max(1, int(math.ceil(max(1.0, target_qps) / 100.0)))
        by_namespace = max(1, int(math.ceil(max(1, namespace_count) / 1024.0)))
        by_memory = max(1, int(math.ceil(max(1, target_memories) / 1_000_000.0)))
        return max(1, min(64, max(by_qps, by_namespace, by_memory)))

    def _task(
        self,
        id: str,
        title: str,
        enabled: bool,
        cadence_seconds: int,
        worker_count: int,
        timeout_seconds: int,
        command: str,
        reason: str,
        *,
        priority: str,
        requires_shared_cache: bool,
        requires_distributed_lock: bool,
    ) -> MemoryOSScheduleTask:
        return MemoryOSScheduleTask(
            id=id,
            title=title,
            enabled=bool(enabled),
            cadence_seconds=max(1, int(cadence_seconds)),
            worker_count=max(1, int(worker_count)),
            timeout_seconds=max(1, int(timeout_seconds)),
            command=command.strip(),
            reason=reason,
            priority=priority,
            requires_shared_cache=bool(requires_shared_cache),
            requires_distributed_lock=bool(requires_distributed_lock),
        )

    def _required_infrastructure(
        self,
        *,
        effective_cache_mode: str,
        worker_count: int,
        production_like: bool,
    ) -> list[str]:
        required: list[str] = []
        if effective_cache_mode == "redis":
            required.append("Redis-compatible shared hot-query cache")
        if production_like or worker_count > 1:
            required.append("distributed worker lock or single-flight scheduler")
            required.append("durable queue or Kubernetes CronJobs")
        if production_like:
            required.append("OpenTelemetry metrics for worker duration, errors, and warmed queries")
        return required

    def _schedule_recommendations(
        self,
        *,
        hot_queries: list[MemoryOSHotQuery],
        effective_cache_mode: str,
        shared_cache_needed: bool,
        production_like: bool,
        architecture: dict[str, object],
        stats: dict[str, object],
        target_memories: int,
        observed_p99_ms: float | None,
        target_p99_ms: float,
        policy_escalation_ids: tuple[str, ...],
        policy_auto_adjustments: tuple[str, ...],
    ) -> list[str]:
        recommendations: list[str] = []
        if policy_escalation_ids:
            recommendations.append(
                "Escalate repeated Memory OS policy gaps: "
                + ", ".join(policy_escalation_ids)
            )
        for adjustment in policy_auto_adjustments:
            if adjustment == "cache_mode:redis":
                recommendations.append(
                    "Scheduler changed auto cache mode to Redis because prefetch policy gaps repeated."
                )
        if shared_cache_needed and effective_cache_mode != "redis":
            recommendations.append("Use Redis cache mode before scaling multiple API workers.")
        if production_like and effective_cache_mode == "local":
            recommendations.append("Local cache is process-local; use Redis for production Memory OS workers.")
        if not hot_queries:
            recommendations.append("Enable query audit traffic before relying on prewarm or predictive prefetch.")
        if not bool(stats.get("index_healthy", True)):
            recommendations.append("Run maintenance with index rebuild before enabling high-QPS scheduler loops.")
        if observed_p99_ms is not None and observed_p99_ms > target_p99_ms:
            recommendations.append("Observed p99 is above target; increase worker cadence only after index/cache tuning.")
        if target_memories >= 10_000_000:
            recommendations.append("Back Memory OS with service-mode ANN indexes and external production evidence runs.")
        for item in architecture.get("recommendations", []):
            if isinstance(item, dict) and item.get("severity") not in {None, "ok"}:
                title = str(item.get("title") or item.get("id") or "architecture recommendation")
                action = str(item.get("action") or "").strip()
                recommendations.append(f"Architecture advisor: {title}" + (f" - {action}" if action else ""))
        if not recommendations:
            recommendations.append("Memory OS schedule is ready; keep task reports in release evidence.")
        return list(dict.fromkeys(recommendations))

    def _schedule_status(
        self,
        *,
        architecture: dict[str, object],
        stats: dict[str, object],
        recommendations: Iterable[str],
        production_like: bool,
        effective_cache_mode: str,
        shared_cache_needed: bool,
        policy_escalation_ids: tuple[str, ...],
    ) -> str:
        if not bool(stats.get("index_healthy", True)):
            return "action_required"
        if architecture.get("status") == "architecture_required":
            return "architecture_required"
        if policy_escalation_ids:
            return "action_required"
        if production_like and effective_cache_mode != "redis" and shared_cache_needed:
            return "architecture_required"
        if any("Enable query audit" in item for item in recommendations):
            return "watch"
        return "ok"


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
