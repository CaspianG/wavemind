from __future__ import annotations

import copy
from pathlib import Path

from wavemind.scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v1.json"


def test_frozen_scientific_protocol_is_current_and_fail_closed():
    protocol = load_scientific_protocol(PROTOCOL_PATH)

    assert validate_scientific_protocol(protocol, project_root=ROOT) == []
    assert protocol["baseline_source_sha"] == "c30205ed389057bc695488655a3f8650ba8e5277"
    assert protocol["held_out_policy"]["opened_at_preregistration"] is False
    assert protocol["held_out_policy"]["full_longmemeval_v2_run_count_at_preregistration"] == 0
    assert "failed_experiment" in protocol["terminal_rule"]


def test_protocol_rejects_threshold_relaxation_and_post_hoc_candidate():
    protocol = load_scientific_protocol(PROTOCOL_PATH)
    changed = copy.deepcopy(protocol)
    changed["admission_gates"]["stale_or_contradiction_error_rate_maximum"] = 0.10
    changed["preregistered_candidates"].append(
        {"id": "post-hoc-candidate", "frozen": False}
    )

    errors = validate_scientific_protocol(changed, project_root=ROOT)

    assert "preregistered candidate order or identity changed" in errors
    assert any("stale_or_contradiction" in error for error in errors)
    assert "protocol digest mismatch" in errors


def test_protocol_preserves_real_competitors_and_one_shot_longmemeval():
    protocol = load_scientific_protocol(PROTOCOL_PATH)
    baselines = {row["id"]: row for row in protocol["baselines"]}
    longmem = next(
        row
        for row in protocol["evaluation"]["official_benchmark_families"]
        if row["id"] == "longmemeval-v2"
    )

    assert "local imitation forbidden" in baselines["mem0-oss"]["implementation"]
    assert "renamed local imitation forbidden" in baselines["langgraph"]["implementation"]
    assert longmem["maximum_full_runs"] == 1
    assert longmem["full_run_allowed_after_development_gate"] is True
