from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v31_longmem_torchvision_continuation_plan.json"


def test_torchvision_continuation_is_preregistered_before_outcomes():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "preregistered_torchvision_continuation_before_outcome"
    assert payload["logical_full_run_count"] == 1
    assert payload["failure_evidence"]["outcome_scores_opened"] is False
    assert payload["failure_evidence"]["scientific_gate_evaluated"] is False
    assert payload["processor_dependency_probe"]["answer_or_gold_read"] is False
    assert payload["processor_dependency_probe"]["model_calls_made"] == 0
    assert payload["processor_dependency_probe"]["scores_opened"] is False
    assert payload["processor_dependency_probe"]["private_gib_after_processor"] < 3.0


def test_torchvision_continuation_changes_only_declared_environment_dependency():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    environment = payload["environment_change"]
    frozen = payload["frozen_invariants"]

    assert environment["torch_before"] == "2.13.0+cpu"
    assert environment["torch_after"] == "2.13.0+cpu"
    assert environment["torch_unchanged"] is True
    assert environment["torchvision_before"] is None
    assert environment["torchvision_after"] == "0.28.0+cpu"
    assert environment["cuda_after"] is None
    assert frozen["candidate_source_sha"] == "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    assert frozen["prompts_unchanged"] is True
    assert frozen["models_unchanged"] is True
    assert frozen["thresholds_unchanged"] is True
    assert frozen["question_order_unchanged"] is True
    assert frozen["scoring_unchanged"] is True


def test_torchvision_continuation_binds_exact_harness_and_single_logical_run():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    harness = payload["exact_harness"]
    execution = payload["continuation_execution"]

    assert harness["required_commit"] == "404c6b127e580d8531176d9e79cd1782bbacc79b"
    assert harness["harness_change_after_streaming_plan"] is False
    for record in harness["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{harness['required_commit']}:{record['path']}"], cwd=ROOT
        )
        assert len(content) == record["bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
    assert execution["logical_full_run_count_must_remain"] == 1
    assert execution["retained_partial_count_before_continuation"] == 4
    assert execution["fresh_scientific_run_forbidden"] is True
    assert execution["memory_monitoring_required"] is True
