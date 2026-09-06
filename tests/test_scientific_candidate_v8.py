from __future__ import annotations

from wavemind.scientific_memory import MemoryDefinition, MemoryKind
from wavemind.scientific_memoryagentbench import compile_candidate_units
from wavemind.scientific_query_phrases import extract_query_candidate_phrases
from wavemind.scientific_reconciliation import ProofCarryingStateReconciler
from wavemind.scientific_runtime import ScientificCandidateMode


def _memory(memory_id: str, content: str, *, order: int) -> MemoryDefinition:
    return MemoryDefinition(
        memory_id=memory_id,
        kind=MemoryKind.FACT,
        content=content,
        provenance=(f"source-order:{order}",),
        estimated_tokens=max(1, len(content) // 4),
        estimated_latency_ms=0.1,
        safety_risk=0.0,
    )


def test_v8_extracts_only_bounded_multiword_string_options_from_query():
    query = (
        "Which event happened? Options: "
        "['The ship reached London.', 'The train left Paris.']"
    )

    assert extract_query_candidate_phrases(query) == (
        "the ship reached london",
        "the train left paris",
    )
    assert extract_query_candidate_phrases("Options: ['single', 'words']") == ()
    assert extract_query_candidate_phrases("Options: [1, 2]") == ()
    assert extract_query_candidate_phrases("Options: __import__('os').system('x')") == ()


def test_v8_phrase_alignment_precedes_higher_partial_lexical_overlap():
    query = (
        "Which event happened? Options: "
        "['The ship reached London.', 'The train left Paris.']"
    )
    definitions = {
        "partial": _memory(
            "partial",
            "Ship train event happened after it reached the station in Paris.",
            order=2,
        ),
        "complete": _memory(
            "complete",
            "At dawn, the ship reached London before the weather changed.",
            order=1,
        ),
    }
    selection = ProofCarryingStateReconciler(
        maximum_candidates=1,
        source_recency_weight=0.0,
        query_phrase_aware=True,
    ).select(
        query,
        definitions,
        token_budget=100,
        latency_budget_ms=10.0,
        max_safety_risk=0.0,
        context={},
        moment=0.0,
    )

    assert selection.memory_ids == ("complete",)
    assert "phrase-aligned" in selection.reason


def test_v8_without_accepted_options_is_exact_v7_ranking_fallback():
    definitions = {
        "older": _memory("older", "The route leads to Reykjavik.", order=1),
        "newer": _memory("newer", "The route leads to Oslo.", order=2),
    }
    query = "Where does the route lead?"
    common = {
        "token_budget": 100,
        "latency_budget_ms": 10.0,
        "max_safety_risk": 0.0,
        "context": {},
        "moment": 0.0,
    }

    v7 = ProofCarryingStateReconciler(source_recency_weight=0.0).select(
        query, definitions, **common
    )
    v8 = ProofCarryingStateReconciler(
        source_recency_weight=0.0,
        query_phrase_aware=True,
    ).select(query, definitions, **common)

    assert v8 == v7


def test_v8_compiler_preserves_frozen_v7_slicing():
    document = "Document 3:\n" + " ".join(
        f"evidence-{index:04d}" for index in range(500)
    )

    v7 = compile_candidate_units(
        context=document,
        source="book",
        official_chunks=(document,),
        mode=ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
    )
    v8 = compile_candidate_units(
        context=document,
        source="book",
        official_chunks=(document,),
        mode=ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
    )

    assert v8 == v7
