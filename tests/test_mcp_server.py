from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def _structured(result: Any) -> dict[str, Any]:
    assert result.isError is False
    payload = result.structuredContent
    assert isinstance(payload, dict)
    return payload


async def _session_call(
    db_path: Path,
    operations: list[tuple[str, dict[str, Any]]],
) -> tuple[list[str], list[Any]]:
    repo_root = Path(__file__).resolve().parents[1]
    server = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "wavemind.mcp_server",
            "--db",
            str(db_path),
        ],
        cwd=repo_root,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            results = []
            for name, arguments in operations:
                results.append(await session.call_tool(name, arguments))
            return [tool.name for tool in tools.tools], results


def _call(
    db_path: Path,
    operations: list[tuple[str, dict[str, Any]]],
) -> tuple[list[str], list[Any]]:
    return asyncio.run(_session_call(db_path, operations))


async def _concurrent_session(db_path: Path) -> tuple[list[Any], bool]:
    repo_root = Path(__file__).resolve().parents[1]
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "wavemind.mcp_server", "--db", str(db_path)],
        cwd=repo_root,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            calls = await asyncio.gather(
                *[
                    session.call_tool(
                        "remember",
                        {
                            "text": f"Concurrent fact {index}",
                            "namespace": "parallel",
                            "idempotency_key": f"parallel-{index}",
                        },
                    )
                    for index in range(20)
                ]
            )
            cancelled_call = asyncio.create_task(
                session.call_tool(
                    "recall",
                    {
                        "query": "concurrent fact",
                        "namespace": "parallel",
                        "top_k": 20,
                    },
                )
            )
            cancelled_call.cancel()
            cancelled = False
            try:
                await cancelled_call
            except asyncio.CancelledError:
                cancelled = True
            return calls, cancelled


