from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from collections.abc import Iterable as IterableABC
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


class CachedTextEncoder:
    def __init__(self, encoder, texts: Iterable[str]):
        self.encoder = encoder
        self.vector_dim = int(getattr(encoder, "vector_dim"))
        unique_texts = list(dict.fromkeys(str(text) for text in texts))
        self._cache: dict[str, np.ndarray] = {}
        if not unique_texts:
            return
        if hasattr(encoder, "encode_vectors"):
            vectors = encoder.encode_vectors(unique_texts)
            for text, vector in zip(unique_texts, vectors):
                self._cache[text] = np.asarray(vector, dtype=np.float32)
            return
        for text in unique_texts:
            self._cache[text] = np.asarray(encoder.encode_vector(text), dtype=np.float32)

    def encode_vector(self, text: str) -> np.ndarray:
        key = str(text)
        if key not in self._cache:
            self._cache[key] = np.asarray(self.encoder.encode_vector(key), dtype=np.float32)
        return self._cache[key]

    def encode_vectors(self, texts: IterableABC[str]) -> np.ndarray:
        vectors = [self.encode_vector(text) for text in texts]
        if not vectors:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        return np.stack(vectors).astype(np.float32)


def cache_encoder_for_dataset(dataset: EvidenceDataset, encoder) -> CachedTextEncoder:
    texts = [memory.text for memory in dataset.memories]
    texts.extend(query.text for query in dataset.queries)
    return CachedTextEncoder(encoder, texts)


CORE_MEMORIES = (
    LongMemory("profile_name", "The user's name is Andrey.", tags=("profile",), priority=5.0),
    LongMemory("profile_role", "Andrey is a trader who studies crypto market breakouts.", tags=("profile",), priority=5.0),
    LongMemory("preference_verbose", "The user once asked for long exploratory answers with broad context.", tags=("preference", "stale"), ttl_seconds=0, priority=1.0),
    LongMemory("preference_short", "The user prefers short practical answers with direct next steps.", tags=("preference",), priority=8.0),
    LongMemory("old_city", "The user's current city is Berlin.", tags=("profile", "stale"), ttl_seconds=0, priority=1.0),
    LongMemory("new_city", "The user's current city is Lisbon.", tags=("profile",), priority=8.0),
    LongMemory("expired_token", "The valid temporary login token for this session is blue-114.", tags=("temporary", "token"), ttl_seconds=0, priority=1.0),
    LongMemory("active_token", "The valid temporary login token for this session is green-772.", tags=("temporary", "token"), priority=5.0),
    LongMemory("budget_user_a", "The user's monthly tool budget is 2000 dollars.", namespace="user-a", tags=("profile", "budget"), priority=5.0),
    LongMemory("budget_user_b", "The user's monthly tool budget is 50 dollars.", namespace="user-b", tags=("profile", "budget"), priority=5.0),
    LongMemory("old_project", "The old side project was Garden Notes.", tags=("project", "stale"), ttl_seconds=0, priority=1.0),
    LongMemory("current_project", "The important current project is WaveMind long-term memory evidence benchmarks.", tags=("project",), priority=8.0),
)

QUERIES = (
    EvidenceQuery("q_name", "What is the user's name?", "user-a", ("profile_name",), category="profile"),
    EvidenceQuery("q_role", "What does Andrey do as a trader?", "user-a", ("profile_role",), category="profile"),
    EvidenceQuery("q_preference", "Should answers be short and practical or long and exploratory?", "user-a", ("preference_short",), ("preference_verbose",), "personalization"),
    EvidenceQuery("q_city", "What is the user's current city now?", "user-a", ("new_city",), ("old_city",), "correction"),
    EvidenceQuery("q_active_token", "What temporary login token is still valid?", "user-a", ("active_token",), ("expired_token",), "ttl"),
    EvidenceQuery("q_expired_token_absent", "Is blue-114 still a valid temporary login token?", "user-a", (), ("expired_token",), "ttl"),
    EvidenceQuery("q_budget", "What is this user's monthly tool budget?", "user-a", ("budget_user_a",), ("budget_user_b",), "namespace"),
    EvidenceQuery("q_project", "Which current project is important right now?", "user-a", ("current_project",), ("old_project",), "personalization"),
)

