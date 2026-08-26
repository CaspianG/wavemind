from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from wavemind.scientific_memops import ScientificMemOpsRetriever
from wavemind.scientific_runtime import ScientificCandidateMode


ROOT = Path(__file__).resolve().parents[1]


def test_v29_removes_pre_tombstone_target_state_from_retrieval(tmp_path):
    corpus = [
        {
            "corpus_id": "case#session1",
            "session_index": 1,
            "text": (
                "user: Please remember my progesterone result was 14.2 ng/mL. "
                "assistant: I stored the progesterone result of 14.2 ng/mL."
            ),
        },
        {
            "corpus_id": "case#session2",
            "session_index": 2,
            "text": (
                "user: Please forget my progesterone result of 14.2 ng/mL. "
                "assistant: Removed; no progesterone result is now on file."
            ),
        },
        {
            "corpus_id": "case#session3",
            "session_index": 3,
            "text": (
                "user: Someone online reported progesterone of 18.6 ng/mL. "
                "assistant: That is not your result."
            ),
        },
    ]
    with ScientificMemOpsRetriever(
        tmp_path / "cutover.db",
        corpus=corpus,
        mode=ScientificCandidateMode.TARGET_STATE_CUTOVER_AGENT,
    ) as retriever:
        ranked, recall = retriever.retrieve(
            "What is my most recent progesterone result?",
            token_budget=2000,
            top_k_context=10,
            evaluation_only=True,
        )

    assert recall.reason == "evaluation-only target-state tombstone cutover evidence"
    assert ranked[0]["corpus_id"] == "case#session2"
    assert "case#session1" not in {item["corpus_id"] for item in ranked}
    assert {item["corpus_id"] for item in ranked} == {
        "case#session2",
        "case#session3",
    }


def test_v29_wrapper_is_diagnostic_only_and_uses_cutover_candidate():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v29_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v29_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)

    assert wrapper.runner.DIAGNOSTIC_ONLY is True
    assert wrapper.runner.CANDIDATE_MODE is ScientificCandidateMode.TARGET_STATE_CUTOVER_AGENT