def test_mcp_stdio_persists_across_restart_and_isolates_namespaces(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    tools, first = _call(
        db_path,
        [
            (
                "remember",
                {
                    "text": "Andrey is a trader",
                    "namespace": "user-a",
                    "idempotency_key": "profile-name",
                    "provenance": {"source": "chat", "message_id": "m-1"},
                },
            ),
            (
                "remember",
                {
                    "text": "Elena is a designer",
                    "namespace": "user-b",
                },
            ),
        ],
    )
    assert {
        "remember",
        "recall",
        "feedback",
        "forget",
        "inspect_memory",
        "explain_memory",
        "manage_namespace",
    }.issubset(tools)
    first_id = _structured(first[0])["id"]

    _, second = _call(
        db_path,
        [
            (
                "recall",
                {
                    "query": "Who is the trader?",
                    "namespace": "user-a",
                    "top_k": 3,
                },
            ),
            (
                "recall",
                {
                    "query": "designer",
                    "namespace": "user-a",
                    "top_k": 3,
                },
            ),
            (
                "explain_memory",
                {
                    "memory_id": first_id,
                    "namespace": "user-a",
                },
            ),
        ],
    )
    recall = _structured(second[0])
    assert recall["results"][0]["id"] == first_id
    assert recall["results"][0]["text"] == "Andrey is a trader"
    assert all(item["namespace"] == "user-a" for item in recall["results"])
    assert all(
        item["text"] != "Elena is a designer"
        for item in _structured(second[1])["results"]
    )
    explanation = _structured(second[2])
    assert explanation["provenance"] == {
        "source": "chat",
        "message_id": "m-1",
    }
    assert explanation["audit_events"][0]["action"] == "remember"


def test_mcp_idempotency_feedback_forget_and_namespace_clear(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _, results = _call(
        db_path,
        [
            (
                "remember",
                {
                    "text": "Budget is 2000 dollars",
                    "namespace": "account",
                    "idempotency_key": "budget-v1",
                },
            ),
            (
                "remember",
                {
                    "text": "Budget is 2000 dollars",
                    "namespace": "account",
                    "idempotency_key": "budget-v1",
                },
            ),
        ],
    )
    created = _structured(results[0])
    replayed = _structured(results[1])
    assert created["created"] is True
    assert replayed == {
        "id": created["id"],
        "namespace": "account",
        "created": False,
        "idempotent_replay": True,
    }

    _, mutation_results = _call(
        db_path,
        [
            (
                "feedback",
                {
                    "memory_id": created["id"],
                    "namespace": "account",
                    "useful": True,
                    "reason": "correct recall",
                },
            ),
            (
                "inspect_memory",
                {
                    "memory_id": created["id"],
                    "namespace": "account",
                },
            ),
            (
                "forget",
                {
                    "memory_id": created["id"],
                    "namespace": "account",
                },
            ),
            (
                "manage_namespace",
                {
                    "namespace": "account",
                    "action": "stats",
                },
            ),
        ],
    )
    assert _structured(mutation_results[0])["accepted"] is True
    assert _structured(mutation_results[1])["priority"] > 1.0
    assert _structured(mutation_results[2])["deleted"] is True
    assert _structured(mutation_results[3])["stats"]["active_memories"] == 0


def test_mcp_rejects_invalid_and_destructive_requests(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _, results = _call(
        db_path,
        [
            ("remember", {"text": "", "namespace": "default"}),
            (
                "manage_namespace",
                {"namespace": "default", "action": "clear"},
            ),
            (
                "recall",
                {"query": "test", "namespace": "default", "top_k": 0},
            ),
        ],
    )
    assert all(result.isError for result in results)
    assert "must not be empty" in results[0].content[0].text
    assert "confirm=true" in results[1].content[0].text
    assert "top_k must be between" in results[2].content[0].text


def test_mcp_idempotency_key_rejects_conflicting_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _, results = _call(
        db_path,
        [
            (
                "remember",
                {
                    "text": "Original fact",
                    "namespace": "default",
                    "idempotency_key": "same-key",
                },
            ),
            (
                "remember",
                {
                    "text": "Conflicting fact",
                    "namespace": "default",
                    "idempotency_key": "same-key",
                },
            ),
        ],
    )
    assert results[0].isError is False
    assert results[1].isError is True
    assert "different payload" in results[1].content[0].text


def test_mcp_concurrent_calls_and_cancellation_do_not_corrupt_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    calls, cancelled = asyncio.run(_concurrent_session(db_path))
    assert cancelled is True
    assert all(result.isError is False for result in calls)
    assert len({_structured(result)["id"] for result in calls}) == 20

    _, results = _call(
        db_path,
        [
            (
                "manage_namespace",
                {"namespace": "parallel", "action": "stats"},
            ),
            (
                "recall",
                {
                    "query": "concurrent fact",
                    "namespace": "parallel",
                    "top_k": 20,
                },
            ),
        ],
    )
    assert _structured(results[0])["stats"]["active_memories"] == 20
    assert len(_structured(results[1])["results"]) == 20


def test_mcp_ttl_suppresses_stale_memory_and_confirmed_clear_is_scoped(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    _, first = _call(
        db_path,
        [
            (
                "remember",
                {
                    "text": "Temporary stale fact",
                    "namespace": "temporary",
                    "ttl_seconds": 0.15,
                },
            ),
            (
                "remember",
                {
                    "text": "Permanent fact",
                    "namespace": "permanent",
                },
            ),
        ],
    )
    assert all(result.isError is False for result in first)
    time.sleep(0.25)

    _, results = _call(
        db_path,
        [
            (
                "recall",
                {
                    "query": "stale fact",
                    "namespace": "temporary",
                },
            ),
            (
                "manage_namespace",
                {
                    "namespace": "temporary",
                    "action": "clear",
                    "confirm": True,
                },
            ),
            (
                "recall",
                {
                    "query": "permanent fact",
                    "namespace": "permanent",
                },
            ),
        ],
    )
    assert _structured(results[0])["results"] == []
    assert _structured(results[1])["deleted"] == 1
    assert _structured(results[2])["results"][0]["text"] == "Permanent fact"


def test_mcp_rejects_remote_http_bind_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wavemind.mcp_server import main

    with pytest.raises(SystemExit, match="Refusing a non-loopback"):
        main(
            [
                "--transport",
                "streamable-http",
                "--host",
                "0.0.0.0",
            ]
        )
