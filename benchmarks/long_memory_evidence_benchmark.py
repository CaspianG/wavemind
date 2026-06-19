from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class LongMemory:
    id: str
    text: str
    namespace: str = "user-a"
    tags: tuple[str, ...] = ("memory",)
    ttl_seconds: float | None = None
    priority: float = 1.0
    timestamp: str | None = None


@dataclass(frozen=True)
class EvidenceQuery:
    id: str
    text: str
    namespace: str
    expected_evidence_ids: tuple[str, ...]
    forbidden_evidence_ids: tuple[str, ...] = ()
    category: str = "general"


@dataclass(frozen=True)
class EvidenceDataset:
    name: str
    memories: list[LongMemory]
    queries: list[EvidenceQuery]


@dataclass(frozen=True)
class EvidenceMetrics:
    engine: str
    evidence_recall_at_k: float
    evidence_precision_at_k: float
    mrr_at_k: float
    precision_at_1: float
    stale_suppression: float
    category_success: dict[str, float]
    context_tokens_returned: int
    context_budget_saved: float
    avg_latency_ms: float
    p95_latency_ms: float
    queries: int


CORE_MEMORIES: tuple[LongMemory, ...] = (
    LongMemory(
        id="profile_name",
        text="The user's name is Andrey.",
        tags=("profile",),
        priority=5.0,
        timestamp="2026-01-01T10:00:00Z",
    ),
    LongMemory(
        id="profile_role",
        text="Andrey is a trader who studies crypto market breakouts.",
        tags=("profile",),
        priority=5.0,
        timestamp="2026-01-01T10:02:00Z",
    ),
    LongMemory(
        id="preference_verbose",
        text="The user once asked for long exploratory answers with broad context.",
        tags=("preference", "stale"),
        ttl_seconds=0,
        priority=1.0,
        timestamp="2026-01-02T12:00:00Z",
    ),
    LongMemory(
        id="preference_short",
        text="The user prefers short practical answers with direct next steps.",
        tags=("preference",),
        priority=8.0,
        timestamp="2026-01-06T12:00:00Z",
    ),
    LongMemory(
        id="old_city",
        text="The user's current city is Berlin.",
        tags=("profile", "stale"),
        ttl_seconds=0,
        priority=1.0,
        timestamp="2026-01-03T09:00:00Z",
    ),
    LongMemory(
        id="new_city",
        text="The user's current city is Lisbon.",
        tags=("profile",),
        priority=8.0,
        timestamp="2026-01-08T09:00:00Z",
    ),
    LongMemory(
        id="expired_token",
        text="The valid temporary login token for this session is blue-114.",
        tags=("temporary", "token"),
        ttl_seconds=0,
        priority=1.0,
        timestamp="2026-01-04T11:00:00Z",
    ),
    LongMemory(
        id="active_token",
        text="The valid temporary login token for this session is green-772.",
        tags=("temporary", "token"),
        priority=5.0,
        timestamp="2026-01-04T11:10:00Z",
    ),
    LongMemory(
        id="budget_user_a",
        text="The user's monthly tool budget is 2000 dollars.",
        namespace="user-a",
        tags=("profile", "budget"),
        priority=5.0,
        timestamp="2026-01-05T13:00:00Z",
    ),
    LongMemory(
        id="budget_user_b",
        text="The user's monthly tool budget is 50 dollars.",
        namespace="user-b",
        tags=("profile", "budget"),
        priority=5.0,
        timestamp="2026-01-05T13:00:00Z",
    ),
    LongMemory(
        id="old_project",
        text="The old side project was Garden Notes.",
        tags=("project", "stale"),
        ttl_seconds=0,
        priority=1.0,
        timestamp="2026-01-02T15:00:00Z",
    ),
    LongMemory(
        id="current_project",
        text="The important current project is WaveMind long-term memory evidence benchmarks.",
        tags=("project",),
        priority=8.0,
        timestamp="2026-01-09T15:00:00Z",
    ),
)


