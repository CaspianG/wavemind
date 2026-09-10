"""Credential-bound Brain MCP tools with strict shared JSON schemas."""

import json
from contextlib import asynccontextmanager
from typing import Literal

from pydantic import create_model
from starlette.concurrency import run_in_threadpool

from .http import OPERATIONS, Text, MAX_BODY, MAX_UPLOAD_BODY, invoke, validated
from .models import BrainError, Principal


def _models():
    models = {}
    for operation, model in OPERATIONS.items():
        fields = (
            {}
            if operation in ("create_brain", "list_brains")
            else {"brain_id": (Text, ...)}
        )
        if operation == "read_citation":
            fields["citation_id"] = (Text, ...)
        if operation in ("verify_outcome", "verify_outcome_with"):
            fields["outcome_id"] = (Text, ...)
        if operation in (
            "review_restored_source",
            "change_source",
            "list_source_citations",
        ):
            fields["source_id"] = (Text, ...)
        if operation == "change_source":
            fields["action"] = (Literal["pause", "resume", "revoke", "delete"], ...)
        models[operation] = create_model("Brain_" + operation, __base__=model, **fields)
    return models


TOOL_MODELS = _models()


class BrainMCPAdapter:
    """Trusted in-process principal, or a mandatory live launcher binding."""

    def __init__(self, service, principal: Principal, *, auth=None, token=None):
        if not isinstance(principal, Principal) or (auth is None) != (token is None):
            raise BrainError("unauthenticated", "Authenticated principal required.")
        self.service, self.principal = service, principal
        self.auth, self._token = auth, token
        self._current()

    def _current(self):
        if self.auth is None:
            return self.principal
        current = self.auth.authenticate(self._token)
        if current != self.principal:
            raise BrainError("unauthenticated", "Credential binding changed.")
        return current

    def call_tool(self, name: str, arguments: dict):
        principal = self._current()
        if name not in TOOL_MODELS:
            raise BrainError("not_found", "Tool not found.")
        try:
            size = len(json.dumps(arguments, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError):
            raise BrainError("invalid_input", "Invalid tool input.") from None
        if size > (MAX_UPLOAD_BODY if name == "preview_import" else MAX_BODY):
            raise BrainError("body_too_large", "Tool input exceeds limits.")
        values = validated(TOOL_MODELS[name], arguments)
        path = {}
        for field in ("brain_id", "citation_id", "outcome_id"):
            if field in values:
                path[field] = values.pop(field)
        if name in ("change_source", "review_restored_source", "list_source_citations"):
            path["source_id"] = values.pop("source_id")
        if name == "change_source":
            path["action"] = values.pop("action")
        return invoke(self.service, principal, name, values, **path)

    def build_context(
        self,
        *,
        brain_id: str,
        question: str,
        moment: float | None = None,
        project_id: str | None = None,
        max_bytes: int = 16384,
    ):
        return self.call_tool(
            "build_context",
            {
                "brain_id": brain_id,
                "question": question,
                "moment": moment,
                "project_id": project_id,
                "max_bytes": max_bytes,
            },
        )

    def read_citation(self, *, brain_id: str, citation_id: str):
        return self.call_tool(
            "read_citation", {"brain_id": brain_id, "citation_id": citation_id}
        )

    def review_records(
        self, *, brain_id: str, record_type: str, record_ids: list[str], action: str
    ):
        return self.call_tool(
            "review_records",
            {
                "brain_id": brain_id,
                "record_type": record_type,
                "record_ids": record_ids,
                "action": action,
            },
        )

    def recheck_dependencies(self, *, brain_id: str):
        return self.call_tool("recheck_dependencies", {"brain_id": brain_id})


def build_brain_mcp_server(service, auth, token: str):
    from ..integrations.mcp_compat import require_fastmcp

    try:
        FastMCP, _ = require_fastmcp()
    except ImportError as exc:
        raise RuntimeError('MCP support requires: pip install "wavemind[mcp]"') from exc
    from mcp.types import Tool, CallToolResult, TextContent

    adapter = BrainMCPAdapter(service, auth.authenticate(token), auth=auth, token=token)
    from .maintenance import BrainMaintenance

    @asynccontextmanager
    async def lifespan(server):
        maintenance = BrainMaintenance(service)
        await maintenance.start()
        try:
            yield {}
        finally:
            await maintenance.stop()

    class AuthenticatedBrainMCP(FastMCP):
        # Public FastMCP handlers are overridden deliberately: its default
        # function binding coerces inputs and drops extra arguments before the
        # service sees them. Validate the raw object with our strict schemas.
        async def list_tools(self):
            await run_in_threadpool(adapter._current)
            return [
                Tool(
                    name=name,
                    description="Authorized Brain " + name.replace("_", " "),
                    inputSchema=model.model_json_schema(),
                )
                for name, model in TOOL_MODELS.items()
            ]

        async def call_tool(self, name, arguments):
            try:
                result = await run_in_threadpool(adapter.call_tool, name, arguments)
                return result if isinstance(result, dict) else {"result": result}
            except BrainError as error:
                return CallToolResult(
                    isError=True,
                    content=[
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "error": {
                                        "code": error.code,
                                        "message": error.message,
                                    }
                                }
                            ),
                        )
                    ],
                )

    return AuthenticatedBrainMCP(
        name="WaveMind Brain", json_response=True, log_level="ERROR", lifespan=lifespan
    )
