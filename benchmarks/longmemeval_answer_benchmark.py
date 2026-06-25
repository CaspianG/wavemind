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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class AnswerMetrics:
    provider: str
    model: str | None
    queries: int
    exact_match: float
    contains_answer: float
    token_f1: float
    evidence_recall_at_k: float
    avg_retrieval_ms: float
    avg_generation_ms: float


def normalize_answer(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9а-яё]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


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
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=15) as response:
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
    prompt = (
        "Answer the question using only the evidence below. "
        "If the evidence is insufficient, answer: I don't know.\n\n"
        f"Question: {question}\n\n"
        "Evidence:\n"
        + "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(contexts))
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
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Ollama generation failed for model {model}: {exc}") from exc
    return str(result.get("response") or "").strip()


def run_benchmark(
    dataset_path: str | Path,
    provider: str = "extractive",
    model: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
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
    rankings, contexts, retrieval_latencies = retrieve_wavemind(dataset, encoder, top_k=top_k)

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

    generated: dict[str, str] = {}
    generation_latencies: list[float] = []
    exact_values: list[float] = []
    contains_values: list[float] = []
    f1_values: list[float] = []
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
        provider=provider,
        model=selected_model,
        queries=len(dataset.queries),
        exact_match=statistics.mean(exact_values) if exact_values else 0.0,
        contains_answer=statistics.mean(contains_values) if contains_values else 0.0,
        token_f1=statistics.mean(f1_values) if f1_values else 0.0,
        evidence_recall_at_k=statistics.mean(evidence_recalls) if evidence_recalls else 0.0,
        avg_retrieval_ms=statistics.mean(retrieval_latencies) if retrieval_latencies else 0.0,
        avg_generation_ms=statistics.mean(generation_latencies) if generation_latencies else 0.0,
    )
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
            "description": "LongMemEval answer-generation evaluation over WaveMind-retrieved evidence.",
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(base_encoder).__name__,
            "cached": True,
            "vector_dim": getattr(encoder, "vector_dim", None),
        },
        "metrics": asdict(metrics),
        "examples": [
            {
                "id": query.id,
                "question": query.text,
                "expected": answers.get(query.id, ""),
                "prediction": generated.get(query.id, ""),
                "evidence_ids": rankings.get(query.id, [])[:top_k],
            }
            for query in dataset.queries[:5]
        ],
    }


def print_table(payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    print("| provider | model | queries | evidence recall@k | exact match | contains answer | token F1 | retrieval | generation |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    print(
        f"| {metrics['provider']} | {metrics.get('model') or '-'} | "
        f"{metrics['queries']} | "
        f"{metrics['evidence_recall_at_k']:.3f} | "
        f"{metrics['exact_match']:.3f} | "
        f"{metrics['contains_answer']:.3f} | "
        f"{metrics['token_f1']:.3f} | "
        f"{metrics['avg_retrieval_ms']:.2f} ms | "
        f"{metrics['avg_generation_ms']:.2f} ms |"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--provider", choices=["extractive", "ollama"], default="extractive")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
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
