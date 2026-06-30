from __future__ import annotations

from typing import Iterable

from wavemind.core import WaveMind


class WaveMindCrewAITools:
    """CrewAI-friendly tool facade around WaveMind memory operations."""

    def __init__(
        self,
        memory: WaveMind,
        namespace: str = "default",
        top_k: int = 5,
    ):
        self.memory = memory
        self.namespace = namespace
        self.top_k = int(top_k)

    def remember(
        self,
        text: str,
        namespace: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> str:
        memory_id = self.memory.remember(
            text,
            namespace=namespace or self.namespace,
            tags=tuple(tags or ()),
        )
        return f"remembered:{memory_id}"

    def query(
        self,
        query: str,
        namespace: str | None = None,
        top_k: int | None = None,
    ) -> str:
        results = self.memory.query(
            query,
            namespace=namespace or self.namespace,
            top_k=top_k or self.top_k,
        )
        return "\n".join(f"{item.score:.3f}: {item.text}" for item in results)

    def forget(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str | None = None,
    ) -> str:
        deleted = self.memory.forget(
            id=id,
            text=text,
            namespace=namespace or self.namespace,
        )
        return f"deleted:{deleted}"

    def tool_specs(self) -> list[dict[str, object]]:
        return [
            {
                "name": "wavemind_remember",
                "description": "Store a durable memory for later recall.",
                "callable": self.remember,
            },
            {
                "name": "wavemind_query",
                "description": "Retrieve relevant durable memories.",
                "callable": self.query,
            },
            {
                "name": "wavemind_forget",
                "description": "Delete memories by id, text, or namespace.",
                "callable": self.forget,
            },
        ]
