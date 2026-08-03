from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wavemind.experience_compiler import ExperienceCompiler
from wavemind.experience_runtime import (
    AgentExperienceRuntime,
    OutcomeVerification,
    VerificationSource,
)
from wavemind.memory_firewall import FirewallContext

from .experience_runtime import AgentExperienceHooks, ProviderExperienceRun


class ExperienceMCPAdapter:
    """Framework-neutral implementation of MCP tools/list and tools/call."""

    def __init__(
        self,
        compiler: ExperienceCompiler,
        runtime: AgentExperienceRuntime | None = None,
    ):
        self.compiler = compiler
        self.runtime = runtime
        self._runs: dict[str, ProviderExperienceRun] = {}

    def list_tools(self) -> list[dict[str, Any]]:
        tools = [
            {
                "name": "compile_experience_packet",
                "description": "Compile a trusted, token-bounded experience packet.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "namespace": {"type": "string", "minLength": 1},
                        "token_budget": {"type": "integer", "minimum": 32},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "required": ["query", "namespace"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "expand_experience",
                "description": "Expand cited experience IDs with full provenance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "experience_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "maxItems": 100,
                        },
                        "namespace": {"type": "string", "minLength": 1},
                    },
                    "required": ["experience_ids", "namespace"],
                    "additionalProperties": False,
                },
            },
        ]
        if self.runtime is not None:
            tools.extend(_runtime_tool_definitions())
        return tools

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        namespace = str(arguments.get("namespace") or "").strip()
        if not namespace:
            raise ValueError("namespace must not be empty")
        context = FirewallContext(namespace=namespace, actor="mcp_client")
        if name == "compile_experience_packet":
            packet = self.compiler.compile_packet(
                str(arguments.get("query") or ""),
                namespace=namespace,
                context=context,
                token_budget=int(arguments.get("token_budget") or 800),
                top_k=int(arguments.get("top_k") or 8),
            )
            return packet.as_dict()
        if name == "expand_experience":
            ids = arguments.get("experience_ids") or []
            if not isinstance(ids, list):
                raise ValueError("experience_ids must be an array")
            return {
                "schema": "wavemind.experience_details.v1",
                "items": [
                    detail.__dict__
                    for detail in self.compiler.expand(
                        (str(item) for item in ids),
                        namespace=namespace,
                        context=context,
                    )
                ],
            }
        if name == "start_experience_run":
            runtime = self._require_runtime()
            hooks = AgentExperienceHooks(
                runtime,
                namespace=namespace,
                provider="mcp",
                token_budget=int(arguments.get("token_budget") or 400),
                top_k=int(arguments.get("top_k") or 3),
            )
            run = hooks.begin(
                str(arguments.get("query") or ""),
                objective=str(arguments.get("objective") or ""),
                domain=str(arguments.get("domain") or "general"),
                task_type=str(arguments.get("task_type") or "task"),
                tools=tuple(str(item) for item in (arguments.get("tools") or [])),
                session_id=_optional_text(arguments.get("session_id")),
                run_id=_optional_text(arguments.get("run_id")),
                task_id=_optional_text(arguments.get("task_id")),
                metadata={"transport": "mcp"},
            )
            self._runs[run.run_id] = run
            return {
                "run_id": run.run_id,
                "session_id": run.captured.session_id,
                "task_id": run.captured.task_id,
                "intervention": run.packet,
            }
        if name == "capture_experience_event":
            run = self._require_run(str(arguments.get("run_id") or ""))
            kind = str(arguments.get("kind") or "")
            tool_name = str(arguments.get("tool_name") or "").strip()
            payload = arguments.get("payload")
            selected_payload = dict(payload) if isinstance(payload, Mapping) else {}
            if kind == "tool.call":
                event_id = run.tool_call(tool_name, selected_payload)
            elif kind == "tool.result":
                event_id = run.tool_result(
                    tool_name,
                    success=bool(arguments.get("success")),
                    output=selected_payload.get("output"),
                    call_id=_optional_text(arguments.get("parent_event_id")),
                    duration_ms=(
                        float(arguments["duration_ms"])
                        if arguments.get("duration_ms") is not None
                        else None
                    ),
                    metadata={
                        key: value
                        for key, value in selected_payload.items()
                        if key != "output"
                    },
                )
            elif kind == "error":
                event_id = run.error(
                    str(selected_payload.get("message") or "agent run error"),
                    error_code=_optional_text(selected_payload.get("error_code")),
                    metadata=selected_payload,
                )
            else:
                raise ValueError("kind must be tool.call, tool.result, or error")
            return {"event_id": event_id, "run_id": run.run_id}
        if name == "verify_experience_run":
            run = self._require_run(str(arguments.get("run_id") or ""))
            verification = OutcomeVerification(
                evidence_id=str(arguments.get("evidence_id") or ""),
                source=VerificationSource(str(arguments.get("source") or "")),
                verifier=str(arguments.get("verifier") or ""),
                success=bool(arguments.get("success")),
                score=(
                    float(arguments["score"])
                    if arguments.get("score") is not None
                    else None
                ),
                reference=_optional_text(arguments.get("reference")),
                metadata=dict(arguments.get("metadata") or {}),
            )
            run.captured.accept_verification(verification)
            result = run.finish().as_dict()
            self._runs.pop(run.run_id, None)
            return result
        if name == "inspect_experience_runtime":
            return self._require_runtime().snapshot(
                namespace=namespace,
                limit=int(arguments.get("limit") or 100),
            )
        if name == "approve_experience":
            status = self._require_runtime().approve(
                str(arguments.get("experience_id") or ""),
                namespace=namespace,
                evidence_id=str(arguments.get("evidence_id") or ""),
                score=float(arguments.get("score") or 1.0),
            )
            return {"experience_id": arguments.get("experience_id"), "status": status}
        if name == "reject_experience":
            return self._require_runtime().reject(
                str(arguments.get("experience_id") or ""),
                namespace=namespace,
                reason=str(arguments.get("reason") or "operator rejected"),
            ).as_dict()
        if name == "rollback_experience":
            return self._require_runtime().rollback(
                str(arguments.get("experience_id") or ""),
                namespace=namespace,
                reason=str(arguments.get("reason") or "operator rollback"),
            ).as_dict()
        raise KeyError(name)

    def _require_runtime(self) -> AgentExperienceRuntime:
        if self.runtime is None:
            raise RuntimeError("runtime tools require AgentExperienceRuntime")
        return self.runtime

    def _require_run(self, run_id: str) -> ProviderExperienceRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run


