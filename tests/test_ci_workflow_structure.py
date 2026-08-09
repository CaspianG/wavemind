from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_yaml(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_python_compatibility_and_windows_install_cli_coverage():
    workflow = load_yaml(WORKFLOWS / "tests.yml")
    jobs = workflow["jobs"]

    assert jobs["pytest"]["strategy"]["matrix"]["python-version"] == [
        "3.10",
        "3.11",
    ]

    compatibility = jobs["python-compatibility"]
    assert compatibility["runs-on"] == "ubuntu-latest"
    assert compatibility["strategy"]["matrix"]["python-version"] == [
        "3.10",
        "3.11",
        "3.12",
        "3.13",
    ]
    compatibility_commands = "\n".join(
        step.get("run", "") for step in compatibility["steps"]
    )
    assert "tests/test_core_persistence.py" in compatibility_commands
    assert "test_module_cli_remember_query_stats_and_backup" in compatibility_commands
    assert "test_cli_init_and_doctor_json" in compatibility_commands

    windows = jobs["windows-install-cli"]
    assert windows["runs-on"] == "windows-latest"
    assert windows["strategy"]["matrix"]["python-version"] == ["3.10", "3.13"]
    windows_commands = "\n".join(step.get("run", "") for step in windows["steps"])
    for command in (
        "python -m pip install .",
        "Set-Location $env:RUNNER_TEMP",
        "wavemind --version",
        "wavemind --db $db remember",
        "wavemind --db $db query",
        "wavemind --db $db stats",
        "python -m wavemind init",
    ):
        assert command in windows_commands


def test_codeql_scans_python_and_typescript_with_security_queries():
    workflow = load_yaml(WORKFLOWS / "codeql.yml")
    assert set(workflow["on"]) == {
        "push",
        "pull_request",
        "schedule",
        "workflow_dispatch",
    }

    analyze = workflow["jobs"]["analyze"]
    assert analyze["permissions"]["security-events"] == "write"
    assert analyze["strategy"]["matrix"]["language"] == [
        "python",
        "javascript-typescript",
    ]
    actions = [step.get("uses") for step in analyze["steps"]]
    assert "github/codeql-action/init@v4" in actions
    assert "github/codeql-action/analyze@v4" in actions
    init = next(step for step in analyze["steps"] if step.get("name") == "Initialize CodeQL")
    assert init["with"]["queries"] == "security-extended"


def test_dependabot_covers_typescript_sdk_npm_dependencies():
    config = load_yaml(ROOT / ".github" / "dependabot.yml")
    npm = next(
        update
        for update in config["updates"]
        if update["package-ecosystem"] == "npm"
    )

    assert npm["directory"] == "/sdk/typescript"
    assert npm["schedule"]["interval"] == "weekly"
    assert npm["open-pull-requests-limit"] == "5"


def test_safe_product_admission_depends_on_real_compatibility_and_sast_jobs():
    workflow = load_yaml(WORKFLOWS / "safe-product.yml")
    jobs = workflow["jobs"]

    compatibility = jobs["compatibility"]["strategy"]["matrix"]["include"]
    assert {entry["python"] for entry in compatibility} == {
        "3.10",
        "3.11",
        "3.12",
        "3.13",
    }
    assert {entry["os"] for entry in compatibility} == {
        "ubuntu-latest",
        "windows-latest",
    }
    assert jobs["sast"]["strategy"]["matrix"]["language"] == [
        "python",
        "javascript-typescript",
    ]
    admission = jobs["admission"]
    assert admission["needs"] == ["compatibility", "sast"]
    commands = "\n".join(
        step.get("run", "") for step in admission["steps"]
    )
    for command in (
        "safe_retrieval_admission.py",
        "product_persistence_admission.py",
        "quickstart_admission.py",
        "safe_product_admission.py",
        "--ci-matrix-passed",
        "--sast-passed",
        "--require-admitted",
    ):
        assert command in commands


def test_full_check_container_smoke_uses_authenticated_explicit_public_bind():
    workflow = load_yaml(WORKFLOWS / "full-check.yml")
    docker_job = workflow["jobs"]["docker"]
    smoke = next(
        step for step in docker_job["steps"] if step.get("name") == "Run Docker API smoke"
    )["run"]
    starter_smoke = next(
        step
        for step in docker_job["steps"]
        if step.get("name") == "Run generated Docker starter smoke"
    )["run"]

    assert "-p 127.0.0.1:8000:8000" in smoke
    assert "WAVEMIND_ADMIN_KEYS=ci-api-key" in smoke
    assert "Authorization: Bearer local-quickstart-key" in starter_smoke
    assert "--host 0.0.0.0 --port 8000 --allow-public" in smoke
    assert "X-API-Key: ci-api-key" in smoke
    assert "= \"401\"" in smoke
