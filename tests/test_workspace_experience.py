from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wavemind import WaveMind
from wavemind.api import create_app
from wavemind.experience import ExperienceStatus
from wavemind.experience_runtime import AgentEventKind, VerificationSource
from wavemind.integrations.mcp_experience import ExperienceMCPAdapter
from wavemind.workspace_experience import (
    WorkspaceEvent,
    WorkspaceExperienceManager,
    WorkspacePathError,
    initialize_workspace,
    render_runbook_markdown,
    resolve_workspace_identity,
    workspace_mcp_config,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _make_repo(path: Path, *, remote: str = "https://github.com/example/project.git") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "WaveMind Test")
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _git(path, "add", "pyproject.toml")
    _git(path, "commit", "-m", "initial")
    _git(path, "remote", "add", "origin", remote)
    return path


def _verified_workspace_run(
    manager: WorkspaceExperienceManager,
    *,
    suffix: str,
    run_id: str | None = None,
) -> str:
    started = manager.start_run(
        query="pytest cache permission failure",
        objective="fix pytest cache permission failure",
        domain="python",
        task_type="pytest-cache",
        tools=("remove-cache", "pytest"),
        run_id=run_id or f"run-{suffix}",
    )
    call = WorkspaceEvent(
        id=f"call-{suffix}",
        run_id=started["run_id"],
        session_id=started["session_id"],
        task_id=started["task_id"],
        kind=AgentEventKind.TOOL_CALL,
        sequence=started["next_sequence"],
        tool_name="remove-cache",
        payload={"input": {"path": ".pytest_cache"}},
    )
    result = WorkspaceEvent(
        id=f"result-{suffix}",
        run_id=started["run_id"],
        session_id=started["session_id"],
        task_id=started["task_id"],
        kind=AgentEventKind.TOOL_RESULT,
        sequence=started["next_sequence"] + 1,
        parent_event_id=call.id,
        tool_name="remove-cache",
        payload={"success": True, "output": {"removed": ".pytest_cache"}},
    )
    assert manager.capture_event(call)["inserted"] is True
    assert manager.capture_event(call)["inserted"] is False
    assert manager.capture_event(result)["inserted"] is True
    final = manager.verify_run(
        run_id=started["run_id"],
        evidence_id=f"pytest-pass-{suffix}",
        source=VerificationSource.TEST,
        verifier="pytest",
        success=True,
        score=1.0,
        reference="pytest://tests",
    )
    assert final["verified"] is True
    return final["candidate_ids"][0]


def test_workspace_identity_is_stable_for_clone_and_isolated_for_fork_user_and_private_paths(
    tmp_path: Path,
) -> None:
    source = _make_repo(tmp_path / "source")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(source), str(clone)], check=True, capture_output=True, text=True)
    _git(clone, "remote", "set-url", "origin", "https://github.com/example/project.git")
    worktree = tmp_path / "worktree"
    _git(source, "worktree", "add", "-b", "feature", str(worktree))

    first = resolve_workspace_identity(source, workspace_id="main", tenant_id="t", user_id="u")
    second = resolve_workspace_identity(clone, workspace_id="main", tenant_id="t", user_id="u")
    branch = resolve_workspace_identity(worktree, workspace_id="main", tenant_id="t", user_id="u")
    fork = _make_repo(tmp_path / "fork", remote="https://github.com/other/project.git")
    fork_identity = resolve_workspace_identity(fork, workspace_id="main", tenant_id="t", user_id="u")
    other_user = resolve_workspace_identity(source, workspace_id="main", tenant_id="t", user_id="other")

    assert first.namespace == second.namespace
    assert first.namespace == branch.namespace
    assert first.namespace != fork_identity.namespace
    assert first.namespace != other_user.namespace

    private_root = tmp_path / ".codex" / "history"
    private_root.mkdir(parents=True)
    with pytest.raises(WorkspacePathError):
        resolve_workspace_identity(private_root, workspace_id="private")


