from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HashingTextEncoder, WaveMind
from wavemind.integrations.llamaindex import WaveMindNode, WaveMindRetriever


NAMESPACE = "llamaindex:demo"


def build_memory(db_path: str | Path | None = None) -> WaveMind:
    return WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=128),
        index_kind="numpy",
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
    )


def seed_memory(memory: WaveMind) -> list[int]:
    return [
        memory.remember(
            "Andrey prefers concise answers with a short action list.",
            namespace=NAMESPACE,
            tags=["profile", "preference"],
            metadata={"source": "chat"},
        ),
        memory.remember(
            "The WaveMind project uses offline retrieval before calling an LLM.",
            namespace=NAMESPACE,
            tags=["project", "architecture"],
            metadata={"source": "project-notes"},
        ),
        memory.remember(
            "For demos, show the retrieved memory context before the final answer.",
            namespace=NAMESPACE,
            tags=["demo", "prompting"],
            metadata={"source": "runbook"},
        ),
    ]


def build_prompt(question: str, nodes: list[WaveMindNode]) -> str:
    context = "\n".join(f"[Memory {node.id}] {node.text}" for node in nodes)
    return (
        "Context information is below.\n"
        f"{context}\n\n"
        "Using only the useful context, answer the query.\n"
        f"Query: {question}\n"
        "Answer:"
    )


def main() -> int:
    question = "How should the agent answer WaveMind demo questions?"
    with build_memory() as memory:
        memory_ids = seed_memory(memory)
        print(f"Remembered {len(memory_ids)} memories.")

        retriever = WaveMindRetriever(memory, namespace=NAMESPACE, top_k=2, min_score=0.0)
        nodes = retriever.retrieve(question)
        if not nodes:
            raise RuntimeError("WaveMindRetriever returned no context nodes.")

        print("WaveMindRetriever nodes:")
        for node in nodes:
            print(f"- {node.text} (score={node.score:.2f})")

        print("\nInjected prompt:")
        print(build_prompt(question, nodes))

        print("\nContext helper:")
        print(retriever.context(question, separator="\n---\n"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
