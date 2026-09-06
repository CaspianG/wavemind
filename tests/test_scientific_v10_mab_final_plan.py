from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import recorded_file_matches, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v10_mab_final_plan.json"


def test_v10_mab_final_plan_is_frozen_before_final_execution():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    expected_digest = payload.pop("plan_digest")
    actual_digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert actual_digest == expected_digest
    assert payload["status"] == "preregistered"
    assert payload["candidate"]["source_sha"] == (
        "47b68e366aab9ce07b659c61a51c81d634b3fff2"
    )
    assert payload["authorization_evidence"]["development_gate_status"] == (
        "passed_development_gate_v10"
    )
    outcome = json.loads(
        (ROOT / payload["authorization_evidence"]["development_outcome_path"])
        .read_text(encoding="utf-8")
    )
    assert validate_artifact_integrity(outcome) == []
    assert outcome["integrity"]["payload_sha256"] == payload[
        "authorization_evidence"
    ]["development_outcome_payload_sha256"]
    assert recorded_file_matches(
        ROOT / payload["authorization_evidence"]["development_outcome_path"],
        sha256=payload["authorization_evidence"]["development_outcome_file_sha256"],
    )
    assert recorded_file_matches(
        ROOT / payload["execution_harness"]["path"],
        sha256=payload["execution_harness"]["sha256"],
    )
    assert recorded_file_matches(
        ROOT / payload["protocol"]["path"],
        sha256=payload["protocol"]["file_sha256"],
    )
    assert recorded_file_matches(
        ROOT / payload["official_source"]["split_manifest_path"],
        sha256=payload["official_source"]["split_manifest_file_sha256"],
    )
    assert payload["frozen_sample"]["required_independent_clusters"] == 5
    assert len(payload["frozen_sample"]["unit_ids"]) == 5
    assert payload["frozen_gate"] == {
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than": 0.0,
        "mean_non_negative": True,
        "minimum_intervention_coverage": 0.8,
        "false_verified_promotions_maximum": 0,
        "production_case_count_maximum": 0,
        "raw_per_case_evidence_required": True,
    }
    assert payload["stage_order"]["stop_on_failure"] is True
    assert payload["held_out_state_at_preregistration"] == {
        "memoryagentbench_final_outcomes_opened": False,
        "memops_final_outcomes_opened": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_runs": 0,
    }
