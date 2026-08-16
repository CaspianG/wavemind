from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

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
    WaveMind,
)
from wavemind.api import create_app
from wavemind.integrations.anthropic import (
    ANTHROPIC_MEMORY_TOOL,
    AnthropicMemoryHandler,
)
from wavemind.integrations.langgraph import (
    make_experience_capture_node,
    make_experience_recall_node,
)
from wavemind.integrations.mcp_experience import ExperienceMCPAdapter
from wavemind.integrations.openai_agents import (
    WaveMindAgentsSession,
    make_experience_input_callback,
)


@pytest.fixture
def compiler(tmp_path):
    store = SQLiteExperienceStore(tmp_path / "experience.db")
    firewall = MemoryFirewall(
        MemoryFirewallPolicy(namespace="agent", policy_id="provider-contract")
    )
    value = ExperienceCompiler(store, firewall)
    store.put(
        ExperienceRecord.create(
            id="exp_deploy",
            kind=ExperienceKind.SUCCESSFUL_STRATEGY,
            title="Recover a failed deployment",
            content="Inspect health and logs, then roll back the failing release.",
            namespace="agent",
            confidence=0.95,
            trust=TrustClass.VERIFIED_OPERATOR,
            status=ExperienceStatus.ACTIVE,
            source=ExperienceSource(
                provider="evaluation",
                source_type="verified_run",
                source_id="deploy-7",
            ),
        )
    )
    try:
        yield value
    finally:
        store.close()


def test_openai_agents_session_matches_async_session_contract(tmp_path) -> None:
    db_path = tmp_path / "agents.db"

    async def exercise() -> None:
        session = WaveMindAgentsSession("thread-1", db_path=db_path)
        await session.add_items(
            [
                {"role": "user", "content": "Deploy failed"},
                {"role": "assistant", "content": "Checking health"},
            ]
        )
        assert [item["role"] for item in await session.get_items()] == [
            "user",
            "assistant",
        ]
        assert await session.get_items(limit=1) == [
            {"role": "assistant", "content": "Checking health"}
        ]
        assert await session.pop_item() == {
            "role": "assistant",
            "content": "Checking health",
        }
        session.close()

        restarted = WaveMindAgentsSession("thread-1", db_path=db_path)
        assert await restarted.get_items() == [
            {"role": "user", "content": "Deploy failed"}
        ]
        await restarted.clear_session()
        assert await restarted.get_items() == []
        restarted.close()

    asyncio.run(exercise())


def test_openai_input_callback_injects_ephemeral_packet_only(compiler) -> None:
    callback = make_experience_input_callback(
        compiler,
        namespace="agent",
        token_budget=200,
    )

    result = asyncio.run(
        callback(
            [{"role": "user", "content": "Earlier message"}],
            [{"role": "user", "content": "How should I recover the deployment?"}],
        )
    )

    assert result[0]["content"] == "Earlier message"
    assert result[-1]["content"] == "How should I recover the deployment?"
    injected = result[-2]
    assert injected["role"] == "system"
    assert "Recover a failed deployment" in injected["content"]
    assert injected["metadata"]["ephemeral"] is True
    assert injected["metadata"]["citations"] == ["experience:exp_deploy@v1"]


def test_anthropic_memory_handler_implements_official_commands(tmp_path) -> None:
    assert ANTHROPIC_MEMORY_TOOL == {
        "type": "memory_20250818",
        "name": "memory",
    }
    handler = AnthropicMemoryHandler(
        str(tmp_path / "anthropic.db"),
        namespace="agent",
    )
    try:
        assert handler.execute(
            "create",
            "/memories/deploy.md",
            file_text="Check health.\nRoll back.",
        )["created"]
        assert handler.execute("view", "/memories")["files"] == [
            "/memories/deploy.md"
        ]
        handler.execute(
            "str_replace",
            "/memories/deploy.md",
            old_str="Check health.",
            new_str="Check health and logs.",
        )
        handler.execute(
            "insert",
            "/memories/deploy.md",
            insert_line=1,
            insert_text="Confirm the failing revision.",
        )
        viewed = handler.execute("view", "/memories/deploy.md")
        assert viewed["content"].splitlines() == [
            "Check health and logs.",
            "Confirm the failing revision.",
            "Roll back.",
        ]
        handler.execute(
            "rename",
            "/memories/deploy.md",
            new_path="/memories/recovery.md",
        )
        assert list(handler.export_files()) == ["/memories/recovery.md"]
        assert handler.execute("delete", "/memories/recovery.md")["deleted"]

        with pytest.raises(ValueError, match="memory path|encoded traversal"):
            handler.execute("view", "/memories/../secrets")
    finally:
        handler.close()


