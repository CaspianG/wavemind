from wavemind import HashingTextEncoder, WaveMind
from wavemind.integrations.autogen import WaveMindAutoGenMemory
from wavemind.integrations.crewai import WaveMindCrewAITools
from wavemind.integrations.langgraph import make_persist_node, make_recall_node
from wavemind.integrations.llamaindex import WaveMindRetriever


def make_memory(tmp_path):
    return WaveMind(
        db_path=tmp_path / "adapters.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=32),
    )


def test_llamaindex_style_retriever_returns_nodes(tmp_path):
    memory = make_memory(tmp_path)
    try:
        memory.remember("Andrey prefers short answers", namespace="agent")
        retriever = WaveMindRetriever(memory, namespace="agent", top_k=1)

        nodes = retriever.retrieve("short answers")

        assert nodes[0].text == "Andrey prefers short answers"
        assert nodes[0].metadata["namespace"] == "agent"
        assert "Andrey prefers short answers" in retriever.context("answers")
    finally:
        memory.close()


def test_crewai_tools_remember_query_and_forget(tmp_path):
    memory = make_memory(tmp_path)
    try:
        tools = WaveMindCrewAITools(memory, namespace="crew", top_k=1)

        remembered = tools.remember("budget is 2000 dollars")
        queried = tools.query("budget")
        deleted = tools.forget(text="budget is 2000 dollars")

        assert remembered.startswith("remembered:")
        assert "budget is 2000 dollars" in queried
        assert deleted == "deleted:1"
        assert [item["name"] for item in tools.tool_specs()] == [
            "wavemind_remember",
            "wavemind_query",
            "wavemind_forget",
        ]
    finally:
        memory.close()


def test_autogen_memory_hooks_add_context_and_persist_turns(tmp_path):
    memory = make_memory(tmp_path)
    try:
        adapter = WaveMindAutoGenMemory(memory, namespace="autogen", top_k=1)

        ids = adapter.remember_turn("my name is Andrey", "noted")
        augmented = adapter.augment_message("what is my name?")

        assert len(ids) == 2
        assert "Relevant memory:" in augmented
        assert "my name is Andrey" in augmented
    finally:
        memory.close()


def test_langgraph_nodes_recall_and_persist_state(tmp_path):
    memory = make_memory(tmp_path)
    try:
        memory.remember("Hermes uses WaveMind for durable memory", namespace="graph")
        recall = make_recall_node(memory, namespace="graph", top_k=1)
        persist = make_persist_node(memory, namespace="graph")

        recalled = recall({"input": "durable memory"})
        persisted = persist({"input": "new user fact", "output": "stored"})

        assert "Hermes uses WaveMind" in recalled["memory_context"]
        assert len(recalled["memory_context_items"]) == 1
        assert len(persisted["wavemind_memory_ids"]) == 2
    finally:
        memory.close()