QUERIES: tuple[EvidenceQuery, ...] = (
    EvidenceQuery(
        id="q_name",
        text="What is the user's name?",
        namespace="user-a",
        expected_evidence_ids=("profile_name",),
        category="profile",
    ),
    EvidenceQuery(
        id="q_role",
        text="What does Andrey do as a trader?",
        namespace="user-a",
        expected_evidence_ids=("profile_role",),
        category="profile",
    ),
    EvidenceQuery(
        id="q_preference",
        text="Should answers be short and practical or long and exploratory?",
        namespace="user-a",
        expected_evidence_ids=("preference_short",),
        forbidden_evidence_ids=("preference_verbose",),
        category="personalization",
    ),
    EvidenceQuery(
        id="q_city",
        text="What is the user's current city now?",
        namespace="user-a",
        expected_evidence_ids=("new_city",),
        forbidden_evidence_ids=("old_city",),
        category="correction",
    ),
    EvidenceQuery(
        id="q_active_token",
        text="What temporary login token is still valid?",
        namespace="user-a",
        expected_evidence_ids=("active_token",),
        forbidden_evidence_ids=("expired_token",),
        category="ttl",
    ),
    EvidenceQuery(
        id="q_expired_token_absent",
        text="Is blue-114 still a valid temporary login token?",
        namespace="user-a",
        expected_evidence_ids=(),
        forbidden_evidence_ids=("expired_token",),
        category="ttl",
    ),
    EvidenceQuery(
        id="q_budget",
        text="What is this user's monthly tool budget?",
        namespace="user-a",
        expected_evidence_ids=("budget_user_a",),
        forbidden_evidence_ids=("budget_user_b",),
        category="namespace",
    ),
    EvidenceQuery(
        id="q_project",
        text="Which current project is important right now?",
        namespace="user-a",
        expected_evidence_ids=("current_project",),
        forbidden_evidence_ids=("old_project",),
        category="personalization",
    ),
)


FILLER_TOPICS: tuple[str, ...] = (
    "calendar planning",
    "coffee preference",
    "code formatting",
    "travel notes",
    "meeting summary",
    "book recommendation",
    "design feedback",
    "server maintenance",
    "billing reminder",
    "research note",
)


def _estimate_tokens(text: str) -> int:
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    return max(1, math.ceil(len(words) * 1.25))


def build_synthetic_dataset(memory_count: int = 200) -> EvidenceDataset:
    if memory_count < len(CORE_MEMORIES):
        raise ValueError(f"memory_count must be at least {len(CORE_MEMORIES)}")
    memories = list(CORE_MEMORIES)
    filler_count = memory_count - len(memories)
    for index in range(1, filler_count + 1):
        topic = FILLER_TOPICS[(index - 1) % len(FILLER_TOPICS)]
        namespace = "user-a" if index % 4 else "user-b"
        memories.append(
            LongMemory(
                id=f"filler_{index:04d}",
                text=(
                    f"Session filler memory {index} about {topic}. "
                    "It adds long conversation noise but is not evidence for the benchmark questions."
                ),
                namespace=namespace,
                tags=("filler", topic.replace(" ", "-")),
                priority=1.0,
                timestamp=f"2026-02-{(index % 28) + 1:02d}T10:00:00Z",
            )
        )
    return EvidenceDataset(name="synthetic", memories=memories, queries=list(QUERIES))


def compute_evidence_metrics(
    queries: Iterable[EvidenceQuery],
    rankings: dict[str, list[str]],
    returned_texts: dict[str, list[str]],
    latencies_ms: list[float],
    full_context_tokens: int,
    top_k: int,
    engine: str,
) -> EvidenceMetrics:
    query_list = list(queries)
    recall_values = []
    precision_values = []
    reciprocal_ranks = []
    precision_1_values = []
    suppression_values = []
    category_values: dict[str, list[float]] = {}

    for query in query_list:
        ranked_ids = rankings.get(query.id, [])[:top_k]
        expected = set(query.expected_evidence_ids)
        forbidden = set(query.forbidden_evidence_ids)
        expected_hits = [item for item in ranked_ids if item in expected]
        forbidden_hits = [item for item in ranked_ids if item in forbidden]

        if expected:
            recall = len(expected_hits) / len(expected)
            recall_values.append(recall)
            precision_values.append(len(expected_hits) / max(1, len(ranked_ids)))
            precision_1_values.append(1.0 if ranked_ids[:1] and ranked_ids[0] in expected else 0.0)
            reciprocal = 0.0
            for rank, item in enumerate(ranked_ids, start=1):
                if item in expected:
                    reciprocal = 1.0 / rank
                    break
            reciprocal_ranks.append(reciprocal)
            success = 1.0 if expected_hits and not forbidden_hits else 0.0
        else:
            success = 1.0 if not forbidden_hits else 0.0

        if forbidden:
            suppression_values.append(1.0 if not forbidden_hits else 0.0)
        category_values.setdefault(query.category, []).append(success)

    context_tokens_returned = sum(
        _estimate_tokens(text)
        for values in returned_texts.values()
        for text in values[:top_k]
    )
    context_budget_saved = 0.0
    if full_context_tokens > 0:
        context_budget_saved = max(0.0, 1.0 - (context_tokens_returned / full_context_tokens))

    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95)) if sorted_latencies else 0
    return EvidenceMetrics(
        engine=engine,
        evidence_recall_at_k=statistics.mean(recall_values) if recall_values else 0.0,
        evidence_precision_at_k=statistics.mean(precision_values) if precision_values else 0.0,
        mrr_at_k=statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        precision_at_1=statistics.mean(precision_1_values) if precision_1_values else 0.0,
        stale_suppression=statistics.mean(suppression_values) if suppression_values else 1.0,
        category_success={
            category: statistics.mean(values)
            for category, values in sorted(category_values.items())
        },
        context_tokens_returned=context_tokens_returned,
        context_budget_saved=context_budget_saved,
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=sorted_latencies[p95_index] if sorted_latencies else 0.0,
        queries=len(query_list),
    )


