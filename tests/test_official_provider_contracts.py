from __future__ import annotations

import asyncio
import sys
import subprocess
from typing import TypedDict

import pytest

from wavemind import (
    ExperienceCompiler,
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    TrustClass,
)
from wavemind.integrations.anthropic import ANTHROPIC_MEMORY_TOOL
from wavemind.integrations.langgraph import make_experience_recall_node
from wavemind.integrations.mcp_experience import build_experience_mcp_server
from wavemind.integrations.openai_agents import WaveMindAgentsSession


@pytest.mark.parametrize("builder", ["memory", "experience"])
def test_mcp_builders_initialize_in_cold_process_without_incomplete_settings(builder):
    pytest.importorskip("mcp.server.fastmcp")
    script = """
import asyncio, json, warnings
from pydantic_settings import IncompleteFieldDefinitionWarning
warnings.simplefilter("error", IncompleteFieldDefinitionWarning)
from wavemind import WaveMind, ExperienceCompiler, MemoryFirewall, MemoryFirewallPolicy, SQLiteExperienceStore
from wavemind.mcp_server import build_mcp_server
from wavemind.integrations.mcp_experience import build_experience_mcp_server
import sys
if sys.argv[1] == "memory":
    resource = WaveMind(db_path=":memory:")
    server = build_mcp_server(resource)
else:
    resource = SQLiteExperienceStore(":memory:")
    server = build_experience_mcp_server(ExperienceCompiler(resource, MemoryFirewall(MemoryFirewallPolicy(namespace="agent"))))
try:
    print(json.dumps([{ "name": t.name, "schema": t.inputSchema } for t in asyncio.run(server.list_tools())]))
finally:
    resource.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, builder], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    import json

    tools = json.loads(result.stdout)
    names = {tool["name"] for tool in tools}
    expected = (
        {"compile_experience_packet", "expand_experience"}
        if builder == "experience"
        else {"remember", "recall"}
    )
    assert expected <= names
    assert all(tool["schema"]["type"] == "object" for tool in tools)
    assert result.stderr == ""


@pytest.fixture
def compiler(tmp_path):
    store = SQLiteExperienceStore(tmp_path / "official-contracts.db")
    store.put(
        ExperienceRecord.create(
            id="exp_official",
            kind=ExperienceKind.PROCEDURE,
            title="Official provider contract",
            content="Retrieve the verified experience before acting.",
            namespace="agent",
            trust=TrustClass.VERIFIED_OPERATOR,
            status=ExperienceStatus.ACTIVE,
            source=ExperienceSource(
                provider="test",
                source_type="verified",
                source_id="official-1",
            ),
        )
    )
    value = ExperienceCompiler(
        store,
        MemoryFirewall(MemoryFirewallPolicy(namespace="agent")),
    )
    try:
        yield value
    finally:
        store.close()


def test_openai_agents_runtime_session_protocol(tmp_path) -> None:
    try:
        agents_memory = pytest.importorskip("agents.memory")
    except (KeyError, TypeError) as exc:
        if sys.version_info[:3] == (3, 11, 0):
            pytest.skip(
                "openai-agents ParamSpec aliases are incompatible with CPython 3.11.0"
            )
        raise exc
    session = WaveMindAgentsSession(
        "official-session",
        db_path=tmp_path / "openai.db",
    )
    try:
        assert isinstance(session, agents_memory.Session)
        asyncio.run(session.add_items([{"role": "user", "content": "hello"}]))
        assert asyncio.run(session.get_items()) == [
            {"role": "user", "content": "hello"}
        ]
    finally:
        session.close()


def test_anthropic_tool_definition_matches_official_typed_dict() -> None:
    beta = pytest.importorskip("anthropic.types.beta")
    annotations = beta.BetaMemoryTool20250818Param.__annotations__
    assert set(ANTHROPIC_MEMORY_TOOL) <= set(annotations)
    assert ANTHROPIC_MEMORY_TOOL == {
        "type": "memory_20250818",
        "name": "memory",
    }


def test_mcp_fastmcp_registers_experience_tools(compiler) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    server = build_experience_mcp_server(compiler)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "compile_experience_packet",
        "expand_experience",
    }
    assert all(tool.inputSchema["type"] == "object" for tool in tools)


def test_langgraph_compiles_and_invokes_experience_node(compiler) -> None:
    graph_module = pytest.importorskip("langgraph.graph")

    class State(TypedDict, total=False):
        input: str
        experience_packet: str
        experience_packet_data: dict

    builder = graph_module.StateGraph(State)
    builder.add_node(
        "experience",
        make_experience_recall_node(
            compiler,
            namespace="agent",
            token_budget=200,
        ),
    )
    builder.add_edge(graph_module.START, "experience")
    builder.add_edge("experience", graph_module.END)
    graph = builder.compile()

    result = graph.invoke({"input": "official provider contract"})
    assert "Official provider contract" in result["experience_packet"]
    assert (
        result["experience_packet_data"]["items"][0]["experience_id"] == "exp_official"
    )
