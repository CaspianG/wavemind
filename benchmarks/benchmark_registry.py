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


def _implemented_entries(root: Path) -> list[dict[str, Any]]:
    agent_payload = _load_json(root / "benchmarks" / "agent_memory_results.json")
    dynamic_payload = _load_json(root / "benchmarks" / "dynamic_memory_results.json")
    field_payload = _load_json(root / "benchmarks" / "field_memory_dynamics_results.json")
    capacity_payload = _load_json(root / "benchmarks" / "wavemind_capacity_results.json")
    long_memory_payload = _load_json(root / "benchmarks" / "long_memory_evidence_results.json")
    open_retrieval_payload = _load_json(root / "benchmarks" / "open_retrieval_scifact_results.json")
    locomo_payload = _load_json(root / "benchmarks" / "locomo_evidence_results.json")

    agent_results = _engine_results(agent_payload)
    dynamic_results = _engine_results(dynamic_payload)
    long_memory_results = _engine_results(long_memory_payload)
    open_retrieval_results = _engine_results(open_retrieval_payload)
    locomo_results = _engine_results(locomo_payload)

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
                        "decay_ratio",
                        "avg_latency_ms",
                    ),
                ),
            },
            "target": "Keep graph precision@1, stale suppression, and concept formation at 1.00 while moving the same memory dynamics into LoCoMo/LongMemEval evidence tasks.",
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
            "target": "Show dynamic-memory gains on stale suppression, correction, namespace isolation, and personalization before adding public LoCoMo/LongMemEval adapters.",
            "next_step": "Run the same normalized evidence benchmark with Chroma and Qdrant installed, then add LoCoMo or LongMemEval adapters.",
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
            "next_step": "Add Qdrant and sentence-transformers runs for SciFact, then add NFCorpus as the second BEIR dataset.",
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
            },
            "target": "Improve LoCoMo evidence_recall@5 beyond the current hash-encoder run with semantic embeddings and field-aware evidence compression.",
            "next_step": "Run LoCoMo with sentence-transformers and add Qdrant static; then add answer generation with a local LLM.",
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
        "status": "planned",
        "source_url": "https://miracl.ai/",
        "dataset": "Native-speaker judged multilingual retrieval benchmark with Russian included.",
        "competitors": ["Chroma", "Qdrant", "FAISS"],
        "metrics": ["nDCG@10", "Recall@100", "avg_latency_ms"],
        "target": "Prove Russian recall with semantic embeddings; target nDCG@10 parity with same-embedding Chroma/Qdrant.",
        "next_step": "Add MIRACL ru/dev loader behind an optional benchmark extra because the dataset is too large for the base package.",
    },
    {
        "id": "ann_benchmarks",
        "name": "ANN-Benchmarks style index curve",
        "category": "index-latency",
        "status": "planned",
        "source_url": "https://github.com/erikbern/ann-benchmarks",
        "dataset": "Approximate nearest-neighbor recall/latency methodology for vector indexes.",
        "competitors": ["FAISS", "Annoy", "Qdrant HNSW"],
        "metrics": ["recall@10", "queries_per_second", "p95_latency_ms"],
        "target": "At 5000 to 100000 memories, preserve recall@10 >= 0.95 while cutting query latency below the NumPy exact path.",
        "next_step": "Add a generated-vector benchmark that compares NumPy exact, Annoy, and FAISS when optional dependencies are installed.",
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
        "id": "longmemeval",
        "name": "LongMemEval",
        "category": "long-term-agent-memory",
        "status": "planned",
        "source_url": "https://arxiv.org/abs/2410.10813",
        "dataset": "Long-term chat-assistant memory with information extraction, multi-session reasoning, temporal reasoning, updates, and abstention.",
        "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"],
        "metrics": ["hit@5", "mrr", "answer_accuracy", "abstention_accuracy"],
        "target": "Demonstrate update/abstention gains over static vector recall without exceeding 100 ms retrieval latency.",
        "next_step": "Store session facts, corrections, and timestamps as first-class metadata and evaluate retrieval evidence before LLM answering.",
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
