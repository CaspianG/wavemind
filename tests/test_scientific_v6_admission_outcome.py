from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v6_failed_admission_is_retained_and_does_not_open_more_held_out_data():
    payload = json.loads(
        (ROOT / "benchmarks" / "scientific_v6_admission_outcome.json").read_text(
            encoding="utf-8"
        )
    )

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_admission_v6"
    assert payload["failed_gate"] == (
        "memoryagentbench_validation_positive_uplift_lcb"
    )
    validation = payload["memoryagentbench_validation"]
    assert validation["paired_effect_values"] == [0.0] * 5
    assert validation["ci95_lower"] == 0.0
    assert validation["intervention_coverage"] == 1.0
    assert validation["production_case_count"] == 0
    assert validation["promoted_memory_ids"] == []
    for evidence in (validation["artifact"], validation["raw"]):
        path = ROOT / evidence["path"]
        assert path.stat().st_size == evidence["bytes"]
        assert file_sha256(path) == evidence["sha256"]
    assert payload["unopened_held_out_evidence"] == {
        "memops_validation_executed": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_run_executed": False,
        "reason": (
            "The preregistered decision rule already failed. Opening more held-out "
            "evidence cannot rescue v6 and would only spend independent evidence."
        ),
    }