def _runtime_tool_definitions() -> list[dict[str, Any]]:
    namespace = {"type": "string", "minLength": 1}
    text = {"type": "string", "minLength": 1}
    return [
        {
            "name": "start_experience_run",
            "description": "Start a verified-experience run and decide selective injection.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "namespace": namespace,
                    "query": text,
                    "objective": text,
                    "domain": text,
                    "task_type": text,
                    "tools": {"type": "array", "items": {"type": "string"}},
                    "session_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "token_budget": {"type": "integer", "minimum": 32},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["namespace", "query", "objective", "domain", "task_type"],
                "additionalProperties": False,
            },
        },
        {
            "name": "capture_experience_event",
            "description": "Capture a tool call, tool result, or error for a runtime run.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "namespace": namespace,
                    "run_id": text,
                    "kind": {"enum": ["tool.call", "tool.result", "error"]},
                    "tool_name": {"type": "string"},
                    "success": {"type": "boolean"},
                    "payload": {"type": "object"},
                    "parent_event_id": {"type": "string"},
                    "duration_ms": {"type": "number", "minimum": 0},
                },
                "required": ["namespace", "run_id", "kind"],
                "additionalProperties": False,
            },
        },
        {
            "name": "verify_experience_run",
            "description": "Finalize a run with independent test, tool, environment, or operator evidence.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "namespace": namespace,
                    "run_id": text,
                    "evidence_id": text,
                    "source": {"enum": ["test", "tool", "environment", "operator"]},
                    "verifier": text,
                    "success": {"type": "boolean"},
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "reference": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["namespace", "run_id", "evidence_id", "source", "verifier", "success"],
                "additionalProperties": False,
            },
        },
        {
            "name": "inspect_experience_runtime",
            "description": "Inspect runs, candidates, evidence, decisions, and audit events.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "namespace": namespace,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
                "required": ["namespace"],
                "additionalProperties": False,
            },
        },
        *[
            {
                "name": f"{action}_experience",
                "description": f"{action.title()} an experience candidate with operator control.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": namespace,
                        "experience_id": text,
                        "reason": {"type": "string"},
                        "evidence_id": {"type": "string"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["namespace", "experience_id"],
                    "additionalProperties": False,
                },
            }
            for action in ("approve", "reject", "rollback")
        ],
    ]


