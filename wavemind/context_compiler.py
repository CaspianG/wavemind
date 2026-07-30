from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence


_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_STRUCTURED_LABELS = (
    "action:",
    "new observed labels:",
    "observed labels:",
    "trajectory outcome:",
)


@dataclass(frozen=True)
class MemoryContextPolicy:
    """Deterministic limits for compiling retrieval results for a reader."""

    default_token_budget: int = 1_200
    max_items: int = 5
    max_item_tokens: int = 800
    min_item_tokens: int = 48
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.default_token_budget < 32:
            raise ValueError("default_token_budget must be at least 32")
        if self.max_items < 1:
            raise ValueError("max_items must be positive")
        if self.max_item_tokens < 8:
            raise ValueError("max_item_tokens must be at least 8")
        if self.min_item_tokens < 8:
            raise ValueError("min_item_tokens must be at least 8")
        if self.min_item_tokens > self.max_item_tokens:
            raise ValueError("min_item_tokens must not exceed max_item_tokens")
        if self.chars_per_token < 1:
            raise ValueError("chars_per_token must be positive")


@dataclass(frozen=True)
class CompiledMemoryContextItem:
    memory_id: int
    rank: int
    text: str
    score: float
    citation: str
    estimated_tokens: int
    original_estimated_tokens: int
    truncated: bool
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompiledMemoryContext:
    query: str
    token_budget: int
    estimated_tokens: int
    original_estimated_tokens: int
    items: tuple[CompiledMemoryContextItem, ...]
    omitted_count: int
    policy: dict[str, Any]

    @property
    def token_saving(self) -> float:
        if self.original_estimated_tokens <= 0:
            return 0.0
        return max(
            0.0,
            1.0 - self.estimated_tokens / self.original_estimated_tokens,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "wavemind.memory_context.v1",
            "query": self.query,
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "original_estimated_tokens": self.original_estimated_tokens,
            "token_saving": self.token_saving,
            "items": [item.as_dict() for item in self.items],
            "omitted_count": self.omitted_count,
            "policy": dict(self.policy),
        }

    def as_prompt(self) -> str:
        lines = ["Memory context:"]
        for item in self.items:
            lines.append(f"[M{item.rank}] {item.text} ({item.citation})")
        return "\n".join(lines)


class MemoryContextCompiler:
    """Compile ranked memories into a query-aware, bounded reader context."""

    def __init__(self, policy: MemoryContextPolicy | None = None):
        self.policy = policy or MemoryContextPolicy()

    def compile(
        self,
        query: str,
        results: Iterable[Any],
        *,
        texts: Sequence[str] | None = None,
        token_budget: int | None = None,
        max_items: int | None = None,
    ) -> CompiledMemoryContext:
        query = query.strip()
        if not query:
            raise ValueError("context query must not be empty")
        budget = int(token_budget or self.policy.default_token_budget)
        if budget < 32:
            raise ValueError("token_budget must be at least 32")
        item_limit = int(max_items or self.policy.max_items)
        if item_limit < 1:
            raise ValueError("max_items must be positive")

        ranked = list(results)
        if texts is None:
            source_texts = [str(result.text) for result in ranked]
        else:
            source_texts = [str(value) for value in texts]
            if len(source_texts) != len(ranked):
                raise ValueError("texts must align one-to-one with results")

        original_tokens = sum(_estimated_tokens(text) for text in source_texts)
        selected = list(zip(ranked, source_texts, strict=True))[:item_limit]
        weights = [2, *([1] * max(0, len(selected) - 1))]
        remaining_budget = budget
        remaining_weight = sum(weights)
        items: list[CompiledMemoryContextItem] = []
        for rank, ((result, source_text), weight) in enumerate(
            zip(selected, weights, strict=True),
            start=1,
        ):
            if remaining_budget < self.policy.min_item_tokens:
                break
            allocation = min(
                self.policy.max_item_tokens,
                max(
                    self.policy.min_item_tokens,
                    int(remaining_budget * weight / max(1, remaining_weight)),
                ),
            )
            excerpt = _query_aware_excerpt(
                source_text,
                query,
                token_budget=allocation,
                chars_per_token=self.policy.chars_per_token,
            )
            estimated = _estimated_tokens(excerpt)
            if estimated > remaining_budget:
                excerpt = _truncate_words(excerpt, remaining_budget)
                estimated = _estimated_tokens(excerpt)
            if not excerpt or estimated > remaining_budget:
                remaining_weight -= weight
                continue
            memory_id = int(getattr(result, "id", 0) or 0)
            metadata = dict(getattr(result, "metadata", {}) or {})
            items.append(
                CompiledMemoryContextItem(
                    memory_id=memory_id,
                    rank=rank,
                    text=excerpt,
                    score=float(getattr(result, "score", 0.0) or 0.0),
                    citation=f"memory:{memory_id}",
                    estimated_tokens=estimated,
                    original_estimated_tokens=_estimated_tokens(source_text),
                    truncated=excerpt != source_text,
                    provenance={
                        "namespace": str(
                            getattr(result, "namespace", "") or ""
                        ),
                        "tags": list(getattr(result, "tags", ()) or ()),
                        "source_memory_ids": list(
                            metadata.get("source_memory_ids") or ()
                        ),
                        "trajectory_id": metadata.get("trajectory_id"),
                    },
                )
            )
            remaining_budget -= estimated
            remaining_weight -= weight

        consumed = sum(item.estimated_tokens for item in items)
        return CompiledMemoryContext(
            query=query,
            token_budget=budget,
            estimated_tokens=consumed,
            original_estimated_tokens=original_tokens,
            items=tuple(items),
            omitted_count=max(0, len(ranked) - len(items)),
            policy={
                **asdict(self.policy),
                "query_aware": True,
                "structured_salience": True,
                "rank_weighting": "2:1",
                "source_text_preserved": True,
            },
        )


