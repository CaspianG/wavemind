from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_fallback_continuation_plan.json"


def test_fallback_continuation_is_preregistered_before_outcomes():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_fallback_streaming_continuation_before_outcome"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure_evidence"]["outcome_scores_opened"] is False
    assert payload["failure_evidence"]["scientific_gate_evaluated"] is False
    assert payload["fallback_probe"]["answer_or_gold_read"] is False
    assert payload["fallback_probe"]["model_calls_made"] == 0
    assert payload["fallback_probe"]["scores_opened"] is False
    assert payload["fallback_probe"]["maximum_recall_seconds"] < 30.0
    assert payload["fallback_probe"]["private_gib"] < 3.0


def test_fallback_continuation_changes_only_v31_wrapper():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    change = payload["harness_change"]
    assert change["previous_commit"] == "404c6b127e580d8531176d9e79cd1782bbacc79b"
    assert change["fallback_commit"] == "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
    assert change["changed_frozen_harness_files"] == [
        "benchmarks/scientific_longmemeval_v2_backend_v31.py"
    ]
    for record in change["all_fallback_harness_files"]:
        content = subprocess.check_output(
            ["git", "show", f"{change['fallback_commit']}:{record['path']}"], cwd=ROOT
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_fallback_continuation_preserves_scientific_semantics_and_run_count():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = payload["semantic_equivalence_contract"]
    frozen = payload["frozen_invariants"]
    execution = payload["continuation_execution"]
    assert contract["query_token_intersections_identical"] is True
    assert contract["document_frequency_identical"] is True
    assert contract["query_weights_identical"] is True
    assert contract["phrase_hits_identical"] is True
    assert contract["recency_scores_identical"] is True
    assert contract["ranking_tuples_identical"] is True
    assert contract["selection_relevance_reason_exactly_equal_in_tests"] is True
    assert contract["original_simultaneous_document_token_sets_minimum"] == 101
    assert contract["streaming_simultaneous_document_token_sets_maximum"] == 2
    assert frozen["prompts_unchanged"] is True
    assert frozen["models_unchanged"] is True
    assert frozen["thresholds_unchanged"] is True
    assert frozen["scoring_unchanged"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["retained_partial_count_before_continuation"] == 5
    assert execution["fresh_scientific_run_forbidden"] is True
