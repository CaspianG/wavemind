from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from wavemind.core import WaveMind


def make_recall_node(
    memory: WaveMind,
    namespace: str = "default",
    input_key: str = "input",
    output_key: str = "memory_context",
    top_k: int = 5,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Create a LangGraph node that adds recalled WaveMind context to state."""

    def recall_node(state: Mapping[str, Any]) -> dict[str, Any]:
        query = str(state.get(input_key, ""))
        results = memory.query(query, namespace=namespace, top_k=top_k) if query else []
        return {
            output_key: "\n".join(result.text for result in results),
            f"{output_key}_items": [
                {
                    "id": result.id,
                    "text": result.text,
                    "score": result.score,
                    "namespace": result.namespace,
                    "tags": list(result.tags),
                }
                for result in results
            ],
        }

    return recall_node


def make_persist_node(
    memory: WaveMind,
    namespace: str = "default",
    input_key: str = "input",
    output_key: str | None = "output",
    tags: tuple[str, ...] = ("conversation",),
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Create a LangGraph node that persists selected state as memory."""

    def persist_node(state: Mapping[str, Any]) -> dict[str, Any]:
        ids: list[int] = []
        input_text = str(state.get(input_key, ""))
        if input_text:
            ids.append(memory.remember(input_text, namespace=namespace, tags=tags))
        if output_key:
            output_text = str(state.get(output_key, ""))
            if output_text:
                ids.append(memory.remember(output_text, namespace=namespace, tags=tags))
        return {"wavemind_memory_ids": ids}

    return persist_node
