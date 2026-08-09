from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.onboarding import initialize_project, run_doctor


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing
        else os.pathsep.join((str(PROJECT_ROOT), existing))
    )
    return env


def test_python_starter_runs_twice_and_returns_persistent_packet(tmp_path):
    project = tmp_path / "starter"
    payload = initialize_project(project, template="python", name="Demo Agent")

    assert payload["status"] == "created"
    assert payload["name"] == "demo-agent"
    assert payload["next_command"] == "python app.py"
    manifest = json.loads(
        (project / ".wavemind-project.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "wavemind.project.v1"
    assert manifest["template"] == "python"

    runs = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "app.py"],
            cwd=project,
            env=_python_env(),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        onboarding = json.loads(result.stdout)
        runs.append(onboarding)
        assert onboarding["schema"] == "wavemind.onboarding.python.v1"
        packet = onboarding["recall"]
        assert packet["schema"] == "wavemind.experience_packet.v1"
        assert packet["namespace"] == "demo-agent"
        assert len(packet["items"]) == 1
        assert packet["items"][0]["experience_id"] == "starter-deploy-recovery"
        assert packet["citations"] == ["experience:starter-deploy-recovery@v1"]
        assert onboarding["verification"] == {
            "status": "active",
            "evidence_ids": [
                "starter-success-1",
                "starter-success-2",
                "starter-success-3",
            ],
        }
        assert (
            onboarding["explain"][0]["experience_id"]
            == "starter-deploy-recovery"
        )

    assert runs[0]["remember"]["created"] is True
    assert runs[1]["remember"]["created"] is False
    assert runs[0]["remember"]["experience_id"] == runs[1]["remember"]["experience_id"]


def test_mcp_verification_flow_recalls_and_expands_after_restart(tmp_path):
    project = tmp_path / "mcp"
    payload = initialize_project(project, template="mcp", name="MCP Agent")

    assert payload["next_command"] == "python verify_flow.py"
    runs = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "verify_flow.py"],
            cwd=project,
            env=_python_env(),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        onboarding = json.loads(result.stdout)
        runs.append(onboarding)
        assert onboarding["schema"] == "wavemind.onboarding.mcp.v1"
        assert onboarding["recall"]["items"][0]["experience_id"] == (
            "mcp-deploy-verification"
        )
        assert onboarding["verification"]["status"] == "active"
        assert onboarding["explain"]["items"][0]["experience_id"] == (
            "mcp-deploy-verification"
        )

    assert runs[0]["remember"]["created"] is True
    assert runs[1]["remember"]["created"] is False
    assert runs[0]["recall"]["citations"] == runs[1]["recall"]["citations"]


def test_typescript_starter_runs_local_sdk_and_survives_server_restart(tmp_path):
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        pytest.skip("Node.js and npm are required for the TypeScript quickstart")
    project = tmp_path / "typescript"
    payload = initialize_project(project, template="typescript", name="TS Agent")

    assert payload["next_command"] == "npm run quickstart"
    package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    dependency = package["dependencies"]["@wavemind/http"]
    assert dependency.startswith("file:")
    sdk_path = (project / dependency.removeprefix("file:")).resolve()
    assert sdk_path == PROJECT_ROOT / "sdk" / "typescript"
    assert 'from "@wavemind/http"' in (project / "src" / "index.ts").read_text(
        encoding="utf-8"
    )
    runner = (project / "scripts" / "quickstart.mjs").read_text(encoding="utf-8")
    assert 'OPENBLAS_NUM_THREADS: "1"' in runner
    assert 'OMP_NUM_THREADS: "1"' in runner
    assert 'MKL_NUM_THREADS: "1"' in runner
    assert "copyFile(resolve(sdkRoot" in runner
    assert "await symlink(sdkRoot" not in runner

    env = _python_env()
    env["PYTHON"] = sys.executable
    result = subprocess.run(
        [npm, "run", "quickstart"],
        cwd=project,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=240,
    )
    json_start = result.stdout.find('{\n  "schema"')
    assert json_start >= 0, result.stdout
    onboarding = json.loads(result.stdout[json_start:])

    assert onboarding["schema"] == "wavemind.onboarding.typescript.restart.v1"
    assert onboarding["first"]["remember"]["created"] is True
    assert onboarding["restarted"]["remember"]["created"] is False
    assert onboarding["persistence"] == {
        "same_memory_id": True,
        "server_restarted": True,
    }
    assert onboarding["restarted"]["explain"]["provenance"] == {
        "source": "typescript-onboarding"
    }
    actions = {
        event["action"] for event in onboarding["restarted"]["explain"]["audit_events"]
    }
    assert {"remember", "feedback"} <= actions


