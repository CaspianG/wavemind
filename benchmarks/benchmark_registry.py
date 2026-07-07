from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
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
    summaries: dict[str, dict[str, Any]] = {}
    for result in latest.get("results", []):
        if "engine" not in result:
            continue
        engine = str(result["engine"])
        if result.get("skipped"):
            summaries[engine] = {
                "skipped": True,
                "reason": result.get("reason", "not configured"),
            }
            continue
        summaries[engine] = _metric_summary(
            result,
            (
                "recall_at_k",
                "target_recall_at_k",
                "target_recall_at_1",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "build_ms",
                "slo_status",
                "slo_required_replicas",
                "slo_autoscaled_qps",
                "cost_status",
                "compute_cost_per_1m_queries_usd",
                "monthly_total_cost_at_target_qps_usd",
                "estimated_storage_gb",
                "pgvector_variant",
            ),
        ) or {}
    return summaries


def _prefixed_ann_results(label: str, payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        f"{label} / {engine}": summary
        for engine, summary in _ann_latest_results(payload).items()
    }


def _streaming_plan_results(label: str, payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for plan in payload.get("plans", []):
        engine = str(plan.get("engine") or "unknown")
        rows[f"{label} / {engine}"] = _metric_summary(
            plan,
            (
                "status",
                "estimated_index_gb",
                "estimated_transient_runner_gb",
                "estimated_application_storage_gb",
                "required_local_free_gb",
                "disk_free_gb",
                "missing_env",
            ),
        ) or {}
    return rows


def _qdrant_ef_sweep_results(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    summaries: dict[str, dict[str, Any]] = {}
    for result in payload.get("results", []):
        ef = result.get("hnsw_ef")
        if ef is None:
            continue
        summaries[f"hnsw_ef={ef}"] = _metric_summary(
            result,
            (
                "recall_at_k",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "max_latency_ms",
                "slo_status",
                "slo_required_replicas",
                "slo_autoscaled_qps",
                "cost_status",
                "compute_cost_per_1m_queries_usd",
                "monthly_total_cost_at_target_qps_usd",
                "estimated_storage_gb",
            ),
        ) or {}
    return summaries


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
                "answered_rate",
                "abstention_rate",
                "grounded_answer_rate",
                "supported_answer_rate",
                "unsupported_answer_rate",
                "faithfulness_rate",
                "avg_retrieval_ms",
                "avg_generation_ms",
            ),
        )
    return summaries


