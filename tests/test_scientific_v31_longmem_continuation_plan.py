from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_continuation_plan.json"


def test_v31_longmem_continuation_is_preregistered_without_outcomes():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == (
        "preregistered_infrastructure_continuation_before_outcome"
    )
    assert payload["logical_full_run_count"] == 1
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    failure = payload["infrastructure_failure"]
    assert failure["outcome_scores_opened"] is False
    assert failure["scientific_gate_evaluated"] is False
    for key in ("original_admission_plan", "infrastructure_failure"):
        record = payload[key]
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]


def test_v31_longmem_continuation_changes_only_synchronization_adapter():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    change = payload["harness_change"]

    assert change["original_commit"] == (
        "8d5052b94dea2cdc2db020208800577e3267ab3c"
    )
    assert change["fixed_commit"] == (
        "303d06138fd205a36ea15473c13d0aa71fe4b150"
    )
    assert change["changed_file_count"] == 1
    assert change["changed_frozen_harness_files"] == [
        "benchmarks/scientific_longmemeval_v2_backend_v31.py"
    ]
    for record in change["all_fixed_harness_files"]:
        content = subprocess.check_output(
            ["git", "show", f"{change['fixed_commit']}:{record['path']}"], cwd=ROOT
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_v31_longmem_continuation_preserves_frozen_semantics():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    invariants = payload["semantic_invariants"]
    execution = payload["continuation_execution"]

    assert invariants["question_count"] == 451
    assert invariants["tier"] == "small"
    assert invariants["model"] == "mistral:7b"
    assert invariants["evaluator_model"] == "mistral:7b"
    assert invariants["temperature"] == 0.0
    assert invariants["shuffle_questions_seed"] == 17
    assert invariants["prompt_build_max_workers"] == 4
    assert invariants["reader_max_concurrent_requests"] == 4
    assert invariants["prompts_unchanged"] is True
    assert invariants["thresholds_unchanged"] is True
    assert execution["same_marker_required"] is True
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["fresh_scientific_run_forbidden"] is True
    assert execution["post_outcome_candidate_change_forbidden"] is True
