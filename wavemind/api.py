from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
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
from .experience import (
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
    experience_from_trajectory,
    parse_tool_trajectory,
)
from .experience_compiler import ExperienceCompiler
from .experience_runtime import (
    AgentEventKind,
    AgentExperienceEvent,
    AgentExperienceRuntime,
    OutcomeVerification,
    VerificationSource,
)
from .experience_portability import (
    export_experience_bundle,
    import_experience_bundle,
)
from .importers import import_path
from .jobs import (
    CachePrewarmWorker,
    HotMemoryCache,
    MemoryOSScheduler,
    MemoryOSWorker,
    QueryVectorCache,
    RedisHotMemoryCache,
    RedisMemoryOSJobGuard,
    RedisMemoryOSLock,
    RedisQueryVectorCache,
    query_with_cache,
    query_with_vector_cache,
)
from .observability import configure_observability, instrument_fastapi_app
from .product_backup import create_rotating_product_backup
from .memory_firewall import (
    FirewallContext,
    MemoryFirewall,
    MemoryFirewallPolicy,
)
from .studio import STUDIO_HTML, field_heatmap, studio_snapshot


logger = logging.getLogger("wavemind.api")
ROLE_LEVELS = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class APIPrincipal:
    identity: str
    role: str
    namespace_prefixes: tuple[str, ...]

    def allows_namespace(self, namespace: str) -> bool:
        selected = namespace.strip()
        return any(
            prefix == "*" or selected.startswith(prefix.removesuffix("*"))
            for prefix in self.namespace_prefixes
        )


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
    def __init__(self, principals: dict[str, APIPrincipal]):
        self.principals = principals

    @classmethod
    def from_env(cls) -> "APIAuth":
        principals: dict[str, APIPrincipal] = {}
        raw_principals = os.environ.get("WAVEMIND_API_PRINCIPALS", "").strip()
        if raw_principals:
            try:
                payload = json.loads(raw_principals)
            except json.JSONDecodeError as exc:
                raise ValueError("WAVEMIND_API_PRINCIPALS must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("WAVEMIND_API_PRINCIPALS must be a JSON object")
            for key, raw in payload.items():
                if not isinstance(key, str) or not key.strip() or not isinstance(raw, dict):
                    raise ValueError("WAVEMIND_API_PRINCIPALS entries must map keys to objects")
                identity = str(raw.get("identity") or "").strip()
                role = str(raw.get("role") or "").strip().lower()
                prefixes = raw.get("namespace_prefixes")
                if not identity or role not in ROLE_LEVELS:
                    raise ValueError("API principals require identity and a valid role")
                if not isinstance(prefixes, list) or not prefixes:
                    raise ValueError("API principals require namespace_prefixes")
                normalized = tuple(
                    str(prefix).strip() for prefix in prefixes if str(prefix).strip()
                )
                if not normalized:
                    raise ValueError("API principal namespace_prefixes must not be empty")
                principals[key] = APIPrincipal(identity, role, normalized)
        for env_name, role in (
            ("WAVEMIND_READ_KEYS", "read"),
            ("WAVEMIND_WRITE_KEYS", "write"),
            ("WAVEMIND_API_KEYS", "admin"),
            ("WAVEMIND_ADMIN_KEYS", "admin"),
        ):
            for key in _split_keys(os.environ.get(env_name, "")):
                principals.setdefault(
                    key,
                    APIPrincipal(
                        identity=f"legacy:{role}",
                        role=role,
                        namespace_prefixes=("*",),
                    ),
                )
        return cls(principals)

    @property
    def enabled(self) -> bool:
        return bool(self.principals)

    def principal_for_request(self, request: Request) -> APIPrincipal | None:
        key = request.headers.get("x-api-key")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        if not key:
            return None
        return self.principals.get(key)

    def check(self, request: Request, required_role: str) -> APIPrincipal:
        if not self.enabled:
            return APIPrincipal("local", "admin", ("*",))
        principal = self.principal_for_request(request)
        if principal is None:
            raise HTTPException(status_code=401, detail="Missing or invalid API key")
        if ROLE_LEVELS[principal.role] < ROLE_LEVELS[required_role]:
            raise HTTPException(status_code=403, detail="Insufficient API key role")
        return principal

    def check_namespaces(
        self,
        principal: APIPrincipal,
        namespaces: set[str],
    ) -> None:
        if principal.namespace_prefixes == ("*",):
            return
        if not namespaces:
            raise HTTPException(
                status_code=403,
                detail="An explicit authorized namespace is required",
            )
        if not all(principal.allows_namespace(namespace) for namespace in namespaces):
            raise HTTPException(status_code=403, detail="Namespace access denied")


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


def _memory_os_job_guard(
    *,
    idempotency_key: str | None,
    prefix: str,
    ttl_seconds: int,
    lock: RedisMemoryOSLock | None,
) -> RedisMemoryOSJobGuard | None:
    if not idempotency_key:
        return None
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    key = f"{prefix.rstrip(':')}:{digest}"
    if lock is not None:
        return RedisMemoryOSJobGuard(
            lock.client,
            key=key,
            ttl_seconds=ttl_seconds,
        )
    redis_url = os.environ.get("WAVEMIND_MEMORY_OS_LOCK_REDIS_URL") or os.environ.get(
        "WAVEMIND_REDIS_URL"
    )
    if not redis_url:
        return None
    return RedisMemoryOSJobGuard.from_url(
        redis_url,
        key=key,
        ttl_seconds=ttl_seconds,
    )


def _memory_os_insights_payload(
    mind: WaveMind,
    *,
    namespace: str | None,
    audit_limit: int,
    max_hot_queries: int,
    min_frequency: int,
    top_k: int,
    min_score: float | None,
    target_memories: int | None,
    namespace_count: int | None,
    node_count: int | None,
    replication_factor: int,
    read_quorum: int,
    read_fanout: int | None,
    target_qps: float,
    target_p99_ms: float,
    observed_p99_ms: float | None,
    deployment: str,
    cache_mode: str,
    multimodal: bool,
    memory_pressure_threshold: int,
) -> dict[str, object]:
    """Build a read-only Memory OS dashboard payload.

    This intentionally uses the scheduler/preflight path and query-audit reads
    only. It must not call MemoryOSWorker.run_once(), because Studio should
    surface operator advice without mutating priorities, concepts, or TTL state.
    """

    worker = MemoryOSWorker(mind)
    events = worker._query_events(namespace=namespace, limit=audit_limit)
    hot_queries = worker._hot_queries(
        events,
        max_hot_queries=max_hot_queries,
        min_frequency=min_frequency,
    )
    plan = MemoryOSScheduler(mind).plan(
        namespace=namespace,
        audit_limit=audit_limit,
        max_hot_queries=max_hot_queries,
        min_frequency=min_frequency,
        top_k=top_k,
        min_score=min_score,
        target_memories=target_memories,
        namespace_count=namespace_count,
        node_count=node_count,
        replication_factor=replication_factor,
        read_quorum=read_quorum,
        read_fanout=read_fanout,
        target_qps=target_qps,
        target_p99_ms=target_p99_ms,
        observed_p99_ms=observed_p99_ms,
        deployment=deployment,
        cache_mode=cache_mode,
        multimodal=multimodal,
        memory_pressure_threshold=memory_pressure_threshold,
    )
    plan_payload = plan.as_dict()
    suggestions = _memory_os_dashboard_suggestions(plan_payload, hot_queries)
    return {
        "namespace": namespace,
        "read_only": True,
        "status": plan_payload["status"],
        "deployment": plan_payload["deployment"],
        "effective_cache_mode": plan_payload["effective_cache_mode"],
        "active_memories": plan_payload["active_memories"],
        "target_memories": plan_payload["target_memories"],
        "hot_query_count": len(hot_queries),
        "hot_queries": [query.as_dict() for query in hot_queries],
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
        "policy_manifest": plan_payload["policy_manifest"],
        "policy_history": plan_payload["policy_history"],
        "execution_plan": plan_payload["execution_plan"],
        "architecture_advice": plan_payload["architecture_advice"],
        "required_infrastructure": plan_payload["required_infrastructure"],
        "recommendations": plan_payload["recommendations"],
        "enabled_task_ids": plan_payload["enabled_task_ids"],
        "plan": plan_payload,
        "ok": plan_payload["ok"],
    }


def _memory_os_dashboard_suggestions(
    plan_payload: dict[str, object],
    hot_queries: list[Any],
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
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
            {
                "id": id,
                "severity": _memory_os_dashboard_severity(severity),
                "title": title,
                "rationale": rationale,
                "action": action,
                "evidence": evidence or {},
            }
        )

    namespace = plan_payload.get("namespace") or "all namespaces"
    if hot_queries:
        add(
            "hot-query-prewarm-candidate",
            "ok",
            "Hot recall paths are visible",
            "Query audit found repeated recalls that Memory OS can prewarm and learn from.",
            "Keep query audit enabled and schedule Memory OS or cache-prewarm for this namespace.",
            {
                "namespace": namespace,
                "hot_queries": len(hot_queries),
                "top_query": hot_queries[0].query,
                "top_frequency": hot_queries[0].frequency,
            },
        )
    else:
        add(
            "query-audit-required",
            "watch",
            "Collect query audit traffic",
            "Memory OS needs query audit events before it can identify hot memories, follow-up queries, or priority signals.",
            "Enable query audit in staging and rerun the insight check after real user traffic.",
            {"namespace": namespace},
        )

    policy_manifest = plan_payload.get("policy_manifest") or {}
    if isinstance(policy_manifest, dict):
        for decision in policy_manifest.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            decision_id = str(decision.get("id") or "policy")
            strategy = str(decision.get("strategy") or decision_id)
            add(
                f"policy:{decision_id}",
                str(decision.get("status") or "watch"),
                _humanize_slug(strategy),
                str(decision.get("rationale") or "Memory OS policy preflight produced a decision."),
                str(decision.get("action") or "Review the Memory OS policy manifest."),
                dict(decision.get("evidence") or {}),
            )

    architecture = plan_payload.get("architecture_advice") or {}
    if isinstance(architecture, dict):
        for recommendation in architecture.get("recommendations") or []:
            if not isinstance(recommendation, dict):
                continue
            severity = str(recommendation.get("severity") or "watch")
            if severity == "ok":
                continue
            rec_id = str(recommendation.get("id") or "architecture")
            add(
                f"architecture:{rec_id}",
                severity,
                str(recommendation.get("title") or _humanize_slug(rec_id)),
                str(
                    recommendation.get("rationale")
                    or "Architecture advisor raised a production recommendation."
                ),
                str(
                    recommendation.get("action")
                    or "Review architecture advisor output before scaling."
                ),
                {
                    "namespace": namespace,
                    "source": "architecture_advisor",
                    "recommendation_id": rec_id,
                },
            )

    execution = plan_payload.get("execution_plan") or {}
    if isinstance(execution, dict):
        warnings = [str(item) for item in execution.get("warnings") or []]
        for warning in warnings:
            add(
                f"execution-warning:{warning}",
                "action_required",
                _humanize_slug(warning),
                "The Memory OS execution plan requires an operator check before production scheduling.",
                "Resolve the execution-plan warning or keep this worker disabled for production.",
                {
                    "namespace": namespace,
                    "deployment": plan_payload.get("deployment"),
                    "warning": warning,
                },
            )
        if execution.get("safe_to_run") is True:
            add(
                "execution-plan-safe",
                "ok",
                "Execution plan is schedulable",
                "The read-only planner found no blocked Memory OS tasks.",
                "Use the generated commands in your scheduler or Kubernetes Memory OS CronJob.",
                {
                    "namespace": namespace,
                    "enabled_task_ids": list(execution.get("enabled_task_ids") or []),
                    "singleton_task_ids": list(execution.get("singleton_task_ids") or []),
                },
            )

    return suggestions


def _memory_os_dashboard_severity(value: str) -> str:
    normalized = str(value or "watch").lower()
    if normalized in {"ok", "watch", "action_required", "architecture_required"}:
        return normalized
    if normalized in {"required", "error", "failed", "fail", "blocked"}:
        return "action_required"
    return "watch"


def _humanize_slug(value: str) -> str:
    text = str(value or "").replace("_", "-").replace(":", "-")
    words = [word for word in text.split("-") if word]
    if not words:
        return "Memory OS recommendation"
    return " ".join(word.capitalize() for word in words)


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


def _collect_namespace_values(value: Any, namespaces: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "namespace" and isinstance(item, str) and item.strip():
                namespaces.add(item.strip())
            else:
                _collect_namespace_values(item, namespaces)
    elif isinstance(value, list):
        for item in value:
            _collect_namespace_values(item, namespaces)


async def _request_namespaces(request: Request) -> set[str]:
    namespaces = {
        value.strip()
        for value in request.query_params.getlist("namespace")
        if value.strip()
    }
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except (ValueError, json.JSONDecodeError):
                payload = None
            _collect_namespace_values(payload, namespaces)
    return namespaces


def require_role(role: str):
    async def dependency(request: Request) -> None:
        auth = request.app.state.auth
        principal = auth.check(request, role)
        auth.check_namespaces(principal, await _request_namespaces(request))
        request.state.wavemind_principal = principal

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


class RememberBatchRequest(BaseModel):
    items: list[RememberRequest] = Field(default_factory=list)


class RememberBatchItemResponse(BaseModel):
    index: int
    id: int
    text: str
    namespace: str


class RememberBatchResponse(BaseModel):
    count: int
    cache_invalidated: int = 0
    items: list[RememberBatchItemResponse]


class QueryRequest(BaseModel):
    text: str = Field(validation_alias=AliasChoices("text", "query"))
    namespace: str = "default"
    top_k: int = 3
    tags: list[str] = Field(default_factory=list)
    min_score: float | None = None
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


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


class QueryBatchRequest(BaseModel):
    queries: list[QueryRequest] = Field(default_factory=list)


class QueryBatchItemResponse(BaseModel):
    index: int
    text: str
    namespace: str
    results: list[QueryResultResponse]


class QueryBatchResponse(BaseModel):
    count: int
    items: list[QueryBatchItemResponse]


class ForgetRequest(BaseModel):
    id: int | None = None
    text: str | None = None
    namespace: str | None = None


class ForgetResponse(BaseModel):
    deleted: int


class ForgetBatchRequest(BaseModel):
    items: list[ForgetRequest] = Field(default_factory=list)


class ForgetBatchItemResponse(BaseModel):
    index: int
    namespace: str | None = None
    deleted: int


class ForgetBatchResponse(BaseModel):
    count: int
    deleted: int
    cache_invalidated: int = 0
    items: list[ForgetBatchItemResponse]


class FeedbackRequest(BaseModel):
    id: int
    namespace: str | None = None
    useful: bool = True
    strength: float = Field(default=0.25, ge=0.0, le=10.0)
    query: str | None = None
    reason: str | None = None


class FeedbackResponse(BaseModel):
    ok: bool
    id: int
    namespace: str
    priority: float
    access_count: int
    cache_invalidated: int = 0


class FeedbackBatchRequest(BaseModel):
    namespace: str | None = None
    items: list[FeedbackRequest] = Field(min_length=1, max_length=10000)


class FeedbackBatchItemResponse(BaseModel):
    ok: bool
    id: int | str | None
    namespace: str | None = None
    priority: float | None = None
    access_count: int | None = None
    error: str | None = None


class FeedbackBatchResponse(BaseModel):
    ok: bool
    accepted: int
    rejected: int
    cache_invalidated: int = 0
    results: list[FeedbackBatchItemResponse]


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


class MemoryTombstoneBatchRequest(BaseModel):
    items: list[MemoryTombstoneRequest] = Field(default_factory=list)


class MemoryTombstoneBatchItemResponse(BaseModel):
    index: int
    namespace: str
    id: int


class MemoryTombstoneBatchWriteResponse(BaseModel):
    count: int
    items: list[MemoryTombstoneBatchItemResponse]


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


class MemoryExplanationResponse(BaseModel):
    schema_name: str = Field(
        default="wavemind.memory_explanation.v1",
        validation_alias="schema",
        serialization_alias="schema",
    )
    id: int
    namespace: str
    text: str
    tags: list[str]
    metadata: dict[str, Any]
    provenance: dict[str, Any]
    created_at: float
    updated_at: float
    expires_at: float | None
    priority: float
    access_count: int
    audit_events: list[AuditEventResponse]


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
    transition_prefetch_window_seconds: float = Field(default=15 * 60, ge=0.0)
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
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=512)
    idempotency_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    idempotency_prefix: str = "wavemind:memory-os:job"


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


class ExperiencePacketRequest(BaseModel):
    query: str = Field(min_length=1)
    namespace: str = Field(default="default", min_length=1)
    token_budget: int = Field(default=800, ge=32)
    top_k: int = Field(default=8, ge=1, le=100)
    domains: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    include_canary: bool = False


class ExperienceTrajectoryRequest(BaseModel):
    payload: Any
    provider: str | None = None
    namespace: str = Field(default="default", min_length=1)
    trajectory_id: str | None = None
    trust: str = TrustClass.TOOL_OUTPUT.value
    status: str = ExperienceStatus.SHADOW.value
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExperienceBundleRequest(BaseModel):
    namespace: str | None = None


class ExperienceBundleImportRequest(BaseModel):
    bundle: dict[str, Any]


class ExperienceRuntimeStartRequest(BaseModel):
    query: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    namespace: str = Field(default="default", min_length=1)
    session_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_budget: int = Field(default=400, ge=32)
    top_k: int = Field(default=3, ge=1, le=100)
    canary: bool = False


class ExperienceRuntimeEventRequest(BaseModel):
    id: str = Field(min_length=1)
    namespace: str = Field(default="default", min_length=1)
    run_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    occurred_at: float | None = None
    session_id: str | None = None
    task_id: str | None = None
    parent_event_id: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExperienceRuntimeVerifyRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1)
    evidence_id: str = Field(min_length=1)
    source: str
    verifier: str = Field(min_length=1)
    success: bool
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    applied_experience_ids: list[str] = Field(default_factory=list)


