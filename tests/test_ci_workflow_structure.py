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
