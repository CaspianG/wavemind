from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.public_memory_report import (
    merge_locomo_artifacts,
    render_markdown,
)


SHA = "a" * 40
DATASET_SHA = "b" * 64


def _artifact(
    path: Path,
    engines: list[str],
    *,
    source_sha: str = SHA,
    queries: int = 1977,
) -> Path:
    results = []
    for index, engine in enumerate(engines):
        row = {
            "engine": engine,
            "evidence_recall_at_k": 0.50 + index * 0.01,
            "precision_at_1": 0.30,
            "mrr_at_k": 0.40,
            "avg_latency_ms": 5.0 + index,
            "p95_latency_ms": 8.0 + index,
            "ingest_avg_ms": 1.0 + index,
            "ingest_scope": "scope",
        }
        if engine in {"Mem0 OSS", "Hindsight OSS"}:
            row.update(
                system_version="1.2.3",
                embedding_profile="native:model",
                provenance_mode="document_id",
            )
        results.append(row)
    payload = {
        "source_sha": source_sha,
        "scenario": {
            "dataset": r"C:\private\benchmark-data\locomo10.json",
            "dataset_sha256": DATASET_SHA,
            "conversations": 10,
            "memories": 5882,
            "queries": queries,
            "top_k": 5,
        },
        "comparison_protocol": {
            "same_memories": True,
            "same_queries": True,
            "same_top_k": True,
            "evidence_mapping": "source provenance only; no text matching",
        },
        "results": results,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_report_merges_complete_same_protocol_artifacts(tmp_path):
    internal = _artifact(
        tmp_path / "internal.json",
        [
            "WaveMind",
            "WaveMind + Memory OS",
            "Chroma static",
            "Qdrant static",
        ],
    )
    mem0 = _artifact(tmp_path / "mem0.json", ["Mem0 OSS"])
    hindsight = _artifact(tmp_path / "hindsight.json", ["Hindsight OSS"])

    payload = merge_locomo_artifacts([internal, mem0, hindsight])
    markdown = render_markdown(payload)

    assert payload["schema"] == "wavemind.public_memory_competitors.v1"
    assert len(payload["results"]) == 6
    assert payload["protocol"]["external_inference"] is False
    assert payload["scenario"]["dataset"] == "locomo10.json"
    assert "C:\\private" not in json.dumps(payload)
    assert "5,882 memories" in markdown
    assert "Ingest scope" in markdown
    assert "not final answer quality" in markdown


def test_report_rejects_mixed_dataset_or_commit(tmp_path):
    internal = _artifact(
        tmp_path / "internal.json",
        [
            "WaveMind",
            "WaveMind + Memory OS",
            "Chroma static",
            "Qdrant static",
        ],
    )
    mem0 = _artifact(
        tmp_path / "mem0.json",
        ["Mem0 OSS"],
        source_sha="c" * 40,
    )
    hindsight = _artifact(
        tmp_path / "hindsight.json",
        ["Hindsight OSS"],
        queries=50,
    )

    with pytest.raises(ValueError, match="scenario.queries"):
        merge_locomo_artifacts([internal, hindsight])
    with pytest.raises(ValueError, match="source_sha"):
        merge_locomo_artifacts([internal, mem0])


def test_report_requires_real_external_system_metadata(tmp_path):
    internal = _artifact(
        tmp_path / "internal.json",
        [
            "WaveMind",
            "WaveMind + Memory OS",
            "Chroma static",
            "Qdrant static",
        ],
    )
    mem0 = _artifact(tmp_path / "mem0.json", ["Mem0 OSS"])
    hindsight = _artifact(tmp_path / "hindsight.json", ["Hindsight OSS"])
    payload = json.loads(mem0.read_text(encoding="utf-8"))
    payload["results"][0]["system_version"] = "unknown"
    mem0.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="system_version"):
        merge_locomo_artifacts([internal, mem0, hindsight])
