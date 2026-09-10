"""Bounded ordinary citation discovery shares live source authority on every page."""

import asyncio
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wavemind.brain.auth import BrainAuth
from wavemind.brain.http import mount_brain
from wavemind.brain.models import BrainError, Principal
from wavemind.brain.service import BrainService


def imported(service, owner, brain, text, source=None):
    file = {"name": "notes.txt", "content": text.encode()}
    if source:
        file["source_id"] = source
    preview = service.preview_import(principal=owner, brain_id=brain, files=[file])
    return service.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )["sources"][0]


def test_pages_versions_restart_and_live_authority(tmp_path):
    service, owner = BrainService(tmp_path), Principal("owner")
    brain = service.create_brain(principal=owner, title="Citations")["id"]
    source = imported(service, owner, brain, "A" * 17000)
    args = dict(principal=owner, brain_id=brain, source_id=source["id"], limit=1)
    page = service.list_source_citations(**args)
    assert page["citations"][0]["text"] == "A" * 8192
    assert page["next_cursor"] == page["citations"][0]["id"]
    service.close()
    service = BrainService(tmp_path)
    second = service.list_source_citations(**args, cursor=page["next_cursor"])
    assert second["citations"][0]["id"] != page["next_cursor"]
    last = service.list_source_citations(**args, cursor=second["next_cursor"])
    assert last["citations"][0]["text"] == "A" * 616
    assert last["next_cursor"] is None
    imported(service, owner, brain, "Updated", source["id"])
    assert service.list_source_citations(**args)["citations"][0]["text"] == "Updated"
    with pytest.raises(BrainError) as denied:
        service.list_source_citations(**args, cursor=page["next_cursor"])
    assert denied.value.code == "not_found"
    historical = service.list_source_citations(
        **args, versions="all", cursor=second["next_cursor"]
    )
    assert historical["citations"][0]["version"] == 1
    current = service.list_source_citations(
        **args, versions="all", cursor=historical["next_cursor"]
    )
    assert current["citations"][0]["version"] == 2
    service.change_source(
        principal=owner, brain_id=brain, source_id=source["id"], action="pause"
    )
    assert service.list_source_citations(**args)["citations"][0]["text"] == "Updated"
    for cap in [frozenset(), frozenset({("other-brain", source["id"])})]:
        with pytest.raises(BrainError) as denied:
            service.list_source_citations(
                **{**args, "principal": Principal("owner", source_refs=cap)}
            )
        assert denied.value.code == "not_found"
    service.change_source(
        principal=owner, brain_id=brain, source_id=source["id"], action="revoke"
    )
    with pytest.raises(BrainError) as denied:
        service.list_source_citations(**args, versions="all")
    assert denied.value.code == "not_found"
    service.close()


def test_http_and_real_mcp_listing_strict_schema(tmp_path):
    from wavemind.brain.mcp import build_brain_mcp_server

    auth = BrainAuth(tmp_path)
    secret = auth.bootstrap_owner()
    owner = auth.authenticate(secret)
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    brain = service.create_brain(principal=owner, title="HTTP citations")["id"]
    source = imported(service, owner, brain, "First citation")
    app = FastAPI()
    mount_brain(app, service, auth)
    server = build_brain_mcp_server(service, auth, secret)

    async def mcp_check():
        tools = await server.list_tools()
        assert "list_source_citations" in {tool.name for tool in tools}
        result = await server.call_tool(
            "list_source_citations",
            {
                "brain_id": brain,
                "source_id": source["id"],
                "limit": 1,
            },
        )
        assert result["citations"][0]["text"] == "First citation"

    asyncio.run(mcp_check())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        path = f"/brain/api/{brain}/sources/{source['id']}/citations"
        headers = {"Authorization": "Bearer " + secret}
        assert client.get(path, headers=headers).json()["next_cursor"] is None
        for query in [
            "limit=true",
            "limit=0",
            "limit=101",
            "limit=1&limit=2",
            "versions=latest",
            "principal=owner",
        ]:
            response = client.get(path + "?" + query, headers=headers)
            assert response.status_code == 422
            assert response.headers["cache-control"] == "no-store"


def test_actual_stdio_listing_and_startup_maintenance(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from brain.test_maintenance import queued_outcome

    auth = BrainAuth(tmp_path)
    secret = auth.bootstrap_owner()
    owner = auth.authenticate(secret)
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    brain = service.create_brain(principal=owner, title="MCP maintenance")["id"]
    source = queued_outcome(service, owner, brain)
    service.close()
    auth.close()

    async def verify():
        config = StdioServerParameters(
            command=sys.executable,
            args=["-m", "wavemind", "brain", "mcp", "--state-dir", str(tmp_path)],
            env={**os.environ, "WAVEMIND_BRAIN_TOKEN": secret},
        )
        async with stdio_client(config) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.call_tool(
                    "list_source_citations",
                    {"brain_id": brain, "source_id": source["id"], "limit": 1},
                )
                assert not listing.isError
                assert (
                    listing.structuredContent["citations"][0]["id"]
                    == source["citations"][0]["id"]
                )
                history = await session.call_tool(
                    "review_experience", {"brain_id": brain}
                )
                assert (
                    history.structuredContent["outcomes"][0]["integration_status"]
                    == "completed"
                )

    asyncio.run(verify())
