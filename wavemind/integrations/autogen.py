from __future__ import annotations

from wavemind.core import WaveMind


class WaveMindAutoGenMemory:
    """AutoGen-style memory hooks for message-based agent loops."""

    def __init__(
        self,
        memory: WaveMind,
        namespace: str = "default",
        top_k: int = 5,
        context_header: str = "Relevant memory:",
    ):
        self.memory = memory
        self.namespace = namespace
        self.top_k = int(top_k)
        self.context_header = context_header

    def build_context(self, message: str) -> str:
        results = self.memory.query(
            message,
            namespace=self.namespace,
            top_k=self.top_k,
        )
        if not results:
            return ""
        lines = [self.context_header]
        lines.extend(f"- {item.text}" for item in results)
        return "\n".join(lines)

    def remember_turn(
        self,
        user_message: str,
        assistant_message: str | None = None,
    ) -> list[int]:
        ids = [
            self.memory.remember(
                f"user: {user_message}",
                namespace=self.namespace,
                tags=("conversation", "user"),
            )
        ]
        if assistant_message:
            ids.append(
                self.memory.remember(
                    f"assistant: {assistant_message}",
                    namespace=self.namespace,
                    tags=("conversation", "assistant"),
                )
            )
        return ids

    def augment_message(self, message: str) -> str:
        context = self.build_context(message)
        if not context:
            return message
        return f"{context}\n\nCurrent message:\n{message}"
