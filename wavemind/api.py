from __future__ import annotations

import logging
import os
import time
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import AliasChoices, BaseModel, Field

from . import __version__
from .core import WaveMind
from .encoders import create_text_encoder
from .importers import import_path
from .observability import configure_observability, instrument_fastapi_app


logger = logging.getLogger("wavemind.api")
ROLE_LEVELS = {"read": 1, "write": 2, "admin": 3}


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
                return False
            hits.append(now)
            return True


def _split_keys(raw: str) -> list[str]:
    return [key.strip() for key in raw.split(",") if key.strip()]


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


def _metrics_text(stats: dict[str, Any]) -> str:
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
    app.state.rate_limiter = InMemoryRateLimiter.from_env()

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        limiter = request.app.state.rate_limiter
        if limiter is not None and not limiter.allow(request):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )
        return await call_next(request)

    @app.post("/remember", response_model=RememberResponse, dependencies=[Depends(require_role("write"))])
    def remember(request: RememberRequest) -> RememberResponse:
        id = app.state.mind.remember(
            request.text,
            namespace=request.namespace,
            tags=request.tags,
            ttl_seconds=request.ttl_seconds,
            metadata=request.metadata,
            priority=request.priority,
        )
        logger.info("remembered id=%s namespace=%s", id, request.namespace)
        return RememberResponse(id=id)

    @app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_role("read"))])
    def query(request: QueryRequest) -> QueryResponse:
        results = app.state.mind.query(
            request.text,
            namespace=request.namespace,
            top_k=request.top_k,
            tags=request.tags,
            min_score=request.min_score,
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
        deleted = app.state.mind.forget(
            id=payload.id,
            text=payload.text,
            namespace=payload.namespace,
        )
        logger.info("forgot deleted=%s namespace=%s", deleted, payload.namespace)
        return ForgetResponse(deleted=deleted)

    @app.get("/stats", dependencies=[Depends(require_role("read"))])
    def stats(namespace: str | None = None):
        return app.state.mind.stats(namespace=namespace)

    @app.get("/index/health", dependencies=[Depends(require_role("read"))])
    def index_health():
        return app.state.mind.index_health()

    @app.post("/index/rebuild", dependencies=[Depends(require_role("admin"))])
    def rebuild_index():
        return app.state.mind.rebuild_index()

    @app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_role("read"))])
    def metrics(namespace: str | None = None) -> PlainTextResponse:
        return PlainTextResponse(
            _metrics_text(app.state.mind.stats(namespace=namespace)),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/observability", response_model=ObservabilityResponse, dependencies=[Depends(require_role("admin"))])
    def observability() -> ObservabilityResponse:
        return ObservabilityResponse(**app.state.observability)

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
        path = app.state.mind.save(
            request.path,
            keep_last=request.keep_last,
            backup_prefix=request.prefix,
        )
        return BackupResponse(path=str(path))

    return app
