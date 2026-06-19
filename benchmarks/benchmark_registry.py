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
    return {str(result["engine"]): result for result in payload.get("results", []) if "engine" in result}


def _metric_summary(result: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not result:
        return None
    return {key: result[key] for key in keys if key in result}


def _implemented_entries(root: Path) -> list[dict[str, Any]]:
    agent = _engine_results(_load_json(root / "benchmarks" / "agent_memory_results.json"))
    dynamic = _engine_results(_load_json(root / "benchmarks" / "dynamic_memory_results.json"))
    long_memory = _engine_results(_load_json(root / "benchmarks" / "long_memory_evidence_results.json"))
    capacity = _load_json(root / "benchmarks" / "wavemind_capacity_results.json") or {}
    return [
        {"id": "agent_memory_static_chroma", "name": "Agent user-memory retrieval", "category": "agent-memory", "status": "implemented", "source": "benchmarks/agent_memory_benchmark.py", "dataset": "200 synthetic user facts, 50 natural-language Russian queries", "competitors": ["Chroma"], "metrics": ["precision@1", "precision@3", "avg_latency_ms"], "current": {"WaveMind": _metric_summary(agent.get("WaveMind"), ("precision_at_1", "precision_at_3", "avg_latency_ms", "p95_latency_ms")), "Chroma": _metric_summary(agent.get("Chroma"), ("precision_at_1", "precision_at_3", "avg_latency_ms", "p95_latency_ms"))}, "target": "Match Chroma precision@1 on static recall, beat it on precision@3, and keep avg latency below 5 ms at 200 memories.", "next_step": "Run the same benchmark with sentence-transformers and a FAISS-backed candidate index."},
        {"id": "dynamic_memory_policy", "name": "Dynamic memory policy", "category": "agent-memory", "status": "implemented", "source": "benchmarks/dynamic_memory_benchmark.py", "dataset": "Hot memory, TTL, correction, and namespace checks over 200 memories", "competitors": ["Chroma static"], "metrics": ["precision@1", "precision@3", "suppression_rate", "avg_latency_ms"], "current": {"WaveMind": _metric_summary(dynamic.get("WaveMind"), ("precision_at_1", "precision_at_3", "suppression_rate", "avg_latency_ms", "p95_latency_ms")), "Chroma static": _metric_summary(dynamic.get("Chroma static"), ("precision_at_1", "precision_at_3", "suppression_rate", "avg_latency_ms", "p95_latency_ms"))}, "target": "Keep precision@1 and stale suppression at 1.00 while reducing avg latency below 10 ms at 1000 memories.", "next_step": "Add Chroma metadata-policy and Qdrant payload-filter baselines."},
        {"id": "wavemind_capacity", "name": "WaveMind capacity curve", "category": "capacity", "status": "implemented", "source": "benchmarks/wavemind_capacity_results.json", "dataset": "Static and dynamic agent-memory checks at 200, 1000, and 5000 memories", "competitors": [], "metrics": ["precision@1", "precision@3", "avg_latency_ms", "p95_latency_ms"], "current": {"static_agent_memory": capacity.get("static_agent_memory"), "dynamic_agent_memory": capacity.get("dynamic_agent_memory")}, "target": "Hold precision@1 >= 0.95 at 5000 memories and avg dynamic query latency below 20 ms.", "next_step": "Move candidate generation to FAISS/Annoy and limit wave-field reranking."},
        {"id": "long_memory_evidence_synthetic", "name": "Long-term memory evidence", "category": "long-term-agent-memory", "status": "implemented", "source": "benchmarks/long_memory_evidence_benchmark.py", "dataset": "Synthetic long-memory evidence scenario with profile, preference, correction, TTL, namespace, and filler history", "competitors": ["Static vector", "Chroma static", "Qdrant static"], "metrics": ["evidence_recall@k", "precision@1", "stale_suppression", "context_budget_saved", "avg_latency_ms"], "current": {"WaveMind": _metric_summary(long_memory.get("WaveMind"), ("evidence_recall_at_k", "precision_at_1", "stale_suppression", "context_budget_saved", "avg_latency_ms", "p95_latency_ms")), "Static vector": _metric_summary(long_memory.get("Static vector"), ("evidence_recall_at_k", "precision_at_1", "stale_suppression", "context_budget_saved", "avg_latency_ms", "p95_latency_ms"))}, "target": "Show dynamic-memory gains on stale suppression, correction, namespace isolation, and personalization before adding public LoCoMo/LongMemEval adapters.", "next_step": "Run the same normalized evidence benchmark with Chroma and Qdrant installed, then add LoCoMo or LongMemEval adapters."},
        {"id": "beir_style_open_retrieval", "name": "BEIR-style open retrieval runner", "category": "retrieval", "status": "implemented", "source": "benchmarks/open_retrieval_benchmark.py", "dataset": "Any local BEIR-style corpus.jsonl, queries.jsonl, and qrels/<split>.tsv dataset.", "competitors": ["Chroma", "Qdrant"], "metrics": ["nDCG@k", "Recall@k", "MRR@k", "precision@1", "avg_latency_ms", "p95_latency_ms"], "current": None, "target": "Run WaveMind, Chroma, and Qdrant with identical embeddings and compare retrieval/index behavior on public qrels.", "next_step": "Download SciFact or NFCorpus into benchmarks/data and publish the first full public-dataset result JSON."},
    ]


PUBLIC_BENCHMARKS: list[dict[str, Any]] = [
    {"id": "beir", "name": "BEIR", "category": "retrieval", "status": "planned", "source_url": "https://github.com/beir-cellar/beir", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "mteb_retrieval", "name": "MTEB Retrieval", "category": "retrieval", "status": "planned", "source_url": "https://github.com/embeddings-benchmark/mteb", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "miracl_ru", "name": "MIRACL Russian", "category": "multilingual-retrieval", "status": "planned", "source_url": "https://miracl.ai/", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "ann_benchmarks", "name": "ANN-Benchmarks style index curve", "category": "index-latency", "status": "planned", "source_url": "https://github.com/erikbern/ann-benchmarks", "competitors": ["FAISS", "Annoy", "Qdrant HNSW"]},
    {"id": "locomo", "name": "LoCoMo", "category": "long-term-conversation-memory", "status": "planned", "source_url": "https://arxiv.org/abs/2402.17753", "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"]},
    {"id": "longmemeval", "name": "LongMemEval", "category": "long-term-agent-memory", "status": "planned", "source_url": "https://arxiv.org/abs/2410.10813", "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"]},
    {"id": "longmemeval_v2", "name": "LongMemEval-V2", "category": "web-agent-memory", "status": "planned", "source_url": "https://arxiv.org/abs/2605.12493", "competitors": ["AgentRunbook-R", "Chroma RAG", "Qdrant RAG"]},
    {"id": "lmeb", "name": "LMEB", "category": "memory-embedding", "status": "planned", "source_url": "https://github.com/KaLM-Embedding/LMEB", "competitors": ["embedding-only baselines", "Chroma", "Qdrant"]},
    {"id": "ragbench", "name": "RAGBench", "category": "rag-quality", "status": "planned", "source_url": "https://huggingface.co/datasets/rungalileo/ragbench", "competitors": ["Chroma RAG", "Qdrant RAG", "Pinecone RAG"]},
]


def build_benchmark_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    return {"schema": "wavemind.benchmark_matrix.v1", "note": "Implemented entries are runnable from this repository. Planned entries are public benchmarks that require optional datasets, services, or heavier dependencies.", "benchmarks": _implemented_entries(root) + PUBLIC_BENCHMARKS}


def print_table(payload: dict[str, Any]) -> None:
    print("| benchmark | category | status | competitors | target |")
    print("|---|---|---|---|---|")
    for entry in payload["benchmarks"]:
        print(f"| {entry['name']} | {entry.get('category', '')} | {entry['status']} | {', '.join(entry.get('competitors', [])) or 'none'} | {entry.get('target', '')} |")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "benchmarks" / "benchmark_matrix_results.json")
    args = parser.parse_args()
    payload = build_benchmark_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
