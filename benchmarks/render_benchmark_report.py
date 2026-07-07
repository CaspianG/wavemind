from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_matrix(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root / "benchmarks" / "benchmark_matrix_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value < 10:
            return f"{value:.2f}"
        return f"{value:.1f}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)


METRIC_LABELS = {
    "task_success_rate": "task success",
    "decision_success_at_1": "top-1 decision",
    "stale_error_rate": "stale error rate",
    "namespace_leak_rate": "namespace leak rate",
    "coherent_turns": "coherent turns",
    "coherent_turn_rate": "coherent turn rate",
    "precision_at_1": "precision@1",
    "precision_at_3": "precision@3",
    "precision@1": "precision@1",
    "precision@3": "precision@3",
    "ndcg_at_k": "nDCG@k",
    "recall_at_k": "Recall@k",
    "target_recall_at_k": "target recall@k",
    "target_recall_at_1": "target recall@1",
    "evidence_recall_at_k": "evidence recall@k",
    "exact_match": "exact match",
    "contains_answer": "contains answer",
    "token_f1": "token F1",
    "answered_rate": "answered rate",
    "abstention_rate": "abstention rate",
    "grounded_answer_rate": "grounded answer rate",
    "supported_answer_rate": "supported answer rate",
    "unsupported_answer_rate": "unsupported answer rate",
    "faithfulness_rate": "faithfulness rate",
    "mrr_at_k": "MRR@k",
    "stale_suppression": "stale suppression",
    "suppression_rate": "stale suppression",
    "concept_formation": "concept formation",
    "concept_consolidation": "concept consolidation",
    "decay_ratio": "decay ratio",
    "context_budget_saved": "context saved",
    "avg_latency_ms": "avg latency",
    "p95_latency_ms": "p95 latency",
    "p99_latency_ms": "p99 latency",
    "cross_modal_queries": "cross-modal queries",
    "cross_modal_precision_at_1": "cross-modal precision@1",
    "cross_modal_embedding_dim": "cross-modal dim",
    "cross_modal_vectors_persisted_rate": "cross-modal vectors persisted",
    "cross_modal_provenance_rate": "cross-modal provenance",
    "cross_modal_avg_latency_ms": "cross-modal avg latency",
    "cross_modal_p99_latency_ms": "cross-modal p99 latency",
    "precomputed_vector_queries": "precomputed-vector queries",
    "precomputed_vector_precision_at_1": "precomputed-vector precision@1",
    "precomputed_vector_embedding_dim": "precomputed-vector dim",
    "precomputed_vector_persisted_rate": "precomputed-vector persisted",
    "precomputed_vector_avg_latency_ms": "precomputed-vector avg latency",
    "precomputed_vector_p99_latency_ms": "precomputed-vector p99 latency",
    "temporal_event_queries": "temporal-event queries",
    "temporal_event_precision_at_1": "temporal-event precision@1",
    "temporal_event_around_precision_at_1": "temporal around@1",
    "temporal_event_window_precision_at_1": "temporal window@1",
    "temporal_event_recency_precision_at_1": "temporal recency@1",
    "temporal_event_interval_precision_at_1": "temporal interval@1",
    "temporal_event_persistence_rate": "temporal persistence",
    "temporal_event_provenance_rate": "temporal provenance",
    "temporal_event_avg_latency_ms": "temporal avg latency",
    "temporal_event_p99_latency_ms": "temporal p99 latency",
    "knowledge_graph_queries": "knowledge-graph queries",
    "knowledge_graph_precision_at_1": "knowledge-graph precision@1",
    "knowledge_graph_path_precision_at_1": "knowledge-graph path precision@1",
    "knowledge_graph_direct_precision_at_1": "knowledge-graph direct@1",
    "knowledge_graph_two_hop_precision_at_1": "knowledge-graph two-hop@1",
    "knowledge_graph_three_hop_precision_at_1": "knowledge-graph three-hop@1",
    "knowledge_graph_predicate_precision_at_1": "knowledge-graph predicate@1",
    "knowledge_graph_persistence_rate": "knowledge-graph persistence",
    "knowledge_graph_provenance_rate": "knowledge-graph provenance",
    "knowledge_graph_avg_latency_ms": "knowledge-graph avg latency",
    "knowledge_graph_p99_latency_ms": "knowledge-graph p99 latency",
    "asset_manifest_verified": "asset manifest verified",
    "asset_manifest_sha256_present": "asset sha256 present",
    "asset_manifest_media_type": "asset media type",
    "asset_manifest_provenance_rate": "asset provenance",
    "slo_status": "SLO",
    "slo_required_replicas": "required replicas",
    "slo_autoscaled_qps": "autoscaled QPS",
    "cost_status": "cost status",
    "compute_cost_per_1m_queries_usd": "cost / 1M queries",
    "monthly_total_cost_at_target_qps_usd": "monthly target cost",
    "estimated_storage_gb": "storage",
    "pgvector_variant": "pgvector variant",
    "status": "status",
    "estimated_index_gb": "estimated index",
    "estimated_transient_runner_gb": "transient runner",
    "estimated_application_storage_gb": "application storage",
    "required_local_free_gb": "required local free",
    "disk_free_gb": "disk free",
    "missing_env": "missing env",
    "readiness_score": "readiness score",
    "overall_status": "overall status",
    "pass_count": "passed criteria",
    "action_required_count": "action required",
    "fail_count": "failed criteria",
    "total_criteria": "total criteria",
    "prewarm_warmed": "prewarm warmed",
    "prewarm_hit": "prewarm hit",
    "local_encode_calls": "local encode calls",
    "local_cache_hits": "local cache hits",
    "local_cache_misses": "local cache misses",
    "local_hit_rate": "local hit rate",
    "redis_shared_across_workers": "Redis shared",
    "redis_encode_calls": "Redis encode calls",
    "redis_reader_hits": "Redis reader hits",
    "service_boundary": "service boundary",
    "service_queries": "service queries",
    "service_results_ok": "service results ok",
    "service_encoder_calls": "service encode calls",
    "service_saved_encode_calls": "service saved encode calls",
    "service_cache_hits": "service cache hits",
    "service_cache_misses": "service cache misses",
    "service_hit_rate": "service hit rate",
    "service_metrics_exposed": "service metrics exposed",
    "avg_service_query_ms": "service avg latency",
    "p99_service_query_ms": "service p99 latency",
    "batch_size": "batch size",
    "individual_http_requests": "individual HTTP requests",
    "batch_http_requests": "batch HTTP requests",
    "request_reduction_ratio": "request reduction",
    "individual_success": "individual success",
    "batch_success": "batch success",
    "individual_encoder_calls": "individual encode calls",
    "batch_encoder_calls": "batch encode calls",
    "individual_cache_hits": "individual cache hits",
    "batch_cache_hits": "batch cache hits",
    "batch_cache_misses": "batch cache misses",
    "batch_hit_rate": "batch hit rate",
    "batch_metrics_exposed": "batch metrics exposed",
    "individual_total_ms": "individual total latency",
    "batch_total_ms": "batch total latency",
    "batch_total_speedup": "batch total speedup",
    "individual_p99_query_ms": "individual p99 latency",
    "batch_request_ms": "batch request latency",
    "transition_prefetch_queries": "transition-prefetch queries",
    "transition_prefetch_edges": "transition-prefetch edges",
    "transition_prefetch_hit": "transition-prefetch hit",
    "memory_os_transition_prefetch_queries": "Memory OS transition-prefetch queries",
    "memory_os_transition_prefetch_edges": "Memory OS transition-prefetch edges",
    "memory_os_transition_prefetch_hit": "Memory OS transition-prefetch hit",
    "repair_repaired_total": "repair repaired",
    "repair_ok": "repair ok",
    "recalled_after_repair": "recall after repair",
    "tombstone_replication_factor": "tombstone RF",
    "tombstone_suppressed_before_repair": "tombstone suppress before repair",
    "tombstone_repair_deleted_records": "tombstone deleted",
    "tombstone_suppressed_after_repair": "tombstone suppress after repair",
    "anti_entropy_worker_ok": "anti-entropy worker ok",
    "anti_entropy_worker_repaired_total": "anti-entropy repaired",
    "anti_entropy_worker_tombstone_deleted": "anti-entropy tombstone deleted",
    "architecture_advice_status": "architecture advice",
    "architecture_advice_recommendation_ids": "architecture ids",
    "architecture_next_commands": "architecture commands",
    "memory_os_architecture_advice_status": "Memory OS architecture advice",
    "memory_os_architecture_recommendations": "Memory OS architecture ids",
    "status_ready": "operator status ready",
    "status_phase": "operator status phase",
    "status_ready_replicas": "operator ready replicas",
    "status_required_replicas": "operator required replicas",
    "status_capacity_within_headroom": "operator capacity within headroom",
    "status_conditions_true": "operator true conditions",
}


def metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key.replace("_", " "))


