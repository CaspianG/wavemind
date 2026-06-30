from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from wavemind.core import QueryResult, WaveMind


@dataclass(frozen=True)
class WaveMindNode:
    text: str
    score: float
    id: int
    metadata: dict


class WaveMindRetriever:
    """Small LlamaIndex-style retriever adapter without a hard dependency."""

    def __init__(
        self,
        memory: WaveMind,
        namespace: str = "default",
        top_k: int = 5,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ):
        self.memory = memory
        self.namespace = namespace
        self.top_k = int(top_k)
        self.tags = tuple(tags or ())
        self.min_score = min_score

    def retrieve(self, query: str) -> list[WaveMindNode]:
        results = self.memory.query(
            query,
            namespace=self.namespace,
            top_k=self.top_k,
            tags=self.tags,
            min_score=self.min_score,
        )
        return [self._node(result) for result in results]

    def context(self, query: str, separator: str = "\n") -> str:
        return separator.join(node.text for node in self.retrieve(query))

    @staticmethod
    def _node(result: QueryResult) -> WaveMindNode:
        metadata = dict(result.metadata)
        metadata.update(
            {
                "wavemind_id": result.id,
                "namespace": result.namespace,
                "tags": list(result.tags),
                "vector_score": result.vector_score,
                "field_score": result.field_score,
                "graph_score": result.graph_score,
            }
        )
        return WaveMindNode(
            text=result.text,
            score=result.score,
            id=result.id,
            metadata=metadata,
        )
