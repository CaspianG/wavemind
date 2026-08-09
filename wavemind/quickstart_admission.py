from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)
from .onboarding import initialize_project


SCHEMA = "wavemind.quickstart_admission.v1"
MAX_FIRST_SUCCESS_SECONDS = 300.0


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float = MAX_FIRST_SUCCESS_SECONDS,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _json_output(stdout: str) -> dict[str, Any]:
    candidates = [index for index, char in enumerate(stdout) if char == "{"]
    for index in candidates:
        try:
            value = json.loads(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError(f"command did not emit a JSON object: {stdout[-500:]}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _python_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root) if not existing else os.pathsep.join((str(root), existing))
    env["PYTHON"] = sys.executable
    return env


def _run_twice(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> tuple[list[dict[str, Any]], float]:
    payloads: list[dict[str, Any]] = []
    first_seconds = 0.0
    for index in range(2):
        started = time.perf_counter()
        result = _run(command, cwd=cwd, env=env)
        elapsed = time.perf_counter() - started
        if index == 0:
            first_seconds = elapsed
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        payloads.append(_json_output(result.stdout))
    return payloads, first_seconds


def _check(check_id: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "action_required",
        "evidence": evidence,
    }


def _run_python(project: Path, env: Mapping[str, str]) -> dict[str, Any]:
    payloads, first_seconds = _run_twice(
        [sys.executable, "app.py"], cwd=project, env=env
    )
    first, second = payloads
    same_id = first["remember"]["experience_id"] == second["remember"]["experience_id"]
    passed = (
        first.get("schema") == "wavemind.onboarding.python.v1"
        and first["remember"]["created"] is True
        and second["remember"]["created"] is False
        and same_id
        and bool(second["recall"]["items"])
        and bool(second["explain"])
        and first_seconds <= MAX_FIRST_SUCCESS_SECONDS
    )
    return _check(
        "python-quickstart",
        passed,
        {"first_seconds": first_seconds, "same_id_after_restart": same_id},
    )


def _run_mcp(project: Path, env: Mapping[str, str]) -> dict[str, Any]:
    payloads, first_seconds = _run_twice(
        [sys.executable, "verify_flow.py"], cwd=project, env=env
    )
    first, second = payloads
    same_id = first["remember"]["experience_id"] == second["remember"]["experience_id"]
    passed = (
        first.get("schema") == "wavemind.onboarding.mcp.v1"
        and first["remember"]["created"] is True
        and second["remember"]["created"] is False
        and same_id
        and bool(second["recall"]["items"])
        and bool(second["explain"]["items"])
        and first_seconds <= MAX_FIRST_SUCCESS_SECONDS
    )
    return _check(
        "mcp-quickstart",
        passed,
        {"first_seconds": first_seconds, "same_id_after_restart": same_id},
    )


def _run_typescript(project: Path, env: Mapping[str, str]) -> dict[str, Any]:
    npm = shutil.which("npm")
    if npm is None:
        return _check("typescript-quickstart", False, {"error": "npm is missing"})
    started = time.perf_counter()
    result = _run([npm, "run", "quickstart"], cwd=project, env=env)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        return _check(
            "typescript-quickstart",
            False,
            {"returncode": result.returncode, "stderr": result.stderr[-1000:]},
        )
    payload = _json_output(result.stdout)
    persistence = payload.get("persistence") or {}
    passed = (
        payload.get("schema") == "wavemind.onboarding.typescript.restart.v1"
        and persistence.get("same_memory_id") is True
        and persistence.get("server_restarted") is True
        and bool(payload.get("restarted", {}).get("explain"))
        and elapsed <= MAX_FIRST_SUCCESS_SECONDS
    )
    return _check(
        "typescript-quickstart",
        passed,
        {"first_seconds": elapsed, "persistence": persistence},
    )


def _run_docker(
    project: Path,
    env: Mapping[str, str],
    *,
    image: str | None,
) -> dict[str, Any]:
    docker = shutil.which("docker")
    if docker is None or not image:
        return _check(
            "docker-quickstart",
            False,
            {"error": "Docker and an exact release-candidate image are required"},
        )
    compose_env = dict(env)
    compose_env["WAVEMIND_IMAGE"] = image
    compose_env["WAVEMIND_PORT"] = str(_free_port())
    compose_env["COMPOSE_PROJECT_NAME"] = f"wm-quickstart-{uuid.uuid4().hex[:10]}"
    started = time.perf_counter()
    first: dict[str, Any] = {}
    second: dict[str, Any] = {}
    diagnostics = ""
    try:
        up = _run(
            [docker, "compose", "up", "-d", "--no-build", "wavemind"],
            cwd=project,
            env=compose_env,
            timeout=120,
        )
        if up.returncode != 0:
            raise RuntimeError(up.stderr or up.stdout)
        first_run = _run(
            [docker, "compose", "run", "--rm", "verify"],
            cwd=project,
            env=compose_env,
            timeout=120,
        )
        if first_run.returncode != 0:
            raise RuntimeError(first_run.stderr or first_run.stdout)
        first = _json_output(first_run.stdout)
        restart = _run(
            [docker, "compose", "restart", "wavemind"],
            cwd=project,
            env=compose_env,
            timeout=60,
        )
        if restart.returncode != 0:
            raise RuntimeError(restart.stderr or restart.stdout)
        second_run = _run(
            [docker, "compose", "run", "--rm", "verify"],
            cwd=project,
            env=compose_env,
            timeout=120,
        )
        if second_run.returncode != 0:
            raise RuntimeError(second_run.stderr or second_run.stdout)
        second = _json_output(second_run.stdout)
    except (RuntimeError, ValueError) as exc:
        diagnostics = str(exc)[-1000:]
    finally:
        _run(
            [docker, "compose", "down", "--remove-orphans"],
            cwd=project,
            env=compose_env,
            timeout=90,
        )
    elapsed = time.perf_counter() - started
    passed = (
        first.get("schema") == "wavemind.onboarding.docker.v1"
        and second.get("schema") == "wavemind.onboarding.docker.v1"
        and first.get("remember", {}).get("id") == second.get("remember", {}).get("id")
        and second.get("remember", {}).get("idempotent_replay") is True
        and bool(second.get("recall"))
        and bool(second.get("feedback", {}).get("ok"))
        and bool(second.get("explain"))
        and elapsed <= MAX_FIRST_SUCCESS_SECONDS
    )
    return _check(
        "docker-quickstart",
        passed,
        {"first_seconds": elapsed, "image": image, "error": diagnostics or None},
    )


def run_quickstart_admission(
    *,
    project_root: str | Path,
    docker_image: str | None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    owned_temp = None
    if temp_root is None:
        owned_temp = tempfile.TemporaryDirectory(prefix="wavemind-quickstart-admission-")
        workspace = Path(owned_temp.name)
    else:
        workspace = Path(temp_root).resolve() / f"run-{uuid.uuid4().hex[:10]}"
        workspace.mkdir(parents=True, exist_ok=False)
    projects: dict[str, Path] = {}
    for template in ("python", "mcp", "typescript", "docker"):
        projects[template] = workspace / template
        initialize_project(
            projects[template], template=template, name=f"safe-{template}"
        )
    env = _python_env(root)
    checks = [
        _run_python(projects["python"], env),
        _run_mcp(projects["mcp"], env),
        _run_typescript(projects["typescript"], env),
        _run_docker(projects["docker"], env, image=docker_image),
    ]
    report = {
        "schema": SCHEMA,
        "status": "admitted" if all(check["passed"] for check in checks) else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": repository_commit(root),
        "max_first_success_seconds": MAX_FIRST_SUCCESS_SECONDS,
        "package_sources": {
            "python": "repository-local package under test",
            "mcp": "repository-local package under test",
            "typescript": "repository-local @wavemind/http package",
            "docker": docker_image,
        },
        "checks": checks,
        "source_manifest": build_source_manifest(
            root,
            [
                "wavemind/onboarding.py",
                "wavemind/quickstart_admission.py",
                "sdk/typescript/package.json",
                "sdk/typescript/src/index.ts",
                "Dockerfile",
            ],
        ),
    }
    if owned_temp is not None:
        owned_temp.cleanup()
    return attach_artifact_integrity(report)


def validate_quickstart_artifact(
    report: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(report)
    if report.get("schema") != SCHEMA:
        errors.append("quickstart schema is invalid")
    if report.get("source_sha") != expected_source_sha:
        errors.append("quickstart source SHA mismatch")
    manifest = report.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("quickstart source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), manifest, require_current_files=True
            )
        )
    checks = report.get("checks")
    expected = {
        "python-quickstart",
        "mcp-quickstart",
        "typescript-quickstart",
        "docker-quickstart",
    }
    observed = {
        str(check.get("id"))
        for check in checks or []
        if isinstance(check, Mapping) and check.get("passed") is True
    }
    if observed != expected:
        errors.append("all four quickstarts must pass")
    if report.get("status") != "admitted":
        errors.append("quickstart status is not admitted")
    return errors
