from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import AliasChoices, BaseModel, Field

from . import __version__
from .advisor import advise_memory_architecture
from .cluster import ClusterNode, build_cluster_autoscale_plan, build_cluster_plan
from .core import WaveMind
from .encoders import create_text_encoder
from .importers import import_path
from .jobs import (
    CachePrewarmWorker,
    HotMemoryCache,
    MemoryOSScheduler,
    MemoryOSWorker,
    QueryVectorCache,
    RedisHotMemoryCache,
    RedisMemoryOSLock,
    RedisQueryVectorCache,
    query_with_cache,
    query_with_vector_cache,
)
from .observability import configure_observability, instrument_fastapi_app
from .studio import STUDIO_HTML, field_heatmap, studio_snapshot


logger = logging.getLogger("wavemind.api")
ROLE_LEVELS = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class RateLimitStats:
    allowed: int
    limited: int
    backend: str
    shared: bool

    @property
    def total(self) -> int:
        return self.allowed + self.limited


class APIAuth:
    def __init__(self, keys: dict[str, str]):
        self.keys = keys

    @classmethod
    def from_env(cls) -> "APIAuth":
        keys: dict[str, str] = {}
        for env_name, role in (
            ("WAVEMIND_READ_KEYS", "read"),
            ("WAVEMIND_WRITE_KEYS", "write"),
            ("WAVEMIND_API_KEYS", "admin"),
            ("WAVEMIND_ADMIN_KEYS", "admin"),
        ):
            for key in _split_keys(os.environ.get(env_name, "")):
                keys[key] = role
        return cls(keys)

    @property
    def enabled(self) -> bool:
        return bool(self.keys)

    def role_for_request(self, request: Request) -> str | None:
        key = request.headers.get("x-api-key")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        if not key:
            return None
        return self.keys.get(key)

    def check(self, request: Request, required_role: str) -> None:
        if not self.enabled:
            return
        role = self.role_for_request(request)
        if role is None:
            raise HTTPException(status_code=401, detail="Missing or invalid API key")
        if ROLE_LEVELS[role] < ROLE_LEVELS[required_role]:
            raise HTTPException(status_code=403, detail="Insufficient API key role")


class InMemoryRateLimiter:
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = max(0, int(requests_per_minute))
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._allowed = 0
        self._limited = 0

    @classmethod
    def from_env(cls) -> "InMemoryRateLimiter | None":
        raw = os.environ.get("WAVEMIND_RATE_LIMIT_PER_MINUTE", "0")
        limit = int(raw or "0")
        if limit <= 0:
            return None
        return cls(limit)

    def allow(self, request: Request) -> bool:
        if self.requests_per_minute <= 0:
            return True
        now = time.time()
        key = _rate_limit_key(request)
        cutoff = now - 60.0
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.requests_per_minute:
                self._limited += 1
                return False
            hits.append(now)
            self._allowed += 1
            return True

    def stats(self) -> RateLimitStats:
        with self._lock:
            return RateLimitStats(
                allowed=self._allowed,
                limited=self._limited,
                backend="memory",
                shared=False,
            )


