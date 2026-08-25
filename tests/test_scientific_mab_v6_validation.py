from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "benchmarks" / "scientific_mab_v6_validation.py"
    spec = importlib.util.spec_from_file_location("scientific_mab_v6_validation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_mab_validation_units_are_independent_and_untouched():
    module = _module()
    manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json").read_text(
            encoding="utf-8"
        )
    )
    units = [
        unit
        for unit in manifest["units"]
        if unit["unit_id"] in module.VALIDATION_UNIT_IDS
    ]

    assert len(units) == 5
    assert all(unit["split"] == "validation" for unit in units)
    assert len({unit["context_sha256"] for unit in units}) == 5
    assert {unit["family"] for unit in units} == {
        "Accurate_Retrieval",
        "Conflict_Resolution",
        "Long_Range_Understanding",
    }