def test_mcp_tools_list_and_call_follow_mcp_shapes(compiler) -> None:
    adapter = ExperienceMCPAdapter(compiler)
    tools = adapter.list_tools()
    assert {tool["name"] for tool in tools} == {
        "compile_experience_packet",
        "expand_experience",
    }
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)

    packet = adapter.call_tool(
        "compile_experience_packet",
        {
            "query": "recover deployment",
            "namespace": "agent",
            "token_budget": 200,
        },
    )
    assert packet["schema"] == "wavemind.experience_packet.v1"
    assert packet["items"][0]["experience_id"] == "exp_deploy"

    details = adapter.call_tool(
        "expand_experience",
        {
            "experience_ids": ["exp_deploy"],
            "namespace": "agent",
        },
    )
    assert details["schema"] == "wavemind.experience_details.v1"
    assert details["items"][0]["citation"] == "experience:exp_deploy@v1"


def test_langgraph_nodes_use_state_mapping_without_framework_dependency(
    compiler,
) -> None:
    recall = make_experience_recall_node(
        compiler,
        namespace="agent",
        token_budget=200,
    )
    state = recall({"input": "recover deployment"})
    assert "Recover a failed deployment" in state["experience_packet"]
    assert state["experience_packet_data"]["items"][0]["experience_id"] == "exp_deploy"

    capture = make_experience_capture_node(
        compiler,
        namespace="agent",
        kind=ExperienceKind.GOTCHA,
    )
    captured = capture(
        {
            "thread_id": "thread-7",
            "experience_title": "Deployment gotcha",
            "experience": "The health endpoint remains cached for ten seconds.",
            "success": True,
        }
    )
    stored = compiler.store.get(captured["wavemind_experience_id"])
    assert stored is not None
    assert stored.kind == ExperienceKind.GOTCHA
    assert stored.status == ExperienceStatus.SHADOW


def test_http_experience_contract_supports_packet_trajectory_and_bundle(
    tmp_path,
) -> None:
    experience_store = SQLiteExperienceStore(tmp_path / "http-experience.db")
    experience_store.put(
        ExperienceRecord.create(
            id="exp_http",
            kind=ExperienceKind.PROCEDURE,
            title="HTTP recovery",
            content="Inspect the failing health check before rollback.",
            namespace="agent",
            trust=TrustClass.VERIFIED_OPERATOR,
            status=ExperienceStatus.ACTIVE,
            source=ExperienceSource(
                provider="test",
                source_type="verified",
                source_id="http-1",
            ),
        )
    )
    mind = WaveMind(db_path=tmp_path / "memory.db")
    try:
        with TestClient(
            create_app(mind=mind, experience_store=experience_store)
        ) as client:
            packet = client.post(
                "/experience/packet",
                json={
                    "query": "recover health check",
                    "namespace": "agent",
                    "token_budget": 200,
                    "compact_prompt": True,
                },
            )
            assert packet.status_code == 200
            assert packet.json()["items"][0]["experience_id"] == "exp_http"
            assert packet.json()["compiler_policy"]["compact_prompt"] is True

            detail = client.get(
                "/experience/exp_http",
                params={"namespace": "agent"},
            )
            assert detail.status_code == 200
            assert detail.json()["citation"] == "experience:exp_http@v1"

            trajectory = client.post(
                "/experience/trajectories",
                json={
                    "provider": "generic",
                    "namespace": "agent",
                    "trajectory_id": "http-trajectory",
                    "payload": {
                        "steps": [
                            {
                                "id": "call-http",
                                "kind": "tool_call",
                                "name": "health",
                            },
                            {
                                "id": "result-http",
                                "kind": "tool_result",
                                "name": "health",
                                "success": True,
                                "parent_id": "call-http",
                            },
                        ]
                    },
                },
            )
            assert trajectory.status_code == 200
            assert trajectory.json()["trajectory"]["id"] == "http-trajectory"
            assert trajectory.json()["inserted"] is True
            replay = client.post(
                "/experience/trajectories",
                json={
                    "provider": "generic",
                    "namespace": "agent",
                    "trajectory_id": "http-trajectory",
                    "payload": {
                        "steps": [
                            {
                                "id": "call-http",
                                "kind": "tool_call",
                                "name": "health",
                            },
                            {
                                "id": "result-http",
                                "kind": "tool_result",
                                "name": "health",
                                "success": True,
                                "parent_id": "call-http",
                            },
                        ]
                    },
                },
            )
            assert replay.status_code == 200
            assert replay.json()["inserted"] is False
            assert (
                replay.json()["experience"]["id"]
                == trajectory.json()["experience"]["id"]
            )

            exported = client.post(
                "/experience/export",
                json={"namespace": "agent"},
            )
            assert exported.status_code == 200
            assert exported.json()["manifest"] == {
                "record_count": 2,
                "trajectory_count": 1,
                "validation_count": 0,
            }
            imported = client.post(
                "/experience/import",
                json={"bundle": exported.json()},
            )
            assert imported.status_code == 200
            assert imported.json()["parity"] == 1.0
    finally:
        mind.close()
        experience_store.close()
