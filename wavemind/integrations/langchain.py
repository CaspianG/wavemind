from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ConfigDict

from wavemind import WaveMind


try:
    from langchain_classic.base_memory import BaseMemory
except ImportError as exc:  # pragma: no cover - exercised in clean installs.
    raise ImportError(
        'WaveMindMemory requires LangChain. Install it with: pip install "wavemind[langchain]"'
    ) from exc


class WaveMindMemory(BaseMemory):
    """LangChain BaseMemory implementation backed by WaveMind."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    memory: WaveMind
    db_path: str | Path | None = None
    memory_key: str = "history"
    input_key: str | None = None
    output_key: str | None = None
    namespace: str = "langchain"
    tags: tuple[str, ...] = ("langchain", "conversation")
    top_k: int = 5
    min_score: float | None = None
    human_prefix: str = "Human"
    ai_prefix: str = "AI"
    include_scores: bool = False
    max_context_chars: int = 4000

    def __init__(self, **data: Any):
        if data.get("memory") is None:
            data["memory"] = WaveMind(db_path=data.get("db_path"))
        if "tags" in data and data["tags"] is not None:
            data["tags"] = tuple(data["tags"])
        super().__init__(**data)

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = self._select_input_text(inputs, allow_empty=True)
        if not query:
            return {self.memory_key: ""}

        results = self.memory.query(
            query,
            namespace=self.namespace,
            tags=self.tags,
            top_k=self.top_k,
            min_score=self.min_score,
        )
        lines = []
        for index, result in enumerate(results, start=1):
            prefix = f"[{index}]"
            if self.include_scores:
                prefix = f"{prefix} ({result.score:.2f})"
            lines.append(f"{prefix} {result.text}")
        return {self.memory_key: self._truncate("\n".join(lines))}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, str]) -> None:
        input_text = self._select_input_text(inputs)
        output_text = self._select_output_text(outputs)
        turn = f"{self.human_prefix}: {input_text}\n{self.ai_prefix}: {output_text}"
        self.memory.remember(
            turn,
            namespace=self.namespace,
            tags=self.tags,
            metadata={
                "kind": "langchain_conversation_turn",
                "input": input_text,
                "output": output_text,
            },
            priority=1.2,
        )

    def clear(self) -> None:
        self.memory.forget(namespace=self.namespace)

    def _select_input_text(self, inputs: dict[str, Any], allow_empty: bool = False) -> str:
        if self.input_key is not None:
            return self._stringify(inputs.get(self.input_key, ""))

        candidate_keys = [key for key in inputs if key not in self.memory_variables]
        for preferred in ("input", "question", "query", "prompt"):
            if preferred in candidate_keys:
                return self._stringify(inputs[preferred])

        if len(candidate_keys) == 1:
            return self._stringify(inputs[candidate_keys[0]])
        if not candidate_keys and allow_empty:
            return ""
        raise ValueError(
            "Could not infer the LangChain input key. Set input_key explicitly."
        )

    def _select_output_text(self, outputs: dict[str, Any]) -> str:
        if self.output_key is not None:
            return self._stringify(outputs.get(self.output_key, ""))

        for preferred in ("output", "answer", "response", "text"):
            if preferred in outputs:
                return self._stringify(outputs[preferred])

        if len(outputs) == 1:
            return self._stringify(next(iter(outputs.values())))
        raise ValueError(
            "Could not infer the LangChain output key. Set output_key explicitly."
        )

    def _truncate(self, text: str) -> str:
        if self.max_context_chars <= 0 or len(text) <= self.max_context_chars:
            return text
        return text[: self.max_context_chars].rstrip()

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if hasattr(value, "content"):
            return str(value.content)
        if isinstance(value, (list, tuple)):
            return "\n".join(self._stringify(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)


__all__ = ["WaveMindMemory"]
