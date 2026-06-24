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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class RetrievalDocument:
    id: str
    text: str


@dataclass(frozen=True)
class RetrievalQuery:
    id: str
    text: str


@dataclass(frozen=True)
class RetrievalDataset:
    name: str
    documents: list[RetrievalDocument]
    queries: list[RetrievalQuery]
    qrels: dict[str, dict[str, float]]


@dataclass(frozen=True)
class RetrievalMetrics:
    engine: str
    ndcg_at_k: float
    recall_at_k: float
    mrr_at_k: float
    precision_at_1: float
    avg_latency_ms: float
    p95_latency_ms: float
    queries: int


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return rows


def _record_id(row: dict) -> str:
    value = row.get("_id", row.get("id"))
    if value is None:
        raise ValueError("Expected JSONL record to contain '_id' or 'id'")
    return str(value)


def load_beir_dataset(dataset_dir: str | Path, split: str = "test", limit_corpus: int | None = None, limit_queries: int | None = None) -> RetrievalDataset:
    root = Path(dataset_dir)
    corpus_path = root / "corpus.jsonl"
    queries_path = root / "queries.jsonl"
    qrels_path = root / "qrels" / f"{split}.tsv"
    if not qrels_path.exists():
        qrels_path = root / f"qrels_{split}.tsv"
    for path in (corpus_path, queries_path, qrels_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing BEIR-style benchmark file: {path}")

    documents = []
    for row in _read_jsonl(corpus_path):
        title = str(row.get("title") or "").strip()
        text = str(row.get("text") or "").strip()
        combined = f"{title}\n{text}".strip() if title else text
        documents.append(RetrievalDocument(id=_record_id(row), text=combined))

    queries = [RetrievalQuery(id=_record_id(row), text=str(row.get("text") or "").strip()) for row in _read_jsonl(queries_path)]

    qrels: dict[str, dict[str, float]] = {}
    with qrels_path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if line_number == 1 and any(part.lower() in {"query-id", "corpus-id", "score"} for part in parts):
                continue
            if len(parts) < 3:
                raise ValueError(f"Invalid qrels row at {qrels_path}:{line_number}")
            query_id, document_id, score = parts[0], parts[1], float(parts[2])
            if score > 0:
                qrels.setdefault(query_id, {})[document_id] = score

    queries = [query for query in queries if query.id in qrels]
    if limit_queries is not None:
        queries = queries[:limit_queries]
    if limit_corpus is not None and limit_corpus > 0:
        required_ids = {doc_id for query in queries for doc_id in qrels.get(query.id, {})}
        selected: list[RetrievalDocument] = []
        selected_ids: set[str] = set()
        for document in documents:
            if document.id in required_ids:
                selected.append(document)
                selected_ids.add(document.id)
        for document in documents:
            if len(selected) >= limit_corpus:
                break
            if document.id not in selected_ids:
                selected.append(document)
                selected_ids.add(document.id)
        documents = selected
    document_ids = {document.id for document in documents}
    qrels = {query.id: {doc_id: score for doc_id, score in qrels.get(query.id, {}).items() if doc_id in document_ids} for query in queries}
    queries = [query for query in queries if qrels.get(query.id)]
    return RetrievalDataset(name=root.name, documents=documents, queries=queries, qrels=qrels)


def _dcg(relevances: list[float]) -> float:
    return sum((2.0 ** relevance - 1.0) / math.log2(rank + 2) for rank, relevance in enumerate(relevances))


def compute_retrieval_metrics(dataset: RetrievalDataset, rankings: dict[str, list[str]], latencies_ms: list[float], top_k: int, engine: str) -> RetrievalMetrics:
    ndcg_values = []
    recall_values = []
    reciprocal_ranks = []
    precision_1_values = []
    for query in dataset.queries:
        relevant = dataset.qrels.get(query.id, {})
        ranked_ids = rankings.get(query.id, [])[:top_k]
        ranked_relevance = [float(relevant.get(document_id, 0.0)) for document_id in ranked_ids]
        ideal = _dcg(sorted(relevant.values(), reverse=True)[:top_k])
        ndcg_values.append(_dcg(ranked_relevance) / ideal if ideal > 0 else 0.0)
        hits = [document_id for document_id in ranked_ids if document_id in relevant]
        recall_values.append(len(hits) / len(relevant) if relevant else 0.0)
        precision_1_values.append(1.0 if ranked_ids[:1] and ranked_ids[0] in relevant else 0.0)
        rr = 0.0
        for rank, document_id in enumerate(ranked_ids, start=1):
            if document_id in relevant:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)
    ordered_latencies = sorted(latencies_ms)
    p95_index = min(len(ordered_latencies) - 1, int(len(ordered_latencies) * 0.95)) if ordered_latencies else 0
    return RetrievalMetrics(
        engine=engine,
        ndcg_at_k=statistics.mean(ndcg_values) if ndcg_values else 0.0,
        recall_at_k=statistics.mean(recall_values) if recall_values else 0.0,
        mrr_at_k=statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        precision_at_1=statistics.mean(precision_1_values) if precision_1_values else 0.0,
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=ordered_latencies[p95_index] if ordered_latencies else 0.0,
        queries=len(dataset.queries),
    )


