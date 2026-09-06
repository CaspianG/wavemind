from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_streaming_continuation_plan.json"


def test_v31_streaming_continuation_is_preregistered_before_outcome():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_streaming_continuation_before_outcome"
    assert payload["logical_full_run_count"] == 1
    assert payload["safety_abort"]["outcome_scores_opened"] is False
    assert payload["safety_abort"]["scientific_gate_evaluated"] is False
    assert payload["streaming_probe"]["query_kind"] == "synthetic_non_held_out"
    assert payload["streaming_probe"]["model_calls_made"] == 0
    assert payload["streaming_probe"]["scores_opened"] is False
    assert payload["streaming_probe"]["private_gib"] < 2.0
    assert payload["streaming_probe"]["chain_errors"] == []


def test_v31_streaming_continuation_changes_only_v31_backend_wrapper():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    change = payload["harness_change"]

    assert change["previous_commit"] == (
        "627f7b054229f1f33f04fe35464b4fd77add65ee"
    )
    assert change["streaming_commit"] == (
        "404c6b127e580d8531176d9e79cd1782bbacc79b"
    )
    assert change["changed_file_count"] == 1
    assert change["changed_frozen_harness_files"] == [
        "benchmarks/scientific_longmemeval_v2_backend_v31.py"
    ]
    for record in change["all_streaming_harness_files"]:
        content = subprocess.check_output(
            ["git", "show", f"{change['streaming_commit']}:{record['path']}"], cwd=ROOT
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_v31_streaming_continuation_preserves_exact_scientific_semantics():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = payload["semantic_equivalence_contract"]
    frozen = payload["frozen_invariants"]
    execution = payload["continuation_execution"]

    assert contract["query_token_intersections_identical"] is True
    assert contract["document_frequency_identical"] is True
    assert contract["lexical_weights_identical"] is True
    assert contract["ranking_tuples_identical"] is True
    assert contract["selection_relevance_reason_exactly_equal_in_tests"] is True
    assert contract["original_simultaneous_document_token_sets_minimum"] == 101
    assert contract["streaming_simultaneous_document_token_sets_maximum"] == 2
    assert frozen["official_prompt_build_max_workers"] == 4
    assert frozen["prompts_unchanged"] is True
    assert frozen["models_unchanged"] is True
    assert frozen["thresholds_unchanged"] is True
    assert frozen["scoring_unchanged"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["fresh_scientific_run_forbidden"] is True