class RedisRateLimiter:
    def __init__(
        self,
        client: Any,
        requests_per_minute: int,
        *,
        prefix: str = "wavemind:rate",
        fail_open: bool = False,
    ):
        self.client = client
        self.requests_per_minute = max(0, int(requests_per_minute))
        self.prefix = prefix.rstrip(":")
        self.fail_open = bool(fail_open)
        self._lock = Lock()
        self._allowed = 0
        self._limited = 0

    @classmethod
    def from_url(
        cls,
        url: str,
        requests_per_minute: int,
        *,
        prefix: str = "wavemind:rate",
        fail_open: bool = False,
    ) -> "RedisRateLimiter":
        import redis  # type: ignore

        return cls(
            redis.Redis.from_url(url, decode_responses=True),
            requests_per_minute,
            prefix=prefix,
            fail_open=fail_open,
        )

    def allow(self, request: Request) -> bool:
        if self.requests_per_minute <= 0:
            return True
        window = int(time.time() // 60)
        identity = hashlib.sha256(_rate_limit_key(request).encode("utf-8")).hexdigest()
        key = f"{self.prefix}:{window}:{identity}"
        try:
            count = int(self.client.incr(key))
            if count == 1:
                self.client.expire(key, 120)
            allowed = count <= self.requests_per_minute
        except Exception:
            logger.warning("Redis rate limiter failed", exc_info=True)
            allowed = self.fail_open
        with self._lock:
            if allowed:
                self._allowed += 1
            else:
                self._limited += 1
        return allowed

    def stats(self) -> RateLimitStats:
        with self._lock:
            return RateLimitStats(
                allowed=self._allowed,
                limited=self._limited,
                backend="redis",
                shared=True,
            )


class APIOperationMetrics:
    def __init__(self, max_samples: int = 512):
        self.max_samples = max(1, int(max_samples))
        self._lock = Lock()
        self._requests: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._durations: dict[str, deque[float]] = {}

    def record(self, operation: str, duration_ms: float, failed: bool) -> None:
        key = _metric_key(operation)
        with self._lock:
            self._requests[key] = self._requests.get(key, 0) + 1
            if failed:
                self._failures[key] = self._failures.get(key, 0) + 1
            durations = self._durations.setdefault(key, deque(maxlen=self.max_samples))
            durations.append(float(duration_ms))

    def snapshot(self) -> dict[str, float | int]:
        payload: dict[str, float | int] = {}
        with self._lock:
            operations = set(self._requests) | set(self._failures) | set(self._durations)
            for operation in sorted(operations):
                durations = list(self._durations.get(operation, ()))
                payload[f"api_{operation}_requests_total"] = self._requests.get(operation, 0)
                payload[f"api_{operation}_failures_total"] = self._failures.get(operation, 0)
                if durations:
                    ordered = sorted(durations)
                    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
                    payload[f"api_{operation}_avg_latency_ms"] = sum(durations) / len(durations)
                    payload[f"api_{operation}_p95_latency_ms"] = ordered[p95_index]
                    payload[f"api_{operation}_max_latency_ms"] = max(durations)
        return payload


def _split_keys(raw: str) -> list[str]:
    return [key.strip() for key in raw.split(",") if key.strip()]


def _cache_from_env() -> HotMemoryCache | RedisHotMemoryCache | None:
    redis_url = os.environ.get("WAVEMIND_REDIS_URL")
    ttl_seconds = float(os.environ.get("WAVEMIND_CACHE_TTL_SECONDS", "60") or "60")
    if redis_url:
        return RedisHotMemoryCache.from_url(
            redis_url,
            prefix=os.environ.get("WAVEMIND_REDIS_PREFIX", "wavemind:hot"),
            ttl_seconds=ttl_seconds,
        )
    capacity = int(os.environ.get("WAVEMIND_CACHE_CAPACITY", "0") or "0")
    if capacity <= 0:
        return None
    return HotMemoryCache(capacity=capacity, ttl_seconds=ttl_seconds)


def _vector_cache_from_env() -> QueryVectorCache | RedisQueryVectorCache | None:
    redis_url = os.environ.get("WAVEMIND_VECTOR_CACHE_REDIS_URL")
    ttl_seconds = float(os.environ.get("WAVEMIND_VECTOR_CACHE_TTL_SECONDS", "300") or "300")
    if redis_url:
        return RedisQueryVectorCache.from_url(
            redis_url,
            prefix=os.environ.get("WAVEMIND_VECTOR_CACHE_REDIS_PREFIX", "wavemind:qvec"),
            ttl_seconds=ttl_seconds,
        )
    capacity = int(os.environ.get("WAVEMIND_VECTOR_CACHE_CAPACITY", "0") or "0")
    if capacity <= 0:
        return None
    return QueryVectorCache(capacity=capacity, ttl_seconds=ttl_seconds)


def _memory_os_lock(
    *,
    namespace: str | None,
    prefix: str,
    ttl_seconds: int,
    cache: HotMemoryCache | RedisHotMemoryCache | None,
) -> RedisMemoryOSLock | None:
    key = f"{prefix.rstrip(':')}:{namespace or 'all'}"
    if isinstance(cache, RedisHotMemoryCache):
        return RedisMemoryOSLock(cache.client, key=key, ttl_seconds=ttl_seconds)
    redis_url = os.environ.get("WAVEMIND_MEMORY_OS_LOCK_REDIS_URL") or os.environ.get(
        "WAVEMIND_REDIS_URL"
    )
    if not redis_url:
        return None
    return RedisMemoryOSLock.from_url(redis_url, key=key, ttl_seconds=ttl_seconds)


def _rate_limiter_from_env() -> InMemoryRateLimiter | RedisRateLimiter | None:
    raw_limit = os.environ.get("WAVEMIND_RATE_LIMIT_PER_MINUTE", "0")
    limit = int(raw_limit or "0")
    if limit <= 0:
        return None
    redis_url = os.environ.get("WAVEMIND_RATE_LIMIT_REDIS_URL")
    if redis_url:
        return RedisRateLimiter.from_url(
            redis_url,
            limit,
            prefix=os.environ.get("WAVEMIND_RATE_LIMIT_REDIS_PREFIX", "wavemind:rate"),
            fail_open=os.environ.get("WAVEMIND_RATE_LIMIT_FAIL_OPEN", "0").lower()
            in {"1", "true", "yes", "on"},
        )
    return InMemoryRateLimiter(limit)


def _invalidate_cache(app: FastAPI, namespace: str | None) -> int:
    cache = getattr(app.state, "cache", None)
    if cache is None:
        return 0
    try:
        if namespace is None:
            size = cache.stats().size
            cache.clear()
            return size
        return cache.invalidate_namespace(namespace)
    except Exception:
        logger.warning("failed to invalidate API cache namespace=%s", namespace, exc_info=True)
        return 0


def _metric_key(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")


def _rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return f"key:{authorization[7:].strip()}"
    api_key = request.headers.get("x-api-key")
    if api_key:
        return f"key:{api_key}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def require_role(role: str):
    def dependency(request: Request) -> None:
        request.app.state.auth.check(request, role)

    return dependency


class RememberRequest(BaseModel):
    text: str
    namespace: str = "default"
    tags: list[str] = Field(default_factory=list)
    ttl_seconds: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    priority: float = 1.0


class RememberResponse(BaseModel):
    id: int


class QueryRequest(BaseModel):
    text: str = Field(validation_alias=AliasChoices("text", "query"))
    namespace: str = "default"
    top_k: int = 3
    tags: list[str] = Field(default_factory=list)
    min_score: float | None = None


class QueryResultResponse(BaseModel):
    id: int
    text: str
    score: float
    vector_score: float
    field_score: float
    graph_score: float
    namespace: str
    tags: list[str]
    metadata: dict[str, Any]


class QueryResponse(BaseModel):
    results: list[QueryResultResponse]


class ForgetRequest(BaseModel):
    id: int | None = None
    text: str | None = None
    namespace: str | None = None


class ForgetResponse(BaseModel):
    deleted: int


class ImportRequest(BaseModel):
    path: str
    namespace: str = "default"
    tags: list[str] = Field(default_factory=list)
    max_chars: int = 1000
    overlap: int = 120


class ImportResponse(BaseModel):
    ids: list[int]


class BackupRequest(BaseModel):
    path: str
    keep_last: int | None = Field(default=None, ge=0)
    prefix: str = "wavemind"


class BackupResponse(BaseModel):
    path: str


class MemoryExportRequest(BaseModel):
    namespace: str
    limit: int = Field(default=1000, ge=0, le=100000)
    include_expired: bool = False
    tags: list[str] = Field(default_factory=list)
    include_tombstones: bool = False
    tombstone_limit: int = Field(default=10000, ge=0, le=100000)


class MemoryExportRecordResponse(BaseModel):
    id: int
    text: str
    namespace: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: float
    updated_at: float
    expires_at: float | None = None
    priority: float
    access_count: int


class MemoryTombstoneResponse(BaseModel):
    id: int
    created_at: float
    record_keys: list[str]
    texts: list[str]


class MemoryExportResponse(BaseModel):
    records: list[MemoryExportRecordResponse]
    tombstones: list[MemoryTombstoneResponse] = Field(default_factory=list)


class MemoryTombstoneRequest(BaseModel):
    namespace: str
    record_keys: list[str] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)


class MemoryTombstoneWriteResponse(BaseModel):
    id: int


class NamespaceDeltaExportRequest(BaseModel):
    namespace: str = "default"
    since: float | None = None
    limit: int | None = Field(default=None, ge=0, le=100000)


class NamespaceDeltaImportRequest(BaseModel):
    delta: dict[str, Any]
    namespace: str | None = None


class NamespaceDeltaImportResponse(BaseModel):
    namespace: str
    imported_records: int = 0
    skipped_records: int = 0
    deleted_records: int = 0
    imported_tombstones: int = 0
    failed_nodes: dict[str, str] = Field(default_factory=dict)
    ok: bool


class AuditEventResponse(BaseModel):
    id: int
    created_at: float
    action: str
    namespace: str | None
    memory_id: int | None
    metadata: dict[str, Any]


class AuditResponse(BaseModel):
    events: list[AuditEventResponse]


class ObservabilityResponse(BaseModel):
    enabled: bool
    exporter: str
    service_name: str
    fastapi_instrumented: bool = False
    reason: str | None = None


class CachePrewarmRequest(BaseModel):
    namespace: str | None = None
    audit_limit: int = Field(default=256, ge=0, le=10000)
    max_queries: int = Field(default=32, ge=0, le=1000)
    min_frequency: int = Field(default=1, ge=1)
    top_k: int = Field(default=3, ge=1, le=100)
    min_score: float | None = None


class CachePrewarmResponse(BaseModel):
    scanned_events: int
    candidates: int
    warmed: int
    skipped: int
    errors: dict[str, str]
    ok: bool


class MemoryOSRequest(BaseModel):
    namespace: str | None = None
    audit_limit: int = Field(default=512, ge=0, le=10000)
    max_hot_queries: int = Field(default=32, ge=0, le=1000)
    min_frequency: int = Field(default=2, ge=1)
    top_k: int = Field(default=3, ge=1, le=100)
    min_score: float | None = None
    consolidate_steps: int = Field(default=10, ge=0, le=10000)
    consolidate_concepts: bool = True
    concept_seed_text: str | None = None
    min_concept_energy: float = Field(default=0.02, ge=0.0)
    min_concept_size: int = Field(default=2, ge=2)
    max_concepts: int = Field(default=3, ge=0, le=100)
    concept_priority: float = Field(default=6.0, ge=0.0)
    predict_priorities: bool = True
    max_priority_predictions: int = Field(default=16, ge=0, le=1000)
    priority_boost_per_hit: float = Field(default=0.05, ge=0.0, le=10.0)
    max_priority_boost: float = Field(default=0.5, ge=0.0, le=100.0)
    adaptive_forgetting: bool = True
    forgetting_min_age_seconds: float = Field(default=7 * 24 * 60 * 60, ge=0.0)
    forgetting_max_memories: int = Field(default=32, ge=0, le=100000)
    forgetting_max_access_count: int = Field(default=0, ge=0)
    forgetting_priority_decay: float = Field(default=0.10, ge=0.0, le=10.0)
    forgetting_min_priority: float = Field(default=0.0, ge=0.0, le=100.0)
    predictive_prefetch: bool = True
    max_predictive_queries: int = Field(default=16, ge=0, le=1000)
    predictive_terms_per_hot_query: int = Field(default=3, ge=0, le=50)
    rebuild_unhealthy_index: bool = True
    memory_pressure_threshold: int = Field(default=50000, ge=0)
    architecture_advice: bool = True
    target_memories: int | None = Field(default=None, ge=0)
    target_p99_ms: float = Field(default=100.0, ge=0.0)
    observed_p99_ms: float | None = Field(default=None, ge=0.0)
    namespace_count: int | None = Field(default=None, ge=0)
    node_count: int | None = Field(default=None, ge=0)
    replication_factor: int = Field(default=3, ge=1)
    read_quorum: int = Field(default=1, ge=1)
    read_fanout: int | None = Field(default=None, ge=1)
    target_qps: float = Field(default=100.0, ge=0.0)
    deployment: str = "local"
    multimodal: bool = False
    lock_required: bool = False
    lock_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    lock_prefix: str = "wavemind:memory-os:lock"


class MemoryOSPlanRequest(BaseModel):
    namespace: str | None = None
    audit_limit: int = Field(default=512, ge=0, le=10000)
    max_hot_queries: int = Field(default=32, ge=0, le=1000)
    min_frequency: int = Field(default=2, ge=1)
    top_k: int = Field(default=3, ge=1, le=100)
    min_score: float | None = None
    target_memories: int | None = Field(default=None, ge=0)
    namespace_count: int | None = Field(default=None, ge=0)
    node_count: int | None = Field(default=None, ge=0)
    replication_factor: int = Field(default=3, ge=1)
    read_quorum: int = Field(default=1, ge=1)
    read_fanout: int | None = Field(default=None, ge=1)
    target_qps: float = Field(default=100.0, ge=0.0)
    target_p99_ms: float = Field(default=100.0, ge=0.0)
    observed_p99_ms: float | None = Field(default=None, ge=0.0)
    deployment: str = "local"
    cache_mode: str = "auto"
    multimodal: bool = False
    memory_pressure_threshold: int = Field(default=50000, ge=0)


class ScalePlanResponse(BaseModel):
    current_memories: int
    target_memories: int
    index: str
    vector_dim: int
    namespace: str | None
    latency_target_ms: float
    tier: str
    status: str
    recommended_index: str
    warnings: list[str]
    actions: list[str]


class ArchitectureRecommendationResponse(BaseModel):
    id: str
    severity: str
    title: str
    rationale: str
    action: str
    commands: list[str]
    docs: list[str]


class ArchitectureAdviceResponse(BaseModel):
    status: str
    production_ready: bool
    deployment: str
    namespace: str | None
    current_memories: int
    target_memories: int
    index: str
    vector_dim: int
    target_p99_ms: float
    observed_p99_ms: float | None
    namespace_count: int | None
    node_count: int | None
    replication_factor: int
    read_quorum: int
    read_fanout: int
    scale_plan: dict[str, Any]
    recommendations: list[ArchitectureRecommendationResponse]
    next_commands: list[str]


class ClusterPlanNodeRequest(BaseModel):
    id: str
    address: str
    zone: str | None = None
    weight: float = Field(default=1.0, gt=0.0)


class ClusterPlanRequest(BaseModel):
    namespaces: list[str] = Field(default_factory=list)
    namespace_prefix: str = "tenant"
    namespace_count: int = Field(default=0, ge=0, le=100_000)
    nodes: list[ClusterPlanNodeRequest] = Field(min_length=1)
    replication_factor: int = Field(default=2, ge=1)
    include_kubernetes: bool = False
    image: str = "wavemind:latest"
    storage_size: str = "20Gi"
    include_repair_cronjob: bool = False
    repair_schedule: str = "*/15 * * * *"
    repair_name: str = "wavemind-cluster-repair"
    repair_api_key_secret: str | None = None
    repair_api_key_secret_key: str = "api-key"
    repair_limit: int = Field(default=1000, ge=1)
    repair_include_expired: bool = False
    repair_tags: list[str] = Field(default_factory=list)


class ClusterAutoscaleRequest(BaseModel):
    namespaces: list[str] = Field(default_factory=list)
    namespace_prefix: str = "tenant"
    namespace_count: int = Field(default=0, ge=0, le=1_000_000)
    nodes: list[ClusterPlanNodeRequest] = Field(min_length=1)
    replication_factor: int = Field(default=3, ge=1)
    target_memories: int = Field(ge=0)
    max_memories_per_node: int = Field(default=1_000_000, gt=0)
    headroom: float = Field(default=0.70, gt=0.0, le=1.0)
    node_prefix: str = "node"
    address_template: str = "http://{node_id}:8000"
    zones: list[str] = Field(default_factory=list)
    max_moves: int = Field(default=100, ge=0, le=100_000)


class ConsolidateRequest(BaseModel):
    namespace: str | None = None
    seed_text: str | None = None
    min_energy: float = Field(default=0.05, ge=0.0)
    min_size: int = Field(default=2, ge=2)
    max_concepts: int = Field(default=3, ge=0, le=100)
    priority: float = Field(default=6.0, ge=0.0)


class ConsolidateResponse(BaseModel):
    concepts: list[dict[str, Any]]


class FeedbackRequest(BaseModel):
    id: int
    useful: bool = True
    strength: float = Field(default=0.25, ge=0.0, le=10.0)


def _remember_response_id(result: Any) -> int:
    if isinstance(result, int):
        return result
    primary_id = getattr(result, "primary_id", None)
    if primary_id is not None:
        return int(primary_id)
    writes = getattr(result, "writes", None)
    if isinstance(writes, dict) and writes:
        return int(next(iter(writes.values())))
    raise TypeError(f"Unsupported remember result: {type(result).__name__}")


def _forget_response_deleted(result: Any) -> int:
    if isinstance(result, int):
        return result
    writes = getattr(result, "writes", None)
    if isinstance(writes, dict) and writes:
        return max(int(value) for value in writes.values())
    return 0


def _require_delta_method(mind: Any, name: str):
    method = getattr(mind, name, None)
    if not callable(method):
        raise HTTPException(
            status_code=501,
            detail=f"Current memory backend does not support {name}",
        )
    return method


def _delta_import_response(report: Any) -> NamespaceDeltaImportResponse:
    return NamespaceDeltaImportResponse(
        namespace=str(getattr(report, "namespace", "default")),
        imported_records=int(getattr(report, "imported_records", 0)),
        skipped_records=int(getattr(report, "skipped_records", 0)),
        deleted_records=int(getattr(report, "deleted_records", 0)),
        imported_tombstones=int(getattr(report, "imported_tombstones", 0)),
        failed_nodes=dict(getattr(report, "failed_nodes", {}) or {}),
        ok=not bool(getattr(report, "failed_nodes", {}) or {}),
    )


@contextmanager
def _api_operation(app: FastAPI, operation: str) -> Iterator[None]:
    started = time.perf_counter()
    failed = False
    lock = getattr(app.state, "operation_lock", None)
    try:
        if lock is None:
            yield
        else:
            with lock:
                yield
    except Exception:
        failed = True
        raise
    finally:
        metrics = getattr(app.state, "operation_metrics", None)
        if metrics is not None:
            metrics.record(operation, (time.perf_counter() - started) * 1000.0, failed)


def _metrics_text(
    stats: dict[str, Any],
    operation_metrics: dict[str, float | int] | None = None,
) -> str:
    metric_names = {
        "active_memories": "wavemind_active_memories",
        "expired_memories": "wavemind_expired_memories",
        "total_memories": "wavemind_total_memories",
        "audit_events": "wavemind_audit_events",
        "field_energy": "wavemind_field_energy",
        "clusters": "wavemind_clusters",
        "graph_nodes": "wavemind_graph_nodes",
        "graph_edges": "wavemind_graph_edges",
        "graph_positive_edges": "wavemind_graph_positive_edges",
        "graph_negative_edges": "wavemind_graph_negative_edges",
        "graph_energy": "wavemind_graph_energy",
        "index_healthy": "wavemind_index_healthy",
        "index_expected_records": "wavemind_index_expected_records",
        "index_vector_records": "wavemind_index_vector_records",
        "index_missing_records": "wavemind_index_missing_records",
        "index_extra_records": "wavemind_index_extra_records",
    }
    lines = [
        "# HELP wavemind_active_memories Active non-expired memories.",
        "# TYPE wavemind_active_memories gauge",
    ]
    for key, metric in metric_names.items():
        value = stats.get(key)
        if isinstance(value, bool):
            value = 1 if value else 0
        if isinstance(value, (int, float)):
            lines.append(f"{metric} {value}")
    if operation_metrics:
        for key, value in sorted(operation_metrics.items()):
            if isinstance(value, (int, float)):
                metric = f"wavemind_{key}"
                if key.endswith("_requests_total"):
                    lines.append(f"# HELP {metric} API operation requests since process start.")
                    lines.append(f"# TYPE {metric} counter")
                elif key.endswith("_failures_total"):
                    lines.append(f"# HELP {metric} API operation failures since process start.")
                    lines.append(f"# TYPE {metric} counter")
                elif key.endswith("_latency_ms"):
                    lines.append(
                        f"# HELP {metric} API operation latency over recent in-process samples."
                    )
                    lines.append(f"# TYPE {metric} gauge")
                lines.append(f"{metric} {float(value):.6g}")
    return "\n".join(lines) + "\n"


def build_default_mind() -> WaveMind:
    db_path = (
        Path(os.environ["WAVEMIND_DB"])
        if "WAVEMIND_DB" in os.environ
        else Path.cwd() / "wavemind.sqlite3"
    )
    index_kind = os.environ.get("WAVEMIND_INDEX", "numpy")
    encoder_kind = os.environ.get("WAVEMIND_ENCODER", "hash").lower()
    score_threshold = float(os.environ.get("WAVEMIND_SCORE_THRESHOLD", "0.0"))
    encoder = create_text_encoder(
        kind=encoder_kind,
        vector_dim=int(os.environ.get("WAVEMIND_VECTOR_DIM", "384")),
        model_name=os.environ.get(
            "WAVEMIND_MODEL",
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        ),
    )
    return WaveMind(
        db_path=db_path,
        encoder=encoder,
        store_kind=os.environ.get("WAVEMIND_STORE"),
        postgres_dsn=os.environ.get("WAVEMIND_POSTGRES_DSN"),
        index_kind=index_kind,
        score_threshold=score_threshold,
        graph_weight=float(os.environ.get("WAVEMIND_GRAPH_WEIGHT", "0.0")),
        graph_steps=int(os.environ.get("WAVEMIND_GRAPH_STEPS", "2")),
        graph_expand_k=int(os.environ.get("WAVEMIND_GRAPH_EXPAND_K", "10")),
        audit_queries=os.environ.get("WAVEMIND_AUDIT_QUERIES", "0").lower()
        in {"1", "true", "yes", "on"},
    )


def create_app(mind: WaveMind | None = None) -> FastAPI:
    logging.basicConfig(level=os.environ.get("WAVEMIND_LOG_LEVEL", "INFO"))
    app = FastAPI(title="WaveMind", version=__version__)
    observability = configure_observability(service_version=__version__)
    app.state.observability = observability.as_dict()
    if observability.enabled:
        app.state.observability["fastapi_instrumented"] = instrument_fastapi_app(app)
    else:
        app.state.observability["fastapi_instrumented"] = False
    app.state.mind = mind or build_default_mind()
    app.state.auth = APIAuth.from_env()
    app.state.rate_limiter = _rate_limiter_from_env()
    app.state.cache = _cache_from_env()
    app.state.vector_cache = _vector_cache_from_env()
    app.state.operation_lock = (
        None
        if os.environ.get("WAVEMIND_API_SERIALIZE_OPERATIONS", "1").lower()
        in {"0", "false", "no", "off"}
        else Lock()
    )
    app.state.operation_metrics = APIOperationMetrics(
        max_samples=int(os.environ.get("WAVEMIND_METRICS_SAMPLE_SIZE", "512"))
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        limiter = request.app.state.rate_limiter
        if limiter is not None and not limiter.allow(request):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )
        return await call_next(request)

    @app.get("/studio", response_class=HTMLResponse, include_in_schema=False)
    def studio() -> HTMLResponse:
        return HTMLResponse(STUDIO_HTML)

    @app.get("/studio/state", dependencies=[Depends(require_role("read"))])
    def studio_state(
        namespace: str | None = None,
        limit: int = Query(default=200, ge=0, le=1000),
    ):
        return studio_snapshot(app.state.mind, namespace=namespace, limit=limit)

    @app.get("/studio/heatmap", dependencies=[Depends(require_role("read"))])
    def studio_heatmap(bins: int = Query(default=18, ge=4, le=48)):
        return field_heatmap(app.state.mind, bins=bins)

    @app.post("/studio/feedback", dependencies=[Depends(require_role("write"))])
    def studio_feedback(request: FeedbackRequest):
        accepted = app.state.mind.feedback(
            request.id,
            useful=request.useful,
            strength=request.strength,
        )
        if not accepted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"ok": True}

    @app.post("/remember", response_model=RememberResponse, dependencies=[Depends(require_role("write"))])
    def remember(request: RememberRequest) -> RememberResponse:
        with _api_operation(app, "remember"):
            remember_result = app.state.mind.remember(
                request.text,
                namespace=request.namespace,
                tags=request.tags,
                ttl_seconds=request.ttl_seconds,
                metadata=request.metadata,
                priority=request.priority,
            )
            id = _remember_response_id(remember_result)
            invalidated = _invalidate_cache(app, request.namespace)
        logger.info("remembered id=%s namespace=%s cache_invalidated=%s", id, request.namespace, invalidated)
        return RememberResponse(id=id)

    @app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_role("read"))])
    def query(request: QueryRequest) -> QueryResponse:
        with _api_operation(app, "query"):
            if app.state.cache is None:
                if app.state.vector_cache is None:
                    results = app.state.mind.query(
                        request.text,
                        namespace=request.namespace,
                        top_k=request.top_k,
                        tags=request.tags,
                        min_score=request.min_score,
                    )
                else:
                    results = query_with_vector_cache(
                        app.state.mind,
                        app.state.vector_cache,
                        request.text,
                        namespace=request.namespace,
                        top_k=request.top_k,
                        tags=request.tags,
                        min_score=request.min_score,
                    )
            else:
                results = query_with_cache(
                    app.state.mind,
                    app.state.cache,
                    request.text,
                    namespace=request.namespace,
                    top_k=request.top_k,
                    tags=request.tags,
                    min_score=request.min_score,
                    vector_cache=app.state.vector_cache,
                )
        return QueryResponse(
            results=[
                QueryResultResponse(
                    id=result.id,
                    text=result.text,
                    score=result.score,
                    vector_score=result.vector_score,
                    field_score=result.field_score,
                    graph_score=result.graph_score,
                    namespace=result.namespace,
                    tags=list(result.tags),
                    metadata=result.metadata,
                )
                for result in results
            ]
        )

    @app.delete("/forget", response_model=ForgetResponse, dependencies=[Depends(require_role("admin"))])
    def forget(
        request: ForgetRequest | None = Body(default=None),
        id: int | None = Query(default=None),
        text: str | None = Query(default=None),
        namespace: str | None = Query(default=None),
    ) -> ForgetResponse:
        payload = request or ForgetRequest(id=id, text=text, namespace=namespace)
        with _api_operation(app, "forget"):
            forget_result = app.state.mind.forget(
                id=payload.id,
                text=payload.text,
                namespace=payload.namespace,
            )
            deleted = _forget_response_deleted(forget_result)
            invalidated = _invalidate_cache(app, payload.namespace) if deleted else 0
        logger.info("forgot deleted=%s namespace=%s cache_invalidated=%s", deleted, payload.namespace, invalidated)
        return ForgetResponse(deleted=deleted)

    @app.get("/stats", dependencies=[Depends(require_role("read"))])
    def stats(namespace: str | None = None):
        return app.state.mind.stats(namespace=namespace)

    @app.post(
        "/memories/export",
        response_model=MemoryExportResponse,
        dependencies=[Depends(require_role("admin"))],
    )
    def export_memories(request: MemoryExportRequest) -> MemoryExportResponse:
        with _api_operation(app, "memories_export"):
            records = app.state.mind.store.list(
                namespace=request.namespace,
                include_expired=request.include_expired,
                tags=request.tags,
            )[: request.limit]
            tombstone_events = (
                app.state.mind.audit_events(
                    namespace=request.namespace,
                    action="distributed_tombstone",
                    limit=request.tombstone_limit,
                )
                if request.include_tombstones
                else []
            )
        return MemoryExportResponse(
            records=[
                MemoryExportRecordResponse(
                    id=record.id,
                    text=record.text,
                    namespace=record.namespace,
                    tags=list(record.tags),
                    metadata=record.metadata,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    expires_at=record.expires_at,
                    priority=record.priority,
                    access_count=record.access_count,
                )
                for record in records
            ],
            tombstones=[
                MemoryTombstoneResponse(
                    id=event.id,
                    created_at=event.created_at,
                    record_keys=[
                        str(key)
                        for key in event.metadata.get("record_keys", [])
                        if key is not None
                    ],
                    texts=[
                        str(text)
                        for text in event.metadata.get("texts", [])
                        if text is not None
                    ],
                )
                for event in tombstone_events
            ],
        )

    @app.post(
        "/memories/tombstone",
        response_model=MemoryTombstoneWriteResponse,
        dependencies=[Depends(require_role("admin"))],
    )
    def write_memory_tombstone(request: MemoryTombstoneRequest) -> MemoryTombstoneWriteResponse:
        if not request.record_keys and not request.texts:
            raise HTTPException(status_code=400, detail="Tombstone requires record_keys or texts.")
        with _api_operation(app, "memories_tombstone"):
            event_id = app.state.mind.store.log_audit_event(
                "distributed_tombstone",
                namespace=request.namespace,
                metadata={
                    "record_keys": sorted(set(request.record_keys)),
                    "texts": sorted(set(request.texts)),
                },
            )
        return MemoryTombstoneWriteResponse(id=event_id)

    @app.post("/namespace-delta/export", dependencies=[Depends(require_role("admin"))])
    def export_namespace_delta(request: NamespaceDeltaExportRequest) -> dict[str, Any]:
        exporter = _require_delta_method(app.state.mind, "export_namespace_delta")
        with _api_operation(app, "namespace_delta_export"):
            return dict(
                exporter(
                    request.namespace,
                    since=request.since,
                    limit=request.limit,
                )
            )

    @app.post(
        "/namespace-delta/import",
        response_model=NamespaceDeltaImportResponse,
        dependencies=[Depends(require_role("admin"))],
    )
    def import_namespace_delta(request: NamespaceDeltaImportRequest) -> NamespaceDeltaImportResponse:
        importer = _require_delta_method(app.state.mind, "import_namespace_delta")
        with _api_operation(app, "namespace_delta_import"):
            report = importer(request.delta, namespace=request.namespace)
            invalidated = _invalidate_cache(
                app,
                request.namespace or str(request.delta.get("namespace") or "default"),
            )
        logger.info(
            "imported namespace delta namespace=%s imported=%s tombstones=%s cache_invalidated=%s",
            getattr(report, "namespace", request.namespace),
            getattr(report, "imported_records", 0),
            getattr(report, "imported_tombstones", 0),
            invalidated,
        )
        return _delta_import_response(report)

    @app.get("/index/health", dependencies=[Depends(require_role("read"))])
    def index_health():
        return app.state.mind.index_health()

    @app.get("/scale-plan", response_model=ScalePlanResponse, dependencies=[Depends(require_role("read"))])
    def scale_plan(
        namespace: str | None = None,
        target_memories: int | None = Query(default=None, ge=0),
        latency_target_ms: float = Query(default=20.0, gt=0),
    ) -> ScalePlanResponse:
        plan = app.state.mind.scale_plan(
            target_memories=target_memories,
            namespace=namespace,
            latency_target_ms=latency_target_ms,
        )
        return ScalePlanResponse(**plan.as_dict())

    @app.get(
        "/architecture/advice",
        response_model=ArchitectureAdviceResponse,
        dependencies=[Depends(require_role("read"))],
    )
    @app.get(
        "/advise",
        response_model=ArchitectureAdviceResponse,
        dependencies=[Depends(require_role("read"))],
        include_in_schema=False,
    )
    def architecture_advice(
        namespace: str | None = None,
        target_memories: int | None = Query(default=None, ge=0),
        target_p99_ms: float = Query(default=100.0, gt=0),
        observed_p99_ms: float | None = Query(default=None, ge=0),
        namespace_count: int | None = Query(default=None, ge=0),
        node_count: int | None = Query(default=None, ge=0),
        replication_factor: int = Query(default=3, ge=1),
        read_quorum: int = Query(default=1, ge=1),
        read_fanout: int | None = Query(default=None, ge=1),
        target_qps: float = Query(default=100.0, gt=0),
        deployment: str = Query(default="local", pattern="^(local|staging|production)$"),
        multimodal: bool = False,
    ) -> ArchitectureAdviceResponse:
        stats = app.state.mind.stats(namespace=namespace)
        plan = app.state.mind.scale_plan(
            target_memories=target_memories,
            namespace=namespace,
            latency_target_ms=min(target_p99_ms, 100.0),
        )
        advice = advise_memory_architecture(
            stats,
            scale_plan=plan,
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
        return ArchitectureAdviceResponse(**advice.as_dict())

    @app.post("/cluster-plan", dependencies=[Depends(require_role("read"))])
    def cluster_plan(request: ClusterPlanRequest):
        namespaces = list(request.namespaces)
        namespaces.extend(
            f"{request.namespace_prefix}:{index}"
            for index in range(request.namespace_count)
        )
        plan = build_cluster_plan(
            namespaces=namespaces,
            nodes=[
                ClusterNode(
                    id=node.id,
                    address=node.address,
                    zone=node.zone,
                    weight=node.weight,
                )
                for node in request.nodes
            ],
            replication_factor=request.replication_factor,
        )
        payload = plan.as_dict()
        if request.include_kubernetes:
            payload["kubernetes"] = plan.kubernetes_manifest(
                image=request.image,
                storage_size=request.storage_size,
            )
        if request.include_repair_cronjob:
            payload["repair_cronjob"] = plan.kubernetes_repair_cronjob(
                image=request.image,
                schedule=request.repair_schedule,
                name=request.repair_name,
                api_key_secret=request.repair_api_key_secret,
                api_key_secret_key=request.repair_api_key_secret_key,
                repair_limit=request.repair_limit,
                include_expired=request.repair_include_expired,
                tags=tuple(request.repair_tags),
            )
        return payload

    @app.post("/cluster-autoscale-plan", dependencies=[Depends(require_role("read"))])
    def cluster_autoscale_plan(request: ClusterAutoscaleRequest):
        namespaces = list(request.namespaces)
        namespaces.extend(
            f"{request.namespace_prefix}:{index}"
            for index in range(request.namespace_count)
        )
        if not namespaces:
            raise HTTPException(
                status_code=400,
                detail="cluster-autoscale-plan requires namespaces or namespace_count",
            )
        plan = build_cluster_autoscale_plan(
            namespaces=namespaces,
            nodes=[
                ClusterNode(
                    id=node.id,
                    address=node.address,
                    zone=node.zone,
                    weight=node.weight,
                )
                for node in request.nodes
            ],
            replication_factor=request.replication_factor,
            target_memories=request.target_memories,
            max_memories_per_node=request.max_memories_per_node,
            headroom=request.headroom,
            node_prefix=request.node_prefix,
            address_template=request.address_template,
            zones=tuple(request.zones),
            max_moves=request.max_moves,
        )
        return plan.as_dict()

    @app.post("/index/rebuild", dependencies=[Depends(require_role("admin"))])
    def rebuild_index():
        with _api_operation(app, "index_rebuild"):
            return app.state.mind.rebuild_index()

    @app.post("/consolidate", response_model=ConsolidateResponse, dependencies=[Depends(require_role("write"))])
    def consolidate(request: ConsolidateRequest) -> ConsolidateResponse:
        with _api_operation(app, "consolidate"):
            concepts = app.state.mind.consolidate_concepts(
                namespace=request.namespace,
                seed_text=request.seed_text,
                min_energy=request.min_energy,
                min_size=request.min_size,
                max_concepts=request.max_concepts,
                priority=request.priority,
            )
        return ConsolidateResponse(concepts=concepts)

    @app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_role("read"))])
    def metrics(namespace: str | None = None) -> PlainTextResponse:
        operation_metrics = app.state.operation_metrics.snapshot()
        if app.state.cache is not None:
            cache_stats = app.state.cache.stats()
            operation_metrics.update(
                {
                    "cache_hits_total": cache_stats.hits,
                    "cache_misses_total": cache_stats.misses,
                    "cache_evictions_total": cache_stats.evictions,
                    "cache_size": cache_stats.size,
                    "cache_capacity": cache_stats.capacity,
                    "cache_hit_rate": cache_stats.hit_rate,
                }
            )
        if app.state.vector_cache is not None:
            vector_cache_stats = app.state.vector_cache.stats()
            operation_metrics.update(
                {
                    "vector_cache_hits_total": vector_cache_stats.hits,
                    "vector_cache_misses_total": vector_cache_stats.misses,
                    "vector_cache_evictions_total": vector_cache_stats.evictions,
                    "vector_cache_size": vector_cache_stats.size,
                    "vector_cache_capacity": vector_cache_stats.capacity,
                    "vector_cache_hit_rate": vector_cache_stats.hit_rate,
                }
            )
        if app.state.rate_limiter is not None:
            rate_limit_stats = app.state.rate_limiter.stats()
            operation_metrics.update(
                {
                    "rate_limit_allowed_total": rate_limit_stats.allowed,
                    "rate_limit_limited_total": rate_limit_stats.limited,
                    "rate_limit_total": rate_limit_stats.total,
                    "rate_limit_shared": 1 if rate_limit_stats.shared else 0,
                }
            )
        return PlainTextResponse(
            _metrics_text(
                app.state.mind.stats(namespace=namespace),
                operation_metrics,
            ),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/observability", response_model=ObservabilityResponse, dependencies=[Depends(require_role("admin"))])
    def observability() -> ObservabilityResponse:
        return ObservabilityResponse(**app.state.observability)

    @app.post("/cache/prewarm", response_model=CachePrewarmResponse, dependencies=[Depends(require_role("admin"))])
    def cache_prewarm(request: CachePrewarmRequest) -> CachePrewarmResponse:
        if app.state.cache is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cache is disabled. Set WAVEMIND_CACHE_CAPACITY > 0 "
                    "or WAVEMIND_REDIS_URL."
                ),
            )
        with _api_operation(app, "cache_prewarm"):
            report = CachePrewarmWorker(app.state.mind, app.state.cache).run_once(
                namespace=request.namespace,
                audit_limit=request.audit_limit,
                max_queries=request.max_queries,
                min_frequency=request.min_frequency,
                top_k=request.top_k,
                min_score=request.min_score,
            )
        return CachePrewarmResponse(**report.as_dict())

    @app.post("/memory-os/plan", dependencies=[Depends(require_role("admin"))])
    def memory_os_plan(request: MemoryOSPlanRequest):
        with _api_operation(app, "memory_os_plan"):
            plan = MemoryOSScheduler(app.state.mind).plan(
                namespace=request.namespace,
                audit_limit=request.audit_limit,
                max_hot_queries=request.max_hot_queries,
                min_frequency=request.min_frequency,
                top_k=request.top_k,
                min_score=request.min_score,
                target_memories=request.target_memories,
                namespace_count=request.namespace_count,
                node_count=request.node_count,
                replication_factor=request.replication_factor,
                read_quorum=request.read_quorum,
                read_fanout=request.read_fanout,
                target_qps=request.target_qps,
                target_p99_ms=request.target_p99_ms,
                observed_p99_ms=request.observed_p99_ms,
                deployment=request.deployment,
                cache_mode=request.cache_mode,
                multimodal=request.multimodal,
                memory_pressure_threshold=request.memory_pressure_threshold,
            )
        return plan.as_dict()

    @app.post("/memory-os/run", dependencies=[Depends(require_role("admin"))])
    def memory_os_run(request: MemoryOSRequest):
        with _api_operation(app, "memory_os"):
            lock = _memory_os_lock(
                namespace=request.namespace,
                prefix=request.lock_prefix,
                ttl_seconds=request.lock_ttl_seconds,
                cache=app.state.cache,
            )
            report = MemoryOSWorker(app.state.mind, app.state.cache).run_once(
                namespace=request.namespace,
                audit_limit=request.audit_limit,
                max_hot_queries=request.max_hot_queries,
                min_frequency=request.min_frequency,
                top_k=request.top_k,
                min_score=request.min_score,
                consolidate_steps=request.consolidate_steps,
                consolidate_concepts=request.consolidate_concepts,
                concept_seed_text=request.concept_seed_text,
                min_concept_energy=request.min_concept_energy,
                min_concept_size=request.min_concept_size,
                max_concepts=request.max_concepts,
                concept_priority=request.concept_priority,
                predict_priorities=request.predict_priorities,
                max_priority_predictions=request.max_priority_predictions,
                priority_boost_per_hit=request.priority_boost_per_hit,
                max_priority_boost=request.max_priority_boost,
                adaptive_forgetting=request.adaptive_forgetting,
                forgetting_min_age_seconds=request.forgetting_min_age_seconds,
                forgetting_max_memories=request.forgetting_max_memories,
                forgetting_max_access_count=request.forgetting_max_access_count,
                forgetting_priority_decay=request.forgetting_priority_decay,
                forgetting_min_priority=request.forgetting_min_priority,
                predictive_prefetch=request.predictive_prefetch,
                max_predictive_queries=request.max_predictive_queries,
                predictive_terms_per_hot_query=request.predictive_terms_per_hot_query,
                rebuild_unhealthy_index=request.rebuild_unhealthy_index,
                memory_pressure_threshold=request.memory_pressure_threshold,
                architecture_advice=request.architecture_advice,
                target_memories=request.target_memories,
                target_p99_ms=request.target_p99_ms,
                observed_p99_ms=request.observed_p99_ms,
                namespace_count=request.namespace_count,
                node_count=request.node_count,
                replication_factor=request.replication_factor,
                read_quorum=request.read_quorum,
                read_fanout=request.read_fanout,
                target_qps=request.target_qps,
                deployment=request.deployment,
                multimodal=request.multimodal,
                lock=lock,
                lock_required=request.lock_required,
            )
        return report.as_dict()

    @app.get("/audit", response_model=AuditResponse, dependencies=[Depends(require_role("admin"))])
    def audit(
        namespace: str | None = None,
        action: str | None = None,
        limit: int = Query(default=100, ge=0, le=1000),
    ) -> AuditResponse:
        events = app.state.mind.audit_events(
            namespace=namespace,
            action=action,
            limit=limit,
        )
        return AuditResponse(
            events=[
                AuditEventResponse(
                    id=int(event.id),
                    created_at=event.created_at,
                    action=event.action,
                    namespace=event.namespace,
                    memory_id=event.memory_id,
                    metadata=event.metadata,
                )
                for event in events
            ]
        )

    @app.post("/import", response_model=ImportResponse, dependencies=[Depends(require_role("write"))])
    def batch_import(request: ImportRequest) -> ImportResponse:
        with _api_operation(app, "import"):
            ids = import_path(
                request.path,
                app.state.mind,
                namespace=request.namespace,
                tags=request.tags,
                max_chars=request.max_chars,
                overlap=request.overlap,
            )
        return ImportResponse(ids=ids)

    @app.post("/backup", response_model=BackupResponse, dependencies=[Depends(require_role("admin"))])
    def backup(request: BackupRequest) -> BackupResponse:
        with _api_operation(app, "backup"):
            path = app.state.mind.save(
                request.path,
                keep_last=request.keep_last,
                backup_prefix=request.prefix,
            )
        return BackupResponse(path=str(path))

    return app