def metric_line(current: dict[str, Any] | None) -> str:
    if not current:
        return "No checked-in result yet."
    parts: list[str] = []
    for engine, metrics in current.items():
        if metrics is None:
            parts.append(f"{engine}: no checked-in result")
        elif isinstance(metrics, list):
            rows = len(metrics)
            last = metrics[-1] if metrics else {}
            parts.append(
                f"{engine}: {rows} points, last p@1 {fmt(last.get('precision_at_1'))}, "
                f"avg {fmt(last.get('avg_latency_ms'))} ms"
            )
        elif metrics.get("skipped"):
            reason = str(metrics.get("reason") or "not configured")
            parts.append(f"{engine}: skipped - {reason}")
        else:
            metric_bits = [
                f"{metric_label(key)} {fmt(value)}"
                for key, value in metrics.items()
            ]
            parts.append(f"{engine}: " + ", ".join(metric_bits))
    return "<br>".join(parts)


def table(entries: list[dict[str, Any]], include_results: bool) -> str:
    if include_results:
        header = "| benchmark | category | status | current result | next step |\n|---|---|---|---|---|\n"
    else:
        header = "| benchmark | category | status | competitors | target |\n|---|---|---|---|---|\n"
    rows: list[str] = []
    for entry in entries:
        name = entry["name"]
        if entry.get("source_url"):
            name = f"[{name}]({entry['source_url']})"
        if include_results:
            rows.append(
                f"| {name} | {entry['category']} | {entry['status']} | "
                f"{metric_line(entry.get('current'))} | {entry.get('next_step', '-')} |"
            )
        else:
            competitors = ", ".join(entry.get("competitors", [])) or "-"
            rows.append(
                f"| {name} | {entry['category']} | {entry['status']} | "
                f"{competitors} | {entry.get('target', '-')} |"
            )
    return header + "\n".join(rows) + "\n"


