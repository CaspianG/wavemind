from __future__ import annotations

from wavemind.scientific_memory import MemoryDefinition, MemoryKind
from wavemind.scientific_memoryagentbench import (
    build_task_aware_treatment_prompt,
    compile_candidate_units,
)
from wavemind.scientific_reconciliation import ProofCarryingStateReconciler
from wavemind.scientific_runtime import ScientificCandidateMode
from benchmarks import scientific_mab_v14_opened_diagnostic as diagnostic


def _memory(index: int, *, estimated_tokens: int = 10) -> MemoryDefinition:
    return MemoryDefinition(
        memory_id=f"memory-{index:02d}",
        kind=MemoryKind.FACT,
        content=f"target event {index}",
        provenance=(f"source-order:{index}",),
        estimated_tokens=estimated_tokens,
        estimated_latency_ms=0.1,
        safety_risk=0.0,
    )


def test_v14_sequence_coverage_is_even_and_retains_both_endpoints():
    definitions = {
        memory.memory_id: memory for memory in (_memory(index) for index in range(10))
    }

    selection = ProofCarryingStateReconciler(
        maximum_candidates=4
    ).select_sequence_coverage(
        definitions,
        token_budget=100,
        latency_budget_ms=10.0,
    )

    assert selection.memory_ids == (
        "memory-00",
        "memory-03",
        "memory-06",
        "memory-09",
    )
    assert set(selection.relevance.values()) == {1.0}
    assert "sequence coverage" in selection.reason


def test_v14_sequence_coverage_respects_the_frozen_token_budget():
    definitions = {
        memory.memory_id: memory
        for memory in (_memory(index, estimated_tokens=6) for index in range(5))
    }

    selection = ProofCarryingStateReconciler(
        maximum_candidates=5
    ).select_sequence_coverage(
        definitions,
        token_budget=18,
        latency_budget_ms=10.0,
    )

    assert selection.memory_ids == ("memory-00", "memory-01", "memory-02")


def test_v14_summarization_prompt_separates_target_from_demonstration_books():
    prompt = build_task_aware_treatment_prompt(
        source="infbench_sum_eng_shots2",
        contents=("Aeneas leaves Troy.", "Aeneas reaches Italy."),
        query="Example: Robinson is shipwrecked. Now summarize the book.",
    )

    assert "Target-book excerpt 1 (chronological):" in prompt
    assert "Aeneas reaches Italy." in prompt
    assert "unrelated formatting demonstrations" in prompt
    assert prompt.rfind("not a demonstration book") > prompt.rfind("Robinson")


def test_v14_retains_the_blind_v11_structural_slicing_contract():
    context = "First paragraph.\n\nSecond paragraph."

    v11 = compile_candidate_units(
        context=context,
        source="infbench_sum_eng_shots2",
        official_chunks=(context,),
        mode=ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
    )
    v14 = compile_candidate_units(
        context=context,
        source="infbench_sum_eng_shots2",
        official_chunks=(context,),
        mode=ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT,
    )

    assert v14 == v11


def test_v14_opened_runner_cannot_be_mistaken_for_a_fresh_gate():
    assert diagnostic.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    )
    assert diagnostic.runner.DIAGNOSTIC_ONLY is True
    assert diagnostic.runner.ARTIFACT_PHASE == "opened-development-diagnostic"
