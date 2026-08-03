from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wavemind import (
    AgentExperienceRuntime,
    CallableOutcomeVerifier,
    ExperienceCompiler,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    VerificationSource,
    WaveMind,
)
from wavemind.api import create_app
from wavemind.integrations.experience_runtime import AgentExperienceHooks
from wavemind.integrations.anthropic import make_anthropic_experience_hooks
from wavemind.integrations.langgraph import (
    make_experience_runtime_finish_node,
    make_experience_runtime_start_node,
    wrap_experience_runtime_node,
)
from wavemind.integrations.mcp_experience import ExperienceMCPAdapter
from wavemind.integrations.openai_agents import make_openai_experience_hooks


def _runtime(path: Path) -> AgentExperienceRuntime:
    store = SQLiteExperienceStore(path)
    return AgentExperienceRuntime(
        ExperienceCompiler(
            store,
            MemoryFirewall(
                MemoryFirewallPolicy(
                    namespace="agent",
                    policy_id="runtime-contract",
                    require_consent_for_user_data=False,
                )
            ),
        )
    )


def test_provider_hooks_share_capture_verify_and_inspect_contract(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "hooks.db")
    hooks = AgentExperienceHooks(
        runtime,
        namespace="agent",
        provider="openai_agents",
    )
    run = hooks.begin(
        "repair deployment",
        objective="repair deployment",
        domain="operations",
        task_type="repair",
        tools=("health",),
        run_id="hook-run",
    )
    call_id = run.tool_call("health", {"authorization": "Bearer secret-token"})
    run.tool_result(
        "health",
        success=True,
        output={"status": "healthy"},
        call_id=call_id,
        duration_ms=2.5,
    )
    run.verify(
        CallableOutcomeVerifier(
            source=VerificationSource.ENVIRONMENT,
            verifier="health-check",
            callback=lambda _context: (True, 1.0),
            reference="health://service",
        )
    )
    final = run.finish()

    assert final.verified is True
    assert final.candidate_ids
    snapshot = hooks.inspect()
    assert snapshot["runs"][0]["run_id"] == "hook-run"
    serialized = str(runtime.events(namespace="agent", run_id="hook-run"))
    assert "secret-token" not in serialized
    runtime.store.close()


def test_http_runtime_supports_full_lifecycle_and_idempotent_capture(tmp_path: Path) -> None:
    store = SQLiteExperienceStore(tmp_path / "http-experience.db")
    mind = WaveMind(db_path=tmp_path / "memory.db")
    try:
        with TestClient(create_app(mind=mind, experience_store=store)) as client:
            started = client.post(
                "/experience/runtime/runs",
                json={
                    "query": "repair deployment",
                    "objective": "repair deployment",
                    "domain": "operations",
                    "task_type": "repair",
                    "namespace": "agent",
                    "run_id": "http-run",
                    "session_id": "http-session",
                    "task_id": "http-task",
                    "tools": ["health"],
                },
            )
            assert started.status_code == 200
            assert started.json()["next_sequence"] == 3
            assert started.json()["intervention"]["inject"] is False

            call = {
                "id": "http-call",
                "namespace": "agent",
                "run_id": "http-run",
                "session_id": "http-session",
                "task_id": "http-task",
                "kind": "tool.call",
                "sequence": 3,
                "tool_name": "health",
                "payload": {"input": {"api_key": "sk-secret-secret-secret"}},
            }
            captured = client.post("/experience/runtime/events", json=call)
            assert captured.status_code == 200
            assert captured.json()["inserted"] is True
            replay = client.post("/experience/runtime/events", json=call)
            assert replay.status_code == 200
            assert replay.json()["inserted"] is False

            result = client.post(
                "/experience/runtime/events",
                json={
                    "id": "http-result",
                    "namespace": "agent",
                    "run_id": "http-run",
                    "session_id": "http-session",
                    "task_id": "http-task",
                    "kind": "tool.result",
                    "sequence": 4,
                    "parent_event_id": "http-call",
                    "tool_name": "health",
                    "duration_ms": 3.0,
                    "payload": {"success": True, "output": {"status": "healthy"}},
                },
            )
            assert result.status_code == 200

            verified = client.post(
                "/experience/runtime/runs/http-run/verify",
                json={
                    "namespace": "agent",
                    "evidence_id": "health-evidence-1",
                    "source": "environment",
                    "verifier": "health-check",
                    "success": True,
                    "score": 1.0,
                    "reference": "health://service",
                },
            )
            assert verified.status_code == 200
            assert verified.json()["verified"] is True
            assert verified.json()["candidate_ids"]

            details = client.get(
                "/experience/runtime/runs/http-run",
                params={"namespace": "agent"},
            )
            assert details.status_code == 200
            assert details.json()["events"][-1]["kind"] == "session.finished"
            assert "sk-secret" not in details.text

            state = client.get(
                "/experience/runtime/state",
                params={"namespace": "agent"},
            )
            assert state.status_code == 200
            assert state.json()["schema"] == "wavemind.agent_experience_snapshot.v1"
            assert state.json()["validation_evidence"]
            studio = client.get("/studio")
            assert studio.status_code == 200
            assert "Verified Agent Experience" in studio.text
            studio_state = client.get(
                "/studio/experience",
                params={"namespace": "agent"},
            )
            assert studio_state.status_code == 200
            assert studio_state.json()["runs"][0]["run_id"] == "http-run"
    finally:
        mind.close()
        store.close()


