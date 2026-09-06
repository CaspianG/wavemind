from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "benchmarks" / "scientific_mab_v7_development.py"
    spec = importlib.util.spec_from_file_location("scientific_mab_v7_development", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v7_mab_gate_units_are_development_independent_and_preregistered():
    module = _module()
    manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json").read_text(
            encoding="utf-8"
        )
    )
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v7.json").read_text(
            encoding="utf-8"
        )
    )
    units = [
        unit for unit in manifest["units"] if unit["unit_id"] in module.GATE_UNIT_IDS
    ]

    assert list(module.GATE_UNIT_IDS) == protocol["frozen_development_gate"][
        "memoryagentbench_unit_ids"
    ]
    assert len(units) == 11
    assert all(unit["split"] == "development" for unit in units)
    assert len({unit["context_sha256"] for unit in units}) == 11
    assert {unit["family"] for unit in units} == {
        "Accurate_Retrieval",
        "Long_Range_Understanding",
        "Test_Time_Learning",
    }