FILLER_TOPICS = ("calendar planning", "coffee preference", "code formatting", "travel notes", "meeting summary", "book recommendation", "design feedback", "server maintenance", "billing reminder", "research note")


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len([word for word in text.replace("\n", " ").split(" ") if word]) * 1.25))


def build_synthetic_dataset(memory_count: int = 200) -> EvidenceDataset:
    if memory_count < len(CORE_MEMORIES):
        raise ValueError(f"memory_count must be at least {len(CORE_MEMORIES)}")
    memories = list(CORE_MEMORIES)
    for index in range(1, memory_count - len(memories) + 1):
        topic = FILLER_TOPICS[(index - 1) % len(FILLER_TOPICS)]
        namespace = "user-a" if index % 4 else "user-b"
        memories.append(LongMemory(
            id=f"filler_{index:04d}",
            text=f"Session filler memory {index} about {topic}. It adds long conversation noise but is not evidence for the benchmark questions.",
            namespace=namespace,
            tags=("filler", topic.replace(" ", "-")),
            priority=1.0,
            timestamp=f"2026-02-{(index % 28) + 1:02d}T10:00:00Z",
        ))
    return EvidenceDataset(name="synthetic", memories=memories, queries=list(QUERIES))


def compute_evidence_metrics(queries: Iterable[EvidenceQuery], rankings: dict[str, list[str]], returned_texts: dict[str, list[str]], latencies_ms: list[float], full_context_tokens: int, top_k: int, engine: str) -> EvidenceMetrics:
    query_list = list(queries)
    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    precision_1: list[float] = []
    suppressions: list[float] = []
    category_values: dict[str, list[float]] = {}
    for query in query_list:
        ranked = rankings.get(query.id, [])[:top_k]
        expected = set(query.expected_evidence_ids)
        forbidden = set(query.forbidden_evidence_ids)
        expected_hits = [item for item in ranked if item in expected]
        forbidden_hits = [item for item in ranked if item in forbidden]
        if expected:
            recalls.append(len(expected_hits) / len(expected))
            precisions.append(len(expected_hits) / max(1, len(ranked)))
            precision_1.append(1.0 if ranked[:1] and ranked[0] in expected else 0.0)
            reciprocal = 0.0
            for rank, item in enumerate(ranked, start=1):
                if item in expected:
                    reciprocal = 1.0 / rank
                    break
            reciprocal_ranks.append(reciprocal)
            success = 1.0 if expected_hits and not forbidden_hits else 0.0
        else:
            success = 1.0 if not forbidden_hits else 0.0
        if forbidden:
            suppressions.append(1.0 if not forbidden_hits else 0.0)
        category_values.setdefault(query.category, []).append(success)
    context_tokens = sum(_estimate_tokens(text) for values in returned_texts.values() for text in values[:top_k])
    saved = max(0.0, 1.0 - (context_tokens / full_context_tokens)) if full_context_tokens else 0.0
    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95)) if sorted_latencies else 0
    return EvidenceMetrics(
        engine=engine,
        evidence_recall_at_k=statistics.mean(recalls) if recalls else 0.0,
        evidence_precision_at_k=statistics.mean(precisions) if precisions else 0.0,
        mrr_at_k=statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        precision_at_1=statistics.mean(precision_1) if precision_1 else 0.0,
        stale_suppression=statistics.mean(suppressions) if suppressions else 1.0,
        category_success={category: statistics.mean(values) for category, values in sorted(category_values.items())},
        context_tokens_returned=context_tokens,
        context_budget_saved=saved,
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=sorted_latencies[p95_index] if sorted_latencies else 0.0,
        queries=len(query_list),
    )


def _full_context_tokens(dataset: EvidenceDataset) -> int:
    return sum(_estimate_tokens(memory.text) for memory in dataset.memories)


