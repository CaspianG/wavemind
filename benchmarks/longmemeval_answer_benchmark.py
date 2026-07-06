from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.long_memory_evidence_benchmark import cache_encoder_for_dataset
from benchmarks.longmemeval_memory_benchmark import (
    DATA_URL,
    SOURCE_URL,
    _is_abstention,
    _question_id,
    _samples,
    _read_json,
    load_longmemeval_dataset,
)
from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


_ANSWER_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class AnswerMetrics:
    engine: str
    provider: str
    model: str | None
    queries: int
    exact_match: float
    contains_answer: float
    token_f1: float
    abstention_rate: float
    grounded_answer_rate: float
    unsupported_answer_rate: float
    evidence_recall_at_k: float
    avg_retrieval_ms: float
    avg_generation_ms: float


def normalize_answer(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9а-яё]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def is_generated_abstention(text: str) -> bool:
    normalized = normalize_answer(text)
    return normalized in {
        "i don t know",
        "unknown",
        "not enough information",
        "insufficient evidence",
        "cannot determine",
        "can t determine",
        "not specified",
    } or normalized.startswith("i don t know ")


def answer_content_tokens(text: str) -> list[str]:
    return [
        token
        for token in normalize_answer(text).split()
        if token not in _ANSWER_STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def answer_grounded_in_context(prediction: str, contexts: list[str]) -> bool:
    if is_generated_abstention(prediction):
        return False
    tokens = answer_content_tokens(prediction)
    if not tokens:
        return False
    evidence_text = normalize_answer("\n".join(contexts))
    if not evidence_text:
        return False
    hits = sum(1 for token in tokens if token in evidence_text)
    return hits / len(tokens) >= 0.75


def token_f1(prediction: str, expected: str) -> float:
    pred_tokens = normalize_answer(prediction).split()
    expected_tokens = normalize_answer(expected).split()
    if not pred_tokens and not expected_tokens:
        return 1.0
    if not pred_tokens or not expected_tokens:
        return 0.0
    expected_counts: dict[str, int] = {}
    for token in expected_tokens:
        expected_counts[token] = expected_counts.get(token, 0) + 1
    overlap = 0
    for token in pred_tokens:
        count = expected_counts.get(token, 0)
        if count > 0:
            overlap += 1
            expected_counts[token] = count - 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


def _is_loopback_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _urlopen(url_or_request, timeout: int):
    url = url_or_request.full_url if isinstance(url_or_request, urllib.request.Request) else str(url_or_request)
    if _is_loopback_url(url):
        return _NO_PROXY_OPENER.open(url_or_request, timeout=timeout)
    return urllib.request.urlopen(url_or_request, timeout=timeout)


def clean_generated_answer(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = text.strip()
    text = re.sub(r"^(final\s+answer|answer)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if len(lines) > 1 and len(lines[-1]) <= 160 else text


def _question_terms(question: str) -> set[str]:
    return {
        token
        for token in normalize_answer(question).split()
        if len(token) > 2
        and token
        not in {
            "what",
            "where",
            "when",
            "which",
            "who",
            "how",
            "did",
            "does",
            "was",
            "were",
            "the",
            "with",
            "for",
            "from",
            "that",
            "this",
            "your",
            "you",
            "did",
        }
    }


def compact_evidence(question: str, contexts: list[str], max_chars_per_context: int = 900) -> list[str]:
    terms = _question_terms(question)
    snippets: list[str] = []
    for context in contexts:
        lines = [line.strip() for line in context.splitlines() if line.strip()]
        if not lines:
            continue
        scored: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines):
            normalized = normalize_answer(line)
            score = sum(1 for term in terms if term in normalized)
            if score:
                scored.append((score, -index, line))
        selected = [
            line
            for _score, _negative_index, line in sorted(scored, reverse=True)[:4]
        ]
        if not selected:
            selected = lines[:3]
        snippet = "\n".join(selected)
        snippets.append(snippet[:max_chars_per_context])
    return snippets


def answer_map(path: str | Path, include_abstention: bool = False) -> dict[str, str]:
    answers: dict[str, str] = {}
    seen_questions: dict[str, int] = {}
    for index, sample in enumerate(_samples(_read_json(Path(path))), start=1):
        raw_question_id = _question_id(sample, index)
        seen_questions[raw_question_id] = seen_questions.get(raw_question_id, 0) + 1
        question_id = (
            raw_question_id
            if seen_questions[raw_question_id] == 1
            else f"{raw_question_id}#{seen_questions[raw_question_id]}"
        )
        if _is_abstention(sample, question_id) and not include_abstention:
            continue
        answer = str(sample.get("answer") or "").strip()
        if answer:
            answers[question_id] = answer
    return answers


def retrieve_wavemind(dataset, encoder, top_k: int) -> tuple[dict[str, list[str]], dict[str, list[str]], list[float]]:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "longmemeval-answer.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            evolve_on_feed=0,
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
                    metadata={"evidence_id": item.id, "timestamp": item.timestamp},
                )
            rankings: dict[str, list[str]] = {}
            contexts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace=query.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [str(result.metadata.get("evidence_id", "")) for result in results]
                contexts[query.id] = [result.text for result in results]
        finally:
            memory.close()
    return rankings, contexts, latencies


def retrieve_static_vector(dataset, encoder, top_k: int) -> tuple[dict[str, list[str]], dict[str, list[str]], list[float]]:
    memory_vectors = encoder.encode_vectors(item.text for item in dataset.memories)
    vectors = {
        item.id: vector
        for item, vector in zip(dataset.memories, memory_vectors)
    }
    text_by_id = {item.id: item.text for item in dataset.memories}
    ids_by_namespace: dict[str, list[str]] = {}
    for item in dataset.memories:
        ids_by_namespace.setdefault(item.namespace, []).append(item.id)
    rankings: dict[str, list[str]] = {}
    contexts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        scored = [
            (item_id, float(np.dot(qvec, vectors[item_id])))
            for item_id in ids_by_namespace.get(query.namespace, [])
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        selected = [item_id for item_id, _ in scored[:top_k]]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = selected
        contexts[query.id] = [text_by_id[item_id] for item_id in selected]
    return rankings, contexts, latencies


def retrieve_chroma_static(dataset, encoder, top_k: int) -> tuple[dict[str, list[str]], dict[str, list[str]], list[float]]:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError('Install Chroma for this benchmark: pip install -e ".[bench]"') from exc
    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        name=f"wavemind_answer_{time.time_ns()}",
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    batch_size = 1000
    for offset in range(0, len(dataset.memories), batch_size):
        batch = dataset.memories[offset : offset + batch_size]
        vectors = encoder.encode_vectors(item.text for item in batch)
        collection.add(
            ids=[item.id for item in batch],
            documents=[item.text for item in batch],
            embeddings=[vector.tolist() for vector in vectors],
            metadatas=[{"namespace": item.namespace} for item in batch],
        )
    rankings: dict[str, list[str]] = {}
    contexts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[qvec.tolist()],
            n_results=top_k,
            where={"namespace": query.namespace},
            include=["documents"],
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = list(result.get("ids", [[]])[0])
        contexts[query.id] = list(result.get("documents", [[]])[0])
    return rankings, contexts, latencies


def retrieve_qdrant_static(dataset, encoder, top_k: int) -> tuple[dict[str, list[str]], dict[str, list[str]], list[float]]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError('Install Qdrant client for this benchmark: pip install -e ".[bench]"') from exc
    client = QdrantClient(":memory:")
    collection_name = f"wavemind_answer_{time.time_ns()}"
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=int(encoder.vector_dim), distance=Distance.COSINE),
    )
    text_by_id = {item.id: item.text for item in dataset.memories}
    memory_vectors = encoder.encode_vectors(item.text for item in dataset.memories)
    points = [
        PointStruct(
            id=index,
            vector=vector.tolist(),
            payload={"evidence_id": item.id, "namespace": item.namespace},
        )
        for index, (item, vector) in enumerate(zip(dataset.memories, memory_vectors), start=1)
    ]
    numeric_to_id = {index: item.id for index, item in enumerate(dataset.memories, start=1)}
    batch_size = 1000
    for offset in range(0, len(points), batch_size):
        client.upsert(collection_name=collection_name, points=points[offset : offset + batch_size])
    rankings: dict[str, list[str]] = {}
    contexts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(query.text for query in dataset.queries)
    for query, qvec in zip(dataset.queries, query_vectors):
        started = time.perf_counter()
        query_filter = Filter(
            must=[FieldCondition(key="namespace", match=MatchValue(value=query.namespace))]
        )
        if hasattr(client, "query_points"):
            hits = list(
                client.query_points(
                    collection_name=collection_name,
                    query=qvec.tolist(),
                    query_filter=query_filter,
                    limit=top_k,
                    with_payload=True,
                ).points
            )
        else:
            hits = client.search(
                collection_name=collection_name,
                query_vector=qvec.tolist(),
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        latencies.append((time.perf_counter() - started) * 1000.0)
        ids = [
            str(getattr(hit, "payload", {}).get("evidence_id") or numeric_to_id.get(int(hit.id), ""))
            for hit in hits
        ]
        rankings[query.id] = ids
        contexts[query.id] = [text_by_id[item_id] for item_id in ids if item_id in text_by_id]
    return rankings, contexts, latencies


RETRIEVERS = {
    "wavemind": ("WaveMind", retrieve_wavemind),
    "static": ("Static vector", retrieve_static_vector),
    "static-vector": ("Static vector", retrieve_static_vector),
    "chroma": ("Chroma static", retrieve_chroma_static),
    "chroma-static": ("Chroma static", retrieve_chroma_static),
    "qdrant": ("Qdrant static", retrieve_qdrant_static),
    "qdrant-static": ("Qdrant static", retrieve_qdrant_static),
}


def generate_extractive(question: str, contexts: list[str]) -> str:
    if not contexts:
        return "I don't know."
    context = contexts[0]
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith(("user:", "assistant:")):
            return line.split(":", 1)[1].strip()[:240]
    return lines[0][:240] if lines else context[:240]


def ollama_models(base_url: str) -> list[str]:
    try:
        with _urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc
    return [str(model.get("name")) for model in payload.get("models", []) if model.get("name")]


def generate_ollama(
    question: str,
    contexts: list[str],
    model: str,
    base_url: str,
) -> str:
    evidence = compact_evidence(question, contexts)
    prompt = (
        "Answer the question using only the evidence below. "
        "If the evidence is insufficient, answer: I don't know. "
        "Return only the final short answer. Do not explain.\n\n"
        f"Question: {question}\n\n"
        "Evidence:\n"
        + "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(evidence))
        + "\n\nAnswer:"
    )
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 96},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Ollama generation failed for model {model}: {exc}") from exc
    return clean_generated_answer(str(result.get("response") or ""))