def _full_context_tokens(dataset: EvidenceDataset) -> int:
    return sum(_estimate_tokens(memory.text) for memory in dataset.memories)


def _metric_payload(
    dataset: EvidenceDataset,
    rankings: dict[str, list[str]],
    returned_texts: dict[str, list[str]],
    latencies: list[float],
    top_k: int,
    engine: str,
) -> EvidenceMetrics:
    return compute_evidence_metrics(
        queries=dataset.queries,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=latencies,
        full_context_tokens=_full_context_tokens(dataset),
        top_k=top_k,
        engine=engine,
    )


def run_wavemind(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "long-memory.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            vector_weight=0.78,
            field_weight=0.06,
            priority_weight=0.16,
            lexical_weight=0.35,
            short_query_lexical_weight=1.5,
            rerank_k=max(top_k, 30),
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )
        try:
            for item in dataset.memories:
                memory.remember(
                    item.text,
                    namespace=item.namespace,
                    tags=item.tags,
                    ttl_seconds=item.ttl_seconds,
                    priority=item.priority,
                    metadata={
                        "evidence_id": item.id,
                        "timestamp": item.timestamp,
                    },
                )

            rankings: dict[str, list[str]] = {}
            returned_texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace=query.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [str(result.metadata.get("evidence_id", "")) for result in results]
                returned_texts[query.id] = [result.text for result in results]
        finally:
            memory.close()
    return _metric_payload(dataset, rankings, returned_texts, latencies, top_k, "WaveMind")


