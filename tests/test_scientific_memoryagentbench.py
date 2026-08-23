from __future__ import annotations

import copy
from pathlib import Path

import pytest

from wavemind.evidence import attach_artifact_integrity, validate_artifact_integrity
from wavemind.scientific_memoryagentbench import (
    MEMORYAGENTBENCH_BOUNDED_DEV_SCHEMA,
    MEMORYAGENTBENCH_CANDIDATE_DEV_SCHEMA,
    MemoryAgentBenchDevelopmentUnit,
    MemoryAgentBenchRuntimeCase,
    NativeOpenAICompatibleClient,
    build_bounded_development_artifact,
    build_candidate_development_artifact,
    build_runtime_and_scoring_cases,
    install_official_compatibility_shims,
    load_development_units,
    require_official_memoryagentbench_sha,
)
from wavemind.scientific_splits import (
    MEMORYAGENTBENCH_REVISION,
    MEMORYAGENTBENCH_SPLIT_SCHEMA,
)


pyarrow = pytest.importorskip("pyarrow")
parquet = pytest.importorskip("pyarrow.parquet")


def _manifest(data_file: Path) -> dict:
    from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes

    rows = parquet.read_table(data_file).to_pylist()
    units = []
    for index, row in enumerate(rows):
        context_hash = sha256_bytes(row["context"].encode())
        question_ids = row["metadata"]["question_ids"]
        units.append(
            {
                "unit_id": f"Accurate_Retrieval:{index:04d}:{context_hash[:16]}",
                "family": "Accurate_Retrieval",
                "row_index": index,
                "context_sha256": context_hash,
                "question_ids_sha256": sha256_bytes(
                    canonical_json_bytes(question_ids)
                ),
                "source_file": f"data/{data_file.name}",
                "source_file_sha256": file_sha256(data_file),
                "split": ["development", "validation", "final"][index],
            }
        )
    return attach_artifact_integrity(
        {
            "schema": MEMORYAGENTBENCH_SPLIT_SCHEMA,
            "upstream": {"revision": MEMORYAGENTBENCH_REVISION},
            "units": units,
        }
    )


def _dataset(tmp_path: Path) -> tuple[Path, dict]:
    data = tmp_path / "data"
    data.mkdir()
    path = data / "Accurate_Retrieval-00000-of-00001.parquet"
    table = pyarrow.table(
        {
            "context": ["a" * 2100, "b" * 2100, "c" * 2100],
            "questions": [["q0"], ["q1"], ["q2"]],
            "answers": [["a0"], ["a1"], ["a2"]],
            "metadata": [
                {"source": "eventqa_65536", "question_ids": [f"id-{index}"]}
                for index in range(3)
            ],
        }
    )
    parquet.write_table(table, path)
    return tmp_path, _manifest(path)


def test_loader_accepts_only_frozen_development_units(tmp_path):
    dataset_root, manifest = _dataset(tmp_path)
    units = load_development_units(
        dataset_root=dataset_root,
        split_manifest=manifest,
        family="Accurate_Retrieval",
    )

    assert len(units) == 1
    assert units[0].row_index == 0
    with pytest.raises(ValueError, match="non-development"):
        load_development_units(
            dataset_root=dataset_root,
            split_manifest=manifest,
            family="Accurate_Retrieval",
            unit_ids=(manifest["units"][2]["unit_id"],),
        )


def test_loader_fails_closed_on_manifest_or_dataset_tampering(tmp_path):
    dataset_root, manifest = _dataset(tmp_path)
    changed = copy.deepcopy(manifest)
    changed["units"][0]["split"] = "final"
    with pytest.raises(ValueError, match="integrity failed"):
        load_development_units(
            dataset_root=dataset_root,
            split_manifest=changed,
            family="Accurate_Retrieval",
        )

    data_file = next((dataset_root / "data").glob("*.parquet"))
    data_file.write_bytes(data_file.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="file hash mismatch"):
        load_development_units(
            dataset_root=dataset_root,
            split_manifest=manifest,
            family="Accurate_Retrieval",
        )


class _OfficialCreator:
    def _process_dataset_item(self, row):
        return row["context"], [("official query", row["answers"], "qa-1")]


def test_runtime_case_is_gold_free_and_official_formatter_is_used():
    unit = MemoryAgentBenchDevelopmentUnit(
        unit_id="unit-1",
        family="Accurate_Retrieval",
        source="eventqa_65536",
        row_index=0,
        context="x" * 2100,
        row={"context": "x" * 2100, "answers": ["secret"]},
    )
    runtime, scoring = build_runtime_and_scoring_cases(
        unit,
        conversation_creator_class=_OfficialCreator,
        agent_name="Simple_rag_bm25",
        max_queries=1,
    )

    assert runtime == [
        MemoryAgentBenchRuntimeCase(
            unit_id="unit-1",
            family="Accurate_Retrieval",
            source="eventqa_65536",
            query_index=0,
            query="official query",
            qa_pair_id="qa-1",
        )
    ]
    assert not hasattr(runtime[0], "answer")
    assert not hasattr(runtime[0], "split")
    assert scoring[0].answer == ["secret"]


