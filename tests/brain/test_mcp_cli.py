"""Real developer subprocesses and already-open MCP credential boundaries."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest


def run_cli(profile, *args, token=None):
    env = dict(os.environ)
    env.pop("WAVEMIND_BRAIN_TOKEN", None)
    if token is not None:
        env["WAVEMIND_BRAIN_TOKEN"] = token
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "brain",
            *args,
            "--state-dir",
            str(profile),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_init_restart_doctor_and_loopback_gate(tmp_path):
    first = run_cli(tmp_path, "init")
    assert first.returncode == 0
    payload = json.loads(first.stdout)
    assert payload["schema"] == "wavemind.brain_init.v1"
    token = payload["owner_secret"]
    assert token and "Python" in payload["notice"] and "D2" in payload["notice"]
    second = run_cli(tmp_path, "init")
    assert second.returncode == 2
    assert token not in second.stdout + second.stderr
    doctor = run_cli(tmp_path, "doctor", token=token)
    assert doctor.returncode == 0
    assert json.loads(doctor.stdout)["network_calls"] == 0
    assert token not in doctor.stdout + doctor.stderr
    denied = run_cli(tmp_path, "serve", "--host", "0.0.0.0", token=token)
    assert denied.returncode == 2
    assert "D3" in denied.stderr and token not in denied.stderr
    assert not (tmp_path / "brain-experience.sqlite3").exists()


def test_cli_backup_restore_export_and_new_destination(tmp_path):
    from wavemind.brain.auth import BrainAuth
    from wavemind.brain.service import BrainService

    original = tmp_path / "original"
    auth = BrainAuth(original)
    secret = auth.bootstrap_owner()
    owner = auth.authenticate(secret)
    service = BrainService(original, bootstrap_owner=auth.owner_identity)
    brain = service.create_brain(principal=owner, title="CLI roundtrip")["id"]
    draft = service.preview_import(
        principal=owner,
        brain_id=brain,
        files=[{"name": "note.md", "content": b"CLI roundtrip evidence"}],
    )
    service.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=draft["id"],
        accepted_ids=[draft["files"][0]["id"]],
    )
    service.close()
    auth.close()
    exported, archive = tmp_path / "export.json", tmp_path / "backup.zip"
    result = run_cli(
        original,
        "export",
        "--brain-id",
        brain,
        "--destination",
        str(exported),
        token=secret,
    )
    assert result.returncode == 0
    assert (
        json.loads(exported.read_text(encoding="utf-8"))["records"]["chunks"][0]["text"]
        == "CLI roundtrip evidence"
    )
    repeated = run_cli(
        original,
        "export",
        "--brain-id",
        brain,
        "--destination",
        str(exported),
        token=secret,
    )
    assert repeated.returncode == 2 and "destination_exists" in repeated.stderr
    result = run_cli(
        original,
        "backup",
        "--brain-id",
        brain,
        "--destination",
        str(archive),
        token=secret,
    )
    assert result.returncode == 0
    assert "import_previews_not_restored" in json.loads(result.stdout)["warnings"]
    target = tmp_path / "target"
    initialized = run_cli(target, "init")
    assert initialized.returncode == 0
    target_secret = json.loads(initialized.stdout)["owner_secret"]
    restored = run_cli(
        target, "restore", "--archive", str(archive), token=target_secret
    )
    assert restored.returncode == 0
    assert json.loads(restored.stdout)["status"] == "restored"
    doctor = run_cli(target, "doctor", token=target_secret)
    assert doctor.returncode == 0
    assert json.loads(doctor.stdout)["brains"][0]["id"] == brain
    assert (
        secret not in restored.stdout + restored.stderr + doctor.stdout + doctor.stderr
    )


def test_cli_refuses_linked_profile_and_credential_file(tmp_path):
    target, link = tmp_path / "real", tmp_path / "linked"
    target.mkdir()
    junction = False
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Filesystem does not permit symbolic links")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        if result.returncode:
            pytest.skip("Windows does not permit test symlink or junction creation")
        junction = True
    try:
        rejected = run_cli(link, "init")
        assert rejected.returncode == 2
        assert "invalid_path" in rejected.stderr
        assert not (target / "brain-auth.sqlite3").exists()
        initialized = run_cli(target, "init")
        assert initialized.returncode == 0
        rejected = run_cli(
            target, "doctor", "--token-file", str(link / "credential.txt")
        )
        assert rejected.returncode == 2 and "invalid_path" in rejected.stderr
    finally:
        if junction:
            os.rmdir(link)
        else:
            link.unlink()


def test_cli_rejects_linked_internal_database_before_bootstrap(tmp_path):
    profile, outside = tmp_path / "profile", tmp_path / "outside"
    profile.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unrelated sentinel")
    link = profile / "brain.sqlite3"
    junction = False
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Filesystem does not permit symbolic links")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True
        )
        if result.returncode:
            pytest.skip("Windows does not permit test symlink or junction creation")
        junction = True
    try:
        result = run_cli(profile, "init")
        assert result.returncode == 2
        assert "invalid_path" in result.stderr
        assert sentinel.read_bytes() == b"unrelated sentinel"
        assert not (profile / "brain-auth.sqlite3").exists()
    finally:
        if junction:
            os.rmdir(link)
        else:
            link.unlink()


def test_brain_mcp_cold_process_has_complete_settings_and_typed_tools(tmp_path):
    pytest.importorskip("mcp")
    script = """
