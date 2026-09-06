from __future__ import annotations

from wavemind.scientific_memory import MemoryDefinition, MemoryKind
from wavemind.scientific_reconciliation import (
    ProofCarryingStateReconciler,
    active_claims,
)


def _memory(memory_id: str, content: str, *, order: int = 0) -> MemoryDefinition:
    return MemoryDefinition(
        memory_id=memory_id,
        kind=MemoryKind.FACT,
        content=content,
        provenance=(f"source-order:{order}",),
        estimated_tokens=max(1, len(content) // 4),
        estimated_latency_ms=0.1,
        safety_risk=0.0,
    )


def test_reconciler_uses_latest_claim_and_traverses_four_hops():
    rows = (
        '506. Anthology 1 was performed by The Beatles.',
        '3690. Anthology 1 was performed by Madonna.',
        '847. The director of Madonna is Guy Oseary.',
        '2813. The director of Madonna is Narendra Modi.',
        '906. Narendra Modi is a citizen of India.',
        '1625. Narendra Modi is a citizen of Australia.',
        '4483. The official language of Australia is Arabic.',
        '2825. Australia is located in the continent of South America.',
    )
    definitions = {
        f"fact-{index}": _memory(f"fact-{index}", content)
        for index, content in enumerate(rows)
    }
    reconciler = ProofCarryingStateReconciler(maximum_graph_hops=4)

    selection = reconciler.select(
        "From which continent does the country of citizenship of the director "
        "who worked with the performer of Anthology 1 belong to?",
        definitions,
        token_budget=512,
        latency_budget_ms=100.0,
        max_safety_risk=0.0,
        context={},
        moment=0.0,
    )
    selected = [definitions[memory_id].content for memory_id in selection.memory_ids]

    assert any("3690. Anthology 1" in content for content in selected)
    assert any("2813. The director of Madonna" in content for content in selected)
    assert any("1625. Narendra Modi" in content for content in selected)
    assert any("2825. Australia" in content for content in selected)
    assert all("506. Anthology 1" not in content for content in selected)
    assert len(active_claims(definitions)) == 5


def test_reconciler_lexical_retrieval_prefers_rare_query_term():
    definitions = {
        "noise": _memory(
            "noise",
            "A long document about countries, history, and general geography.",
            order=1,
        ),
        "answer": _memory(
            "answer",
            "Normandy is a geographical and cultural region in France.",
            order=2,
        ),
    }
    selection = ProofCarryingStateReconciler().select(
        "In what country is Normandy located?",
        definitions,
        token_budget=20,
        latency_budget_ms=10.0,
        max_safety_risk=0.0,
        context={},
        moment=0.0,
    )

    assert selection.memory_ids == ("answer",)


def test_target_scoped_operation_mode_does_not_let_unrelated_tombstone_dominate():
    definitions = {
        "relevant": MemoryDefinition(
            memory_id="relevant",
            kind=MemoryKind.FACT,
            content="Kevin currently follows a vegan diet for the birthday dinner.",
            provenance=("source-order:10", "memory-operation:1"),
            estimated_tokens=10,
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        ),
        "unrelated-tombstone": MemoryDefinition(
            memory_id="unrelated-tombstone",
            kind=MemoryKind.FACT,
            content="Please forget the old Tecumseh history note.",
            provenance=(
                "source-order:20",
                "memory-operation:1",
                "memory-tombstone:1",
            ),
            estimated_tokens=10,
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        ),
    }
    kwargs = {
        "token_budget": 10,
        "latency_budget_ms": 10.0,
        "max_safety_risk": 0.0,
        "context": {},
        "moment": 0.0,
    }
    legacy = ProofCarryingStateReconciler(operation_aware=True).select(
        "What is Kevin's current diet?", definitions, **kwargs
    )
    targeted = ProofCarryingStateReconciler(
        operation_aware=True,
        query_phrase_aware=True,
        target_scoped_tombstones=True,
    ).select("What is Kevin's current diet?", definitions, **kwargs)

    assert legacy.memory_ids == ("unrelated-tombstone",)
    assert targeted.memory_ids == ("relevant",)


def test_reconciler_recency_breaks_equal_state_relevance_toward_clean_checkpoint():
    definitions = {
        "stale": _memory(
            "stale",
            "user residence neighborhood lease previous city details",
            order=4,
        ),
        "clean": _memory(
            "clean",
            "user residence neighborhood lease previous city detail removed",
            order=46,
        ),
    }
    selection = ProofCarryingStateReconciler().select(
        "Which residence neighborhood lease and previous city details are usable?",
        definitions,
        token_budget=15,
        latency_budget_ms=10.0,
        max_safety_risk=0.0,
        context={},
        moment=0.0,
    )

    assert selection.memory_ids == ("clean",)
