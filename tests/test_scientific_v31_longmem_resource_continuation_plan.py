from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_resource_continuation_plan.json"


def test_v31_resource_continuation_is_bound_before_outcome():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_resource_continuation_before_outcome"
    assert payload["logical_full_run_count"] == 1
    assert payload["oom_failure"]["outcome_scores_opened"] is False
    assert payload["oom_failure"]["scientific_gate_evaluated"] is False
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )


def test_v31_resource_continuation_changes_only_v31_backend_wrapper():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    change = payload["harness_change"]

    assert change["previous_commit"] == (
        "303d06138fd205a36ea15473c13d0aa71fe4b150"
    )
    assert change["resource_safe_commit"] == (
        "627f7b054229f1f33f04fe35464b4fd77add65ee"
    )
    assert change["changed_file_count"] == 1
    assert change["changed_frozen_harness_files"] == [
        "benchmarks/scientific_longmemeval_v2_backend_v31.py"
    ]
    for record in change["all_resource_safe_harness_files"]:
        content = subprocess.check_output(
            ["git", "show", f"{change['resource_safe_commit']}:{record['path']}"],
            cwd=ROOT,
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_v31_resource_continuation_preserves_scientific_semantics():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = payload["resource_safety_contract"]
    execution = payload["continuation_execution"]

    assert contract["official_prompt_build_max_workers"] == 4
    assert contract["maximum_concurrent_shared_candidate_queries"] == 1
    assert contract["query_results_unchanged"] is True
    assert contract["prompts_unchanged"] is True
    assert contract["token_counts_unchanged"] is True
    assert contract["reader_and_evaluator_models_unchanged"] is True
    assert contract["scoring_unchanged"] is True
    assert contract["per_worker_metadata_is_thread_local"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["third_partial_must_be_retained"] is True
    assert execution["fresh_scientific_run_forbidden"] is True
