from __future__ import annotations

from benchmarks import scientific_memops_v10_development as runner


def test_memory_dependence_v5_prefers_operation_trace_without_gold():
    entries = [
        {
            "question_id": "subject_q6",
            "evaluation_type": "StateTransition",
            "question": "state",
        },
        {
            "question_id": "subject_q2",
            "evaluation_type": "OperationTrace",
            "question": "trace",
        },
        {
            "question_id": "subject_q4",
            "evaluation_type": "TargetBinding",
            "question": "target",
        },
    ]
    previous = runner.QUESTION_SELECTION
    runner.QUESTION_SELECTION = "memory-dependence-v5"
    try:
        selected = runner._select_entries(entries)
    finally:
        runner.QUESTION_SELECTION = previous

    assert selected == [entries[1]]
