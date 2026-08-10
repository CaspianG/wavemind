from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.long_memory_evidence_benchmark import EvidenceMetrics
from benchmarks.quality_leadership_candidate2_dev import (
    build_candidate2_dataset,
    development_rows_from_protocol,
    run_candidate2_development,
)
from benchmarks.quality_leadership_freeze_protocol import (
    CANDIDATE2_LANE,
    build_frozen_protocol,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _memory_agent_metadata() -> dict:
    return {
        "id": "ai-hyz/MemoryAgentBench",
        "sha": "7ea066982b140a19337e17e60d45d4076e042faf",
        "cardData": {
            "license": "mit",
            "dataset_info": {
                "splits": [
                    {"name": "Accurate_Retrieval", "num_examples": 22},
                    {"name": "Test_Time_Learning", "num_examples": 6},
                    {"name": "Long_Range_Understanding", "num_examples": 110},
                    {"name": "Conflict_Resolution", "num_examples": 8},
                ],
            },
        },
        "siblings": [
            {
                "rfilename": "data/Accurate_Retrieval-00000-of-00001.parquet",
                "blobId": "a" * 40,
                "size": 20024386,
                "lfs": {"sha256": "1" * 64, "size": 20024386},
            },
            {
                "rfilename": "data/Test_Time_Learning-00000-of-00001.parquet",
                "blobId": "b" * 40,
                "size": 3947476,
                "lfs": {"sha256": "2" * 64, "size": 3947476},
            },
            {
                "rfilename": "data/Long_Range_Understanding-00000-of-00001.parquet",
                "blobId": "c" * 40,
                "size": 49342452,
                "lfs": {"sha256": "3" * 64, "size": 49342452},
            },
            {
                "rfilename": "data/Conflict_Resolution-00000-of-00001.parquet",
                "blobId": "d" * 40,
                "size": 1491588,
                "lfs": {"sha256": "4" * 64, "size": 1491588},
            },
        ],
    }


def _candidate2_protocol() -> dict:
    return build_frozen_protocol(
        root=PROJECT_ROOT,
        memory_agent_metadata=_memory_agent_metadata(),
        lane=CANDIDATE2_LANE,
    )


def _dev_rows() -> list[dict]:
    rows: list[dict] = []
    for split in (
        "Accurate_Retrieval",
        "Conflict_Resolution",
        "Long_Range_Understanding",
        "Test_Time_Learning",
    ):
        for index in range(2):
            rows.append(
                {
                    "split": split,
                    "row_idx": index,
                    "row": {
                        "context": (
                            f"Case {split} {index}.\n"
                            f"The verified answer for {split} {index} is Alpha-{index}.\n"
                            "The stale distractor is Beta."
                        ),
                        "questions": [
                            f"What is the verified answer for {split} {index}?"
                        ],
                        "answers": [[f"Alpha-{index}"]],
                    },
                    "fetch_ms": 1.0,
                }
            )
    return rows


def _metrics(engine: str, category_success: dict[str, float]) -> EvidenceMetrics:
    return EvidenceMetrics(
        engine=engine,
        evidence_recall_at_k=0.5,
        evidence_precision_at_k=0.5,
        mrr_at_k=0.5,
        precision_at_1=0.5,
        stale_suppression=1.0,
        category_success=category_success,
        context_tokens_returned=24,
        context_budget_saved=0.4,
        avg_latency_ms=1.0,
        p50_latency_ms=1.0,
        p95_latency_ms=2.0,
        p99_latency_ms=2.5,
        queries=sum(1 for _ in category_success),
    )


def test_candidate2_development_rows_are_exact_preregistered_dev_rows() -> None:
    rows = development_rows_from_protocol(_candidate2_protocol())

    assert rows == {
        "Accurate_Retrieval": [0, 1],
        "Conflict_Resolution": [0, 1],
        "Long_Range_Understanding": [0, 1],
        "Test_Time_Learning": [0, 1],
    }


def test_candidate2_development_rows_reject_heldout_overlap() -> None:
    protocol = _candidate2_protocol()
    held_out = protocol["new_quality_dataset"]["held_out_split"]
    held_out["case_fingerprints"].append(
        protocol["new_quality_dataset"]["development_split"]["case_fingerprints"][0]
    )

    with pytest.raises(ValueError, match="development/held-out row overlap"):
        development_rows_from_protocol(protocol)


def test_candidate2_dataset_uses_literal_answer_evidence_without_hidden_labels() -> None:
    dataset, per_query, metadata = build_candidate2_dataset(
        _dev_rows(),
        questions_per_row=1,
    )

    assert metadata["rows"] == 8
    assert metadata["queries"] == 8
    assert len(dataset.memories) >= 8
    assert len(dataset.queries) == 8
    assert len(per_query) == 8
    assert sorted(metadata["category_query_counts"].values()) == [2, 2, 2, 2]
    assert all(query.expected_evidence_ids for query in dataset.queries)


def test_candidate2_runner_writes_bounded_dev_payload_without_heldout_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = _candidate2_protocol()
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    categories = {
        "Accurate_Retrieval": 0.5,
        "Conflict_Resolution": 0.5,
        "Long_Range_Understanding": 0.5,
        "Test_Time_Learning": 0.5,
    }

    def fake_fetch(**kwargs):
        assert kwargs["development_rows"] == development_rows_from_protocol(protocol)
        return _dev_rows()

    def fake_trials(dataset, *, top_k, measurement_trials):
        assert top_k == 3
        assert measurement_trials == 5
        assert len(dataset.queries) == 8
        return {
            "WaveMind Core": [_metrics("WaveMind Core", categories) for _ in range(5)],
            "WaveMind + Memory OS": [
                _metrics("WaveMind + Memory OS", categories) for _ in range(5)
            ],
            "Static vector": [_metrics("Static vector", categories) for _ in range(5)],
        }

    monkeypatch.setattr(
        "benchmarks.quality_leadership_candidate2_dev."
        "fetch_memory_agent_bench_development_rows",
        fake_fetch,
    )
    monkeypatch.setattr(
        "benchmarks.quality_leadership_candidate2_dev._run_engine_trials",
        fake_trials,
    )

    payload, rows = run_candidate2_development(protocol_path=protocol_path)

    assert payload["schema"] == "wavemind.agent_memory_advantage_benchmark.v1"
    assert payload["status"] == "pass"
    assert payload["protocol"]["lane"] == CANDIDATE2_LANE
    assert payload["protocol"]["held_out_viewed"] is False
    assert payload["protocol"]["row_access"] == (
        "huggingface_rows_api_development_rows_only"
    )
    assert payload["paired_lift"]["overall_task_success"]["mean"] == 0.0
    assert len(rows) == 8