def _implemented_entries(root: Path) -> list[dict[str, Any]]:
    agent_payload = _load_json(root / "benchmarks" / "agent_memory_results.json")
    agent_coherence_payload = _load_json(root / "benchmarks" / "agent_coherence_results.json")
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
    production_pgvector_tuning_payload = _load_json(root / "benchmarks" / "production_pgvector_tuning_results.json")
    production_load_payload = _load_json(root / "benchmarks" / "production_load_results.json")
    production_load_1m_payload = _load_json(root / "benchmarks" / "production_load_qdrant_1m_results.json")
    production_load_100k_tuned_payload = _load_json(root / "benchmarks" / "production_load_qdrant_100k_tuned_results.json")
    production_load_1m_tuned_payload = _load_json(root / "benchmarks" / "production_load_qdrant_1m_tuned_results.json")
    production_load_faiss_1m_payload = _load_json(root / "benchmarks" / "production_load_faiss_1m_results.json")
    production_load_1m_ef_sweep_payload = _load_json(root / "benchmarks" / "production_load_qdrant_1m_ef_sweep_results.json")
    production_streaming_payload = _load_json(root / "benchmarks" / "production_streaming_load_smoke_results.json")
    production_streaming_ivfpq_100k_payload = _load_json(root / "benchmarks" / "production_streaming_load_ivfpq_100k_results.json")
    production_streaming_ivfpq_1m_payload = _load_json(root / "benchmarks" / "production_streaming_load_ivfpq_1m_results.json")
    production_streaming_ivfpq_10m_payload = _load_json(root / "benchmarks" / "production_streaming_load_ivfpq_10m_results.json")
    production_streaming_50m_plan_payload = _load_json(root / "benchmarks" / "production_streaming_load_50m_plan.json")
    production_streaming_qdrant_smoke_payload = _load_json(root / "benchmarks" / "production_streaming_load_qdrant_smoke_results.json")
    production_streaming_qdrant_10m_plan_payload = _load_json(root / "benchmarks" / "production_streaming_load_qdrant_10m_plan.json")
    production_streaming_pgvector_smoke_payload = _load_json(root / "benchmarks" / "production_streaming_load_pgvector_smoke_results.json")
    production_streaming_pgvector_10m_plan_payload = _load_json(root / "benchmarks" / "production_streaming_load_pgvector_10m_plan.json")
    scale_readiness_payload = _load_json(root / "benchmarks" / "scale_readiness_results.json")
    local_http_cluster_payload = _load_json(root / "benchmarks" / "local_http_cluster_smoke_results.json")
    external_http_cluster_payload = _load_json(root / "benchmarks" / "http_cluster_load_results.json")
    production_readiness_payload = _load_json(root / "benchmarks" / "production_readiness_results.json")
    memory_competitor_payload = _load_json(root / "benchmarks" / "memory_competitor_results.json")
    answer_payload = _load_json(root / "benchmarks" / "longmemeval_answer_extractive_20_results.json")
    vectordbbench_payload = _load_json(root / "benchmarks" / "vectordbbench_dataset_manifest.json")

    agent_results = _engine_results(agent_payload)
    agent_coherence_results = _engine_results(agent_coherence_payload)
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
    production_pgvector_tuning_results = _ann_latest_results(production_pgvector_tuning_payload)
    production_load_results = _ann_latest_results(production_load_payload)
    production_load_1m_results = _ann_latest_results(production_load_1m_payload)
    production_load_100k_tuned_results = _ann_latest_results(production_load_100k_tuned_payload)
    production_load_1m_tuned_results = _ann_latest_results(production_load_1m_tuned_payload)
    production_load_faiss_1m_results = _ann_latest_results(production_load_faiss_1m_payload)
    production_load_1m_ef_sweep_results = _qdrant_ef_sweep_results(production_load_1m_ef_sweep_payload)
    production_streaming_results = {
        **_prefixed_ann_results("10k smoke", production_streaming_payload),
        **_prefixed_ann_results("100k compressed", production_streaming_ivfpq_100k_payload),
        **_prefixed_ann_results("1M compressed", production_streaming_ivfpq_1m_payload),
        **_prefixed_ann_results("10M compressed", production_streaming_ivfpq_10m_payload),
        **_streaming_plan_results("50M preflight", production_streaming_50m_plan_payload),
        **_prefixed_ann_results("Qdrant smoke", production_streaming_qdrant_smoke_payload),
        **_streaming_plan_results("10M Qdrant preflight", production_streaming_qdrant_10m_plan_payload),
        **_prefixed_ann_results("pgvector smoke", production_streaming_pgvector_smoke_payload),
        **_streaming_plan_results("10M pgvector preflight", production_streaming_pgvector_10m_plan_payload),
    }
    scale_readiness_results = _engine_results(scale_readiness_payload)
    local_http_cluster_results = _engine_results(local_http_cluster_payload)
    external_http_cluster_results = _engine_results(external_http_cluster_payload)
    production_readiness_summary = (
        production_readiness_payload.get("summary", {})
        if production_readiness_payload
        else {}
    )
    memory_competitor_results = _engine_results(memory_competitor_payload)
    vectordbbench_summary = (
        {
            "WaveMind custom dataset export": {
                "status": vectordbbench_payload.get("status"),
                "vectors": vectordbbench_payload.get("dataset", {}).get("vectors"),
                "queries": vectordbbench_payload.get("dataset", {}).get("queries"),
                "dim": vectordbbench_payload.get("dataset", {}).get("dim"),
                "top_k": vectordbbench_payload.get("dataset", {}).get("top_k"),
            }
        }
        if vectordbbench_payload
        else {}
    )
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
            "id": "agent_coherence_quality",
            "name": "Agent coherence and token savings",
            "category": "agent-memory",
            "status": "implemented",
            "source": "benchmarks/agent_coherence_benchmark.py",
            "dataset": "500-memory long user history with corrections, TTL, namespace isolation, project recall, and repeated personalization tasks",
            "competitors": ["Static vector", "Chroma static"],
            "metrics": [
                "task_success_rate",
                "decision_success_at_1",
                "stale_error_rate",
                "context_budget_saved",
                "coherent_turns",
                "avg_latency_ms",
            ],
            "current": {
                "WaveMind": _metric_summary(
                    agent_coherence_results.get("WaveMind"),
                    (
                        "task_success_rate",
                        "decision_success_at_1",
                        "stale_error_rate",
                        "namespace_leak_rate",
                        "context_budget_saved",
                        "coherent_turns",
                        "coherent_turn_rate",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Static vector": _metric_summary(
                    agent_coherence_results.get("Static vector"),
                    (
                        "task_success_rate",
                        "decision_success_at_1",
                        "stale_error_rate",
                        "namespace_leak_rate",
                        "context_budget_saved",
                        "coherent_turns",
                        "coherent_turn_rate",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
                "Chroma static": _metric_summary(
                    agent_coherence_results.get("Chroma static"),
                    (
                        "task_success_rate",
                        "decision_success_at_1",
                        "stale_error_rate",
                        "namespace_leak_rate",
                        "context_budget_saved",
                        "coherent_turns",
                        "coherent_turn_rate",
                        "avg_latency_ms",
                        "p95_latency_ms",
                    ),
                ),
            },
            "target": (
                "Show that dynamic memory improves agent behavior, not only retrieval: "
                "higher task success, fewer stale errors, longer coherent runs, and compact context."
            ),
            "next_step": "Move this scenario from deterministic task scoring to LLM answer-quality scoring on LoCoMo/LongMemEval-style tasks.",
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
            "next_step": "Use the dedicated production load profile for 100000 and 1000000-vector service tests, then tune pgvector and Qdrant for recall/latency.",
        },
        {
            "id": "production_pgvector_tuning_profile",
            "name": "Production pgvector tuning profile",
            "category": "index-latency",
            "status": "implemented",
            "source": "benchmarks/production_pgvector_tuning_results.json",
            "dataset": "Docker-backed PostgreSQL/pgvector tuning profile over 10000 and 50000 generated normalized 128-d vectors, with Qdrant service as the reference service baseline.",
            "competitors": ["Qdrant service", "pgvector HNSW", "pgvector exact", "pgvector iterative HNSW"],
            "metrics": ["recall@10", "avg_latency_ms", "p95_latency_ms", "p99_latency_ms", "build_ms"],
            "current": production_pgvector_tuning_results,
            "target": "Use pgvector exact as the recall floor and keep pgvector iterative above recall@10 0.95 with p99 below 100 ms at 50000 vectors.",
            "next_step": "Promote pgvector iterative from the 50000-vector tuning profile into the 100k/1M production load SLO profiles when disk and build time allow it.",
        },
        {
            "id": "production_load_profile_100k",
            "name": "Production load profile 100k",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/production_load_benchmark.py",
            "dataset": "100000 generated normalized 128-d vectors; recall@10 measured against exact cosine neighbors.",
            "competitors": ["Qdrant service", "pgvector HNSW", "FAISS persisted"],
            "metrics": [
                "recall@10",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "SLO status",
                "required replicas",
                "autoscaled QPS",
                "compute cost / 1M queries",
                "monthly target cost",
                "build_ms",
            ],
            "current": {**production_load_results, **production_load_100k_tuned_results},
            "target": "Reach recall@10 >= 0.95 and p99 latency < 100 ms on at least one production service backend at 100000 memories.",
            "next_step": "Keep at least one service backend at SLO pass while adding persisted FAISS from the Linux benchmark container and raising the target QPS.",
        },
        {
            "id": "production_load_profile_1m",
            "name": "Production load profile 1M",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/production_load_faiss_1m_results.json",
            "dataset": "1000000 generated normalized 128-d vectors; FAISS persisted and Qdrant service recall@10/latency profiles.",
            "competitors": ["FAISS persisted", "Qdrant service"],
            "metrics": [
                "recall@10",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "SLO status",
                "required replicas",
                "autoscaled QPS",
                "compute cost / 1M queries",
                "monthly target cost",
                "build_ms",
            ],
            "current": {
                **production_load_1m_results,
                **production_load_1m_tuned_results,
                **production_load_faiss_1m_results,
            },
            "target": "Keep recall@10 >= 0.95 and push p99 latency below 100 ms at 1M vectors.",
            "next_step": "Keep the FAISS persisted 1M profile green and tune Qdrant/pgvector so service-mode vector DB backends also pass recall and p99.",
        },
        {
            "id": "production_load_qdrant_1m_ef_sweep",
            "name": "Qdrant 1M HNSW ef sweep",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/production_load_qdrant_1m_ef_sweep_results.json",
            "dataset": "1000000 generated normalized 128-d vectors; one Qdrant service collection queried with multiple hnsw_ef settings.",
            "competitors": ["Qdrant service"],
            "metrics": [
                "recall@10",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "SLO status",
                "required replicas",
                "autoscaled QPS",
                "compute cost / 1M queries",
                "monthly target cost",
            ],
            "current": production_load_1m_ef_sweep_results,
            "target": "Find a setting that keeps recall@10 >= 0.95 while keeping p99 latency below 100 ms.",
            "next_step": "Repeat with 100+ queries and collection-level HNSW build parameters; the current best recall setting still misses the p99 SLO.",
        },
        {
            "id": "production_streaming_load_runner",
            "name": "Production streaming load runner",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/production_streaming_load_benchmark.py",
            "dataset": "Memory-bounded streaming generator for 10M and 50M target-recall load profiles. Checked-in artifacts include 10k smoke plus 100k, 1M, and 10M compressed FAISS IVF-PQ profiles, real Qdrant and PostgreSQL/pgvector service smokes, Qdrant and pgvector 10M service preflights, and a 50M FAISS IVF-PQ plan-only resource/command preflight.",
            "competitors": ["FAISS persisted streaming", "FAISS IVF-PQ persisted streaming", "Qdrant service streaming", "pgvector streaming"],
            "metrics": [
                "target_recall@10",
                "target_recall@1",
                "avg_latency_ms",
                "p95_latency_ms",
                "p99_latency_ms",
                "SLO status",
                "required replicas",
                "autoscaled QPS",
                "compute cost / 1M queries",
                "build_ms",
            ],
            "current": production_streaming_results,
            "target": "Keep 10M compressed FAISS IVF-PQ above recall@10 0.95 and p99 below 100 ms, keep Qdrant and pgvector streaming smokes green, keep 10M Qdrant/pgvector and 50M FAISS preflights reproducible, then run 10M Qdrant/pgvector and 50M compressed FAISS on hardware sized for the index.",
            "next_step": "Set service credentials and run the checked 10M Qdrant/pgvector reproduction commands, then run the 50M compressed FAISS command on hardware sized for the index.",
        },
        {
            "id": "scale_readiness",
            "name": "Scale readiness profile",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/scale_readiness_benchmark.py",
            "dataset": "Deterministic 1M-memory simulation for namespace placement, cluster autoscale planning, Kubernetes StatefulSet/CronJob/HPA generation, Knative/KEDA serverless plan generation, quorum runtime, service-mode replica repair, real HTTP shard transport, service-mode tombstone repair, anti-entropy repair worker, cursor-based active-active delta sync, field-only hotness delta sync, field-state CRDT convergence, replicated snapshot/offsite/archive restore, S3-compatible object-store upload verification, query-audit cache prewarm, query-vector cache, Redis-compatible shared rate limiting, Memory OS adaptive prewarm/consolidation/forgetting plus production architecture advice, hot-cache, API cache mutation safety, and structured-payload retrieval checks.",
            "competitors": ["Mem0", "Zep", "LangGraph persistent memory", "GraphRAG"],
            "metrics": [
                "node_loss_min_availability",
                "required_nodes",
                "additional_nodes",
                "kubernetes_repair_cronjob_kind",
                "has_hpa",
                "status_ready",
                "scale_to_zero",
                "hit_rate",
                "local_encode_calls",
                "local_hit_rate",
                "redis_shared_across_workers",
                "shared_rate_limiter_limited",
                "shared_cache_visible_across_clients",
                "memory_os_cross_worker_hit",
                "stale_prevented_after_remember",
                "stale_prevented_after_forget",
                "memory_os_ok",
                "architecture_advice_status",
                "memory_os_architecture_advice_status",
                "concepts_created",
                "concurrent_write_ok",
                "concurrent_query_hit_rate",
                "precision@1",
                "p99_latency_ms",
            ],
            "current": {
                "WaveMind cluster planner": _metric_summary(
                    scale_readiness_results.get("WaveMind cluster planner"),
                    (
                        "simulated_memories",
                        "namespaces",
                        "nodes",
                        "replication_factor",
                        "node_loss_min_availability",
                        "zone_loss_min_availability",
                        "read_quorum",
                        "write_quorum",
                        "kubernetes_manifest_kind",
                        "kubernetes_repair_cronjob_kind",
                        "kubernetes_repair_cronjob_namespaces",
                        "placement_ms",
                    ),
                ),
                "WaveMind cluster autoscaler": _metric_summary(
                    scale_readiness_results.get("WaveMind cluster autoscaler"),
                    (
                        "status",
                        "namespace_count",
                        "current_nodes",
                        "required_nodes",
                        "additional_nodes",
                        "replication_factor",
                        "target_memories",
                        "max_memories_per_node",
                        "headroom",
                        "current_max_node_memories",
                        "target_max_node_memories",
                        "target_within_headroom",
                        "move_sample",
                        "omitted_moves",
                        "has_scale_action",
                        "plan_ms",
                    ),
                ),
                "WaveMind hot cache": _metric_summary(
                    scale_readiness_results.get("WaveMind hot cache"),
                    (
                        "queries",
                        "capacity",
                        "hit_rate",
                        "evictions",
                        "prewarm_warmed",
                        "prewarm_hit",
                        "p99_lookup_ms",
                    ),
                ),
                "WaveMind query vector cache": _metric_summary(
                    scale_readiness_results.get("WaveMind query vector cache"),
                    (
                        "queries",
                        "local_encode_calls",
                        "local_hit_rate",
                        "redis_shared_across_workers",
                        "redis_encode_calls",
                        "redis_reader_hits",
                        "p99_local_query_ms",
                    ),
                ),
                "WaveMind shared rate limiter": _metric_summary(
                    scale_readiness_results.get("WaveMind shared rate limiter"),
                    (
                        "backend",
                        "workers",
                        "limit_per_minute",
                        "allowed",
                        "limited",
                        "shared_across_workers",
                        "expire_seconds",
                        "p99_check_ms",
                    ),
                ),
                "WaveMind Memory OS": _metric_summary(
                    scale_readiness_results.get("WaveMind Memory OS"),
                    (
                        "ok",
                        "hot_queries",
                        "prewarm_warmed",
                        "prewarm_hit",
                        "predictive_prefetch_generated",
                        "predictive_prefetch_warmed",
                        "expired_purged",
                        "concepts_created",
                        "concept_recall",
                        "priority_predictions",
                        "forgetting_demotions",
                        "architecture_advice_status",
                        "architecture_advice_recommendation_ids",
                        "architecture_next_commands",
                        "run_ms",
                    ),
                ),
                "WaveMind Redis hot cache": _metric_summary(
                    scale_readiness_results.get("WaveMind Redis hot cache"),
                    (
                        "client",
                        "shared_cache_visible_across_clients",
                        "cache_prewarm_warmed",
                        "cache_prewarm_cross_worker_hit",
                        "memory_os_ok",
                        "memory_os_hot_queries",
                        "memory_os_prewarm_warmed",
                        "memory_os_predictive_generated",
                        "memory_os_predictive_warmed",
                        "memory_os_concepts_created",
                        "memory_os_priority_predictions",
                        "memory_os_forgetting_demotions",
                        "memory_os_architecture_advice_status",
                        "memory_os_architecture_recommendations",
                        "memory_os_cross_worker_hit",
                        "namespace_invalidation_removed",
                        "redis_keys",
                        "avg_lookup_ms",
                        "p99_lookup_ms",
                    ),
                ),
                "WaveMind sustained HTTP cluster load": _metric_summary(
                    scale_readiness_results.get("WaveMind sustained HTTP cluster load"),
                    (
                        "nodes",
                        "namespaces",
                        "replication_factor",
                        "writes",
                        "queries",
                        "failover_queries",
                        "write_success_rate",
                        "query_hit_rate",
                        "failover_hit_rate",
                        "delete_suppression_rate",
                        "repair_repaired_total",
                        "success_rate",
                        "p99_operation_ms",
                    ),
                ),
                "WaveMind API cache mutation safety": _metric_summary(
                    scale_readiness_results.get("WaveMind API cache mutation safety"),
                    (
                        "client",
                        "first_query_cached",
                        "cache_invalidated_on_remember",
                        "stale_prevented_after_remember",
                        "cache_invalidated_on_forget",
                        "stale_prevented_after_forget",
                        "old_recall_after_forget",
                        "avg_api_ms",
                        "p99_api_ms",
                    ),
                ),
                "WaveMind Kubernetes operator": _metric_summary(
                    scale_readiness_results.get("WaveMind Kubernetes operator"),
                    (
                        "bundle_has_crd",
                        "bundle_has_operator_deployment",
                        "has_service",
                        "has_statefulset",
                        "has_hpa",
                        "has_repair_cronjob",
                        "autoscaling_min_replicas",
                        "autoscaling_max_replicas",
                        "status_ready",
                        "status_phase",
                        "status_ready_replicas",
                        "status_required_replicas",
                        "status_capacity_within_headroom",
                        "status_conditions_true",
                        "autoscaling_metrics",
                        "repair_namespaces",
                    ),
                ),
                "WaveMind serverless plan": _metric_summary(
                    scale_readiness_results.get("WaveMind serverless plan"),
                    (
                        "has_knative_service",
                        "has_keda_scaled_object",
                        "scale_to_zero",
                        "max_scale",
                        "target_concurrency",
                        "uses_postgres",
                        "uses_external_qdrant",
                        "uses_shared_cache",
                        "safe_for_pod_eviction",
                        "keda_scale_target_kind",
                        "valid_keda_scale_target",
                        "env_has_postgres_dsn",
                        "env_has_qdrant_url",
                        "env_has_redis_url",
                    ),
                ),
                "WaveMind serverless operational profile": _metric_summary(
                    scale_readiness_results.get("WaveMind serverless operational profile"),
                    (
                        "slo_pass",
                        "requests_per_second",
                        "avg_request_ms",
                        "p99_request_ms",
                        "target_p99_ms",
                        "cold_start_ms",
                        "cold_start_total_ms",
                        "cold_start_budget_ms",
                        "cold_start_budget_ok",
                        "required_replicas",
                        "warm_replicas",
                        "max_scale",
                        "target_concurrency",
                        "burst_capacity_rps",
                        "scale_out_possible",
                        "scale_to_zero_safe",
                        "external_state_ok",
                        "uses_postgres",
                        "uses_external_qdrant",
                        "uses_shared_cache",
                        "has_auth_secret",
                        "safe_for_pod_eviction",
                        "monthly_compute_cost_usd",
                        "monthly_budget_usd",
                        "cost_ok",
                        "observed_telemetry_present",
                        "observed_telemetry_source",
                        "observed_requests_per_second",
                        "observed_measured_pool_requests_per_second",
                        "observed_per_replica_requests_per_second",
                        "observed_measured_replicas",
                        "observed_p99_request_ms",
                        "observed_cold_start_total_ms",
                        "observed_error_rate",
                        "observed_max_replicas",
                        "observed_scale_out_seconds",
                        "observed_monthly_compute_cost_usd",
                        "observed_slo_pass",
                    ),
                ),
                "WaveMind distributed sharding": _metric_summary(
                    scale_readiness_results.get("WaveMind distributed sharding"),
                    (
                        "nodes",
                        "replication_factor",
                        "write_quorum",
                        "read_quorum",
                        "writes",
                        "recalled_after_primary_loss",
                        "repair_repaired_total",
                        "repair_ok",
                        "recalled_after_repair",
                        "forget_replicated_deletes",
                        "tombstone_replication_factor",
                        "tombstone_suppressed_before_repair",
                        "tombstone_repair_deleted_records",
                        "tombstone_suppressed_after_repair",
                        "anti_entropy_worker_ok",
                        "anti_entropy_worker_repaired_total",
                        "anti_entropy_worker_tombstone_deleted",
                        "query_after_primary_loss_ms",
                    ),
                ),
                "WaveMind distributed HTTP sharding": _metric_summary(
                    scale_readiness_results.get("WaveMind distributed HTTP sharding"),
                    (
                        "nodes",
                        "replication_factor",
                        "write_quorum",
                        "read_quorum",
                        "proxy_bypass_default",
                        "writes",
                        "recalled_after_primary_loss",
                        "repair_repaired_total",
                        "repair_ok",
                        "recalled_after_repair",
                        "tombstone_missed_delete_replica_records",
                        "tombstone_suppressed_before_repair",
                        "tombstone_repair_deleted_records",
                        "tombstone_stale_records_after_repair",
                        "tombstone_suppressed_after_repair",
                        "concurrent_writes",
                        "concurrent_write_ok",
                        "concurrent_query_hit_rate",
                        "query_after_primary_loss_ms",
                        "concurrent_ms",
                        "repair_ms",
                    ),
                ),
                "WaveMind replicated runtime": _metric_summary(
                    scale_readiness_results.get("WaveMind replicated runtime"),
                    (
                        "nodes",
                        "replication_factor",
                        "write_quorum",
                        "read_quorum",
                        "recalled_after_node_loss",
                        "repair_copied_records",
                        "tombstone_repair_deleted_records",
                        "concurrent_writes",
                        "concurrent_write_ok",
                        "concurrent_query_hit_rate",
                        "concurrent_ms",
                        "p99_query_after_loss_ms",
                    ),
                ),
                "WaveMind active-active delta sync": _metric_summary(
                    scale_readiness_results.get("WaveMind active-active delta sync"),
                    (
                        "regions",
                        "replication_factor_per_region",
                        "records_imported",
                        "converged_after_bidirectional_sync",
                        "suppressed_stale_import_after_delete",
                        "tombstone_converged",
                        "sync_ms",
                    ),
                ),
                "WaveMind field-state CRDT": _metric_summary(
                    scale_readiness_results.get("WaveMind field-state CRDT"),
                    (
                        "regions",
                        "commutative_convergence",
                        "idempotent_remerge",
                        "tombstone_wins",
                        "top_key_converged",
                        "budget_activation",
                        "merge_ms",
                    ),
                ),
                "WaveMind replicated snapshot": _metric_summary(
                    scale_readiness_results.get("WaveMind replicated snapshot"),
                    (
                        "nodes",
                        "manifest_healthy",
                        "offsite_verified",
                        "archive_verified",
                        "object_store_verified",
                        "object_store_latest_verified",
                        "object_store_pruned",
                        "object_store_download_verified",
                        "object_store_drill_ok",
                        "restored_files",
                        "recalled_after_restore_node_loss",
                        "snapshot_ms",
                        "restore_ms",
                    ),
                ),
                "WaveMind structured payloads": _metric_summary(
                    scale_readiness_results.get("WaveMind structured payloads"),
                    (
                        "queries",
                        "precision_at_1",
                        "cross_modal_queries",
                        "cross_modal_precision_at_1",
                        "cross_modal_embedding_dim",
                        "cross_modal_vectors_persisted_rate",
                        "cross_modal_provenance_rate",
                        "precomputed_vector_queries",
                        "precomputed_vector_precision_at_1",
                        "precomputed_vector_embedding_dim",
                        "precomputed_vector_persisted_rate",
                        "avg_latency_ms",
                        "p99_latency_ms",
                        "cross_modal_avg_latency_ms",
                        "cross_modal_p99_latency_ms",
                        "precomputed_vector_avg_latency_ms",
                        "precomputed_vector_p99_latency_ms",
                    ),
                ),
                "WaveMind 100M capacity envelope": _metric_summary(
                    scale_readiness_results.get("WaveMind 100M capacity envelope"),
                    (
                        "target_memories",
                        "namespace_count",
                        "node_count",
                        "zones",
                        "replication_factor",
                        "write_quorum",
                        "node_loss_min_availability",
                        "zone_loss_min_availability",
                        "replica_load_skew",
                        "primary_load_skew",
                        "max_storage_per_node_gb",
                        "recommended_autoscaling_max_replicas",
                        "valid_capacity_plan",
                        "placement_ms",
                    ),
                ),
            },
            "target": "Prove the production foundation before heavier 100k, 1M, 10M, and 100M vector load tests: deterministic placement, cluster autoscale planning, Kubernetes deployment, HPA autoscaling, serverless scale-to-zero planning, scheduled repair manifests, service-mode distributed namespace sharding, real HTTP shard transport, sustained mixed HTTP cluster load, missing-replica repair, tombstone-aware delete repair, anti-entropy repair worker, survivable replicas, cursor-based active-active sync, field-only hotness sync, field-state convergence, offsite/archive/object-store upload/latest-metadata/download/retention/DR-drill checks, query-vector cache, shared rate limiting, Memory OS adaptive prewarm/consolidation/forgetting with production architecture advice, hot-cache behavior, API cache mutation safety, structured payload recall, and a 100M-memory capacity envelope.",
            "next_step": "Move from deterministic 100M capacity planning to service-backed 100M Qdrant/pgvector/FAISS load tests on sized hardware.",
        },
        {
            "id": "production_readiness_gate",
            "name": "Production readiness gate",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/production_readiness_results.json",
            "dataset": "Gate generated from checked-in benchmark artifacts: production load SLO/cost, cluster placement, Kubernetes/operator output, serverless state externalization, cache/prewarm, query-vector cache, shared rate limiting, API cache mutation safety, Memory OS adaptive worker and embedded production architecture advice, distributed repair, cursor-based active-active CRDT convergence, backups, structured payloads, and 10M-load presence. External competitor-service evidence is tracked separately.",
            "competitors": [],
            "metrics": [
                "readiness_score",
                "overall_status",
                "pass_count",
                "action_required_count",
                "fail_count",
                "total_criteria",
            ],
            "current": {
                "WaveMind production readiness": _metric_summary(
                    production_readiness_summary,
                    (
                        "readiness_score",
                        "overall_status",
                        "pass_count",
                        "action_required_count",
                        "fail_count",
                        "total_criteria",
                    ),
                ),
            },
            "target": "Reach readiness_score 1.0 with zero action_required items before claiming complete million-plus production readiness.",
            "next_step": "Keep the gate at readiness_score 1.0 while repeating larger service-backed runs and moving external competitor evidence into the separate adapter profile.",
        },
        {
            "id": "local_http_cluster_smoke",
            "name": "Local HTTP cluster smoke",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/local_http_cluster_smoke.py",
            "dataset": "Four real localhost WaveMind API processes with isolated SQLite stores. The workload checks quorum writes, normal queries, simulated node failover queries, missing-replica repair, replicated forget, delete suppression, p99, and SLO status.",
            "competitors": ["WaveMind local API nodes"],
            "metrics": [
                "success_rate",
                "write_success_rate",
                "query_hit_rate",
                "failover_hit_rate",
                "delete_suppression_rate",
                "repair_repaired_total",
                "p99_operation_ms",
                "slo_pass",
            ],
            "current": {
                "WaveMind local HTTP cluster smoke": _metric_summary(
                    local_http_cluster_results.get("WaveMind local HTTP cluster smoke"),
                    (
                        "nodes",
                        "namespaces",
                        "memories_per_namespace",
                        "replication_factor",
                        "read_fanout",
                        "workers",
                        "success_rate",
                        "write_success_rate",
                        "query_hit_rate",
                        "failover_hit_rate",
                        "delete_suppression_rate",
                        "repair_repaired_total",
                        "p99_operation_ms",
                        "slo_pass",
                    ),
                ),
            },
            "target": "Keep success_rate at 1.0, failover_hit_rate at 1.0, delete_suppression_rate at 1.0, and p99 below 1000 ms in CI before promoting remote service-node deployments.",
            "next_step": "Run the same workload against external service nodes and then increase namespace count and payload size on sized hardware.",
        },
        {
            "id": "external_http_cluster_load_runner",
            "name": "External HTTP cluster load runner",
            "category": "production-scale",
            "status": "implemented",
            "source": "benchmarks/http_cluster_load_benchmark.py",
            "dataset": "Real WaveMind HTTP API-node sustained workload: quorum writes, normal queries, simulated node failover queries, missing-replica repair, replicated forget, delete suppression, and SLO verdict over user-supplied node URLs.",
            "competitors": ["WaveMind remote service nodes"],
            "metrics": [
                "success_rate",
                "write_success_rate",
                "query_hit_rate",
                "failover_hit_rate",
                "delete_suppression_rate",
                "repair_repaired_total",
                "p99_operation_ms",
                "slo_pass",
            ],
            "current": {
                "WaveMind external HTTP cluster load": (
                    _metric_summary(
                        external_http_cluster_results.get("WaveMind external HTTP cluster load"),
                        (
                            "nodes",
                            "namespaces",
                            "memories_per_namespace",
                            "replication_factor",
                            "read_fanout",
                            "workers",
                            "success_rate",
                            "write_success_rate",
                            "query_hit_rate",
                            "failover_hit_rate",
                            "delete_suppression_rate",
                            "repair_repaired_total",
                            "p99_operation_ms",
                            "slo_pass",
                        ),
                    )
                    or {
                        "runner_ready": True,
                        "checked_in_result": False,
                        "requires": "--nodes-file deploy/cluster/external-http-cluster.sample.json or --node id=https://host for each real API node",
                    }
                ),
            },
            "target": "Keep the service-node workload green against real API processes, then repeat it against remote Kubernetes or serverless nodes before claiming external-cluster production readiness.",
            "next_step": "Replace the current loopback service-node artifact with a remote node manifest run from a multi-node deployment.",
        },
        {
            "id": "memory_competitor_adapter_profile",
            "name": "Memory competitor adapter profile",
            "category": "agent-memory",
            "status": "implemented",
            "source": "benchmarks/memory_competitor_benchmark.py",
            "dataset": "Small dynamic-memory adapter profile covering correction, TTL, namespace isolation, and preferences.",
            "competitors": ["Mem0", "Zep", "LangGraph persistent memory", "GraphRAG static graph"],
            "metrics": ["precision@1", "precision@3", "stale_suppression", "avg_latency_ms"],
            "current": {
                "WaveMind": _metric_summary(
                    memory_competitor_results.get("WaveMind"),
                    ("precision_at_1", "precision_at_3", "stale_suppression", "avg_latency_ms", "p95_latency_ms"),
                ),
                "Mem0": memory_competitor_results.get("Mem0"),
                "Zep": memory_competitor_results.get("Zep"),
                "LangGraph persistent memory": memory_competitor_results.get("LangGraph persistent memory"),
                "GraphRAG static graph": memory_competitor_results.get("GraphRAG static graph"),
            },
            "target": "Keep Mem0, LangGraph, and GraphRAG-style local adapter results checked in, then check in a live Zep Cloud or OSS-compatible service run once ZEP_API_URL or ZEP_API_KEY is configured.",
            "next_step": "Run the live Zep adapter against a configured service and expand the GraphRAG baseline from this small static graph to a larger update/conflict workload.",
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
            "next_step": "Run all 470 non-abstention questions with a stronger local/API model and add LLM-judge faithfulness scoring.",
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
        "status": "runner-ready",
        "source": "benchmarks/vectordbbench_dataset.py",
        "source_url": "https://github.com/zilliztech/VectorDBBench",
        "dataset": "VectorDBBench custom dataset export with train/test/neighbors/scalar-label parquet files. Checked-in manifest points to a reproducible 10000-vector, 100-query, 128-d cosine dataset.",
        "competitors": ["Chroma", "Qdrant", "Milvus", "Weaviate", "Pinecone", "FAISS"],
        "metrics": ["qps", "serial_latency_ms", "recall@k", "load_time", "cost_performance"],
        "current": {},
        "target": "Use official VectorDBBench runs to compare WaveMind's production index paths without pretending NumPy local mode is a cloud vector database.",
        "next_step": "Run the generated custom dataset through official VectorDBBench targets for Qdrant, Milvus, pgvector, and WaveMind-backed FAISS/Qdrant profiles.",
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
        "generated_at": _generated_at(),
        "source_ref": _source_ref(root),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "refresh_profile": os.environ.get("WAVEMIND_BENCHMARK_REFRESH_PROFILE", "local"),
        "note": (
            "Implemented entries are runnable from this repository. Planned entries are "
            "public benchmarks that require optional datasets, services, or heavier dependencies."
        ),
        "benchmarks": _implemented_entries(root) + _public_benchmarks(root),
    }


def _public_benchmarks(root: Path) -> list[dict[str, Any]]:
    entries = [dict(entry) for entry in PUBLIC_BENCHMARKS]
    vectordbbench_payload = _load_json(root / "benchmarks" / "vectordbbench_dataset_manifest.json")
    if vectordbbench_payload:
        summary = {
            "WaveMind custom dataset export": {
                "status": vectordbbench_payload.get("status"),
                "vectors": vectordbbench_payload.get("dataset", {}).get("vectors"),
                "queries": vectordbbench_payload.get("dataset", {}).get("queries"),
                "dim": vectordbbench_payload.get("dataset", {}).get("dim"),
                "top_k": vectordbbench_payload.get("dataset", {}).get("top_k"),
            }
        }
        for entry in entries:
            if entry.get("id") == "vectordbbench":
                entry["current"] = summary
                break
    return entries


def _generated_at() -> str:
    value = os.environ.get("WAVEMIND_BENCHMARK_GENERATED_AT")
    if value:
        return value
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str:
    value = os.environ.get("GITHUB_SHA") or os.environ.get("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


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