def run_benchmark(
    dataset_path: str | Path,
    provider: str = "extractive",
    model: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
    engines: Iterable[str] = ("wavemind",),
    encoder_kind: str = "hash",
    granularity: str = "session",
    top_k: int = 5,
    limit_queries: int | None = 20,
    include_abstention: bool = False,
) -> dict[str, Any]:
    dataset = load_longmemeval_dataset(
        dataset_path,
        granularity=granularity,
        limit_queries=limit_queries,
        include_abstention=include_abstention,
    )
    answers = answer_map(dataset_path, include_abstention=include_abstention)
    base_encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    encoder = cache_encoder_for_dataset(dataset, base_encoder)

    selected_model = model
    if provider == "ollama":
        models = ollama_models(ollama_url)
        if selected_model is None:
            selected_model = models[0] if models else None
        if not selected_model:
            raise RuntimeError(
                "Ollama is reachable but no local models are installed. "
                "Install or select a local model, then rerun with --provider ollama."
            )

    results: list[dict[str, Any]] = []
    examples_by_engine: dict[str, list[dict[str, Any]]] = {}
    for engine in engines:
        key = engine.lower()
        if key not in RETRIEVERS:
            raise ValueError(f"Unknown engine: {engine}")
        engine_name, retrieve = RETRIEVERS[key]
        rankings, contexts, retrieval_latencies = retrieve(dataset, encoder, top_k)
        generated: dict[str, str] = {}
        generation_latencies: list[float] = []
        exact_values: list[float] = []
        contains_values: list[float] = []
        f1_values: list[float] = []
        abstention_values: list[float] = []
        grounded_values: list[float] = []
        unsupported_values: list[float] = []
        evidence_recalls: list[float] = []
        for query in dataset.queries:
            expected_answer = answers.get(query.id, "")
            expected_evidence = set(query.expected_evidence_ids)
            ranked = rankings.get(query.id, [])[:top_k]
            evidence_recalls.append(len(set(ranked) & expected_evidence) / max(1, len(expected_evidence)))
            started = time.perf_counter()
            if provider == "extractive":
                answer = generate_extractive(query.text, contexts.get(query.id, []))
            elif provider == "ollama":
                answer = generate_ollama(query.text, contexts.get(query.id, []), selected_model or "", ollama_url)
            else:
                raise ValueError("provider must be extractive or ollama")
            generation_latencies.append((time.perf_counter() - started) * 1000.0)
            generated[query.id] = answer
            abstained = is_generated_abstention(answer)
            grounded = answer_grounded_in_context(answer, contexts.get(query.id, []))
            abstention_values.append(1.0 if abstained else 0.0)
            grounded_values.append(1.0 if grounded else 0.0)
            unsupported_values.append(1.0 if not abstained and not grounded else 0.0)
            if expected_answer:
                normalized_prediction = normalize_answer(answer)
                normalized_expected = normalize_answer(expected_answer)
                exact_values.append(1.0 if normalized_prediction == normalized_expected else 0.0)
                contains_values.append(
                    1.0
                    if normalized_expected and normalized_expected in normalized_prediction
                    else 0.0
                )
                f1_values.append(token_f1(answer, expected_answer))

        metrics = AnswerMetrics(
            engine=engine_name,
            provider=provider,
            model=selected_model,
            queries=len(dataset.queries),
            exact_match=statistics.mean(exact_values) if exact_values else 0.0,
            contains_answer=statistics.mean(contains_values) if contains_values else 0.0,
            token_f1=statistics.mean(f1_values) if f1_values else 0.0,
            abstention_rate=statistics.mean(abstention_values) if abstention_values else 0.0,
            grounded_answer_rate=statistics.mean(grounded_values) if grounded_values else 0.0,
            unsupported_answer_rate=statistics.mean(unsupported_values) if unsupported_values else 0.0,
            evidence_recall_at_k=statistics.mean(evidence_recalls) if evidence_recalls else 0.0,
            avg_retrieval_ms=statistics.mean(retrieval_latencies) if retrieval_latencies else 0.0,
            avg_generation_ms=statistics.mean(generation_latencies) if generation_latencies else 0.0,
        )
        results.append(asdict(metrics))
        examples_by_engine[engine_name] = [
            {
                "id": query.id,
                "question": query.text,
                "expected": answers.get(query.id, ""),
                "prediction": generated.get(query.id, ""),
                "evidence_ids": rankings.get(query.id, [])[:top_k],
            }
            for query in dataset.queries[:5]
        ]
    return {
        "scenario": {
            "name": "longmemeval_answer_generation",
            "dataset": str(dataset_path),
            "source_url": SOURCE_URL,
            "data_url": DATA_URL,
            "granularity": granularity,
            "queries": len(dataset.queries),
            "memories": len(dataset.memories),
            "top_k": top_k,
            "engines": [result["engine"] for result in results],
            "description": "LongMemEval answer-generation evaluation over retrieved compact evidence.",
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(base_encoder).__name__,
            "cached": True,
            "vector_dim": getattr(encoder, "vector_dim", None),
        },
        "results": results,
        "metrics": results[0] if results else {},
        "examples": next(iter(examples_by_engine.values()), []),
        "examples_by_engine": examples_by_engine,
    }


