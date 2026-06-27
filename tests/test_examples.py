import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def test_framework_integrations_example_runs_from_checkout():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/framework_integrations.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "LangGraph recall:" in result.stdout
    assert "LlamaIndex-style retriever:" in result.stdout
    assert "CrewAI-style tools:" in result.stdout
    assert "AutoGen-style hooks:" in result.stdout


def test_sharded_memory_example_runs_from_temp_directory(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, str(project_root / "examples" / "sharded_memory.py")],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "Tenant A:" in result.stdout
    assert "Tenant B:" in result.stdout
    assert "Shard stats:" in result.stdout
    assert (tmp_path / ".wavemind-shards").exists()


def load_example():
    path = Path("examples/agent_with_memory.py")
    spec = importlib.util.spec_from_file_location("agent_with_memory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_example_uses_environment_key_not_hardcoded_secret():
    text = Path("examples/agent_with_memory.py").read_text(encoding="utf-8")

    assert "sk-or-v1-" not in text
    assert "OPENROUTER_API_KEY" in text
    assert "https://openrouter.ai/api/v1/chat/completions" in text


def test_offline_demo_prints_recall_flow():
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/demo.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert '✓ Remembered: "' in result.stdout
    assert 'Query: "' in result.stdout
    assert "→ Result 1" in result.stdout
    assert "→ Result 2" in result.stdout


def test_agent_example_help_runs_from_checkout():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "examples/agent_with_memory.py", "--help"],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "usage: agent_with_memory.py" in result.stdout


def test_agent_example_remembers_and_recalls_user_profile(tmp_path):
    module = load_example()
    memory = module.build_memory(tmp_path / "agent.sqlite3")

    module.observe_user_message(memory, "меня зовут Андрей, я трейдер")
    context = module.recall_memory(memory, "как меня зовут?")

    assert "Андрей" in context
    assert "трейдер" in context