def run_static_vector(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    vectors = {
        memory.id: encoder.encode_vector(memory.text)
        for memory in dataset.memories
    }
    texts = {memory.id: memory.text for memory in dataset.memories}
    rankings: dict[str, list[str]] = {}
    returned_texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in dataset.queries:
        query_vector = encoder.encode_vector(query.text)
        started = time.perf_counter()
        scored = [
            (memory_id, float(np.dot(query_vector, vector)))
            for memory_id, vector in vectors.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        selected = [memory_id for memory_id, _ in scored[:top_k]]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = selected
        returned_texts[query.id] = [texts[memory_id] for memory_id in selected]
    return _metric_payload(dataset, rankings, returned_texts, latencies, top_k, "Static vector")


def run_chroma_static(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError('Install Chroma for this benchmark: pip install -e ".[bench]"') from exc

    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        name=f"wavemind_long_memory_{time.time_ns()}",
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    collection.add(
        ids=[item.id for item in dataset.memories],
        documents=[item.text for item in dataset.memories],
        embeddings=[encoder.encode_vector(item.text).tolist() for item in dataset.memories],
    )
    rankings: dict[str, list[str]] = {}
    returned_texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in dataset.queries:
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[encoder.encode_vector(query.text).tolist()],
            n_results=top_k,
            include=["documents"],
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = list(result.get("ids", [[]])[0])
        returned_texts[query.id] = list(result.get("documents", [[]])[0])
    return _metric_payload(dataset, rankings, returned_texts, latencies, top_k, "Chroma static")


def run_qdrant_static(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError('Install Qdrant client for this benchmark: pip install -e ".[bench]"') from exc

    client = QdrantClient(":memory:")
    collection_name = f"wavemind_long_memory_{time.time_ns()}"
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=int(encoder.vector_dim), distance=Distance.COSINE),
    )
    numeric_to_id: dict[int, str] = {}
    points = []
    for index, item in enumerate(dataset.memories, start=1):
        numeric_to_id[index] = item.id
        points.append(
            PointStruct(
                id=index,
                vector=encoder.encode_vector(item.text).tolist(),
                payload={"evidence_id": item.id, "text": item.text},
            )
        )
    client.upsert(collection_name=collection_name, points=points)
    rankings: dict[str, list[str]] = {}
    returned_texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in dataset.queries:
        vector = encoder.encode_vector(query.text).tolist()
        started = time.perf_counter()
        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=collection_name,
                query=vector,
                limit=top_k,
                with_payload=True,
            )
            hits = list(response.points)
        else:
            hits = client.search(
                collection_name=collection_name,
                query_vector=vector,
                limit=top_k,
                with_payload=True,
            )
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = [
            str(getattr(hit, "payload", {}).get("evidence_id") or numeric_to_id.get(int(hit.id), ""))
            for hit in hits
        ]
        returned_texts[query.id] = [
            str(getattr(hit, "payload", {}).get("text", ""))
            for hit in hits
        ]
    return _metric_payload(dataset, rankings, returned_texts, latencies, top_k, "Qdrant static")


def load_dataset(kind: str, memory_count: int) -> EvidenceDataset:
    if kind == "synthetic":
        return build_synthetic_dataset(memory_count=memory_count)
    path = Path(kind)
    if not path.exists():
        raise FileNotFoundError(f"Unknown dataset or missing file: {kind}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    memories = [
        LongMemory(
            id=str(item["id"]),
            text=str(item["text"]),
            namespace=str(item.get("namespace", "user-a")),
            tags=tuple(item.get("tags", ["memory"])),
            ttl_seconds=item.get("ttl_seconds"),
            priority=float(item.get("priority", 1.0)),
            timestamp=item.get("timestamp"),
        )
        for item in payload.get("memories", [])
    ]
    queries = [
        EvidenceQuery(
            id=str(item["id"]),
            text=str(item["text"]),
            namespace=str(item.get("namespace", "user-a")),
            expected_evidence_ids=tuple(item.get("expected_evidence_ids", [])),
            forbidden_evidence_ids=tuple(item.get("forbidden_evidence_ids", [])),
            category=str(item.get("category", "general")),
        )
        for item in payload.get("queries", [])
    ]
    return EvidenceDataset(name=str(payload.get("name", path.stem)), memories=memories, queries=queries)


def run_benchmark(
    dataset_kind: str,
    engines: Iterable[str],
    memory_count: int = 200,
    encoder_kind: str = "hash",
    top_k: int = 5,
) -> dict:
    dataset = load_dataset(dataset_kind, memory_count)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {
        "wavemind": run_wavemind,
        "static": run_static_vector,
        "static-vector": run_static_vector,
        "chroma": run_chroma_static,
        "chroma-static": run_chroma_static,
        "qdrant": run_qdrant_static,
        "qdrant-static": run_qdrant_static,
    }
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](dataset, encoder, top_k)))
    return {
        "scenario": {
            "name": "long_memory_evidence",
            "dataset": dataset.name,
            "memories": len(dataset.memories),
            "queries": len(dataset.queries),
            "top_k": top_k,
            "description": (
                "Retrieval-only long-term memory evidence benchmark. "
                "It measures expected evidence recall, stale suppression, personalization, "
                "namespace isolation, context budget, and latency."
            ),
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
            "note": "All engines receive embeddings from the same WaveMind encoder.",
        },
        "results": results,
    }


def print_table(payload: dict) -> None:
    top_k = payload["scenario"]["top_k"]
    print(
        f"| engine | evidence recall@{top_k} | precision@1 | stale suppression | context saved | avg latency |"
    )
    print("|---|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['evidence_recall_at_k']:.2f} | "
            f"{result['precision_at_1']:.2f} | "
            f"{result['stale_suppression']:.2f} | "
            f"{result['context_budget_saved']:.2f} | "
            f"{result['avg_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="synthetic")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["wavemind", "static", "static-vector", "chroma", "chroma-static", "qdrant", "qdrant-static"],
        default=["wavemind", "static"],
    )
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--memories", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/long_memory_evidence_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        dataset_kind=args.dataset,
        engines=args.engines,
        memory_count=args.memories,
        encoder_kind=args.encoder,
        top_k=args.top_k,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
