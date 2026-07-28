from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wavemind.experience_compiler import ExperienceCompiler
from wavemind.memory_firewall import FirewallContext


class ExperienceMCPAdapter:
    """Framework-neutral implementation of MCP tools/list and tools/call."""

    def __init__(self, compiler: ExperienceCompiler):
        self.compiler = compiler

    def list_tools(self) -> list[dict[str, Any]]:
        return [
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
        raise KeyError(name)


def build_experience_mcp_server(
    compiler: ExperienceCompiler,
    *,
    name: str = "WaveMind Experience",
) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            'MCP support requires: pip install "wavemind[mcp]"'
        ) from exc
    adapter = ExperienceMCPAdapter(compiler)
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

    return server