def _optional_text(value: Any) -> str | None:
    selected = str(value or "").strip()
    return selected or None


def build_experience_mcp_server(
    compiler: ExperienceCompiler,
    *,
    runtime: AgentExperienceRuntime | None = None,
    name: str = "WaveMind Experience",
) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            'MCP support requires: pip install "wavemind[mcp]"'
        ) from exc
    adapter = ExperienceMCPAdapter(compiler, runtime)
    server = FastMCP(name=name, json_response=True)

    @server.tool(description="Compile a trusted, token-bounded experience packet.")
    def compile_experience_packet(
        query: str,
        namespace: str,
        token_budget: int = 800,
        top_k: int = 8,
    ) -> dict[str, Any]:
        return adapter.call_tool(
            "compile_experience_packet",
            {
                "query": query,
                "namespace": namespace,
                "token_budget": token_budget,
                "top_k": top_k,
            },
        )

    @server.tool(description="Expand cited experience IDs with full provenance.")
    def expand_experience(
        experience_ids: list[str],
        namespace: str,
    ) -> dict[str, Any]:
        return adapter.call_tool(
            "expand_experience",
            {
                "experience_ids": experience_ids,
                "namespace": namespace,
            },
        )

    if runtime is not None:

        @server.tool(description="Start a selective verified-experience run.")
        def start_experience_run(
            query: str,
            objective: str,
            domain: str,
            task_type: str,
            namespace: str,
            tools: list[str] | None = None,
            session_id: str | None = None,
            run_id: str | None = None,
            task_id: str | None = None,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "start_experience_run",
                {
                    "query": query,
                    "objective": objective,
                    "domain": domain,
                    "task_type": task_type,
                    "namespace": namespace,
                    "tools": tools or [],
                    "session_id": session_id,
                    "run_id": run_id,
                    "task_id": task_id,
                },
            )

        @server.tool(description="Capture a runtime tool call, result, or error.")
        def capture_experience_event(
            run_id: str,
            kind: str,
            namespace: str,
            tool_name: str = "",
            success: bool = False,
            payload: dict[str, Any] | None = None,
            parent_event_id: str | None = None,
            duration_ms: float | None = None,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "capture_experience_event",
                {
                    "run_id": run_id,
                    "kind": kind,
                    "namespace": namespace,
                    "tool_name": tool_name,
                    "success": success,
                    "payload": payload or {},
                    "parent_event_id": parent_event_id,
                    "duration_ms": duration_ms,
                },
            )

        @server.tool(description="Finalize a run with independent evidence.")
        def verify_experience_run(
            run_id: str,
            evidence_id: str,
            source: str,
            verifier: str,
            success: bool,
            namespace: str,
            score: float | None = None,
            reference: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "verify_experience_run",
                {
                    "run_id": run_id,
                    "evidence_id": evidence_id,
                    "source": source,
                    "verifier": verifier,
                    "success": success,
                    "namespace": namespace,
                    "score": score,
                    "reference": reference,
                    "metadata": metadata or {},
                },
            )

        @server.tool(description="Inspect verified-experience runtime state.")
        def inspect_experience_runtime(
            namespace: str,
            limit: int = 100,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "inspect_experience_runtime",
                {"namespace": namespace, "limit": limit},
            )

        @server.tool(description="Approve a candidate with operator evidence.")
        def approve_experience(
            experience_id: str,
            evidence_id: str,
            namespace: str,
            score: float = 1.0,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "approve_experience",
                {
                    "experience_id": experience_id,
                    "evidence_id": evidence_id,
                    "namespace": namespace,
                    "score": score,
                },
            )

        @server.tool(description="Reject an experience candidate.")
        def reject_experience(
            experience_id: str,
            reason: str,
            namespace: str,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "reject_experience",
                {
                    "experience_id": experience_id,
                    "reason": reason,
                    "namespace": namespace,
                },
            )

        @server.tool(description="Roll back a superseded experience version.")
        def rollback_experience(
            experience_id: str,
            reason: str,
            namespace: str,
        ) -> dict[str, Any]:
            return adapter.call_tool(
                "rollback_experience",
                {
                    "experience_id": experience_id,
                    "reason": reason,
                    "namespace": namespace,
                },
            )

    return server