def test_http_runtime_rejects_llm_self_assessment(tmp_path: Path) -> None:
    store = SQLiteExperienceStore(tmp_path / "http-experience.db")
    mind = WaveMind(db_path=tmp_path / "memory.db")
    try:
        with TestClient(create_app(mind=mind, experience_store=store)) as client:
            assert client.post(
                "/experience/runtime/runs",
                json={
                    "query": "task",
                    "objective": "task",
                    "domain": "general",
                    "task_type": "task",
                    "namespace": "agent",
                    "run_id": "self-run",
                },
            ).status_code == 200
            response = client.post(
                "/experience/runtime/runs/self-run/verify",
                json={
                    "namespace": "agent",
                    "evidence_id": "self-evidence",
                    "source": "tool",
                    "verifier": "agent-output",
                    "success": True,
                    "metadata": {"llm_self_assessed": True},
                },
            )
            assert response.status_code == 422
            assert "self-assessment" in response.text
    finally:
        mind.close()
        store.close()


def test_provider_factories_and_langgraph_nodes_use_the_same_runtime(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "providers.db")
    openai_hooks = make_openai_experience_hooks(runtime, namespace="agent")
    anthropic_hooks = make_anthropic_experience_hooks(runtime, namespace="agent")
    assert openai_hooks.provider == "openai_agents"
    assert anthropic_hooks.provider == "anthropic_agent_sdk"

    start = make_experience_runtime_start_node(
        openai_hooks,
        domain="operations",
        task_type="health-check",
        tools=("health",),
    )
    state = {
        "input": "check service",
        "objective": "verify service health",
        "thread_id": "graph-thread",
        "run_id": "graph-run",
    }
    state.update(start(state))
    wrapped = wrap_experience_runtime_node(
        lambda _state: {"healthy": True},
        tool_name="health",
    )
    state.update(wrapped(state))
    finish = make_experience_runtime_finish_node(
        CallableOutcomeVerifier(
            source=VerificationSource.TEST,
            verifier="graph-test",
            callback=lambda _context: True,
        )
    )
    result = finish(state)
    assert result["wavemind_verification"]["success"] is True
    assert result["wavemind_finalization"]["candidate_ids"]
    runtime.store.close()


def test_mcp_runtime_tools_cover_capture_verify_inspect_and_lifecycle(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "mcp.db")
    adapter = ExperienceMCPAdapter(runtime.compiler, runtime)
    names = {tool["name"] for tool in adapter.list_tools()}
    assert {
        "start_experience_run",
        "capture_experience_event",
        "verify_experience_run",
        "inspect_experience_runtime",
        "approve_experience",
        "reject_experience",
        "rollback_experience",
    } <= names

    started = adapter.call_tool(
        "start_experience_run",
        {
            "namespace": "agent",
            "query": "check service",
            "objective": "check service",
            "domain": "operations",
            "task_type": "health-check",
            "tools": ["health"],
            "run_id": "mcp-run",
        },
    )
    call = adapter.call_tool(
        "capture_experience_event",
        {
            "namespace": "agent",
            "run_id": started["run_id"],
            "kind": "tool.call",
            "tool_name": "health",
            "payload": {"url": "http://service/health"},
        },
    )
    adapter.call_tool(
        "capture_experience_event",
        {
            "namespace": "agent",
            "run_id": started["run_id"],
            "kind": "tool.result",
            "tool_name": "health",
            "success": True,
            "parent_event_id": call["event_id"],
            "payload": {"output": {"healthy": True}},
        },
    )
    final = adapter.call_tool(
        "verify_experience_run",
        {
            "namespace": "agent",
            "run_id": started["run_id"],
            "evidence_id": "mcp-health-1",
            "source": "environment",
            "verifier": "health-check",
            "success": True,
        },
    )
    assert final["verified"] is True
    snapshot = adapter.call_tool(
        "inspect_experience_runtime",
        {"namespace": "agent"},
    )
    candidate_id = final["candidate_ids"][0]
    assert snapshot["runs"][0]["run_id"] == "mcp-run"
    rejected = adapter.call_tool(
        "reject_experience",
        {
            "namespace": "agent",
            "experience_id": candidate_id,
            "reason": "operator review",
        },
    )
    assert rejected["status"] == "rejected"
    runtime.store.close()
