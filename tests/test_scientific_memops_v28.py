from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from wavemind.scientific_memops import (
    ScientificMemOpsRetriever,
    classify_memory_operation_slice,
)
from wavemind.scientific_runtime import ScientificCandidateMode


ROOT = Path(__file__).resolve().parents[1]


def test_slice_classifier_recovers_embedded_forget_turn():
    content = (
        "assistant: The old value is 14.2. user: Those details are otherwise right. "
        "Can you forget the progesterone number? assistant: Removed from your records."
    )

    assert classify_memory_operation_slice(content) == (True, True)
    assert classify_memory_operation_slice("assistant: General progesterone guidance.") == (
        False,
        False,
    )


def test_slice_classifier_does_not_treat_autobiographical_uncertainty_as_deletion():
    content = (
        "user: James's test was in March, but I don't remember the exact date. "
        "assistant: I will note that the date is uncertain."
    )

    operation, tombstone = classify_memory_operation_slice(content)

    assert tombstone is False
    assert operation is False


def test_v28_prioritizes_relevant_local_tombstone_without_marking_whole_session(
    tmp_path,
):
    corpus = [
        {
            "corpus_id": "case#session1",
            "session_index": 1,
            "text": (
                "user: My progesterone result was 14.2 ng/mL. "
                "assistant: I have stored 14.2 ng/mL. "
                + ("unrelated filler " * 90)
                + "user: Can you forget the progesterone result of 14.2 ng/mL? "
                "assistant: Removed; no progesterone result is now on file."
            ),
        },
        {
            "corpus_id": "case#session2",
            "session_index": 2,
            "text": "user: What is general progesterone guidance? assistant: Ask a clinician.",
        },
    ]
    with ScientificMemOpsRetriever(
        tmp_path / "slice-local.db",
        corpus=corpus,
        mode=ScientificCandidateMode.SLICE_LOCAL_TOMBSTONE_AGENT,
    ) as retriever:
        ranked, recall = retriever.retrieve(
            "What is my progesterone result?",
            token_budget=2000,
            top_k_context=10,
            evaluation_only=True,
        )
        definitions = retriever.runtime.event_log.definitions()

    assert "forget the progesterone" in ranked[0]["text"].lower()
    tombstones = [
        memory_id
        for memory_id, definition in definitions.items()
        if "memory-tombstone:1" in definition.provenance
    ]
    assert len(tombstones) == 1
    assert recall.selected_memory_ids[0] == tombstones[0]


def test_v28_wrapper_is_diagnostic_only_and_uses_slice_local_candidate():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v28_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v28_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)

    assert wrapper.runner.DIAGNOSTIC_ONLY is True
    assert wrapper.runner.ARTIFACT_PHASE == "opened-development-diagnostic"
    assert (
        wrapper.runner.CANDIDATE_MODE
        is ScientificCandidateMode.SLICE_LOCAL_TOMBSTONE_AGENT
    )
