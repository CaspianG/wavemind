from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from wavemind.scientific_runtime import ScientificCandidateMode


ROOT = Path(__file__).resolve().parents[1]


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "test_scientific_memops_v30_wrapper",
        ROOT / "benchmarks" / "scientific_memops_v30_opened_diagnostic.py",
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wrapper
    spec.loader.exec_module(wrapper)
    return wrapper


def test_v30_routes_only_trajectory_to_session_level_path():
    wrapper = _load_wrapper()

    assert wrapper.runner._candidate_mode_for_entry(
        {"operation_type": "TrajectoryOps"}
    ) is ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT
    for operation_type in ("Forget", "Reflect", "Remember", "Update"):
        assert wrapper.runner._candidate_mode_for_entry(
            {"operation_type": operation_type}
        ) is ScientificCandidateMode.TARGET_STATE_CUTOVER_AGENT


def test_v30_wrapper_is_diagnostic_only_and_gold_blind():
    wrapper = _load_wrapper()

    assert wrapper.runner.DIAGNOSTIC_ONLY is True
    assert set(wrapper.runner.CANDIDATE_MODE_BY_OPERATION) == {"TrajectoryOps"}