def _to_metrics(dataset: EvidenceDataset, rankings: dict[str, list[str]], texts: dict[str, list[str]], latencies: list[float], top_k: int, engine: str) -> EvidenceMetrics:
    return compute_evidence_metrics(dataset.queries, rankings, texts, latencies, _full_context_tokens(dataset), top_k, engine)


def run_wavemind(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(db_path=Path(tmp) / "long-memory.sqlite3", encoder=encoder, index_kind="numpy", score_threshold=0.0, vector_weight=0.78, field_weight=0.06, priority_weight=0.16, lexical_weight=0.35, short_query_lexical_weight=1.5, rerank_k=max(top_k, 30), persist_access_on_query=False, query_feedback_strength=0.0)
        try:
            for item in dataset.memories:
                memory.remember(item.text, namespace=item.namespace, tags=item.tags, ttl_seconds=item.ttl_seconds, priority=item.priority, metadata={"evidence_id": item.id, "timestamp": item.timestamp})
            rankings: dict[str, list[str]] = {}
            texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace=query.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [str(result.metadata.get("evidence_id", "")) for result in results]
                texts[query.id] = [result.text for result in results]
        finally:
            memory.close()
    return _to_metrics(dataset, rankings, texts, latencies, top_k, "WaveMind")


def run_static_vector(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    memory_vectors = encoder.encode_vectors(item.text for item in dataset.memories)
    vectors = {
        item.id: vector
        for item, vector in zip(dataset.memories, memory_vectors)
    }
    text_by_id = {item.id: item.text for item in dataset.memories}
    rankings: dict[str, list[str]] = {}
    texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        scored = [(item_id, float(np.dot(qvec, vector))) for item_id, vector in vectors.items()]
        scored.sort(key=lambda item: item[1], reverse=True)
        selected = [item_id for item_id, _ in scored[:top_k]]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = selected
        texts[query.id] = [text_by_id[item_id] for item_id in selected]
    return _to_metrics(dataset, rankings, texts, latencies, top_k, "Static vector")


def run_chroma_static(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError('Install Chroma for this benchmark: pip install -e ".[bench]"') from exc
    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(name=f"wavemind_long_memory_{time.time_ns()}", metadata={"hnsw:space": "cosine"}, embedding_function=None)
    batch_size = 1000
    for offset in range(0, len(dataset.memories), batch_size):
        batch = dataset.memories[offset : offset + batch_size]
        vectors = encoder.encode_vectors(item.text for item in batch)
        collection.add(
            ids=[item.id for item in batch],
            documents=[item.text for item in batch],
            embeddings=[vector.tolist() for vector in vectors],
        )
    rankings: dict[str, list[str]] = {}
    texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        result = collection.query(query_embeddings=[qvec.tolist()], n_results=top_k, include=["documents"])
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = list(result.get("ids", [[]])[0])
        texts[query.id] = list(result.get("documents", [[]])[0])
    return _to_metrics(dataset, rankings, texts, latencies, top_k, "Chroma static")


def run_qdrant_static(dataset: EvidenceDataset, encoder, top_k: int) -> EvidenceMetrics:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError('Install Qdrant client for this benchmark: pip install -e ".[bench]"') from exc
    client = QdrantClient(":memory:")
    collection_name = f"wavemind_long_memory_{time.time_ns()}"
    client.recreate_collection(collection_name=collection_name, vectors_config=VectorParams(size=int(encoder.vector_dim), distance=Distance.COSINE))
    text_by_id = {item.id: item.text for item in dataset.memories}
    memory_vectors = encoder.encode_vectors(item.text for item in dataset.memories)
    points = [
        PointStruct(id=i, vector=vector.tolist(), payload={"evidence_id": item.id})
        for i, (item, vector) in enumerate(zip(dataset.memories, memory_vectors), start=1)
    ]
    numeric_to_id = {i: item.id for i, item in enumerate(dataset.memories, start=1)}
    batch_size = 1000
    for offset in range(0, len(points), batch_size):
        client.upsert(collection_name=collection_name, points=points[offset : offset + batch_size])
    rankings: dict[str, list[str]] = {}
    texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        if hasattr(client, "query_points"):
            hits = list(client.query_points(collection_name=collection_name, query=qvec.tolist(), limit=top_k, with_payload=True).points)
        else:
            hits = client.search(collection_name=collection_name, query_vector=qvec.tolist(), limit=top_k, with_payload=True)
        latencies.append((time.perf_counter() - started) * 1000.0)
        ids = [str(getattr(hit, "payload", {}).get("evidence_id") or numeric_to_id.get(int(hit.id), "")) for hit in hits]
        rankings[query.id] = ids
        texts[query.id] = [text_by_id[item_id] for item_id in ids if item_id in text_by_id]
    return _to_metrics(dataset, rankings, texts, latencies, top_k, "Qdrant static")


def load_dataset(kind: str, memory_count: int) -> EvidenceDataset:
    if kind == "synthetic":
        return build_synthetic_dataset(memory_count)
    path = Path(kind)
    payload = json.loads(path.read_text(encoding="utf-8"))
    memories = [LongMemory(id=str(item["id"]), text=str(item["text"]), namespace=str(item.get("namespace", "user-a")), tags=tuple(item.get("tags", ["memory"])), ttl_seconds=item.get("ttl_seconds"), priority=float(item.get("priority", 1.0)), timestamp=item.get("timestamp")) for item in payload.get("memories", [])]
    queries = [EvidenceQuery(id=str(item["id"]), text=str(item["text"]), namespace=str(item.get("namespace", "user-a")), expected_evidence_ids=tuple(item.get("expected_evidence_ids", [])), forbidden_evidence_ids=tuple(item.get("forbidden_evidence_ids", [])), category=str(item.get("category", "general"))) for item in payload.get("queries", [])]
    return EvidenceDataset(name=str(payload.get("name", path.stem)), memories=memories, queries=queries)


def run_benchmark(dataset_kind: str, engines: Iterable[str], memory_count: int = 200, encoder_kind: str = "hash", top_k: int = 5) -> dict:
    dataset = load_dataset(dataset_kind, memory_count)
    base_encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    encoder = cache_encoder_for_dataset(dataset, base_encoder)
    runners = {"wavemind": run_wavemind, "static": run_static_vector, "static-vector": run_static_vector, "chroma": run_chroma_static, "chroma-static": run_chroma_static, "qdrant": run_qdrant_static, "qdrant-static": run_qdrant_static}
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](dataset, encoder, top_k)))
    return {"scenario": {"name": "long_memory_evidence", "dataset": dataset.name, "memories": len(dataset.memories), "queries": len(dataset.queries), "top_k": top_k, "description": "Retrieval-only long-term memory evidence benchmark. It measures expected evidence recall, stale suppression, personalization, namespace isolation, context budget, and latency."}, "embedding": {"kind": encoder_kind, "class": type(base_encoder).__name__, "cached": True, "vector_dim": getattr(encoder, "vector_dim", None), "note": "All engines receive embeddings from the same WaveMind encoder."}, "results": results}


def print_table(payload: dict) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| engine | evidence recall@{top_k} | precision@1 | stale suppression | context saved | avg latency |")
    print("|---|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(f"| {result['engine']} | {result['evidence_recall_at_k']:.2f} | {result['precision_at_1']:.2f} | {result['stale_suppression']:.2f} | {result['context_budget_saved']:.2f} | {result['avg_latency_ms']:.2f} ms |")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="synthetic")
    parser.add_argument("--engines", nargs="+", choices=["wavemind", "static", "static-vector", "chroma", "chroma-static", "qdrant", "qdrant-static"], default=["wavemind", "static"])
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--memories", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/long_memory_evidence_results.json"))
    args = parser.parse_args()
    payload = run_benchmark(args.dataset, args.engines, args.memories, args.encoder, args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
