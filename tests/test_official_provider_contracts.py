from __future__ import annotations

import asyncio
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
    agents_memory = pytest.importorskip("agents.memory")
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
        result["experience_packet_data"]["items"][0]["experience_id"]
        == "exp_official"
    )
