from __future__ import annotations

from wavemind.scientific_memoryagentbench import compile_candidate_units
from wavemind.scientific_memops import ScientificMemOpsRetriever
from wavemind.scientific_runtime import ScientificCandidateMode
from wavemind.scientific_slicing import slice_candidate_content


def test_v7_slices_are_deterministic_bounded_and_overlapping():
    content = " ".join(f"token-{index:04d}" for index in range(600))

    first = slice_candidate_content(content)
    second = slice_candidate_content(content)

    assert first == second
    assert len(first) > 2
    assert all(0 < len(value) <= 1024 for value, _ in first)
    assert [offset for _, offset in first] == sorted(offset for _, offset in first)
    for (left, _), (right, _) in zip(first, first[1:]):
        assert set(left.split()[-10:]).intersection(right.split()[:40])


def test_v7_compiler_slices_documents_without_changing_v6():
    document = "Document 7:\n" + " ".join(
        f"evidence-{index:04d}" for index in range(500)
    )

    v6 = compile_candidate_units(
        context=document,
        source="book",
        official_chunks=(document,),
        mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
    )
    v7 = compile_candidate_units(
        context=document,
        source="book",
        official_chunks=(document,),
        mode=ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
    )

    assert len(v6) == 1
    assert len(v6[0].content) > 1024
    assert len(v7) > 1
    assert all(len(unit.content) <= 1024 for unit in v7)
    assert all(unit.structural_kind == "query-slice:document-section" for unit in v7)


def test_v7_memops_filters_then_slices_with_zero_recency_weight(tmp_path):
    long_dialogue = (
        "user: Please remember my travel information. assistant: Noted. "
        + "unrelated filler " * 180
        + "user: My connection is through Reykjavik. assistant: Remembered."
    )
    corpus = [
        {
            "corpus_id": "A16#session1",
            "session_index": 1,
            "text": "user: Tell me a joke. assistant: Sure.",
        },
        {
            "corpus_id": "A16#session2",
            "session_index": 2,
            "text": long_dialogue,
        },
    ]

    with ScientificMemOpsRetriever(
        tmp_path / "v7.db",
        corpus=corpus,
        mode=ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
    ) as retriever:
        ranked, recall = retriever.retrieve(
            "Where is my connection? Reykjavik",
            token_budget=8192,
            top_k_context=10,
            evaluation_only=True,
        )

        assert ranked
        assert all(item["corpus_id"] == "A16#session2" for item in ranked)
        assert all(len(item["text"]) <= 1024 for item in ranked)
        assert any("Reykjavik" in item["text"] for item in ranked)
        assert recall.estimated_tokens <= 8192
        assert retriever.runtime.state_reconciler.source_recency_weight == 0.0
        assert retriever.runtime.retriever.store.count(namespace="scientific") == 0
        assert retriever.runtime.event_log.validate_chain() == []
