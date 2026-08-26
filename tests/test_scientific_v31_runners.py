from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from wavemind.scientific_runtime import ScientificCandidateMode


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_v31_memops_runner_matches_preregistered_operation_router():
    wrapper = _load(
        "test_scientific_memops_v31_wrapper",
        "benchmarks/scientific_memops_v31_development.py",
    )

    assert wrapper.runner.DIAGNOSTIC_ONLY is False
    assert wrapper.runner.CANDIDATE_MODE is ScientificCandidateMode.TARGET_STATE_CUTOVER_AGENT
    assert wrapper.runner.CANDIDATE_MODE_BY_OPERATION == {
        "TrajectoryOps": ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT
    }
    assert wrapper.runner.QUESTION_SELECTION == "operation-adaptive-v7"


def test_v31_mab_runner_keeps_frozen_task_aware_path():
    wrapper = _load(
        "test_scientific_mab_v31_wrapper",
        "benchmarks/scientific_mab_v31_development.py",
    )

    assert (
        wrapper.runner.CANDIDATE_MODE
        is ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    )
    assert wrapper.runner.REQUIRED_SOURCE == "infbench_sum_eng_shots2"
