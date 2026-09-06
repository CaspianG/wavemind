from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import recorded_file_matches, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
OUTCOME = ROOT / "benchmarks" / "scientific_v19_admission_outcome.json"


def test_v19_admission_outcome_preserves_mab_pass_and_memops_failure():
    payload = json.loads(OUTCOME.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "failed_admission_v19"
    assert payload["candidate_source_sha"] == (
        "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
    )
    assert payload["development_gate"]["required_runs_passed"] == 6
    assert payload["memoryagentbench_final"]["status"] == "pass"
    assert payload["memoryagentbench_final"]["ci95_lower"] > 0.0
    assert payload["memops_final"]["status"] == "failed_final"
    assert payload["memops_final"]["mean_difference"] == 0.15
    assert payload["memops_final"]["ci95_lower"] == 0.0
    assert payload["memops_final"]["gate_checks"][
        "paired_subject_cluster_bootstrap_ci_lower_strictly_positive"
    ] is False
    assert payload["unopened_held_out_evidence"] == {
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_run_executed": False,
        "reason": payload["unopened_held_out_evidence"]["reason"],
    }
    assert payload["post_outcome_policy"]["repeat_v19_final_runs_forbidden"] is True
    assert payload["post_outcome_policy"]["thresholds_may_be_relaxed"] is False
    for arm in ("memoryagentbench_final", "memops_final"):
        for label in ("artifact", "raw"):
            record = payload[arm][label]
            path = ROOT / record["path"]
            assert recorded_file_matches(
                path, size=record["bytes"], sha256=record["sha256"]
            )