import asyncio, json, sys, warnings
from pathlib import Path
from pydantic_settings import IncompleteFieldDefinitionWarning
warnings.simplefilter("error", IncompleteFieldDefinitionWarning)
from wavemind.brain.auth import BrainAuth
from wavemind.brain.service import BrainService
from wavemind.brain.mcp import build_brain_mcp_server
auth = BrainAuth(Path(sys.argv[1]))
token = auth.bootstrap_owner()
service = BrainService(Path(sys.argv[1]), bootstrap_owner=auth.owner_identity)
try:
    server = build_brain_mcp_server(service, auth, token)
    print(json.dumps([{ "name":t.name, "schema":t.inputSchema } for t in asyncio.run(server.list_tools())]))
finally:
    service.close()
    auth.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and result.stderr == ""
    tools = {t["name"]: t["schema"] for t in json.loads(result.stdout)}
    assert tools["build_context"]["additionalProperties"] is False
    assert tools["build_context"]["properties"]["brain_id"]["type"] == "string"
    assert tools["review_records"]["properties"]["record_type"]["enum"] == [
        "entity",
        "relation",
    ]


def test_two_live_mcp_connections_recheck_revoke_and_source_cap(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from wavemind.brain.auth import BrainAuth
    from wavemind.brain.service import BrainService

    auth = BrainAuth(tmp_path)
    secret = auth.bootstrap_owner()
    owner = auth.authenticate(secret)
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    brain = service.create_brain(principal=owner, title="MCP boundary")["id"]

    def import_source(text, **extra):
        preview = service.preview_import(
            principal=owner,
            brain_id=brain,
            files=[{"name": "note.md", "content": text.encode()}],
            **extra,
        )
        return service.commit_import(
            principal=owner,
            brain_id=brain,
            preview_id=preview["id"],
            accepted_ids=[preview["files"][0]["id"]],
        )["sources"][0]

    first = import_source("Visible source")
    hidden = import_source("Hidden by credential cap")
    grant = auth.issue_agent(
        principal=owner,
        brain_ids=[brain],
        source_grants={brain: [first["id"]]},
        operations=["read"],
        label="Scoped MCP",
    )
    independent = auth.issue_agent(
        principal=owner, brain_ids=[brain], operations=["read"], label="Independent MCP"
    )

    async def exercise():
        async with AsyncExitStack() as stack:
            sessions = []
            for credential in (grant, independent):
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "wavemind",
                        "brain",
                        "mcp",
                        "--state-dir",
                        str(tmp_path),
                    ],
                    cwd=Path(__file__).resolve().parents[2],
                    env={**os.environ, "WAVEMIND_BRAIN_TOKEN": credential["token"]},
                )
                read, write = await stack.enter_async_context(stdio_client(parameters))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                sessions.append(session)
            scoped, other = sessions
            tools = await scoped.list_tools()
            assert {
                "build_context",
                "read_citation",
                "review_records",
                "recheck_dependencies",
            } <= {t.name for t in tools.tools}
            ok = await scoped.call_tool(
                "read_citation",
                {"brain_id": brain, "citation_id": first["citations"][0]["id"]},
            )
            assert not ok.isError
            denied = await scoped.call_tool(
                "read_citation",
                {"brain_id": brain, "citation_id": hidden["citations"][0]["id"]},
            )
            assert denied.isError
            context = await scoped.call_tool(
                "build_context",
                {"brain_id": brain, "question": "Hidden by credential cap"},
            )
            assert not context.isError
            assert "Hidden by credential cap" not in json.dumps(
                context.structuredContent.get("citations", [])
            )
            forged = await scoped.call_tool(
                "build_context",
                {
                    "brain_id": brain,
                    "question": "notes",
                    "principal": {"identity": owner.identity},
                },
            )
            assert forged.isError
            restricted = import_source(
                "Restricted while connected", new_source_readers=[]
            )
            for session in sessions:
                result = await session.call_tool(
                    "read_citation",
                    {
                        "brain_id": brain,
                        "citation_id": restricted["citations"][0]["id"],
                    },
                )
                assert result.isError
            auth.revoke_token(principal=owner, token_id=grant["token_id"])
            for name, arguments in [
                ("build_context", {"brain_id": brain, "question": "notes"}),
                (
                    "read_citation",
                    {"brain_id": brain, "citation_id": first["citations"][0]["id"]},
                ),
            ]:
                result = await scoped.call_tool(name, arguments)
                assert result.isError
                result = await other.call_tool(name, arguments)
                assert not result.isError
            service.set_member(
                principal=owner,
                brain_id=brain,
                identity=independent["identity"],
                role=None,
            )
            denied = await other.call_tool(
                "read_citation",
                {"brain_id": brain, "citation_id": first["citations"][0]["id"]},
            )
            assert denied.isError

    try:
        asyncio.run(exercise())
    finally:
        service.close()
        auth.close()
