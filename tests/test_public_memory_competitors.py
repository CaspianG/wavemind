from __future__ import annotations

from typing import Any

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceQuery,
    LongMemory,
)
from benchmarks.public_memory_competitors import (
    run_hindsight_evidence,
    run_mem0_evidence,
)


def _dataset() -> EvidenceDataset:
    return EvidenceDataset(
        name="public-competitor-fixture",
        memories=[
            LongMemory(
                id="conversation-a::D1:1",
                text="Andrey trades crypto breakouts.",
                namespace="conversation-a",
                timestamp="1:56 pm on 8 May, 2023",
            ),
            LongMemory(
                id="conversation-a::D2:1",
                text="Andrey's monthly tool budget is 2000 dollars.",
                namespace="conversation-a",
            ),
            LongMemory(
                id="conversation-b::D1:1",
                text="Maria is a product designer.",
                namespace="conversation-b",
            ),
        ],
        queries=[
            EvidenceQuery(
                id="conversation-a::Q1",
                text="What does Andrey trade?",
                namespace="conversation-a",
                expected_evidence_ids=("conversation-a::D1:1",),
            ),
            EvidenceQuery(
                id="conversation-b::Q1",
                text="What is Maria's job?",
                namespace="conversation-b",
                expected_evidence_ids=("conversation-b::D1:1",),
            ),
        ],
    )


class FakeMem0:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.closed = False
        self.vector_store = FakeVectorStore()

    def add(
        self,
        text: str,
        *,
        user_id: str,
        metadata: dict[str, Any],
        infer: bool,
    ) -> dict[str, Any]:
        assert infer is False
        row = {
            "id": f"mem-{len(self.rows) + 1}",
            "memory": text,
            "user_id": user_id,
            "metadata": metadata,
        }
        self.rows.append(row)
        return {"results": [row]}

    def search(
        self,
        query: str,
        *,
        filters: dict[str, str],
        top_k: int,
        threshold: float,
        show_expired: bool,
    ) -> dict[str, Any]:
        assert threshold == 0.0
        assert show_expired is False
        candidates = [
            row for row in self.rows if row["user_id"] == filters["user_id"]
        ]
        if "trade" in query.lower():
            candidates.sort(key=lambda row: "trades" not in row["memory"])
        return {"results": candidates[:top_k]}

    def close(self) -> None:
        self.closed = True


class FakeQdrantClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeVectorStore:
    def __init__(self) -> None:
        self.client = FakeQdrantClient()


def test_mem0_adapter_uses_real_metadata_provenance_and_namespace_filters():
    created: list[FakeMem0] = []
    configs: list[dict[str, Any]] = []

    def factory(config: dict[str, Any]) -> FakeMem0:
        configs.append(config)
        memory = FakeMem0()
        created.append(memory)
        return memory

    result = run_mem0_evidence(
        _dataset(),
        None,
        1,
        memory_factory=factory,
    )

    assert result.engine == "Mem0 OSS"
    assert result.precision_at_1 == 1.0
    assert result.provenance_mode == "metadata.evidence_id"
    assert result.ingest_total_ms >= 0.0
    assert configs[0]["embedder"]["provider"] == "fastembed"
    assert configs[0]["vector_store"]["provider"] == "qdrant"
    assert all(memory.closed for memory in created)
    assert all(memory.vector_store.client.closed for memory in created)


class FakeHindsightTransport:
    def __init__(self) -> None:
        self.banks: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        parts = path.strip("/").split("/")
        bank_id = parts[3]
        if method == "PUT":
            assert payload is not None
            assert payload["retain_extraction_mode"] == "chunks"
            assert payload["enable_observations"] is False
            self.banks[bank_id] = []
            return {"bank_id": bank_id}
        if method == "DELETE":
            self.banks.pop(bank_id)
            return {"success": True}
        if path.endswith("/memories/recall"):
            assert payload is not None
            rows = list(self.banks[bank_id])
            query = str(payload["query"]).lower()
            if "trade" in query:
                rows.sort(key=lambda row: "trades" not in row["content"])
            return {
                "results": [
                    {
                        "id": f"unit-{index}",
                        "text": row["content"],
                        "document_id": row["document_id"],
                        "metadata": row["metadata"],
                    }
                    for index, row in enumerate(rows, start=1)
                ]
            }
        assert method == "POST"
        assert payload is not None
        self.banks[bank_id].extend(payload["items"])
        return {"success": True, "items_count": len(payload["items"])}


def test_hindsight_adapter_scores_document_provenance_and_cleans_banks():
    transport = FakeHindsightTransport()

    result = run_hindsight_evidence(
        _dataset(),
        None,
        1,
        transport=transport,
        bank_prefix="test-run",
        system_version="0.8.5",
        embedding_profile="onnx:intfloat/multilingual-e5-small",
    )

    assert result.engine == "Hindsight OSS"
    assert result.precision_at_1 == 1.0
    assert result.provenance_mode == "document_id"
    assert result.system_version == "0.8.5"
    assert result.embedding_profile == "onnx:intfloat/multilingual-e5-small"
    assert result.ingest_total_ms >= 0.0
    assert transport.banks == {}
    recall_calls = [
        payload
        for method, path, payload in transport.calls
        if method == "POST" and path.endswith("/memories/recall")
    ]
    assert len(recall_calls) == 2
    assert all(call["tags_match"] == "all_strict" for call in recall_calls)
    retained = [
        payload
        for method, path, payload in transport.calls
        if method == "POST" and path.endswith("/memories")
    ]
    assert all(
        item["document_id"] == item["metadata"]["evidence_id"]
        for payload in retained
        for item in payload["items"]
    )
    assert all(
        item.get("timestamp") == "2023-05-08T13:56:00"
        for payload in retained
        for item in payload["items"]
        if item["document_id"] == "conversation-a::D1:1"
    )
    assert all(
        "timestamp" not in item
        for payload in retained
        for item in payload["items"]
        if item["document_id"] != "conversation-a::D1:1"
    )
