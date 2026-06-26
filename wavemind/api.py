from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.responses import PlainTextResponse
from pydantic import AliasChoices, BaseModel, Field

from . import __version__
from .core import WaveMind
from .encoders import create_text_encoder
from .importers import import_path


logger = logging.getLogger("wavemind.api")


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


class AuditEventResponse(BaseModel):
    id: int
    created_at: float
    action: str
    namespace: str | None
    memory_id: int | None
    metadata: dict[str, Any]


class AuditResponse(BaseModel):
    events: list[AuditEventResponse]


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
    app.state.mind = mind or build_default_mind()

    @app.post("/remember", response_model=RememberResponse)
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

    @app.post("/query", response_model=QueryResponse)
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

    @app.delete("/forget", response_model=ForgetResponse)
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

    @app.get("/stats")
    def stats(namespace: str | None = None):
        return app.state.mind.stats(namespace=namespace)

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(namespace: str | None = None) -> PlainTextResponse:
        return PlainTextResponse(
            _metrics_text(app.state.mind.stats(namespace=namespace)),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/audit", response_model=AuditResponse)
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

    @app.post("/import", response_model=ImportResponse)
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

    return app
