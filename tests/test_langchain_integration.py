import subprocess
import sys
from pathlib import Path

from wavemind import HashingTextEncoder, WaveMind


def make_memory(tmp_path):
    from wavemind.integrations.langchain import WaveMindMemory

    mind = WaveMind(
        db_path=tmp_path / "langchain.sqlite3",
        encoder=HashingTextEncoder(vector_dim=128),
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
        score_threshold=0.0,
    )
    return WaveMindMemory(memory=mind, top_k=3)


def test_wavemind_memory_exposes_langchain_base_memory_methods(tmp_path):
    memory = make_memory(tmp_path)

    assert memory.memory_variables == ["history"]
    assert hasattr(memory, "load_memory_variables")
    assert hasattr(memory, "save_context")
    assert hasattr(memory, "clear")


def test_wavemind_memory_saves_context_and_recalls_relevant_history(tmp_path):
    memory = make_memory(tmp_path)

    memory.save_context(
        {"input": "my name is Andrey and I am a trader"},
        {"output": "remembered"},
    )
    loaded = memory.load_memory_variables({"input": "what is my name?"})

    assert set(loaded) == {"history"}
    assert "Andrey" in loaded["history"]
    assert "trader" in loaded["history"]


def test_wavemind_memory_supports_custom_input_output_keys(tmp_path):
    memory = make_memory(tmp_path)
    memory.input_key = "question"
    memory.output_key = "answer"

    memory.save_context(
        {"question": "the user budget is 2000 dollars", "irrelevant": "skip me"},
        {"answer": "saved", "other": "ignore me"},
    )
    loaded = memory.load_memory_variables({"question": "what is the budget?"})

    assert "2000 dollars" in loaded["history"]
    assert "skip me" not in loaded["history"]
    assert "ignore me" not in loaded["history"]


def test_wavemind_memory_clear_forgets_namespace(tmp_path):
    memory = make_memory(tmp_path)

    memory.save_context({"input": "Andrey likes short answers"}, {"output": "ok"})
    assert "Andrey" in memory.load_memory_variables({"input": "short answers"})["history"]

    memory.clear()

    assert memory.load_memory_variables({"input": "short answers"})["history"] == ""


def test_langchain_example_runs_without_external_keys():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "examples/langchain_memory.py"],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "WaveMindMemory history:" in result.stdout
    assert "Andrey" in result.stdout
