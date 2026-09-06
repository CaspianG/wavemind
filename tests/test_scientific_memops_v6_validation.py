from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MEMOPS = ROOT.parents[1] / "scientific-evidence" / "upstreams" / "memops"


def _module():
    path = ROOT / "benchmarks" / "scientific_memops_v6_validation.py"
    spec = importlib.util.spec_from_file_location(
        "scientific_memops_v6_validation", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not MEMOPS.is_dir(),
    reason="official MemOps upstream is not included in this repository",
)
def test_frozen_memops_validation_subjects_and_operation_matrix_are_untouched():
    module = _module()
    manifest = json.loads(
        (ROOT / "benchmarks" / "evaluation_split_manifest_results.json").read_text(
            encoding="utf-8"
        )
    )
    units = [
        unit
        for unit in manifest["units"]
        if unit.get("dataset") == "memops"
        and unit.get("subject_id") in module.VALIDATION_SUBJECTS
    ]
    adjacent = MEMOPS / "generated_result" / "2-evidence_conversation"
    longitudinal = (
        MEMOPS / "generated_result" / "4-inject_evidence_with_distractors"
    )
    adjacent_names = {
        path.name
        for subject in module.VALIDATION_SUBJECTS
        for path in adjacent.glob(f"{subject}_*.json")
    }
    longitudinal_names = {
        path.name
        for subject in module.VALIDATION_SUBJECTS
        for path in longitudinal.glob(f"{subject}_*.json")
    }

    assert {unit["subject_id"] for unit in units} == set(
        module.VALIDATION_SUBJECTS
    )
    assert all(unit["split"] == "validation" for unit in units)
    assert adjacent_names == longitudinal_names
    assert len(adjacent_names) == 23
