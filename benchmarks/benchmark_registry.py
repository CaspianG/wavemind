from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


BENCHMARKS = [
    {
        "id": "agent_memory_static_chroma",
        "name": "Agent user-memory retrieval",
        "status": "implemented",
        "competitors": ["Chroma"],
        "metrics": ["precision@1", "precision@3", "avg_latency_ms"],
        "current": {
            "WaveMind": {"precision_at_1": 0.82, "precision_at_3": 0.90, "avg_latency_ms": 2.25},
            "Chroma": {"precision_at_1": 0.82, "precision_at_3": 0.88, "avg_latency_ms": 0.93},
        },
    },
    {
        "id": "dynamic_memory_policy",
        "name": "Dynamic memory policy",
        "status": "implemented",
        "competitors": ["Chroma static"],
        "metrics": ["precision@1", "precision@3", "stale_suppression", "avg_latency_ms"],
        "current": {
            "WaveMind": {"precision_at_1": 1.00, "precision_at_3": 1.00, "suppression_rate": 1.00, "avg_latency_ms": 25.26},
            "Chroma static": {"precision_at_1": 0.57, "precision_at_3": 1.00, "suppression_rate": 0.00, "avg_latency_ms": 1.75},
        },
    },
    {
        "id": "wavemind_capacity",
        "name": "WaveMind capacity curve",
        "status": "implemented",
        "competitors": [],
        "metrics": ["precision@1", "precision@3", "avg_latency_ms", "p95_latency_ms"],
        "source": "benchmarks/wavemind_capacity_results.json",
    },
    {
        "id": "beir_style_open_retrieval",
        "name": "BEIR-style open retrieval runner",
        "status": "implemented",
        "competitors": ["Chroma", "Qdrant"],
        "metrics": ["nDCG@k", "Recall@k", "MRR@k", "precision@1", "avg_latency_ms", "p95_latency_ms"],
        "current": None,
        "next_step": "Download SciFact or NFCorpus and publish the first full public-dataset result JSON.",
    },
    {"id": "beir", "name": "BEIR", "status": "planned", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "mteb_retrieval", "name": "MTEB Retrieval", "status": "planned", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "miracl_ru", "name": "MIRACL Russian", "status": "planned", "competitors": ["Chroma", "Qdrant", "FAISS"]},
    {"id": "ann_benchmarks", "name": "ANN-Benchmarks style index curve", "status": "planned", "competitors": ["FAISS", "Annoy", "Qdrant HNSW"]},
    {"id": "locomo", "name": "LoCoMo", "status": "planned", "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"]},
    {"id": "longmemeval", "name": "LongMemEval", "status": "planned", "competitors": ["Chroma RAG", "Qdrant RAG", "Mem0-style memory"]},
    {"id": "longmemeval_v2", "name": "LongMemEval-V2", "status": "planned", "competitors": ["AgentRunbook-R", "Chroma RAG", "Qdrant RAG"]},
    {"id": "lmeb", "name": "LMEB", "status": "planned", "competitors": ["Chroma", "Qdrant"]},
    {"id": "ragbench", "name": "RAGBench", "status": "planned", "competitors": ["Chroma RAG", "Qdrant RAG", "Pinecone RAG"]},
]


def build_matrix() -> dict:
    return {
        "schema": "wavemind.benchmark_matrix.v1",
        "note": "Implemented entries are runnable from this repository. Planned entries are public benchmarks that require optional datasets, services, or heavier dependencies.",
        "benchmarks": BENCHMARKS,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "benchmarks" / "benchmark_matrix_results.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_matrix(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
