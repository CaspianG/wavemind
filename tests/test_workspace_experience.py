from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.experience import ExperienceStatus
from wavemind.experience_runtime import AgentEventKind, VerificationSource
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
