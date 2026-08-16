from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from benchmarks.competitive_task_admission import (
    MANDATORY_ENGINES,
    evaluate_competitive_task_admission,
    render_markdown,
)
from benchmarks.competitive_task_benchmark import run_benchmark
from benchmarks.long_memory_evidence_benchmark import compute_evidence_metrics
from benchmarks.public_memory_competitors import ExternalEvidenceMetrics
from wavemind.evidence import repository_commit, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def _runner(
    engine: str,
    *,
    version: str,
    embedding_profile: str,
    provenance_mode: str,
):
    def run(dataset, _encoder, top_k):
        memories = {memory.id: memory for memory in dataset.memories}
        memory_by_namespace = {memory.namespace: memory for memory in dataset.memories}
        rankings = {}
        texts = {}
        for query in dataset.queries:
            if query.expected_evidence_ids:
                selected = query.expected_evidence_ids[0]
            else:
                selected = memory_by_namespace[query.namespace].id
            rankings[query.id] = [selected]
            texts[query.id] = [memories[selected].text]
        base = compute_evidence_metrics(
            dataset.queries,
            rankings,
            texts,
            [0.1 for _ in dataset.queries],
            sum(len(memory.text) // 4 for memory in dataset.memories),
            top_k,
            engine,
        )
        values = asdict(base)
        values.update(
            system_version=version,
            embedding_profile=embedding_profile,
            provenance_mode=provenance_mode,
            ingest_total_ms=1.0,
            ingest_avg_ms=1.0 / len(dataset.memories),
            ingest_scope="real-test-double-contract",
        )
        return ExternalEvidenceMetrics(**values)

    return run


def _runners():
    return {
        "Chroma static": _runner(
            "Chroma static",
            version="1.5.9",
            embedding_profile="shared:hash-384",
            provenance_mode="memory.id",
        ),
        "Qdrant static": _runner(
            "Qdrant static",
            version="1.19.0",
            embedding_profile="shared:hash-384",
            provenance_mode="memory.id",
        ),
        "LangGraph BaseStore": _runner(
            "LangGraph BaseStore",
            version="1.2.11",
            embedding_profile="shared:hash-384",
            provenance_mode="value.evidence_id",
        ),
        "Mem0 OSS": _runner(
            "Mem0 OSS",
            version="2.0.18",
            embedding_profile="fastembed:BAAI/bge-small-en-v1.5",
            provenance_mode="metadata.evidence_id",
        ),
    }


def test_competitive_benchmark_executes_same_held_out_tasks():
    source_sha = repository_commit(ROOT)
    payload = run_benchmark(
        source_sha=source_sha,
        repeats=5,
        runners=_runners(),
    )

    assert payload["status"] == "complete"
    assert payload["protocol"]["held_out_tasks"] == 150
    assert payload["protocol"]["hard_tasks"] == 120
    assert payload["protocol"]["routine_tasks"] == 30
    assert payload["candidate"]["task_success"]["mean"] == 1.0
    assert payload["candidate"]["failed_task_attempts"] == 0.0
    assert {row["engine"] for row in payload["competitors"]} == set(MANDATORY_ENGINES)
    assert all(row["task_success"]["mean"] == 0.8 for row in payload["competitors"])
    assert all(
        lift["lower"] > 0.0 for lift in payload["paired_task_success_lift"].values()
    )


def test_competitive_admission_is_exact_sha_and_fail_closed():
    source_sha = repository_commit(ROOT)
    benchmark = run_benchmark(
        source_sha=source_sha,
        repeats=5,
        runners=_runners(),
    )
    admitted = evaluate_competitive_task_admission(
        benchmark,
        expected_source_sha=source_sha,
        project_root=ROOT,
    )

    assert admitted["status"] == "admitted"
    assert admitted["admitted"] is True
    assert admitted["summary"]["blocker_ids"] == []
    assert admitted["summary"]["checks_passed"] == admitted["summary"]["checks_total"]
    assert validate_artifact_integrity(admitted) == []
    assert "Status: **admitted**" in render_markdown(admitted)

    benchmark["skipped"] = [
        {
            "engine": "Mem0 OSS",
            "status": "skipped",
            "reason": "missing; no imitation substituted",
        }
    ]
    benchmark["status"] = "blocked"
    benchmark["competitors"] = [
        row for row in benchmark["competitors"] if row["engine"] != "Mem0 OSS"
    ]
    blocked = evaluate_competitive_task_admission(
        benchmark,
        expected_source_sha=source_sha,
        project_root=ROOT,
    )

    assert blocked["status"] == "blocked"
    assert blocked["admitted"] is False
    assert "benchmark-complete" in blocked["summary"]["blocker_ids"]
    assert "mandatory-real-engines" in blocked["summary"]["blocker_ids"]