def test_workspace_capture_review_packet_restart_and_bundle_parity(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    config = initialize_workspace(repo, workspace_id="agent", tenant_id="tenant", user_id="user")
    manager = WorkspaceExperienceManager(config)
    candidate_id = _verified_workspace_run(manager, suffix="one")
    queue = manager.review_queue()
    assert queue[0]["experience"]["id"] == candidate_id
    assert queue[0]["runbook"]["schema"] == "wavemind.workspace_runbook.v1"
    assert "pytest-cache" in json.dumps(queue[0]["runbook"], sort_keys=True)
    assert render_runbook_markdown(queue[0]["runbook"]).startswith("# ")
    assert manager.approve(candidate_id, evidence_id="operator-approve") == ExperienceStatus.ACTIVE.value
    packet = manager.packet(
        "pytest cache permission failure",
        domain="python",
        task_type="pytest-cache",
        tools=("remove-cache",),
    )
    assert packet["abstain"] is False
    assert packet["selected_citations"]
    exported = manager.export_bundle()
    manager.close()

    reopened = WorkspaceExperienceManager.open(repo)
    replayed = reopened.packet(
        "pytest cache permission failure",
        domain="python",
        task_type="pytest-cache",
        tools=("remove-cache",),
    )
    assert replayed["selected_citations"] == packet["selected_citations"]
    reopened.close()

    config_path = Path(config.config_path)
    Path(config.experience_db_path).unlink()
    fresh = WorkspaceExperienceManager.open(config_path)
    report = fresh.import_bundle(exported)
    assert report["parity"] == 1.0
    imported = fresh.packet(
        "pytest cache permission failure",
        domain="python",
        task_type="pytest-cache",
        tools=("remove-cache",),
    )
    assert imported["selected_citations"] == packet["selected_citations"]
    fresh.close()


def test_workspace_edit_approve_supersedes_and_rollback_preserves_provenance(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    config = initialize_workspace(repo, workspace_id="agent", tenant_id="tenant", user_id="user")
    manager = WorkspaceExperienceManager(config)
    try:
        candidate_id = _verified_workspace_run(manager, suffix="edit")
        edited = manager.edit_and_approve(
            candidate_id,
            evidence_id="operator-edit-approve",
            title="Edited pytest cache recovery",
            content="When pytest cache permission fails, remove .pytest_cache and rerun pytest.",
            reason="tighten runbook wording",
        )
        edited_id = edited["experience_id"]
        assert edited["status"] == "active"
        assert edited["experience"]["supersedes_id"] == candidate_id
        assert edited["runbook"]["evidence_count"] >= 2
        original = manager.store.get(candidate_id)
        assert original is not None
        assert original.status == ExperienceStatus.SUPERSEDED
        packet = manager.packet(
            "pytest cache permission failure",
            domain="python",
            task_type="pytest-cache",
            tools=("remove-cache",),
        )
        assert packet["selected_citations"] == [f"experience:{edited_id}@v2"]

        restored = manager.rollback(edited_id, reason="restore original candidate")
        assert restored["rollback_of_id"] == edited_id
        assert restored["supersedes_id"] == edited_id
        assert restored["status"] == "active"
        rolled_back = manager.store.get(edited_id)
        assert rolled_back is not None
        assert rolled_back.status == ExperienceStatus.ROLLED_BACK
        after_rollback = manager.packet(
            "pytest cache permission failure",
            domain="python",
            task_type="pytest-cache",
            tools=("remove-cache",),
        )
        assert after_rollback["selected_citations"] == [
            f"experience:{restored['id']}@v3"
        ]
        assert any(
            item["experience_id"] == edited_id and item["status"] == "rolled_back"
            for item in after_rollback["excluded"]
        )
        audit_actions = {
            event.action
            for event in manager.store.audit_events(limit=20)
        }
        assert {"superseded", "rolled_back"}.issubset(audit_actions)
    finally:
        manager.close()


def test_workspace_negative_controls_abstain_and_bundle_namespace_mismatch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    config = initialize_workspace(repo, workspace_id="agent", tenant_id="tenant", user_id="user")
    manager = WorkspaceExperienceManager(config)
    candidate_id = _verified_workspace_run(manager, suffix="one")
    assert manager.approve(candidate_id, evidence_id="operator-approve") == "active"
    irrelevant = manager.packet("kubernetes helm rollback timeout", domain="ops", task_type="helm")
    assert irrelevant["abstain"] is True
    exported = manager.export_bundle()
    manager.close()

    other_config = initialize_workspace(
        repo,
        workspace_id="other-agent",
        tenant_id="tenant",
        user_id="user",
        force=True,
    )
    other = WorkspaceExperienceManager(other_config)
    assert other.packet("pytest cache permission failure", domain="python", task_type="pytest-cache")[
        "abstain"
    ] is True
    with pytest.raises(ValueError, match="namespace"):
        other.import_bundle(exported)
    other.close()


def test_workspace_protected_delete_and_mcp_config(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    config = initialize_workspace(repo, workspace_id="agent")
    manager = WorkspaceExperienceManager(config)
    candidate_id = _verified_workspace_run(manager, suffix="one")
    assert manager.approve(candidate_id, evidence_id="operator-approve") == "active"
    with pytest.raises(ValueError, match="confirmation"):
        manager.protected_delete(candidate_id, reason="cleanup", confirmation="delete:wrong")
    assert manager.protected_delete(
        candidate_id,
        reason="cleanup",
        confirmation=f"delete:{candidate_id}",
    )
    assert manager.packet("pytest cache permission failure", domain="python", task_type="pytest-cache")[
        "abstain"
    ] is True
    mcp = workspace_mcp_config(config)
    assert mcp["mcpServers"]["wavemind-workspace"]["command"] == "wavemind-mcp"
    assert config.identity.namespace in json.dumps(mcp, sort_keys=True)
    manager.close()


def test_workspace_cli_init_doctor_status_and_mcp_config(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    commands = [
        [
            "workspace",
            "--root",
            str(repo),
            "init",
            "--workspace-id",
            "cli-agent",
            "--json",
        ],
        ["workspace", "--root", str(repo), "doctor", "--json"],
        ["workspace", "--root", str(repo), "status", "--json"],
        ["workspace", "--root", str(repo), "mcp-config", "--json"],
    ]
    outputs = []
    for command in commands:
        completed = subprocess.run(
            [sys.executable, "-m", "wavemind.cli", *command],
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(completed.stdout))
    assert outputs[0]["schema"] == "wavemind.workspace_config.v1"
    assert outputs[1]["status"] == "pass"
    assert outputs[2]["schema"] == "wavemind.workspace_status.v1"
    assert "wavemind-workspace" in outputs[3]["mcpServers"]
    demo = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind.cli",
            "workspace",
            "--root",
            str(repo),
            "demo",
            "--workspace-id",
            "cli-agent",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    demo_payload = json.loads(demo.stdout)
    assert demo_payload["schema"] == "wavemind.workspace_demo.v1"
    assert demo_payload["packet"]["abstain"] is False
    assert demo_payload["packet"]["selected_citations"]
    assert "wavemind-workspace" in demo_payload["mcp"]["mcpServers"]


def test_workspace_http_capture_review_and_cross_process_replay(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    evidence_file = repo / "evidence.log"
    evidence_file.write_text("pytest passed after cache cleanup\n", encoding="utf-8")
    initialize_workspace(repo, workspace_id="http-agent", tenant_id="tenant", user_id="user")
    mind = WaveMind(db_path=tmp_path / "memory.sqlite3")
    try:
        with TestClient(create_app(mind=mind)) as client:
            start = client.post(
                "/workspace/runtime/runs",
                json={
                    "root": str(repo),
                    "query": "pytest cache permission failure",
                    "objective": "fix pytest cache permission failure",
                    "domain": "python",
                    "task_type": "pytest-cache",
                    "run_id": "http-run",
                    "session_id": "http-session",
                    "task_id": "http-task",
                    "tools": ["remove-cache"],
                },
            )
            assert start.status_code == 200
            started = start.json()
            assert started["idempotent_replay"] is False
            replay = client.post(
                "/workspace/runtime/runs",
                json={
                    "root": str(repo),
                    "query": "pytest cache permission failure",
                    "objective": "fix pytest cache permission failure",
                    "domain": "python",
                    "task_type": "pytest-cache",
                    "run_id": "http-run",
                    "session_id": "http-session",
                    "task_id": "http-task",
                    "tools": ["remove-cache"],
                },
            )
            assert replay.status_code == 200
            assert replay.json()["idempotent_replay"] is True
            assert replay.json()["next_sequence"] == started["next_sequence"]

            call = {
                "root": str(repo),
                "id": "http-call",
                "run_id": "http-run",
                "session_id": "http-session",
                "task_id": "http-task",
                "kind": "tool.call",
                "sequence": started["next_sequence"],
                "tool_name": "remove-cache",
                "payload": {
                    "input": {"path": ".pytest_cache"},
                    "api_key": "sk-test-secret",
                    "attachments": [
                        {"label": "pytest-log", "path": "evidence.log"},
                        {"label": "inline-note", "content": {"status": "pass"}},
                    ],
                },
            }
            event = client.post("/workspace/runtime/events", json=call)
            assert event.status_code == 200
            assert event.json()["inserted"] is True
            event_payload = event.json()["event"]["payload"]
            assert event_payload["api_key"] == "[REDACTED]"
            assert event_payload["attachments"][0]["sha256"] == hashlib.sha256(
                evidence_file.read_bytes()
            ).hexdigest()
            assert event_payload["attachments"][0]["path"] == "evidence.log"
            assert "content" not in event_payload["attachments"][1]
            duplicate = client.post("/workspace/runtime/events", json=call)
            assert duplicate.status_code == 200
            assert duplicate.json()["inserted"] is False
            result = client.post(
                "/workspace/runtime/events",
                json={
                    "root": str(repo),
                    "id": "http-result",
                    "run_id": "http-run",
                    "session_id": "http-session",
                    "task_id": "http-task",
                    "kind": "tool.result",
                    "sequence": started["next_sequence"] + 1,
                    "parent_event_id": "http-call",
                    "tool_name": "remove-cache",
                    "payload": {"success": True, "output": {"removed": ".pytest_cache"}},
                },
            )
            assert result.status_code == 200
            verified = client.post(
                "/workspace/runtime/runs/http-run/verify",
                json={
                    "root": str(repo),
                    "evidence_id": "http-pytest-pass",
                    "source": "test",
                    "verifier": "pytest",
                    "success": True,
                    "score": 1.0,
                    "reference": "pytest://tests",
                },
            )
            assert verified.status_code == 200
            candidate_id = verified.json()["candidate_ids"][0]

            queue = client.post("/workspace/review", json={"root": str(repo)})
            assert queue.status_code == 200
            assert queue.json()["items"][0]["experience"]["id"] == candidate_id
            approved = client.post(
                f"/workspace/runtime/{candidate_id}/edit-and-approve",
                json={
                    "root": str(repo),
                    "evidence_id": "http-operator-edit-approve",
                    "reason": "tighten HTTP runbook",
                    "title": "HTTP pytest cache recovery",
                    "content": (
                        "When pytest cache permission fails over HTTP, remove "
                        ".pytest_cache and rerun pytest."
                    ),
                },
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "active"
            edited_id = approved.json()["experience_id"]
            packet = client.post(
                "/workspace/packet",
                json={
                    "root": str(repo),
                    "query": "pytest cache permission failure",
                    "domain": "python",
                    "task_type": "pytest-cache",
                    "tools": ["remove-cache"],
                },
            )
            assert packet.status_code == 200
            assert packet.json()["abstain"] is False
            assert packet.json()["selected_citations"] == [f"experience:{edited_id}@v2"]

            escaped = dict(call)
            escaped["id"] = "http-escaped"
            escaped["payload"] = {"attachments": [{"label": "bad", "path": "../secret.txt"}]}
            escaped_result = client.post("/workspace/runtime/events", json=escaped)
            assert escaped_result.status_code == 422

            cancelled_start = client.post(
                "/workspace/runtime/runs",
                json={
                    "root": str(repo),
                    "query": "cancelled task",
                    "objective": "cancel cancelled task",
                    "domain": "python",
                    "task_type": "cancel",
                    "run_id": "http-cancel",
                },
            )
            assert cancelled_start.status_code == 200
            cancelled = client.post(
                "/workspace/runtime/runs/http-cancel/cancel",
                json={
                    "root": str(repo),
                    "evidence_id": "operator-cancel",
                    "reason": "operator cancelled cleanly",
                },
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["verified"] is True
            assert cancelled.json()["verification"]["success"] is False
    finally:
        mind.close()

    other_process = WorkspaceExperienceManager.open(repo)
    try:
        replayed = other_process.packet(
            "pytest cache permission failure",
            domain="python",
            task_type="pytest-cache",
            tools=("remove-cache",),
        )
        assert replayed["selected_citations"] == [f"experience:{edited_id}@v2"]
    finally:
        other_process.close()


def test_workspace_mcp_adapter_uses_same_runtime_and_namespace(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    config = initialize_workspace(repo, workspace_id="mcp-agent", tenant_id="tenant", user_id="user")
    manager = WorkspaceExperienceManager(config)
    try:
        adapter = ExperienceMCPAdapter(manager.compiler, manager.runtime)
        namespace = config.identity.namespace
        started = adapter.call_tool(
            "start_experience_run",
            {
                "namespace": namespace,
                "query": "pytest cache permission failure",
                "objective": "fix pytest cache permission failure",
                "domain": "python",
                "task_type": "pytest-cache",
                "tools": ["remove-cache"],
                "run_id": "mcp-run",
                "session_id": "mcp-session",
                "task_id": "mcp-task",
            },
        )
        assert started["run_id"] == "mcp-run"
        call = adapter.call_tool(
            "capture_experience_event",
            {
                "namespace": namespace,
                "run_id": "mcp-run",
                "kind": "tool.call",
                "tool_name": "remove-cache",
                "payload": {"input": {"path": ".pytest_cache"}},
            },
        )
        assert call["run_id"] == "mcp-run"
        adapter.call_tool(
            "capture_experience_event",
            {
                "namespace": namespace,
                "run_id": "mcp-run",
                "kind": "tool.result",
                "tool_name": "remove-cache",
                "success": True,
                "parent_event_id": call["event_id"],
                "payload": {"output": {"removed": ".pytest_cache"}},
            },
        )
        finalized = adapter.call_tool(
            "verify_experience_run",
            {
                "namespace": namespace,
                "run_id": "mcp-run",
                "evidence_id": "mcp-pytest-pass",
                "source": "test",
                "verifier": "pytest",
                "success": True,
                "score": 1.0,
            },
        )
        candidate_id = finalized["candidate_ids"][0]
        status = adapter.call_tool(
            "approve_experience",
            {
                "namespace": namespace,
                "experience_id": candidate_id,
                "evidence_id": "mcp-operator-approve",
            },
        )
        assert status["status"] == "active"
        packet = manager.packet(
            "pytest cache permission failure",
            domain="python",
            task_type="pytest-cache",
            tools=("remove-cache",),
        )
        assert packet["selected_citations"] == [f"experience:{candidate_id}@v1"]
    finally:
        manager.close()