def run_wavemind(dataset: RetrievalDataset, encoder, top_k: int) -> RetrievalMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(db_path=Path(tmp) / "open-retrieval.sqlite3", encoder=encoder, index_kind="numpy", vector_weight=1.0, field_weight=0.0, priority_weight=0.0, lexical_weight=0.0, short_query_lexical_weight=0.0, score_threshold=0.0, rerank_k=max(top_k, 50), evolve_on_feed=0)
        try:
            for document in dataset.documents:
                memory.remember(document.text, namespace="retrieval", metadata={"benchmark_id": document.id})
            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace="retrieval", top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [str(result.metadata.get("benchmark_id", "")) for result in results]
        finally:
            memory.close()
    return compute_retrieval_metrics(dataset, rankings, latencies, top_k, "WaveMind")


def run_chroma(dataset: RetrievalDataset, encoder, top_k: int) -> RetrievalMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError('Install Chroma for this benchmark: pip install -e ".[bench]"') from exc
    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(name=f"wavemind_open_retrieval_{time.time_ns()}", metadata={"hnsw:space": "cosine"}, embedding_function=None)
    collection.add(ids=[document.id for document in dataset.documents], documents=[document.text for document in dataset.documents], embeddings=[encoder.encode_vector(document.text).tolist() for document in dataset.documents])
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in dataset.queries:
        started = time.perf_counter()
        result = collection.query(query_embeddings=[encoder.encode_vector(query.text).tolist()], n_results=top_k, include=[])
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = list(result.get("ids", [[]])[0])
    return compute_retrieval_metrics(dataset, rankings, latencies, top_k, "Chroma")


def run_qdrant(dataset: RetrievalDataset, encoder, top_k: int) -> RetrievalMetrics:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError('Install Qdrant client for this benchmark: pip install -e ".[bench]"') from exc
    client = QdrantClient(":memory:")
    collection_name = f"wavemind_open_retrieval_{time.time_ns()}"
    client.recreate_collection(collection_name=collection_name, vectors_config=VectorParams(size=int(encoder.vector_dim), distance=Distance.COSINE))
    mapping: dict[int, str] = {}
    points = []
    for offset, document in enumerate(dataset.documents, start=1):
        mapping[offset] = document.id
        points.append(PointStruct(id=offset, vector=encoder.encode_vector(document.text).tolist(), payload={"benchmark_id": document.id}))
    client.upsert(collection_name=collection_name, points=points)
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in dataset.queries:
        started = time.perf_counter()
        vector = encoder.encode_vector(query.text).tolist()
        if hasattr(client, "query_points"):
            response = client.query_points(collection_name=collection_name, query=vector, limit=top_k, with_payload=True)
            hits = list(response.points)
        else:
            hits = client.search(collection_name=collection_name, query_vector=vector, limit=top_k, with_payload=True)
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = [str(getattr(hit, "payload", {}).get("benchmark_id") or mapping.get(int(hit.id), "")) for hit in hits]
    return compute_retrieval_metrics(dataset, rankings, latencies, top_k, "Qdrant")


def run_benchmark(dataset_dir: str | Path, engines: Iterable[str], split: str = "test", encoder_kind: str = "hash", top_k: int = 10, limit_corpus: int | None = None, limit_queries: int | None = None) -> dict:
    dataset = load_beir_dataset(dataset_dir, split=split, limit_corpus=limit_corpus, limit_queries=limit_queries)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {"wavemind": run_wavemind, "chroma": run_chroma, "qdrant": run_qdrant}
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](dataset, encoder, top_k)))
    return {
        "scenario": {"name": "open_retrieval_beir_format", "dataset": dataset.name, "documents": len(dataset.documents), "queries": len(dataset.queries), "split": split, "top_k": top_k},
        "embedding": {"kind": encoder_kind, "class": type(encoder).__name__, "vector_dim": getattr(encoder, "vector_dim", None), "note": "All engines receive embeddings from the same WaveMind encoder."},
        "results": results,
    }


def print_table(payload: dict) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| engine | nDCG@{top_k} | Recall@{top_k} | MRR@{top_k} | precision@1 | avg latency |")
    print("|---|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(f"| {result['engine']} | {result['ndcg_at_k']:.3f} | {result['recall_at_k']:.3f} | {result['mrr_at_k']:.3f} | {result['precision_at_1']:.3f} | {result['avg_latency_ms']:.2f} ms |")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--engines", nargs="+", choices=["wavemind", "chroma", "qdrant"], default=["wavemind"])
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit-corpus", type=int, default=None)
    parser.add_argument("--limit-queries", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/open_retrieval_results.json"))
    args = parser.parse_args()
    payload = run_benchmark(dataset_dir=args.dataset, engines=args.engines, split=args.split, encoder_kind=args.encoder, top_k=args.top_k, limit_corpus=args.limit_corpus, limit_queries=args.limit_queries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
