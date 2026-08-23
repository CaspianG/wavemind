from __future__ import annotations

import json
from pathlib import Path

import pytest

from wavemind.evidence import validate_artifact_integrity
from wavemind.scientific_baselines import (
    SCIENTIFIC_BASELINE_MATRIX_SCHEMA,
    BaselineCorpusItem,
    _budget_hits,
    build_baseline_retrievers,
    close_baseline_retrievers,
    deterministic_arm_order,
    frozen_baseline_configs,
)
from wavemind.scientific_memoryagentbench import MemoryAgentBenchDevelopmentUnit
from wavemind.scientific_memoryagentbench_baselines import (
    build_baseline_matrix_artifact,
    summarize_raw_baseline_rows,
)
from wavemind.scientific_protocol import REQUIRED_BASELINES


ROOT = Path(__file__).resolve().parents[1]


def _protocol() -> dict:
    return json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v1.json").read_text(
            encoding="utf-8"
        )
    )


def test_frozen_baseline_config_and_arm_order_are_exact():
    configs = frozen_baseline_configs(_protocol())

    assert set(configs) == REQUIRED_BASELINES
    assert configs["static-vector-retrieval"]["vector_weight"] == 1.0
    assert configs["wavemind-wavefield"]["field_weight"] == 0.04
    assert configs["wavemind-graph"]["graph_weight"] == 0.1
    assert configs["wavemind-memory-os"]["memory_os"] is True
    order = deterministic_arm_order(seed=17, case_id="case-1")
    assert set(order) == REQUIRED_BASELINES
    assert order == deterministic_arm_order(seed=17, case_id="case-1")


def test_common_budget_is_order_preserving_and_never_exceeded():
    ids, contents, scores, used = _budget_hits(
        (
            ("large", "x" * 80, 1.0),
            ("small", "ok", 0.9),
            ("small-2", "go", 0.8),
        ),
        token_budget=2,
    )

    assert ids == ("small", "small-2")
    assert contents == ("ok", "go")
    assert scores == (0.9, 0.8)
    assert used == 2


def test_real_baseline_backends_execute_same_embedding_contract(tmp_path):
    for package in ("mem0", "langgraph", "chromadb", "qdrant_client"):
        pytest.importorskip(package)
    corpus = (
        BaselineCorpusItem("m1", "The launch code is amber."),
        BaselineCorpusItem("m2", "The capital of France is Paris."),
        BaselineCorpusItem("m3", "A failed strategy was to guess."),
    )
    retrievers = build_baseline_retrievers(
        corpus=corpus,
        scratch_dir=tmp_path / "real-baselines",
        protocol=_protocol(),
        seed=17,
    )
    try:
        assert set(retrievers) == REQUIRED_BASELINES
        results = {
            arm_id: retriever.retrieve(
                "What is the capital of France?",
                top_k=2,
                token_budget=100,
            )
            for arm_id, retriever in retrievers.items()
        }
    finally:
        close_baseline_retrievers(retrievers)

    assert results["no-memory"].memory_ids == ()
    for arm_id in REQUIRED_BASELINES - {"no-memory"}:
        assert results[arm_id].memory_ids[0] == "m2"
        assert results[arm_id].context_tokens <= 100
    assert results["mem0-oss"].backend["real_mem0_add_and_search_executed"]
    assert results["wavemind-memory-os"].backend["real_memory_os_worker_executed"]


def _raw_rows() -> list[dict]:
    rows = []
    for case_id in ("case-1", "case-2"):
        order = deterministic_arm_order(seed=17, case_id=case_id)
        for index, arm_id in enumerate(order):
            rows.append(
                {
                    "case_id": case_id,
                    "arm_id": arm_id,
                    "arm_index": index,
                    "arm_order": order,
                    "answer_cache_hit": index > 0,
                    "prompt_sha256": ("a" if index == 0 else "b") * 64,
                    "retrieval": {"context_tokens": index},
                    "official_metrics": {"substring_exact_match": 1.0},
                }
            )
    return rows


def test_raw_baseline_summary_requires_every_case_arm_pair():
    rows = _raw_rows()
    summary = summarize_raw_baseline_rows(rows)

    assert summary["logical_arm_case_count"] == 2 * len(REQUIRED_BASELINES)
    assert summary["per_arm"]["mem0-oss"]["mean"] == 1.0
    with pytest.raises(ValueError, match="incomplete or duplicated"):
        summarize_raw_baseline_rows(rows[:-1])


def test_baseline_artifact_is_development_only_and_records_confound(
    tmp_path, monkeypatch
):
    official = tmp_path / "official"
    official.mkdir()
    (official / "main.py").write_text("# pinned\n", encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    project = tmp_path / "project"
    (project / "wavemind").mkdir(parents=True)
    (project / "wavemind" / "encoders.py").write_text("# encoder\n", encoding="utf-8")
    raw = tmp_path / "raw.jsonl"
    raw.write_text("{}\n", encoding="utf-8")
    failed = tmp_path / "failed.jsonl"
    failed.write_text('{"error":"missing optional client"}\n', encoding="utf-8")
    unit = MemoryAgentBenchDevelopmentUnit(
        unit_id="unit-1",
        family="Conflict_Resolution",
        source="factconsolidation_mh_64k",
        row_index=0,
        context="context",
        row={},
    )
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench_baselines._exact_git_sha",
        lambda repository: "f" * 40,
    )
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench_baselines.hardware_inventory",
        lambda: {"machine": "test"},
    )
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench_baselines.real_baseline_package_metadata",
        lambda: {
            arm_id: {"package": arm_id}
            for arm_id in ("mem0-oss", "langgraph", "chroma", "qdrant-local")
        },
    )
    summary = {
        "case_orders": {"unit-1:q0000": sorted(REQUIRED_BASELINES)},
        "unique_prompt_count": 2,
        "answer_invocation_count": 2,
        "logical_arm_case_count": len(REQUIRED_BASELINES),
        "per_arm": {arm_id: {"mean": 0.0} for arm_id in REQUIRED_BASELINES},
    }

    payload = build_baseline_matrix_artifact(
        project_root=project,
        source_sha="a" * 40,
        protocol=_protocol(),
        official_repository=official,
        dataset_root=dataset,
        model="mistral:7b",
        model_digest="b" * 64,
        context_window=32768,
        token_budget=8192,
        top_k=10,
        seed=17,
        units=(unit,),
        raw_results_file=raw,
        summary=summary,
        failed_attempt_files=(failed,),
    )

    assert payload["schema"] == SCIENTIFIC_BASELINE_MATRIX_SCHEMA
    assert payload["admission_eligible"] is False
    assert payload["gold_fields_exposed_to_retrievers_or_answer_agent"] == []
    graph = next(
        row for row in payload["ablation_pairs"] if row["id"] == "graph-on-vs-graph-off"
    )
    assert graph["single_factor"] is False
    assert set(graph["config_differences"]) == {"graph_weight", "vector_weight"}
    assert payload["failed_attempts_retained"][0]["sha256"]
    assert validate_artifact_integrity(payload) == []
