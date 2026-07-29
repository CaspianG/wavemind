from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from .core import QueryResult, WaveMind

_INTERNAL_METADATA_KEY = "_wavemind_mcp"
_MAX_TEXT_LENGTH = 1_000_000
_MAX_NAMESPACE_LENGTH = 255
_MAX_TOP_K = 100


def _require_mcp() -> tuple[type[Any], type[Any]]:
    try:
        from mcp.server.fastmcp import Context, FastMCP
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise RuntimeError(
            'MCP support is not installed. Run: pip install "wavemind[mcp]"'
        ) from exc
    return FastMCP, Context


def _validate_namespace(namespace: str) -> str:
    value = str(namespace).strip()
    if not value:
        raise ValueError("namespace must not be empty")
    if len(value) > _MAX_NAMESPACE_LENGTH:
        raise ValueError(f"namespace must be at most {_MAX_NAMESPACE_LENGTH} characters")
    return value


def _validate_text(text: str, *, field: str = "text") -> str:
    value = str(text).strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{field} must be at most {_MAX_TEXT_LENGTH} characters")
    return value


def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized = []
    seen = set()
    for raw_tag in tags or []:
        tag = str(raw_tag).strip()
        if not tag or tag in seen:
            continue
        if len(tag) > 128:
            raise ValueError("tags must be at most 128 characters each")
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key != _INTERNAL_METADATA_KEY
    }


