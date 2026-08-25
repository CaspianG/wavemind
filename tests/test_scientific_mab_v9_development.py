from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "benchmarks" / "scientific_mab_v9_development.py"
    spec = importlib.util.spec_from_file_location("scientific_mab_v9_development", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v9_mab_gate_units_are_fresh_development_and_preregistered():
    module = _module()
    manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json").read_text(
            encoding="utf-8"
        )
    )
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v9.json").read_text(
            encoding="utf-8"
        )
    )
    previous_ids: set[str] = set()
    for version in (7, 8):
        previous = json.loads(
            (ROOT / "benchmarks" / f"scientific_memory_protocol_v{version}.json").read_text(
                encoding="utf-8"
            )
        )
        previous_ids.update(
            previous["frozen_development_gate"]["memoryagentbench_unit_ids"]
        )
    by_id = {unit["unit_id"]: unit for unit in manifest["units"]}
    units = [by_id[unit_id] for unit_id in module.GATE_UNIT_IDS]
    previous_fingerprints = {
        by_id[unit_id]["context_sha256"]
        for unit_id in previous_ids
        if unit_id in by_id
    }

    assert list(module.GATE_UNIT_IDS) == protocol["frozen_development_gate"][
        "memoryagentbench_unit_ids"
    ]
    assert len(units) == 5
    assert all(unit["split"] == "development" for unit in units)
    assert len({unit["context_sha256"] for unit in units}) == 5
    assert {unit["family"] for unit in units} == {"Long_Range_Understanding"}
    assert {unit["context_sha256"] for unit in units}.isdisjoint(
        previous_fingerprints
    )
    assert protocol["metric_governance"]["primary_metric"] == "exact_match"
