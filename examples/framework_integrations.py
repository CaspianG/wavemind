from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HashingTextEncoder, WaveMind


def build_memory(db_path: str | Path | None = None) -> WaveMind:
    return WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=128),
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
    )


def langgraph_before_model(state: dict, memory: WaveMind) -> dict:
    namespace = state.get("namespace", "default")
    message = state.get("user_message", "")
    hits = memory.query(message, namespace=namespace, top_k=3, min_score=0.0)
    state["memory_context"] = "\n".join(f"- {hit.text}" for hit in hits)
    return state


def langgraph_after_model(state: dict, memory: WaveMind) -> dict:
    namespace = state.get("namespace", "default")
    if state.get("user_message"):
        memory.remember(
            f"User said: {state['user_message']}",
            namespace=namespace,
            tags=["conversation"],
        )
    if state.get("assistant_message"):
        memory.remember(
            f"Assistant said: {state['assistant_message']}",
            namespace=namespace,
            tags=["conversation"],
        )
    return state


class LlamaIndexStyleRetriever:
    def __init__(self, memory: WaveMind, namespace: str = "default", top_k: int = 5):
        self.memory = memory
        self.namespace = namespace
        self.top_k = int(top_k)

    def retrieve(self, query: str) -> list[dict]:
        return [
            {"text": hit.text, "score": hit.score, "metadata": hit.metadata}
            for hit in self.memory.query(
                query,
                namespace=self.namespace,
                top_k=self.top_k,
                min_score=0.0,
            )
        ]


def crewai_tools(memory: WaveMind, namespace: str = "crew") -> dict[str, object]:
    def remember_tool(text: str) -> str:
        memory_id = memory.remember(text, namespace=namespace, tags=["crew"])
        return f"remembered:{memory_id}"

    def recall_tool(query: str) -> str:
        hits = memory.query(query, namespace=namespace, top_k=3, min_score=0.0)
        return "\n".join(hit.text for hit in hits)

    return {"remember": remember_tool, "recall": recall_tool}


def autogen_retrieve(memory: WaveMind, message: str, user_id: str = "demo") -> str:
    namespace = f"autogen:{user_id}"
    hits = memory.query(message, namespace=namespace, top_k=3, min_score=0.0)
    return "\n".join(f"- {hit.text}" for hit in hits)


def autogen_store(memory: WaveMind, message: str, user_id: str = "demo") -> int:
    namespace = f"autogen:{user_id}"
    return memory.remember(message, namespace=namespace, tags=["autogen"])


def main() -> int:
    memory = build_memory()

    state = {
        "namespace": "langgraph:user:42",
        "user_message": "Andrey prefers short answers",
        "assistant_message": "I will keep answers concise.",
    }
    langgraph_after_model(state, memory)
    recalled_state = langgraph_before_model(
        {"namespace": "langgraph:user:42", "user_message": "answer style"},
        memory,
    )
    print("LangGraph recall:")
    print(recalled_state["memory_context"])

    retriever = LlamaIndexStyleRetriever(memory, namespace="langgraph:user:42", top_k=1)
    print("LlamaIndex-style retriever:")
    print(retriever.retrieve("short answers")[0]["text"])

    tools = crewai_tools(memory)
    print("CrewAI-style tools:")
    print(tools["remember"]("Crew should use WaveMind for project memory"))
    print(tools["recall"]("project memory"))

    print("AutoGen-style hooks:")
    autogen_store(memory, "AutoGen user is testing persistent recall", user_id="42")
    print(autogen_retrieve(memory, "persistent recall", user_id="42"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
