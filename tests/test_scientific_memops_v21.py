from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "test_scientific_memops_v21_base",
    ROOT / "benchmarks" / "scientific_memops_v10_development.py",
)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


def test_v21_selector_prioritizes_discrimination_then_trajectory():
    previous = runner.QUESTION_SELECTION
    runner.QUESTION_SELECTION = "causal-discrimination-v6"
    try:
        entries = [
            {"evaluation_type": "OperationTrace", "question_id": "q1"},
            {"evaluation_type": "StateTrajectory", "question_id": "q3"},
            {"evaluation_type": "CandidateDisambiguation", "question_id": "q4"},
        ]
        assert runner._select_entries(entries)[0]["question_id"] == "q4"
        assert runner._select_entries(entries[:2])[0]["question_id"] == "q3"
    finally:
        runner.QUESTION_SELECTION = previous


def test_v21_retrieval_query_includes_official_options_without_gold():
    previous = runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS
    runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = True
    try:
        entry = {
            "question": "Which value is current?",
            "evaluation_type": "CandidateDisambiguation",
            "candidate_options": ["old", "current", "tentative"],
            "expected_answer": "current",
        }
        query = runner._retrieval_query(entry)
        assert query == (
            "Which value is current?\n"
            "Candidate options: old | current | tentative"
        )
        assert "expected_answer" not in query
    finally:
        runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = previous


def test_v21_retrieval_query_does_not_change_other_question_types():
    previous = runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS
    runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = True
    try:
        entry = {
            "question": "Summarize the sequence.",
            "evaluation_type": "StateTrajectory",
            "candidate_options": ["unused"],
        }
        assert runner._retrieval_query(entry) == entry["question"]
    finally:
        runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = previous


def test_v22_configuration_keeps_query_grounding_out_of_blind_sequence_mode():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v22_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v22_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)
    assert wrapper.runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS is True
    assert wrapper.runner.CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE is False
    assert (
        wrapper.runner.CANDIDATE_DISAMBIGUATION_OPERATION_ONLY_SEQUENCE_COVERAGE
        is False
    )
    assert wrapper.runner.TRAJECTORY_SEQUENCE_COVERAGE is True


def test_v23_configuration_uses_targeted_application_without_blind_coverage():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v23_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v23_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)
    assert wrapper.runner.QUESTION_SELECTION == "causal-application-v2"
    assert wrapper.runner.TRAJECTORY_SEQUENCE_COVERAGE is False
    assert wrapper.runner.UPDATE_SEQUENCE_COVERAGE is False
    assert wrapper.runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS is False


def test_v26_selector_routes_by_operation_type_without_gold_fields():
    previous = runner.QUESTION_SELECTION
    runner.QUESTION_SELECTION = "operation-adaptive-v7"
    try:
        base = [
            {"operation_type": "Forget", "evaluation_type": "OperationTrace", "question_id": "q2"},
            {
                "operation_type": "Forget",
                "evaluation_type": "CandidateDisambiguation",
                "question_id": "q8",
            },
            {
                "operation_type": "Forget",
                "evaluation_type": "OperationApplication",
                "question_id": "q10",
            },
        ]
        assert runner._select_entries(base)[0]["question_id"] == "q8"
        update = [{**entry, "operation_type": "Update"} for entry in base]
        assert runner._select_entries(update)[0]["question_id"] == "q10"
        trajectory = [{**entry, "operation_type": "TrajectoryOps"} for entry in base]
        assert runner._select_entries(trajectory)[0]["question_id"] == "q2"
    finally:
        runner.QUESTION_SELECTION = previous


def test_v26_configuration_separates_targeted_and_sequence_queries():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v26_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v26_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)
    assert wrapper.runner.QUESTION_SELECTION == "operation-adaptive-v7"
    assert wrapper.runner.OPERATION_TRACE_SEQUENCE_COVERAGE is True
    assert wrapper.runner.OPERATION_TRACE_OPERATION_ONLY_SEQUENCE_COVERAGE is True
    assert wrapper.runner.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS is True
    assert wrapper.runner.CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE is False
