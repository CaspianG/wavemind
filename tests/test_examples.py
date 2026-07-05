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


def test_llamaindex_retriever_example_runs_from_checkout():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/llamaindex_retriever.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "Remembered 3 memories." in result.stdout
    assert "WaveMindRetriever nodes:" in result.stdout
    assert "Injected prompt:" in result.stdout
    assert "Context helper:" in result.stdout
    assert "Context information is below." in result.stdout
    assert "WaveMind project uses offline retrieval" in result.stdout


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


def load_customer_support_example():
    path = Path("examples/customer_support_memory.py")
    spec = importlib.util.spec_from_file_location("customer_support_memory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_research_notebook_example():
    path = Path("examples/research_notebook_memory.py")
    spec = importlib.util.spec_from_file_location("research_notebook_memory", path)
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

    assert '[ok] Remembered: "' in result.stdout
    assert 'Query: "' in result.stdout
    assert "-> Result 1" in result.stdout
    assert "-> Result 2" in result.stdout


def test_dynamic_memory_demo_prints_core_differentiators():
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/dynamic_memory_demo.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "WaveMind dynamic memory demo" in result.stdout
    assert "[ok] corrected newer budget outranks the stale budget" in result.stdout
    assert "[ok] namespace isolation keeps Maria separate from Andrey" in result.stdout
    assert "[ok] expired temporary memory is not recalled" in result.stdout
    assert "[ok] numpy-exact healthy=True expected=3 vectors=3" in result.stdout


def test_customer_support_memory_example_prints_vertical_use_case():
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/customer_support_memory.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "WaveMind customer support memory demo" in result.stdout
    assert "[ok] corrected account plan outranks stale CRM data" in result.stdout
    assert "[ok] expired discount code is not recalled" in result.stdout
    assert "[ok] customer namespaces prevent cross-account leakage" in result.stdout
    assert "INV-2042" in result.stdout


def test_customer_support_memory_example_enforces_crm_memory_policy(tmp_path):
    module = load_customer_support_example()
    memory = module.build_memory(tmp_path / "support.sqlite3")
    try:
        results = module.run_customer_support_checks(memory)

        assert results["purged"] == 1
        assert "Enterprise" in results["plan_hits"][0].text
        assert all("SAVE20" not in hit.text for hit in results["discount_hits"])
        assert results["discount_hits"] == []
        assert results["globex_hits"][0].namespace == module.GLOBEX_NAMESPACE
        assert "Globex" in results["globex_hits"][0].text
        assert all("Globex" not in hit.text for hit in results["acme_cross_check"])
        assert results["stats"]["active_memories"] == 5
        assert results["stats"]["index_healthy"] is True
    finally:
        memory.close()


def test_research_notebook_memory_example_prints_vertical_use_case():
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "examples/research_notebook_memory.py"],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "WaveMind research notebook memory demo" in result.stdout
    assert "[ok] confirmed finding is recalled with source metadata" in result.stdout
    assert "[ok] expired hypothesis is not recalled" in result.stdout
    assert "[ok] project namespaces keep analyst notes isolated" in result.stdout
    assert "benchmark-2026-07-03" in result.stdout


def test_research_notebook_memory_example_enforces_analyst_memory_policy(tmp_path):
    module = load_research_notebook_example()
    memory = module.build_memory(tmp_path / "research.sqlite3")
    try:
        results = module.run_research_checks(memory)

        assert results["purged"] == 1
        assert "p95 latency improved" in results["finding_hits"][0].text
        assert results["finding_hits"][0].metadata["source"] == "benchmark-2026-07-03"
        assert all(
            "nightly index rebuilds" not in hit.text
            for hit in results["expired_hypothesis_hits"]
        )
        assert results["pricing_hits"][0].namespace == module.PRICING_NAMESPACE
        assert "pricing conversion lift" in results["pricing_hits"][0].text
        assert all(
            "pricing conversion" not in hit.text
            for hit in results["latency_cross_check"]
        )
        assert results["stats"]["active_memories"] == 4
        assert results["stats"]["index_healthy"] is True
    finally:
        memory.close()


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