def _estimated_tokens(text: str) -> int:
    words = text.split()
    return max(1, math.ceil(len(words) * 1.25)) if text else 0


def _truncate_words(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    word_budget = max(1, math.floor(token_budget / 1.25))
    words = text.split()
    if len(words) <= word_budget:
        return text
    return " ".join(words[:word_budget]).strip()


def _query_aware_excerpt(
    text: str,
    query: str,
    *,
    token_budget: int,
    chars_per_token: int,
) -> str:
    if not text:
        return ""
    if _estimated_tokens(text) <= token_budget:
        return text
    max_chars = max(32, token_budget * chars_per_token)
    query_terms = {
        token.casefold()
        for token in _TOKEN_RE.findall(query)
        if len(token) >= 3
    }
    chunks = _text_chunks(text, max_chars=min(600, max_chars))
    if not chunks:
        return _truncate_words(text, token_budget)

    def relevance(item: tuple[int, str]) -> tuple[float, int, int]:
        index, value = item
        folded = value.casefold()
        matches = sum(term in folded for term in query_terms)
        density = matches / math.sqrt(max(1, len(_TOKEN_RE.findall(value))))
        structured_salience = sum(
            1.0 for label in _STRUCTURED_LABELS if label in folded
        )
        combined = matches + density + structured_salience * 0.35
        return (-combined, -matches, index)

    ranked = sorted(enumerate(chunks), key=relevance)
    selected: set[int] = set()
    total_chars = 0
    for index, value in ranked:
        candidates = [index]
        if index > 0:
            candidates.insert(0, index - 1)
        if index + 1 < len(chunks):
            candidates.append(index + 1)
        additions = [candidate for candidate in candidates if candidate not in selected]
        addition_chars = sum(len(chunks[candidate]) + 1 for candidate in additions)
        if total_chars + addition_chars > max_chars:
            additions = [index] if index not in selected else []
            addition_chars = len(value) + 1 if additions else 0
        if total_chars + addition_chars > max_chars:
            continue
        selected.update(additions)
        total_chars += addition_chars
        if total_chars >= max_chars * 0.85:
            break
    if not selected:
        selected.add(0)
    excerpt = "\n".join(chunks[index] for index in sorted(selected))
    return _truncate_words(excerpt, token_budget)


def _text_chunks(text: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    for line in (line.strip() for line in text.splitlines() if line.strip()):
        if len(line) <= max_chars:
            chunks.append(line)
            continue
        chunks.extend(
            line[offset : offset + max_chars].strip()
            for offset in range(0, len(line), max_chars)
            if line[offset : offset + max_chars].strip()
        )
    return chunks
