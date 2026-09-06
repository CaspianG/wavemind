from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_judge_parser_continuation_plan.json"


def test_judge_parser_continuation_is_preregistered_before_comparison_aggregate():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_judge_parser_continuation_before_comparison_aggregate"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure_evidence"]["completed_candidate_arm_metric_opened"] is False
    assert payload["failure_evidence"]["failed_comparison_arm_aggregate_exists"] is False
    assert payload["failure_evidence"]["scientific_gate_evaluated"] is False


def test_judge_parser_continuation_changes_only_runner_and_binds_exact_files():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    change = payload["harness_change"]

    assert change["changed_frozen_harness_files"] == [
        "benchmarks/scientific_longmemeval_v2_run.py"
    ]
    for record in change["all_parser_harness_files"]:
        content = subprocess.check_output(
            ["git", "show", f"{change['parser_commit']}:{record['path']}"], cwd=ROOT
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_judge_parser_continuation_preserves_semantics_and_logical_run():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = payload["parser_equivalence_contract"]
    frozen = payload["frozen_invariants"]
    execution = payload["continuation_execution"]

    assert contract["existing_parser_always_attempted_first"] is True
    assert contract["fallback_only_after_value_error"] is True
    assert contract["returned_label_is_exact_leading_binary"] is True
    assert contract["reason_does_not_change_binary_score"] is True
    assert contract["ambiguous_unlabelled_invalid_label_empty_reason_text_still_raises"] is True
    assert frozen["answers_unchanged"] is True
    assert frozen["thresholds_unchanged"] is True
    assert frozen["binary_scoring_rule_unchanged"] is True
    assert frozen["gate_unchanged"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["retained_partial_count_before_continuation"] == 7
    assert execution["completed_candidate_web_arm_must_be_skipped"] is True
    assert execution["restart_first_incomplete_arm"] == "no_retrieval_web_small"
    assert execution["fresh_scientific_run_forbidden"] is True