@pytest.mark.parametrize(
    ("template", "expected"),
    (
        ("typescript", "src/index.ts"),
        ("mcp", "experience_mcp.py"),
        ("docker", "compose.yaml"),
    ),
)
def test_init_writes_provider_starters(tmp_path, template, expected):
    project = tmp_path / template
    payload = initialize_project(project, template=template)

    assert expected in payload["files"]
    assert (project / expected).is_file()
    assert (project / ".wavemind-project.json").is_file()


def test_docker_starter_has_valid_compose_config(tmp_path):
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed")
    project = tmp_path / "docker"
    initialize_project(project, template="docker")

    result = subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    compose = (project / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")
    assert "127.0.0.1:${WAVEMIND_PORT:-8000}:8000" in compose
    assert "WAVEMIND_EXPERIENCE_DB: /data/wavemind-experience.sqlite3" in compose
    assert "WAVEMIND_API_PRINCIPALS" in compose
    assert "docker-onboarding" in (project / "verify_flow.py").read_text(
        encoding="utf-8"
    )
    assert "docker compose run --rm verify" in (project / "README.md").read_text(
        encoding="utf-8"
    )
    assert "condition: service_healthy" in compose
    assert 'command: ["wavemind", "serve", "--host", "0.0.0.0"' in compose
    assert "--allow-public" in dockerfile


def test_generated_python_sources_compile(tmp_path):
    for template, filename in (
        ("python", "app.py"),
        ("mcp", "experience_mcp.py"),
    ):
        project = tmp_path / template
        initialize_project(project, template=template)
        subprocess.run(
            [sys.executable, "-m", "py_compile", filename],
            cwd=project,
            check=True,
            timeout=30,
        )


def test_init_refuses_overwrite_but_force_preserves_unrelated_files(tmp_path):
    project = tmp_path / "starter"
    initialize_project(project)
    unrelated = project / "notes.txt"
    unrelated.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        initialize_project(project)

    initialize_project(project, force=True)
    assert unrelated.read_text(encoding="utf-8") == "keep me"


def test_doctor_passes_initialized_project_and_uses_strict_json(tmp_path):
    project = tmp_path / "starter"
    initialize_project(project)

    report = run_doctor(project)

    assert report["schema"] == "wavemind.doctor.v1"
    assert report["status"] == "pass"
    assert report["summary"]["required_failed"] == 0
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["project-manifest"]["status"] == "pass"
    assert checks["experience-packet"]["detail"] == "items=1"
    json.dumps(report, allow_nan=False)


def test_cli_init_and_doctor_json(tmp_path):
    project = tmp_path / "cli-starter"
    initialized = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "init",
            str(project),
            "--template",
            "python",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    init_payload = json.loads(initialized.stdout)
    assert init_payload["status"] == "created"

    checked = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "doctor",
            "--project",
            str(project),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    doctor_payload = json.loads(checked.stdout)
    assert doctor_payload["status"] == "pass"
    assert doctor_payload["summary"]["required_failed"] == 0


def test_doctor_fails_missing_project_directory(tmp_path):
    report = run_doctor(tmp_path / "missing")

    assert report["status"] == "fail"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["project-directory"]["status"] == "fail"