def print_table(payload: dict[str, Any]) -> None:
    print("| engine | provider | model | queries | evidence recall@k | exact match | contains answer | token F1 | grounded | unsupported | abstain | retrieval | generation |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for metrics in payload.get("results", [payload["metrics"]]):
        print(
            f"| {metrics['engine']} | "
            f"{metrics['provider']} | "
            f"{metrics.get('model') or '-'} | "
            f"{metrics['queries']} | "
            f"{metrics['evidence_recall_at_k']:.3f} | "
            f"{metrics['exact_match']:.3f} | "
            f"{metrics['contains_answer']:.3f} | "
            f"{metrics['token_f1']:.3f} | "
            f"{metrics['grounded_answer_rate']:.3f} | "
            f"{metrics['unsupported_answer_rate']:.3f} | "
            f"{metrics['abstention_rate']:.3f} | "
            f"{metrics['avg_retrieval_ms']:.2f} ms | "
            f"{metrics['avg_generation_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--provider", choices=["extractive", "ollama"], default="extractive")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["wavemind", "static", "static-vector", "chroma", "chroma-static", "qdrant", "qdrant-static"],
        default=["wavemind"],
    )
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--granularity", choices=["session", "turn"], default="session")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-queries", type=int, default=20)
    parser.add_argument("--include-abstention", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/longmemeval_answer_results.json"))
    args = parser.parse_args()
    try:
        payload = run_benchmark(
            dataset_path=args.dataset,
            provider=args.provider,
            model=args.model,
            ollama_url=args.ollama_url,
            engines=args.engines,
            encoder_kind=args.encoder,
            granularity=args.granularity,
            top_k=args.top_k,
            limit_queries=args.limit_queries,
            include_abstention=args.include_abstention,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