class ExperienceRuntimeInterventionRequest(BaseModel):
    query: str = Field(min_length=1)
    namespace: str = Field(default="default", min_length=1)
    run_id: str | None = None
    task_id: str | None = None
    domains: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    token_budget: int = Field(default=400, ge=32)
    top_k: int = Field(default=3, ge=1, le=100)
    canary: bool = False


class ExperienceRuntimeLifecycleRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1)
    reason: str = Field(min_length=1)
    evidence_id: str | None = None
    score: float = Field(default=1.0, ge=0.0, le=1.0)


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
        recovery_journal_path=os.environ.get("WAVEMIND_RECOVERY_JOURNAL"),
        shared_store_refresh_seconds=float(
            os.environ.get("WAVEMIND_SHARED_STORE_REFRESH_SECONDS", "-1")
        ),
    )


def create_app(
    mind: WaveMind | None = None,
    *,
    experience_store: SQLiteExperienceStore | None = None,
) -> FastAPI:
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
    app.state.experience_store = experience_store
    app.state.experience_store_owned = False
    app.state.experience_compilers = {}
    app.state.experience_runtimes = {}
    app.state.experience_lock = Lock()

    def _experience_compiler(namespace: str) -> ExperienceCompiler:
        selected = namespace.strip()
        if not selected:
            raise HTTPException(status_code=422, detail="namespace must not be empty")
        with app.state.experience_lock:
            store = app.state.experience_store
            if store is None:
                store = SQLiteExperienceStore(
                    Path(
                        os.environ.get(
                            "WAVEMIND_EXPERIENCE_DB",
                            "wavemind-experience.db",
                        )
                    )
                )
                app.state.experience_store = store
                app.state.experience_store_owned = True
            compiler = app.state.experience_compilers.get(selected)
            if compiler is None:
                compiler = ExperienceCompiler(
                    store,
                    MemoryFirewall(
                        MemoryFirewallPolicy(
                            namespace=selected,
                            policy_id=f"http-api:{selected}",
                        )
                    ),
                )
                app.state.experience_compilers[selected] = compiler
            return compiler

    def _experience_runtime(namespace: str) -> AgentExperienceRuntime:
        compiler = _experience_compiler(namespace)
        selected = namespace.strip()
        with app.state.experience_lock:
            runtime = app.state.experience_runtimes.get(selected)
            if runtime is None:
                runtime = AgentExperienceRuntime(compiler)
                app.state.experience_runtimes[selected] = runtime
            return runtime

    def _close_experience_store() -> None:
        if (
            app.state.experience_store_owned
            and app.state.experience_store is not None
        ):
            app.state.experience_store.close()
            app.state.experience_store = None
            app.state.experience_compilers.clear()
            app.state.experience_runtimes.clear()

    app.router.add_event_handler("shutdown", _close_experience_store)

    def _query_results(request: QueryRequest):
        if app.state.cache is None:
            if app.state.vector_cache is None:
                return app.state.mind.query(
                    request.text,
                    namespace=request.namespace,
                    top_k=request.top_k,
                    tags=request.tags,
                    min_score=request.min_score,
                    metadata_filters=request.metadata_filters,
                )
            return query_with_vector_cache(
                app.state.mind,
                app.state.vector_cache,
                request.text,
                namespace=request.namespace,
                top_k=request.top_k,
                tags=request.tags,
                min_score=request.min_score,
                metadata_filters=request.metadata_filters,
            )
        return query_with_cache(
            app.state.mind,
            app.state.cache,
            request.text,
            namespace=request.namespace,
            top_k=request.top_k,
            tags=request.tags,
            min_score=request.min_score,
            vector_cache=app.state.vector_cache,
            metadata_filters=request.metadata_filters,
        )

    def _query_result_responses(results) -> list[QueryResultResponse]:
        return [
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

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        limiter = request.app.state.rate_limiter
        if limiter is not None and not limiter.allow(request):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )
        return await call_next(request)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "commit_sha": os.getenv("WAVEMIND_COMMIT_SHA", "unknown"),
        }

    @app.get("/studio", response_class=HTMLResponse, include_in_schema=False)
    def studio() -> HTMLResponse:
        return HTMLResponse(STUDIO_HTML)

    @app.get("/studio/state", dependencies=[Depends(require_role("read"))])
    def studio_state(
        namespace: str | None = None,
        limit: int = Query(default=200, ge=0, le=1000),
    ):
        return studio_snapshot(app.state.mind, namespace=namespace, limit=limit)

    @app.get("/studio/experience", dependencies=[Depends(require_role("read"))])
    def studio_experience(
        namespace: str = "default",
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return _experience_runtime(namespace).snapshot(namespace=namespace, limit=limit)

    @app.get("/studio/heatmap", dependencies=[Depends(require_role("read"))])
    def studio_heatmap(bins: int = Query(default=18, ge=4, le=48)):
        return field_heatmap(app.state.mind, bins=bins)

    @app.post("/studio/feedback", dependencies=[Depends(require_role("write"))])
    def studio_feedback(request: FeedbackRequest):
        accepted = app.state.mind.feedback(
            request.id,
            useful=request.useful,
            strength=request.strength,
            namespace=request.namespace,
            query=request.query,
            reason=request.reason,
        )
        if not accepted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"ok": True}

    @app.post("/feedback", response_model=FeedbackResponse, dependencies=[Depends(require_role("write"))])
    def feedback(request: FeedbackRequest) -> FeedbackResponse:
        with _api_operation(app, "feedback"):
            accepted = app.state.mind.feedback(
                request.id,
                useful=request.useful,
                strength=request.strength,
                namespace=request.namespace,
                query=request.query,
                reason=request.reason,
            )
            if not accepted:
                raise HTTPException(status_code=404, detail="Memory not found")
            record = app.state.mind.store.get(request.id)
            if record is None:
                raise HTTPException(status_code=404, detail="Memory not found")
            invalidated = _invalidate_cache(app, record.namespace)
        logger.info(
            "feedback id=%s namespace=%s useful=%s cache_invalidated=%s",
            request.id,
            record.namespace,
            request.useful,
            invalidated,
        )
        return FeedbackResponse(
            ok=True,
            id=int(record.id),
            namespace=record.namespace,
            priority=float(record.priority),
            access_count=int(record.access_count),
            cache_invalidated=invalidated,
        )

    @app.post(
        "/feedback/batch",
        response_model=FeedbackBatchResponse,
        dependencies=[Depends(require_role("write"))],
    )
    def feedback_batch(request: FeedbackBatchRequest) -> FeedbackBatchResponse:
        with _api_operation(app, "feedback_batch"):
            report = app.state.mind.feedback_batch(
                [item.model_dump() for item in request.items],
                namespace=request.namespace,
            )
            invalidated = 0
            for namespace in report.get("namespaces", ()):
                invalidated += _invalidate_cache(app, str(namespace))
        accepted_results = [
            FeedbackBatchItemResponse(ok=True, **dict(item))
            for item in report.get("results", ())
        ]
        rejected_results = [
            FeedbackBatchItemResponse(ok=False, **dict(item))
            for item in report.get("errors", ())
        ]
        logger.info(
            "feedback_batch accepted=%s rejected=%s cache_invalidated=%s",
            report.get("accepted", 0),
            report.get("rejected", 0),
            invalidated,
        )
        return FeedbackBatchResponse(
            ok=int(report.get("rejected", 0)) == 0,
            accepted=int(report.get("accepted", 0)),
            rejected=int(report.get("rejected", 0)),
            cache_invalidated=invalidated,
            results=accepted_results + rejected_results,
        )

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

    @app.post(
        "/remember/batch",
        response_model=RememberBatchResponse,
        dependencies=[Depends(require_role("write"))],
    )
    def remember_batch(request: RememberBatchRequest) -> RememberBatchResponse:
        if not request.items:
            raise HTTPException(status_code=400, detail="remember batch must contain at least one item")
        max_items = int(os.environ.get("WAVEMIND_REMEMBER_BATCH_MAX_ITEMS", "1000") or "1000")
        if len(request.items) > max_items:
            raise HTTPException(
                status_code=413,
                detail=f"remember batch exceeds WAVEMIND_REMEMBER_BATCH_MAX_ITEMS={max_items}",
            )
        items: list[RememberBatchItemResponse] = []
        invalidated_namespaces: set[str] = set()
        with _api_operation(app, "remember_batch"):
            payloads = [
                {
                    "text": item.text,
                    "namespace": item.namespace,
                    "tags": item.tags,
                    "ttl_seconds": item.ttl_seconds,
                    "metadata": item.metadata,
                    "priority": item.priority,
                }
                for item in request.items
            ]
            remember_batch_method = getattr(app.state.mind, "remember_batch", None)
            if callable(remember_batch_method):
                remembered_ids = [
                    _remember_response_id(value)
                    for value in remember_batch_method(payloads)
                ]
            else:
                remembered_ids = [
                    _remember_response_id(
                        app.state.mind.remember(
                            item.text,
                            namespace=item.namespace,
                            tags=item.tags,
                            ttl_seconds=item.ttl_seconds,
                            metadata=item.metadata,
                            priority=item.priority,
                        )
                    )
                    for item in request.items
                ]
            for index, (item, memory_id) in enumerate(
                zip(request.items, remembered_ids)
            ):
                items.append(
                    RememberBatchItemResponse(
                        index=index,
                        id=memory_id,
                        text=item.text,
                        namespace=item.namespace,
                    )
                )
                invalidated_namespaces.add(item.namespace)
            invalidated = sum(
                _invalidate_cache(app, namespace)
                for namespace in sorted(invalidated_namespaces)
            )
        logger.info(
            "remember_batch count=%s namespaces=%s cache_invalidated=%s",
            len(items),
            len(invalidated_namespaces),
            invalidated,
        )
        return RememberBatchResponse(
            count=len(items),
            cache_invalidated=invalidated,
            items=items,
        )

    @app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_role("read"))])
    def query(request: QueryRequest) -> QueryResponse:
        with _api_operation(app, "query"):
            results = _query_results(request)
        return QueryResponse(results=_query_result_responses(results))

    @app.post(
        "/experience/packet",
        dependencies=[Depends(require_role("read"))],
    )
    def compile_experience_packet(request: ExperiencePacketRequest):
        compiler = _experience_compiler(request.namespace)
        packet = compiler.compile_packet(
            request.query,
            namespace=request.namespace,
            context=FirewallContext(
                namespace=request.namespace,
                actor="http_api",
            ),
            token_budget=request.token_budget,
            top_k=request.top_k,
            domains=request.domains,
            task_types=request.task_types,
            tools=request.tools,
            include_canary=request.include_canary,
        )
        return packet.as_dict()

    @app.get(
        "/experience/{experience_id}",
        dependencies=[Depends(require_role("read"))],
    )
    def expand_experience(experience_id: str, namespace: str = "default"):
        compiler = _experience_compiler(namespace)
        details = compiler.expand(
            [experience_id],
            namespace=namespace,
            context=FirewallContext(namespace=namespace, actor="http_api"),
        )
        if not details:
            raise HTTPException(status_code=404, detail="Experience not found")
        return details[0].__dict__

    @app.post(
        "/experience/trajectories",
        dependencies=[Depends(require_role("write"))],
    )
    def ingest_experience_trajectory(request: ExperienceTrajectoryRequest):
        try:
            trajectory = parse_tool_trajectory(
                request.payload,
                provider=request.provider,
                namespace=request.namespace,
                trajectory_id=request.trajectory_id,
            )
            record = experience_from_trajectory(
                trajectory,
                trust=TrustClass(request.trust),
                status=ExperienceStatus(request.status),
                confidence=request.confidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        compiler = _experience_compiler(request.namespace)
        with app.state.experience_lock:
            existing = compiler.store.get_trajectory_by_source(
                namespace=request.namespace,
                source_sha256=trajectory.source_sha256,
            )
            if existing is not None:
                records = compiler.store.list_for_trajectory(existing.id)
                return {
                    "experience": records[0].as_dict() if records else None,
                    "trajectory": existing.as_dict(),
                    "firewall": None,
                    "inserted": False,
                }
            stored, decision = compiler.submit(
                record,
                context=FirewallContext(
                    namespace=request.namespace,
                    actor="http_api",
                    actor_trust=TrustClass.TOOL_OUTPUT,
                ),
            )
            compiler.store.restore_trajectory(trajectory)
        return {
            "experience": stored.as_dict(),
            "trajectory": trajectory.as_dict(),
            "firewall": decision.as_dict(),
            "inserted": True,
        }

    @app.post(
        "/experience/export",
        dependencies=[Depends(require_role("admin"))],
    )
    def export_experiences(request: ExperienceBundleRequest):
        compiler = _experience_compiler(request.namespace or "default")
        return export_experience_bundle(
            compiler.store,
            namespace=request.namespace,
        )

    @app.post(
        "/experience/import",
        dependencies=[Depends(require_role("admin"))],
    )
    def import_experiences(request: ExperienceBundleImportRequest):
        namespace = str(request.bundle.get("namespace") or "default")
        compiler = _experience_compiler(namespace)
        try:
            report = import_experience_bundle(compiler.store, request.bundle)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return report.__dict__

    @app.post(
        "/experience/runtime/runs",
        dependencies=[Depends(require_role("write"))],
    )
    def start_experience_runtime_run(request: ExperienceRuntimeStartRequest):
        runtime = _experience_runtime(request.namespace)
        session_id = request.session_id or f"session_{uuid.uuid4().hex}"
        run_id = request.run_id or f"run_{uuid.uuid4().hex}"
        task_id = request.task_id or f"task_{uuid.uuid4().hex}"
        try:
            intervention = runtime.decide(
                request.query,
                namespace=request.namespace,
                run_id=run_id,
                task_id=task_id,
                domains=(request.domain,),
                task_types=(request.task_type,),
                tools=request.tools,
                token_budget=request.token_budget,
                top_k=request.top_k,
                canary=request.canary,
            )
            applied = (
                tuple(item.experience_id for item in intervention.packet.items)
                if intervention.inject and intervention.packet is not None
                else ()
            )
            handle = runtime.begin_run(
                namespace=request.namespace,
                objective=request.objective,
                domain=request.domain,
                task_type=request.task_type,
                session_id=session_id,
                run_id=run_id,
                task_id=task_id,
                metadata={"provider": "http", **request.metadata},
                applied_experience_ids=applied,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema": "wavemind.agent_experience_run.v1",
            "namespace": request.namespace,
            "session_id": handle.session_id,
            "run_id": handle.run_id,
            "task_id": handle.task_id,
            "next_sequence": runtime.next_sequence(
                namespace=request.namespace,
                run_id=handle.run_id,
            ),
            "intervention": intervention.as_dict(),
            "applied_experience_ids": list(applied),
        }

    @app.post(
        "/experience/runtime/events",
        dependencies=[Depends(require_role("write"))],
    )
    def capture_experience_runtime_event(request: ExperienceRuntimeEventRequest):
        runtime = _experience_runtime(request.namespace)
        try:
            occurred_at = request.occurred_at
            if occurred_at is None:
                occurred_at = next(
                    (
                        event.occurred_at
                        for event in runtime.events(
                            namespace=request.namespace,
                            run_id=request.run_id,
                        )
                        if event.id == request.id
                    ),
                    time.time(),
                )
            result = runtime.capture(
                AgentExperienceEvent(
                    id=request.id,
                    namespace=request.namespace,
                    run_id=request.run_id,
                    session_id=request.session_id,
                    task_id=request.task_id,
                    kind=AgentEventKind(request.kind),
                    sequence=request.sequence,
                    occurred_at=occurred_at,
                    parent_event_id=request.parent_event_id,
                    tool_name=request.tool_name,
                    duration_ms=request.duration_ms,
                    payload=request.payload,
                )
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"inserted": result.inserted, "event": result.event.as_dict()}

    @app.post(
        "/experience/runtime/runs/{run_id}/verify",
        dependencies=[Depends(require_role("write"))],
    )
    def verify_experience_runtime_run(
        run_id: str,
        request: ExperienceRuntimeVerifyRequest,
    ):
        runtime = _experience_runtime(request.namespace)
        try:
            verification = OutcomeVerification(
                evidence_id=request.evidence_id,
                source=VerificationSource(request.source),
                verifier=request.verifier,
                success=request.success,
                score=request.score,
                reference=request.reference,
                metadata=request.metadata,
            )
            finalization = runtime.finalize_external_run(
                namespace=request.namespace,
                run_id=run_id,
                verification=verification,
                applied_experience_ids=request.applied_experience_ids,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Runtime run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return finalization.as_dict()

    @app.post(
        "/experience/runtime/interventions",
        dependencies=[Depends(require_role("read"))],
    )
    def decide_experience_runtime_intervention(
        request: ExperienceRuntimeInterventionRequest,
    ):
        runtime = _experience_runtime(request.namespace)
        try:
            return runtime.decide(
                request.query,
                namespace=request.namespace,
                run_id=request.run_id,
                task_id=request.task_id,
                domains=request.domains,
                task_types=request.task_types,
                tools=request.tools,
                token_budget=request.token_budget,
                top_k=request.top_k,
                canary=request.canary,
            ).as_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/experience/runtime/runs",
        dependencies=[Depends(require_role("read"))],
    )
    def list_experience_runtime_runs(
        namespace: str = "default",
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return {
            "runs": _experience_runtime(namespace).list_runs(
                namespace=namespace,
                limit=limit,
            )
        }

    @app.get(
        "/experience/runtime/runs/{run_id}",
        dependencies=[Depends(require_role("read"))],
    )
    def inspect_experience_runtime_run(run_id: str, namespace: str = "default"):
        try:
            return _experience_runtime(namespace).run_details(
                namespace=namespace,
                run_id=run_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Runtime run not found") from exc

    @app.get(
        "/experience/runtime/state",
        dependencies=[Depends(require_role("read"))],
    )
    def inspect_experience_runtime_state(
        namespace: str = "default",
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return _experience_runtime(namespace).snapshot(namespace=namespace, limit=limit)

    @app.post(
        "/experience/runtime/{experience_id}/approve",
        dependencies=[Depends(require_role("admin"))],
    )
    def approve_experience_runtime_candidate(
        experience_id: str,
        request: ExperienceRuntimeLifecycleRequest,
    ):
        if not request.evidence_id:
            raise HTTPException(status_code=422, detail="evidence_id is required")
        try:
            status = _experience_runtime(request.namespace).approve(
                experience_id,
                namespace=request.namespace,
                evidence_id=request.evidence_id,
                score=request.score,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experience not found") from exc
        return {"experience_id": experience_id, "status": status}

    @app.post(
        "/experience/runtime/{experience_id}/reject",
        dependencies=[Depends(require_role("admin"))],
    )
    def reject_experience_runtime_candidate(
        experience_id: str,
        request: ExperienceRuntimeLifecycleRequest,
    ):
        try:
            record = _experience_runtime(request.namespace).reject(
                experience_id,
                namespace=request.namespace,
                reason=request.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experience not found") from exc
        return record.as_dict()

    @app.post(
        "/experience/runtime/{experience_id}/rollback",
        dependencies=[Depends(require_role("admin"))],
    )
    def rollback_experience_runtime_candidate(
        experience_id: str,
        request: ExperienceRuntimeLifecycleRequest,
    ):
        try:
            record = _experience_runtime(request.namespace).rollback(
                experience_id,
                namespace=request.namespace,
                reason=request.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experience not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return record.as_dict()

    @app.post(
        "/query/batch",
        response_model=QueryBatchResponse,
        dependencies=[Depends(require_role("read"))],
    )
    def query_batch(request: QueryBatchRequest) -> QueryBatchResponse:
        if not request.queries:
            raise HTTPException(status_code=400, detail="query batch must contain at least one query")
        max_items = int(os.environ.get("WAVEMIND_QUERY_BATCH_MAX_ITEMS", "256") or "256")
        if len(request.queries) > max_items:
            raise HTTPException(
                status_code=413,
                detail=f"query batch exceeds WAVEMIND_QUERY_BATCH_MAX_ITEMS={max_items}",
            )
        items: list[QueryBatchItemResponse] = []
        with _api_operation(app, "query_batch"):
            for index, item in enumerate(request.queries):
                results = _query_results(item)
                items.append(
                    QueryBatchItemResponse(
                        index=index,
                        text=item.text,
                        namespace=item.namespace,
                        results=_query_result_responses(results),
                    )
                )
        return QueryBatchResponse(count=len(items), items=items)

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

    @app.post(
        "/forget/batch",
        response_model=ForgetBatchResponse,
        dependencies=[Depends(require_role("admin"))],
    )
    def forget_batch(request: ForgetBatchRequest) -> ForgetBatchResponse:
        if not request.items:
            raise HTTPException(status_code=400, detail="forget batch must contain at least one item")
        max_items = int(os.environ.get("WAVEMIND_FORGET_BATCH_MAX_ITEMS", "1000") or "1000")
        if len(request.items) > max_items:
            raise HTTPException(
                status_code=413,
                detail=f"forget batch exceeds WAVEMIND_FORGET_BATCH_MAX_ITEMS={max_items}",
            )
        items: list[ForgetBatchItemResponse] = []
        invalidated_namespaces: set[str | None] = set()
        with _api_operation(app, "forget_batch"):
            for index, item in enumerate(request.items):
                if item.id is None and item.text is None:
                    raise HTTPException(status_code=400, detail=f"forget batch item {index} requires id or text")
                forget_result = app.state.mind.forget(
                    id=item.id,
                    text=item.text,
                    namespace=item.namespace,
                )
                deleted = _forget_response_deleted(forget_result)
                if deleted:
                    invalidated_namespaces.add(item.namespace)
                items.append(
                    ForgetBatchItemResponse(
                        index=index,
                        namespace=item.namespace,
                        deleted=deleted,
                    )
                )
            invalidated = sum(
                _invalidate_cache(app, namespace)
                for namespace in sorted(
                    invalidated_namespaces,
                    key=lambda value: "" if value is None else value,
                )
            )
        total_deleted = sum(item.deleted for item in items)
        logger.info(
            "forget_batch count=%s deleted=%s namespaces=%s cache_invalidated=%s",
            len(items),
            total_deleted,
            len(invalidated_namespaces),
            invalidated,
        )
        return ForgetBatchResponse(
            count=len(items),
            deleted=total_deleted,
            cache_invalidated=invalidated,
            items=items,
        )

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

    @app.post(
        "/memories/tombstone/batch",
        response_model=MemoryTombstoneBatchWriteResponse,
        dependencies=[Depends(require_role("admin"))],
    )
    def write_memory_tombstone_batch(
        request: MemoryTombstoneBatchRequest,
    ) -> MemoryTombstoneBatchWriteResponse:
        if not request.items:
            raise HTTPException(status_code=400, detail="tombstone batch must contain at least one item")
        max_items = int(os.environ.get("WAVEMIND_TOMBSTONE_BATCH_MAX_ITEMS", "1000") or "1000")
        if len(request.items) > max_items:
            raise HTTPException(
                status_code=413,
                detail=f"tombstone batch exceeds WAVEMIND_TOMBSTONE_BATCH_MAX_ITEMS={max_items}",
            )
        items: list[MemoryTombstoneBatchItemResponse] = []
        with _api_operation(app, "memories_tombstone_batch"):
            for index, item in enumerate(request.items):
                if not item.record_keys and not item.texts:
                    raise HTTPException(
                        status_code=400,
                        detail=f"tombstone batch item {index} requires record_keys or texts",
                    )
                event_id = app.state.mind.store.log_audit_event(
                    "distributed_tombstone",
                    namespace=item.namespace,
                    metadata={
                        "record_keys": sorted(set(item.record_keys)),
                        "texts": sorted(set(item.texts)),
                    },
                )
                items.append(
                    MemoryTombstoneBatchItemResponse(
                        index=index,
                        namespace=item.namespace,
                        id=event_id,
                    )
                )
        return MemoryTombstoneBatchWriteResponse(count=len(items), items=items)

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

    @app.get("/memory-os/insights", dependencies=[Depends(require_role("read"))])
    def memory_os_insights(
        namespace: str | None = None,
        audit_limit: int = Query(default=512, ge=0, le=10000),
        max_hot_queries: int = Query(default=32, ge=0, le=1000),
        min_frequency: int = Query(default=2, ge=1),
        top_k: int = Query(default=3, ge=1, le=100),
        min_score: float | None = Query(default=None),
        target_memories: int | None = Query(default=None, ge=0),
        namespace_count: int | None = Query(default=None, ge=0),
        node_count: int | None = Query(default=None, ge=0),
        replication_factor: int = Query(default=3, ge=1),
        read_quorum: int = Query(default=1, ge=1),
        read_fanout: int | None = Query(default=None, ge=1),
        target_qps: float = Query(default=100.0, ge=0.0),
        target_p99_ms: float = Query(default=100.0, ge=0.0),
        observed_p99_ms: float | None = Query(default=None, ge=0.0),
        deployment: str = "local",
        cache_mode: str = "auto",
        multimodal: bool = False,
        memory_pressure_threshold: int = Query(default=50000, ge=0),
    ):
        with _api_operation(app, "memory_os_insights"):
            return _memory_os_insights_payload(
                app.state.mind,
                namespace=namespace,
                audit_limit=audit_limit,
                max_hot_queries=max_hot_queries,
                min_frequency=min_frequency,
                top_k=top_k,
                min_score=min_score,
                target_memories=target_memories,
                namespace_count=namespace_count,
                node_count=node_count,
                replication_factor=replication_factor,
                read_quorum=read_quorum,
                read_fanout=read_fanout,
                target_qps=target_qps,
                target_p99_ms=target_p99_ms,
                observed_p99_ms=observed_p99_ms,
                deployment=deployment,
                cache_mode=cache_mode,
                multimodal=multimodal,
                memory_pressure_threshold=memory_pressure_threshold,
            )

    @app.post("/memory-os/run", dependencies=[Depends(require_role("admin"))])
    def memory_os_run(request: MemoryOSRequest):
        with _api_operation(app, "memory_os"):
            lock = _memory_os_lock(
                namespace=request.namespace,
                prefix=request.lock_prefix,
                ttl_seconds=request.lock_ttl_seconds,
                cache=app.state.cache,
            )
            job_guard = _memory_os_job_guard(
                idempotency_key=request.idempotency_key,
                prefix=request.idempotency_prefix,
                ttl_seconds=request.idempotency_ttl_seconds,
                lock=lock,
            )
            if request.idempotency_key and job_guard is None:
                raise HTTPException(
                    status_code=503,
                    detail="Memory OS idempotency requires WAVEMIND_MEMORY_OS_LOCK_REDIS_URL or WAVEMIND_REDIS_URL",
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
                transition_prefetch_window_seconds=request.transition_prefetch_window_seconds,
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
                job_guard=job_guard,
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

    @app.get(
        "/memories/{memory_id}/explain",
        response_model=MemoryExplanationResponse,
        dependencies=[Depends(require_role("read"))],
    )
    def explain_memory(
        memory_id: int,
        namespace: str = Query(default="default", min_length=1),
        audit_limit: int = Query(default=20, ge=1, le=100),
    ) -> MemoryExplanationResponse:
        record = app.state.mind.store.get(memory_id)
        if record is None or record.namespace != namespace or record.is_expired:
            raise HTTPException(status_code=404, detail="Memory not found")
        events = app.state.mind.audit_events(
            namespace=namespace,
            memory_id=memory_id,
            limit=audit_limit,
        )
        mcp_metadata = record.metadata.get("_wavemind_mcp", {})
        provenance = (
            dict(mcp_metadata.get("provenance") or {})
            if isinstance(mcp_metadata, dict)
            else {}
        )
        if not provenance and isinstance(record.metadata.get("provenance"), dict):
            provenance = dict(record.metadata["provenance"])
        return MemoryExplanationResponse(
            id=int(record.id),
            namespace=record.namespace,
            text=record.text,
            tags=list(record.tags),
            metadata=record.metadata,
            provenance=provenance,
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
            priority=record.priority,
            access_count=record.access_count,
            audit_events=[
                AuditEventResponse(
                    id=int(event.id),
                    created_at=event.created_at,
                    action=event.action,
                    namespace=event.namespace,
                    memory_id=event.memory_id,
                    metadata=event.metadata,
                )
                for event in events
            ],
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
        experience_store = _experience_compiler("default").store
        with _api_operation(app, "backup"):
            path = create_rotating_product_backup(
                app.state.mind,
                experience_store,
                request.path,
                prefix=request.prefix,
                keep_last=request.keep_last,
            )
        return BackupResponse(path=str(path))

    return app
