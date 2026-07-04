from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _engine_results(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    return {
        str(result["engine"]): result
        for result in payload.get("results", [])
        if "engine" in result
    }


def _metric_summary(result: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not result:
        return None
    return {key: result[key] for key in keys if key in result}


def _ann_latest_results(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    size_results = payload.get("results", [])
    if not size_results:
        return {}
    latest = size_results[-1]
    return {
        str(result["engine"]): _metric_summary(
            result,
            ("recall_at_k", "avg_latency_ms", "p95_latency_ms", "build_ms"),
        )
        for result in latest.get("results", [])
        if "engine" in result
    }


def _answer_result_summaries(
    payload: dict[str, Any] | None,
    default_label: str,
) -> dict[str, dict[str, Any] | None]:
    if not payload:
        return {}
    metrics = payload.get("results") or [payload.get("metrics", {})]
    summaries: dict[str, dict[str, Any] | None] = {}
    for result in metrics:
        if not result:
            continue
        engine = str(result.get("engine") or default_label)
        model = str(result.get("model") or "").strip()
        if model:
            label = f"{engine} + {model}"
        else:
            label = default_label
        summaries[label] = _metric_summary(
            result,
            (
                "queries",
                "evidence_recall_at_k",
                "exact_match",
                "contains_answer",
                "token_f1",
                "avg_retrieval_ms",
                "avg_generation_ms",
            ),
        )
    return summaries


def _implemented_entries(root: Path) -> list[dict[str, Any]]:
    agent_payload = _load_json(root / "benchmarks" / "agent_memory_results.json")
    dynamic_payload = _load_json(root / "benchmarks" / "dynamic_memory_results.json")
    field_payload = _load_json(root / "benchmarks" / "field_memory_dynamics_results.json")
    capacity_payload = _load_json(root / "benchmarks" / "wavemind_capacity_results.json")
    long_memory_payload = _load_json(root / "benchmarks" / "long_memory_evidence_results.json")
    open_retrieval_payload = _load_json(root / "benchmarks" / "open_retrieval_scifact_results.json")
    nomiracl_payload = _load_json(root / "benchmarks" / "nomiracl_russian_results.json")
    locomo_payload = _load_json(root / "benchmarks" / "locomo_evidence_results.json")
    locomo_sentence_payload = _load_json(root / "benchmarks" / "locomo_sentence_evidence_results.json")
    longmemeval_payload = _load_json(root / "benchmarks" / "longmemeval_evidence_results.json")
    longmemeval_50_payload = _load_json(root / "benchmarks" / "longmemeval_evidence_50_results.json")
    ann_payload = _load_json(root / "benchmarks" / "ann_index_curve_results.json")
    production_index_payload = _load_json(root / "benchmarks" / "production_index_profile_results.json")
    answer_payload = _load_json(root / "benchmarks" / "longmemeval_answer_extractive_20_results.json")

    agent_results = _engine_results(agent_payload)
    dynamic_results = _engine_results(dynamic_payload)
    long_memory_results = _engine_results(long_memory_payload)
    open_retrieval_results = _engine_results(open_retrieval_payload)
    nomiracl_results = _engine_results(nomiracl_payload)
    locomo_results = _engine_results(locomo_payload)
    locomo_sentence_results = _engine_results(locomo_sentence_payload)
    longmemeval_results = _engine_results(longmemeval_payload)
    longmemeval_50_results = _engine_results(longmemeval_50_payload)
    ann_results = _ann_latest_results(ann_payload)
    production_index_results = _ann_latest_results(production_index_payload)
    answer_qwen05_payload = _load_json(root / "benchmarks" / "longmemeval_answer_qwen25_0_5b_50_results.json")
    answer_qwen15_payload = _load_json(root / "benchmarks" / "longmemeval_answer_qwen25_1_5b_50_results.json")
    answer_results = {
        **_answer_result_summaries(answer_payload, "extractive smoke"),
        **_answer_result_summaries(answer_qwen05_payload, "qwen2.5:0.5b smoke"),
        **_answer_result_summaries(answer_qwen15_payload, "qwen2.5:1.5b smoke"),
    }

    return [
        {
            "id": "agent_memory_static_chroma",
            "name": "Agent user-memory retrieval",
            "category": "agent-memory",
            "status": "implemented",
            "source": "benchmarks/agent_memory_benchmark.py",
            "dataset": "200 synthetic user facts, 50 natural-language Russian queries",
            "competitors": ["Chroma"],
            "metrics": ["precision@1", "precision@3", "avg_latency_ms"],
            "current": {
                "WaveMind": _metric_summary(
                    agent_results.get("WaveMind"),
                    ("precision_at_1", "precision_at_3", "avg_latency_ms", "p95_latency_ms"),
                ),
                "Chroma": _metric_summary(
                    agent_results.get("Chroma"),
                    ("precision_at_1", "precision_at_3", "avg_latency_ms", "p95_latency_ms"),
                ),
            },
            "target": "Match Chroma precision@1 on static recall, beat it on precision@3, and keep avg latency below 5 ms at 200 memories.",
            "next_step": "Run the same benchmark with sentence-transformers and a FAISS-backed candidate index.",
        },
        {
            "id": "dynamic_memory_policy",
            "name": "Dynamic memory policy",
            "category": "agent-memory",
            "status": "implemented",
            "source": "benchmarks/dynamic_memory_benchmark.py",
            "dataset": "Hot memory, TTL, correction, and namespace checks over 200 memories",
            "competitors": ["Chroma static"],
            "metrics": ["precision@1", "precision@3", "suppression_rate", "avg_latency_ms"],
            "current": {
                "WaveMind": _metric_summary(
                    dynamic_results.get("WaveMind"),
                    ("precision_at_1", "precision_at_3", "suppression_rate", "avg_latency_ms", "p95_latency_ms"),
                ),
                "Chroma static": _metric_summary(
                    dynamic_results.get("Chroma static"),
                    ("precision_at_1", "precision_at_3", "suppression_rate", "avg_latency_ms", "p95_latency_ms"),
                ),
            },
            "target": "Keep precision@1 and stale suppression at 1.00 while reducing avg latency below 10 ms at 1000 memories.",
            "next_step": "Add Chroma metadata-policy and Qdrant payload-filter baselines so the comparison is not only static-vector search.",
        },
        {
            "id": "field_memory_dynamics",
            "name": "Field memory graph dynamics",
            "category": "agent-memory",
            "status": "implemented",
            "source": "benchmarks/field_memory_dynamics_benchmark.py",
            "dataset": "13 deterministic memories: conflicting facts, related concept memories, activation spreading, inhibition, and decay",
            "competitors": ["WaveMind static"],
            "metrics": [
                "precision@1",
                "precision@3",
                "stale_suppression",
                "concept_formation",
                "concept_consolidation",
                "decay_ratio",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind graph": _metric_summary(
                    (field_payload or {}).get("wave_graph"),
                    (
                        "precision@1",
                        "precision@3",
                        "stale_suppression",
                        "concept_formation",
                        "concept_consolidation",
                        "decay_ratio",
                        "avg_latency_ms",
                    ),
                ),
                "WaveMind static": _metric_summary(
                    (field_payload or {}).get("wave_static"),
                    (
                        "precision@1",
                        "precision@3",
                        "stale_suppression",
                        "concept_formation",
                        "concept_consolidation",
                        "decay_ratio",
                        "avg_latency_ms",
                    ),
                ),
            },
            "target": "Keep graph precision@1, stale suppression, concept formation, and concept consolidation at 1.00 while moving the same memory dynamics into LoCoMo/LongMemEval evidence tasks.",
            "next_step": "Make MemoryFieldGraph incremental and evaluate conflict/update behavior on public long-memory datasets.",
        },
        {
            "id": "wavemind_capacity",
            "name": "WaveMind capacity curve",
            "category": "capacity",
            "status": "implemented",
            "source": "benchmarks/wavemind_capacity_results.json",
            "dataset": "Static and dynamic agent-memory checks at 200, 1000, and 5000 memories",
            "competitors": [],
            "metrics": ["precision@1", "precision@3", "avg_latency_ms", "p95_latency_ms"],
            "current": {
                "static_agent_memory": (capacity_payload or {}).get("static_agent_memory"),
                "dynamic_agent_memory": (capacity_payload or {}).get("dynamic_agent_memory"),
            },
            "target": "Hold precision@1 >= 0.95 at 5000 memories and avg dynamic query latency below 20 ms.",
            "next_step": "Move candidate generation to FAISS/Annoy and limit wave-field reranking to the top candidate set.",
        },
        {
            "id": "long_memory_evidence_synthetic",
            "name": "Long-term memory evidence",
            "category": "long-term-agent-memory",
            "status": "implemented",
            "source": "benchmarks/long_memory_evidence_benchmark.py",
            "dataset": "Synthetic long-memory evidence scenario with profile, preference, correction, TTL, namespace, and filler history",
            "competitors": ["Static vector", "Chroma static", "Qdrant static"],
            "metrics": [
                "evidence_recall@k",
                "precision@1",
                "stale_suppression",
                "context_budget_saved",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind": _metric_summary(
                    long_memory_results.get("WaveMind"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "stale_suppression",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Static vector": _metric_summary(
                    long_memory_results.get("Static vector"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "stale_suppression",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Keep this as a small regression check for stale suppression, correction, namespace isolation, and personalization.",
            "next_step": "Use public LoCoMo and LongMemEval for external claims; keep this synthetic scenario for fast regression testing.",
        },
        {
            "id": "beir_style_open_retrieval",
            "name": "BEIR-style open retrieval runner",
            "category": "retrieval",
            "status": "implemented",
            "source": "benchmarks/open_retrieval_benchmark.py",
            "dataset": "Any local BEIR-style corpus.jsonl, queries.jsonl, and qrels/<split>.tsv dataset.",
            "competitors": ["Chroma", "Qdrant"],
            "metrics": ["nDCG@k", "Recall@k", "MRR@k", "precision@1", "avg_latency_ms", "p95_latency_ms"],
            "current": {
                "WaveMind": _metric_summary(
                    open_retrieval_results.get("WaveMind"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma": _metric_summary(
                    open_retrieval_results.get("Chroma"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant": _metric_summary(
                    open_retrieval_results.get("Qdrant"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Run WaveMind, Chroma, and Qdrant with identical embeddings and compare retrieval/index behavior on public qrels.",
            "next_step": "Add sentence-transformers runs for SciFact, then add NFCorpus as the second BEIR dataset.",
        },
        {
            "id": "nomiracl_russian_retrieval",
            "name": "NoMIRACL Russian retrieval",
            "category": "multilingual-retrieval",
            "status": "implemented",
            "source": "benchmarks/nomiracl_russian_benchmark.py",
            "source_url": "https://huggingface.co/datasets/miracl/nomiracl",
            "dataset": "NoMIRACL Russian test relevant subset, 200 queries, 5000 compact top-k candidate passages, human-annotated relevance labels.",
            "competitors": ["Chroma", "Qdrant"],
            "metrics": ["nDCG@10", "Recall@10", "MRR@10", "precision@1", "avg_latency_ms", "p95_latency_ms"],
            "current": {
                "WaveMind": _metric_summary(
                    nomiracl_results.get("WaveMind"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma": _metric_summary(
                    nomiracl_results.get("Chroma"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant": _metric_summary(
                    nomiracl_results.get("Qdrant"),
                    (
                        "ndcg_at_k",
                        "recall_at_k",
                        "mrr_at_k",
                        "precision_at_1",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Reach same-embedding Russian nDCG@10 parity with Chroma/Qdrant while moving latency below 5 ms through FAISS/service-mode candidate indexes.",
            "next_step": "Run sentence-transformers on the same NoMIRACL Russian split and then add the full MIRACL Russian corpus profile when disk/service capacity allows it.",
        },
        {
            "id": "locomo_evidence_retrieval",
            "name": "LoCoMo evidence retrieval runner",
            "category": "long-term-conversation-memory",
            "status": "implemented" if locomo_payload else "runner-ready",
            "source": "benchmarks/locomo_memory_benchmark.py",
            "source_url": "https://github.com/snap-research/locomo",
            "dataset": "Official LoCoMo locomo10.json, using conversation turns as memories and QA evidence dialog ids as relevance labels.",
            "competitors": ["Static vector", "Chroma static", "Qdrant static"],
            "metrics": [
                "evidence_recall@k",
                "precision@1",
                "MRR@k",
                "context_budget_saved",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind": _metric_summary(
                    locomo_results.get("WaveMind"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Static vector": _metric_summary(
                    locomo_results.get("Static vector"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma static": _metric_summary(
                    locomo_results.get("Chroma static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant static": _metric_summary(
                    locomo_results.get("Qdrant static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "WaveMind sentence": _metric_summary(
                    locomo_sentence_results.get("WaveMind"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma sentence": _metric_summary(
                    locomo_sentence_results.get("Chroma static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant sentence": _metric_summary(
                    locomo_sentence_results.get("Qdrant static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Improve LoCoMo evidence_recall@5 with semantic embeddings and keep retrieval latency below 20 ms for WaveMind.",
            "next_step": "Add LoCoMo answer generation with a local LLM and measure answer accuracy/faithfulness.",
        },
        {
            "id": "longmemeval_evidence_retrieval",
            "name": "LongMemEval evidence retrieval",
            "category": "long-term-agent-memory",
            "status": "implemented",
            "source": "benchmarks/longmemeval_memory_benchmark.py",
            "source_url": "https://github.com/xiaowu0162/LongMemEval",
            "dataset": "Official LongMemEval-S cleaned file, 470 non-abstention questions, 22419 session memories, session-level evidence retrieval.",
            "competitors": ["Static vector", "Chroma static", "Qdrant static"],
            "metrics": [
                "evidence_recall@k",
                "precision@1",
                "MRR@k",
                "context_budget_saved",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind": _metric_summary(
                    longmemeval_results.get("WaveMind"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma static": _metric_summary(
                    longmemeval_results.get("Chroma static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Static vector": _metric_summary(
                    longmemeval_results.get("Static vector"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant static": _metric_summary(
                    longmemeval_results.get("Qdrant static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Keep full LongMemEval-S evidence recall above static vector-store baselines while staying below 20 ms retrieval latency.",
            "next_step": "Run turn-level evidence mode and sentence-transformers, then add LLM answer accuracy/abstention evaluation.",
        },
        {
            "id": "longmemeval_evidence_50_smoke",
            "name": "LongMemEval evidence 50-query smoke",
            "category": "long-term-agent-memory",
            "status": "implemented",
            "source": "benchmarks/longmemeval_evidence_50_results.json",
            "source_url": "https://github.com/xiaowu0162/LongMemEval",
            "dataset": "Official LongMemEval-S cleaned file, first 50 non-abstention questions, session-level evidence retrieval.",
            "competitors": ["Static vector", "Chroma static", "Qdrant static"],
            "metrics": [
                "evidence_recall@k",
                "precision@1",
                "MRR@k",
                "context_budget_saved",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind": _metric_summary(
                    longmemeval_50_results.get("WaveMind"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma static": _metric_summary(
                    longmemeval_50_results.get("Chroma static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Static vector": _metric_summary(
                    longmemeval_50_results.get("Static vector"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Qdrant static": _metric_summary(
                    longmemeval_50_results.get("Qdrant static"),
                    (
                        "evidence_recall_at_k",
                        "precision_at_1",
                        "mrr_at_k",
                        "context_budget_saved",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": "Keep this smoke profile above Chroma/Qdrant evidence recall while using it as the fast regression check before full LongMemEval reruns.",
            "next_step": "Speed up full LongMemEval reruns by reusing per-question candidate indexes or adding a streaming runner mode.",
        },
        {
            "id": "ann_index_curve",
            "name": "ANN index latency curve",
            "category": "index-latency",
            "status": "implemented",
            "source": "benchmarks/ann_index_curve_benchmark.py",
            "source_url": "https://github.com/erikbern/ann-benchmarks",
            "dataset": "Generated normalized 128-d vectors at 1000, 5000, 10000, and 50000 points; recall@10 measured against exact cosine neighbors.",
            "competitors": ["Quantized int8", "Annoy", "Qdrant local"],
            "metrics": ["recall@10", "avg_latency_ms", "p95_latency_ms", "build_ms"],
            "current": ann_results,
            "target": "At 50000 vectors, keep recall@10 above 0.95 while reducing latency below exact NumPy or move this role to a production vector index.",
            "next_step": "Tune quantized search kernels, add FAISS on Linux/macOS CI, and test Qdrant service-mode curves beyond 50000 vectors.",
        },
        {
            "id": "production_index_profile",
            "name": "Production index profile",
            "category": "index-latency",
            "status": "implemented",
            "source": "benchmarks/production_index_profile_results.json",
            "dataset": "Docker-backed 50000-vector profile comparing persisted FAISS, Qdrant service, and PostgreSQL/pgvector HNSW.",
            "competitors": ["Qdrant service", "pgvector HNSW"],
            "metrics": ["recall@10", "avg_latency_ms", "p95_latency_ms", "build_ms"],
            "current": production_index_results,
            "target": "Keep persisted FAISS and service-mode vector backends at recall@10 >= 0.95 while staying below 10 ms average query latency at 50000 vectors.",
            "next_step": "Add 100000 and 1000000-vector profiles, plus persistence/rebuild validation after process restart.",
        },
        {
            "id": "longmemeval_answer_generation",
            "name": "LongMemEval answer generation",
            "category": "long-term-agent-memory",
            "status": "implemented",
            "source": "benchmarks/longmemeval_answer_benchmark.py",
            "source_url": "https://github.com/xiaowu0162/LongMemEval",
            "dataset": "LongMemEval-S questions answered from compact retrieved evidence. Checked-in local runs compare WaveMind, Chroma, and Qdrant using Ollama qwen2.5:0.5b and qwen2.5:1.5b over the first 50 non-abstention questions.",
            "competitors": ["Ollama local LLM", "Chroma RAG", "Qdrant RAG"],
            "metrics": ["exact_match", "contains_answer", "token_f1", "evidence_recall@k"],
            "current": answer_results,
            "target": "Move from lightweight local smoke runs to full LongMemEval-S answer generation with stronger local and API models, then compare against Chroma/Qdrant RAG.",
            "next_step": "Run all 470 non-abstention questions with a stronger local/API model and add faithfulness/abstention scoring.",
        },
    ]


PUBLIC_BENCHMARKS: list[dict[str, Any]] = [
    {
        "id": "beir",
        "name": "BEIR",
        "category": "retrieval",
        "status": "planned",
        "source_url": "https://github.com/beir-cellar/beir",
        "dataset": "Heterogeneous zero-shot information retrieval benchmark across many public datasets.",
        "competitors": ["Chroma", "Qdrant", "FAISS"],
        "metrics": ["nDCG@10", "Recall@100", "avg_latency_ms"],
        "target": "On identical embeddings, stay within 0.02 nDCG@10 of Chroma/Qdrant and keep WaveMind reranking latency below 10 ms.",
        "next_step": "Implement a BEIR adapter for SciFact and NFCorpus first because they are small enough for local CI smoke runs.",
    },
    {
        "id": "mteb_retrieval",
        "name": "MTEB Retrieval",
        "category": "retrieval",
        "status": "planned",
        "source_url": "https://github.com/embeddings-benchmark/mteb",
        "dataset": "Massive Text Embedding Benchmark retrieval tasks across many datasets and languages.",
        "competitors": ["Chroma", "Qdrant", "FAISS"],
        "metrics": ["nDCG@10", "MAP", "Recall@10"],
        "target": "Use MTEB to separate encoder quality from memory-policy quality; WaveMind should not reduce same-embedding retrieval quality.",
        "next_step": "Run a small retrieval subset with hash, sentence-transformers, and a modern multilingual embedding model.",
    },
    {
        "id": "miracl_ru",
        "name": "MIRACL Russian",
        "category": "multilingual-retrieval",
        "status": "runner-ready",
        "source_url": "https://miracl.ai/",
        "dataset": "Native-speaker judged multilingual retrieval benchmark with Russian included. NoMIRACL Russian compact candidate benchmark is implemented; full-corpus MIRACL remains planned.",
        "competitors": ["Chroma", "Qdrant", "FAISS"],
        "metrics": ["nDCG@10", "Recall@100", "avg_latency_ms"],
        "target": "Prove Russian recall with semantic embeddings; target nDCG@10 parity with same-embedding Chroma/Qdrant.",
        "next_step": "Extend the NoMIRACL loader to full MIRACL Russian corpus once disk/service capacity is available.",
    },
    {
        "id": "vectordbbench",
        "name": "VectorDBBench",
        "category": "vector-db",
        "status": "planned",
        "source_url": "https://github.com/zilliztech/VectorDBBench",
        "dataset": "Vector database benchmark scenarios for insertion, search, filtered search, and cost/performance comparisons.",
        "competitors": ["Chroma", "Qdrant", "Milvus", "Weaviate", "Pinecone", "FAISS"],
        "metrics": ["qps", "serial_latency_ms", "recall@k", "load_time", "cost_performance"],
        "target": "Use this only after WaveMind has a production index path; current NumPy mode is not a fair vector database competitor.",
        "next_step": "Add a WaveMind adapter or a methodology note that compares WaveMind as a memory layer above a vector database, not as a standalone cloud vector DB.",
    },
    {
        "id": "locomo_answer_generation",
        "name": "LoCoMo answer generation",
        "category": "long-term-conversation-memory",
        "status": "planned",
        "source_url": "https://arxiv.org/abs/2402.17753",
        "dataset": "LoCoMo questions answered from retrieved evidence with an LLM.",
        "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"],
        "metrics": ["answer_accuracy", "faithfulness", "avg_end_to_end_latency_ms"],
        "target": "Beat static vector-store RAG on temporal/correction questions by at least 15 percentage points while returning compact evidence.",
        "next_step": "After the retrieval-only LoCoMo run is published, add an optional Ollama answer-generation layer using the user's installed local model.",
    },
    {
        "id": "longmemeval_v2",
        "name": "LongMemEval-V2",
        "category": "web-agent-memory",
        "status": "planned",
        "source_url": "https://arxiv.org/abs/2605.12493",
        "dataset": "Web-agent histories with state recall, dynamic state tracking, workflow knowledge, gotchas, and premise awareness.",
        "competitors": ["AgentRunbook-R", "Chroma RAG", "Qdrant RAG"],
        "metrics": ["evidence_recall@k", "answer_accuracy", "latency"],
        "target": "Become a compact evidence retriever for agent trajectories, with explicit wins on dynamic state tracking and gotcha recall.",
        "next_step": "Prototype trajectory-to-memory segmentation and compare compact WaveMind evidence against plain chunk retrieval.",
    },
    {
        "id": "lmeb",
        "name": "LMEB",
        "category": "memory-embedding",
        "status": "planned",
        "source_url": "https://github.com/KaLM-Embedding/LMEB",
        "dataset": "Long-horizon Memory Embedding Benchmark across episodic, dialogue, semantic, and procedural memory tasks.",
        "competitors": ["embedding-only baselines", "Chroma", "Qdrant"],
        "metrics": ["nDCG@10", "Recall@10", "MRR"],
        "target": "Use LMEB to choose the default semantic encoder and prove that memory retrieval is not just passage retrieval.",
        "next_step": "Run LMEB retrieval tasks once optional dataset downloads are available outside restricted CI.",
    },
    {
        "id": "ragbench",
        "name": "RAGBench",
        "category": "rag-quality",
        "status": "planned",
        "source_url": "https://huggingface.co/datasets/rungalileo/ragbench",
        "dataset": "Large RAG evaluation dataset with industry-style corpora and explainable labels.",
        "competitors": ["Chroma RAG", "Qdrant RAG", "Pinecone RAG"],
        "metrics": ["context_relevance", "answer_faithfulness", "answer_relevance"],
        "target": "Show whether WaveMind's dynamic suppression improves context quality when facts become stale or conflicting.",
        "next_step": "Add an optional RAGBench adapter after retrieval benchmarks are stable.",
    },
]


def build_benchmark_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    return {
        "schema": "wavemind.benchmark_matrix.v1",
        "note": (
            "Implemented entries are runnable from this repository. Planned entries are "
            "public benchmarks that require optional datasets, services, or heavier dependencies."
        ),
        "benchmarks": _implemented_entries(root) + PUBLIC_BENCHMARKS,
    }


def print_table(payload: dict[str, Any]) -> None:
    print("| benchmark | category | status | competitors | target |")
    print("|---|---|---|---|---|")
    for entry in payload["benchmarks"]:
        competitors = ", ".join(entry.get("competitors", [])) or "none"
        print(
            f"| {entry['name']} | {entry['category']} | {entry['status']} | "
            f"{competitors} | {entry['target']} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/benchmark_matrix_results.json"),
    )
    args = parser.parse_args()

    payload = build_benchmark_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