def test_native_client_preserves_openai_shape():
    calls = []

    def caller(prompt, model, *, temperature, max_tokens):
        calls.append((prompt, model, temperature, max_tokens))
        return {
            "content": "answer",
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

    response = NativeOpenAICompatibleClient(caller).create(
        model="mistral:7b",
        messages=[{"role": "user", "content": "question"}],
        temperature=0.0,
        max_tokens=40,
    )

    assert response.choices[0].message.content == "answer"
    assert response.usage.prompt_tokens == 10
    assert calls == [("USER:\nquestion", "mistral:7b", 0.0, 40)]


def test_bounded_artifact_preserves_official_metric_names(tmp_path, monkeypatch):
    official = tmp_path / "official"
    official.mkdir()
    (official / "main.py").write_text("# pinned\n", encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    raw = tmp_path / "raw.jsonl"
    raw.write_text('{"exact_match":1.0}\n', encoding="utf-8")
    failed = tmp_path / "failed.jsonl"
    failed.write_text('{"failure":"punkt_tab missing"}\n', encoding="utf-8")
    unit = MemoryAgentBenchDevelopmentUnit(
        unit_id="unit-1",
        family="Accurate_Retrieval",
        source="eventqa_65536",
        row_index=0,
        context="x" * 2100,
        row={},
    )
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench._exact_git_sha",
        lambda repository: "f" * 40,
    )
    payload = build_bounded_development_artifact(
        source_sha="a" * 40,
        official_repository=official,
        dataset_root=dataset,
        model="mistral:7b",
        model_digest="b" * 64,
        context_window=32768,
        units=(unit,),
        case_ids=("unit-1:q0000",),
        raw_results_file=raw,
        metrics={"substring_exact_match": [1.0], "rougeL_f1": [0.5]},
        failed_attempt_files=(failed,),
        compatibility_shims=(
            {
                "target": "BM25Retriever.get_relevant_documents",
                "replacement": "BM25Retriever.invoke",
                "reason": "removed alias",
            },
        ),
    )

    assert payload["schema"] == MEMORYAGENTBENCH_BOUNDED_DEV_SCHEMA
    assert payload["admission_eligible"] is False
    assert payload["gold_fields_exposed_to_answer_agent"] == []
    assert payload["validation_split_touched"] is False
    assert payload["final_split_touched"] is False
    assert payload["failed_attempts_retained"][0]["sha256"]
    assert payload["compatibility_shims"][0]["replacement"] == (
        "BM25Retriever.invoke"
    )
    assert payload["official_native_metrics"]["substring_exact_match"]["mean"] == 1.0
    assert payload["official_native_metrics"]["rougeL_f1"]["mean"] == 0.5
    assert validate_artifact_integrity(payload) == []


def test_official_sha_check_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench._exact_git_sha",
        lambda repository: "0" * 40,
    )
    with pytest.raises(RuntimeError, match="upstream SHA mismatch"):
        require_official_memoryagentbench_sha(tmp_path)


def test_langchain_compatibility_shim_routes_to_invoke(monkeypatch):
    from langchain_community.retrievers import BM25Retriever

    monkeypatch.delattr(BM25Retriever, "get_relevant_documents", raising=False)
    monkeypatch.setattr(
        BM25Retriever,
        "invoke",
        lambda self, query: [f"retrieved:{query}"],
    )

    shims = install_official_compatibility_shims()
    instance = object.__new__(BM25Retriever)

    assert instance.get_relevant_documents("query") == ["retrieved:query"]
    assert shims[0]["replacement"] == "BM25Retriever.invoke"


def test_candidate_artifact_is_shadow_only_and_fail_closed(tmp_path, monkeypatch):
    official = tmp_path / "official"
    official.mkdir()
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    raw = tmp_path / "candidate.jsonl"
    raw.write_text(
        '{"case_id":"unit-1:q0000","paired_effect":0.0}\n',
        encoding="utf-8",
    )
    unit = MemoryAgentBenchDevelopmentUnit(
        unit_id="unit-1",
        family="Conflict_Resolution",
        source="factconsolidation_mh_64k",
        row_index=0,
        context="x" * 2100,
        row={},
    )
    monkeypatch.setattr(
        "wavemind.scientific_memoryagentbench._exact_git_sha",
        lambda repository: "f" * 40,
    )
    payload = build_candidate_development_artifact(
        source_sha="a" * 40,
        protocol_digest="b" * 64,
        official_repository=official,
        dataset_root=dataset,
        model="mistral:7b",
        model_digest="c" * 64,
        context_window=32768,
        token_budget=8192,
        units=(unit,),
        raw_results_file=raw,
        summary={
            "candidate_id": "causal-utility-controller-v1",
            "control_id": "no-memory",
            "paired_metric": "substring_exact_match",
            "paired_effects": [0.0],
            "verified_receipt_count": 1,
            "production_case_count": 0,
            "selected_memory_ids": ["memory-1"],
            "promoted_memory_ids": [],
            "false_verified_promotions": 0,
        },
    )

    assert payload["schema"] == MEMORYAGENTBENCH_CANDIDATE_DEV_SCHEMA
    assert payload["admission_eligible"] is False
    assert payload["gold_fields_exposed_to_answer_agent"] == []
    assert payload["paired_effect"]["mean"] == 0.0
    assert payload["production_case_count"] == 0
    assert payload["promoted_memory_ids"] == []
    assert payload["false_verified_promotions"] == 0
    assert validate_artifact_integrity(payload) == []