def render_report(root: Path = PROJECT_ROOT) -> str:
    payload = load_matrix(root)
    entries = payload["benchmarks"]
    completed = [entry for entry in entries if entry["status"] == "implemented"]
    runner_ready = [entry for entry in entries if entry["status"] == "runner-ready"]
    planned = [entry for entry in entries if entry["status"] == "planned"]

    runner_ready_block = (
        table(runner_ready, include_results=True).rstrip()
        if runner_ready
        else "None currently. LoCoMo and BEIR/SciFact now have checked-in retrieval results."
    )

    lines = [
        "# WaveMind Benchmark Report",
        "",
        "This report is generated from `benchmarks/benchmark_matrix_results.json`.",
        f"Last refresh: `{payload.get('generated_at', 'unknown')}` from `{payload.get('source_ref', 'unknown')}`.",
        "It separates completed local runs from runner-ready public benchmarks and planned external evaluations.",
        "",
        "Planned rows are not claimed wins. They are the public proof path WaveMind must complete before stronger production claims.",
        "",
        "## Completed Runs",
        "",
        table(completed, include_results=True).rstrip(),
        "",
        "## Runner-Ready Public Benchmarks",
        "",
        runner_ready_block,
        "",
        "## Public Benchmark Roadmap",
        "",
        table(planned, include_results=False).rstrip(),
        "",
        "## Reading Guide",
        "",
        "- Retrieval benchmarks such as BEIR, MTEB, and MIRACL test whether WaveMind can preserve vector-search quality.",
        "- Vector database benchmarks such as ANN-Benchmarks and VectorDBBench test latency, recall, and scale, not memory policy.",
        "- Agent-memory benchmarks such as LoCoMo and LongMemEval are the most important public proof targets for WaveMind.",
        "- The synthetic dynamic-memory and long-memory evidence checks remain useful regression tests, but they are not substitutes for public datasets.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/BENCHMARK_REPORT.md"),
    )
    args = parser.parse_args()
    report = render_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