def _request_hash(
    *,
    text: str,
    tags: list[str],
    ttl_seconds: float | None,
    priority: float,
    metadata: dict[str, Any],
    provenance: dict[str, Any] | None,
) -> str:
    payload = {
        "text": text,
        "tags": tags,
        "ttl_seconds": ttl_seconds,
        "priority": priority,
        "metadata": metadata,
        "provenance": provenance or {},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_payload(result: QueryResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "text": result.text,
        "score": result.score,
        "vector_score": result.vector_score,
        "field_score": result.field_score,
        "graph_score": result.graph_score,
        "namespace": result.namespace,
        "tags": list(result.tags),
        "metadata": _public_metadata(result.metadata),
    }


def build_mcp_server(
    mind: WaveMind | None = None,
    *,
    db_path: str | Path | None = None,
    name: str = "WaveMind",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Any:
    """Build a FastMCP server backed by one durable WaveMind instance."""

    FastMCP, _ = _require_mcp()
    owns_mind = mind is None
    memory = mind or WaveMind(db_path=Path(db_path or "wavemind.db"))
    operation_lock = threading.RLock()
    closed = False

    def close_memory() -> None:
        nonlocal closed
        if owns_mind and not closed:
            closed = True
            memory.close()

    if owns_mind:
        atexit.register(close_memory)

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"memory": memory}
        finally:
            close_memory()

    server = FastMCP(
        name=name,
        instructions=(
            "Durable dynamic memory for agents. Every operation is isolated by "
            "an explicit namespace."
        ),
        host=host,
        port=int(port),
        lifespan=lifespan,
        json_response=True,
    )

    @server.tool(
        description=(
            "Store one durable memory. Reusing an idempotency key with the same "
            "payload returns the original memory; a conflicting payload is rejected."
        )
    )
    def remember(
        text: str,
        namespace: str = "default",
        tags: list[str] | None = None,
        ttl_seconds: float | None = None,
        priority: float = 1.0,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        selected_text = _validate_text(text)
        selected_tags = _normalize_tags(tags)
        selected_metadata = dict(metadata or {})
        selected_provenance = dict(provenance or {})
        if ttl_seconds is not None and float(ttl_seconds) <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if float(priority) < 0:
            raise ValueError("priority must be non-negative")
        selected_key = str(idempotency_key).strip() if idempotency_key else None
        if idempotency_key is not None and not selected_key:
            raise ValueError("idempotency_key must not be empty")
        if selected_key and len(selected_key) > 255:
            raise ValueError("idempotency_key must be at most 255 characters")
        digest = _request_hash(
            text=selected_text,
            tags=selected_tags,
            ttl_seconds=ttl_seconds,
            priority=float(priority),
            metadata=selected_metadata,
            provenance=selected_provenance,
        )
        with operation_lock:
            if selected_key:
                for record in memory.list_records(selected_namespace):
                    internal = record.metadata.get(_INTERNAL_METADATA_KEY, {})
                    if internal.get("idempotency_key") != selected_key:
                        continue
                    if internal.get("request_hash") != digest:
                        raise ValueError(
                            "idempotency_key already exists with a different payload"
                        )
                    return {
                        "id": int(record.id),
                        "namespace": selected_namespace,
                        "created": False,
                        "idempotent_replay": True,
                    }
            stored_metadata = dict(selected_metadata)
            stored_metadata[_INTERNAL_METADATA_KEY] = {
                "idempotency_key": selected_key,
                "request_hash": digest,
                "provenance": selected_provenance,
            }
            memory_id = memory.remember(
                selected_text,
                namespace=selected_namespace,
                tags=selected_tags,
                ttl_seconds=ttl_seconds,
                metadata=stored_metadata,
                priority=float(priority),
            )
            return {
                "id": memory_id,
                "namespace": selected_namespace,
                "created": True,
                "idempotent_replay": False,
            }

    @server.tool(description="Recall ranked, non-expired memories from one namespace.")
    def recall(
        query: str,
        namespace: str = "default",
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        selected_query = _validate_text(query, field="query")
        if not 1 <= int(top_k) <= _MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {_MAX_TOP_K}")
        with operation_lock:
            results = memory.query(
                selected_query,
                namespace=selected_namespace,
                top_k=int(top_k),
                tags=_normalize_tags(tags),
                min_score=min_score,
            )
        return {
            "namespace": selected_namespace,
            "query": selected_query,
            "results": [_result_payload(result) for result in results],
        }

    @server.tool(description="Record positive or negative feedback for a recalled memory.")
    def feedback(
        memory_id: int,
        namespace: str,
        useful: bool = True,
        strength: float = 0.25,
        query: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        if not 0 < float(strength) <= 10:
            raise ValueError("strength must be greater than zero and at most 10")
        with operation_lock:
            accepted = memory.feedback(
                int(memory_id),
                useful=bool(useful),
                strength=float(strength),
                namespace=selected_namespace,
                query=query,
                reason=reason,
            )
        if not accepted:
            raise ValueError("memory was not found in the requested namespace")
        return {
            "id": int(memory_id),
            "namespace": selected_namespace,
            "accepted": True,
            "useful": bool(useful),
        }

    @server.tool(description="Delete one memory from one namespace.")
    def forget(memory_id: int, namespace: str) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        with operation_lock:
            record_ids = {
                int(record.id) for record in memory.list_records(selected_namespace)
            }
            if int(memory_id) not in record_ids:
                raise ValueError("memory was not found in the requested namespace")
            deleted = memory.forget(
                id=int(memory_id),
                namespace=selected_namespace,
            )
        return {
            "id": int(memory_id),
            "namespace": selected_namespace,
            "deleted": deleted == 1,
        }

    @server.tool(description="Inspect one memory without searching other namespaces.")
    def inspect_memory(memory_id: int, namespace: str) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        with operation_lock:
            record = next(
                (
                    item
                    for item in memory.list_records(selected_namespace)
                    if int(item.id) == int(memory_id)
                ),
                None,
            )
        if record is None:
            raise ValueError("memory was not found in the requested namespace")
        return {
            "id": int(record.id),
            "text": record.text,
            "namespace": record.namespace,
            "tags": list(record.tags),
            "metadata": _public_metadata(record.metadata),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at,
            "priority": record.priority,
            "access_count": record.access_count,
        }

    @server.tool(
        description=(
            "Explain a memory's provenance and the latest audit events associated "
            "with it."
        )
    )
    def explain_memory(
        memory_id: int,
        namespace: str,
        audit_limit: int = 20,
    ) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        if not 1 <= int(audit_limit) <= 100:
            raise ValueError("audit_limit must be between 1 and 100")
        with operation_lock:
            record = next(
                (
                    item
                    for item in memory.list_records(selected_namespace)
                    if int(item.id) == int(memory_id)
                ),
                None,
            )
            if record is None:
                raise ValueError("memory was not found in the requested namespace")
            events = [
                event
                for event in memory.store.list_audit_events(
                    namespace=selected_namespace,
                    memory_id=int(memory_id),
                    limit=int(audit_limit),
                )
            ]
        internal = record.metadata.get(_INTERNAL_METADATA_KEY, {})
        return {
            "id": int(record.id),
            "namespace": selected_namespace,
            "provenance": dict(internal.get("provenance") or {}),
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "priority": record.priority,
            "access_count": record.access_count,
            "audit_events": [
                {
                    "action": event.action,
                    "created_at": event.created_at,
                    "metadata": event.metadata,
                }
                for event in events
            ],
        }

    @server.tool(
        description=(
            "Inspect or clear a namespace. The clear action requires confirm=true."
        )
    )
    def manage_namespace(
        namespace: str,
        action: Literal["stats", "list", "clear"] = "stats",
        limit: int = 100,
        confirm: bool = False,
    ) -> dict[str, Any]:
        selected_namespace = _validate_namespace(namespace)
        if not 1 <= int(limit) <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with operation_lock:
            if action == "stats":
                return {
                    "namespace": selected_namespace,
                    "action": action,
                    "stats": memory.stats(namespace=selected_namespace),
                }
            records = memory.list_records(selected_namespace)
            if action == "list":
                return {
                    "namespace": selected_namespace,
                    "action": action,
                    "memories": [
                        {
                            "id": int(record.id),
                            "text": record.text,
                            "tags": list(record.tags),
                            "priority": record.priority,
                            "expires_at": record.expires_at,
                        }
                        for record in records[: int(limit)]
                    ],
                    "total": len(records),
                }
            if not confirm:
                raise ValueError("clear requires confirm=true")
            deleted = memory.forget(namespace=selected_namespace)
            return {
                "namespace": selected_namespace,
                "action": action,
                "deleted": deleted,
            }

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wavemind-mcp",
        description="Run WaveMind as a durable Model Context Protocol server.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.cwd() / "wavemind.db",
        help="SQLite database path (default: ./wavemind.db).",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow streamable HTTP to bind outside loopback.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (
        args.transport == "streamable-http"
        and args.host not in {"127.0.0.1", "::1", "localhost"}
        and not args.allow_remote
    ):
        raise SystemExit(
            "Refusing a non-loopback MCP bind without --allow-remote. "
            "Add authentication and TLS before exposing this endpoint."
        )
    server = build_mcp_server(
        db_path=args.db,
        host=args.host,
        port=args.port,
    )
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
