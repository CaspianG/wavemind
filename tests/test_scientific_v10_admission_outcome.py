from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
OUTCOME = ROOT / "benchmarks" / "scientific_v10_admission_outcome.json"


def test_v10_failed_admission_is_immutable_and_stops_later_final_arms():
    payload = json.loads(OUTCOME.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_admission_v10"
    assert payload["failed_gate"] == (
        "memoryagentbench_final_positive_uplift_lcb"
    )
    final = payload["memoryagentbench_final"]
    assert final["paired_effect_values"] == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert final["mean_difference"] == 0.4
    assert final["ci95_lower"] == 0.0
    assert final["intervention_coverage"] == 1.0
    assert final["production_case_count"] == 0
    assert final["promoted_memory_ids"] == []
    assert final["gate_checks"][
        "paired_cluster_bootstrap_ci_lower_strictly_positive"
    ] is False
    for evidence in (final["artifact"], final["raw"]):
        path = ROOT / evidence["path"]
        assert path.stat().st_size == evidence["bytes"]
        assert file_sha256(path) == evidence["sha256"]
    assert payload["unopened_held_out_evidence"] == {
        "memops_final_executed": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_run_executed": False,
        "reason": (
            "The preregistered MAB final gate failed. Opening later held-out arms "
            "cannot rescue v10 and would spend independent evidence."
        ),
    }
    assert payload["post_outcome_policy"][
        "mab_final_cases_may_be_used_for_future_tuning"
    ] is False
