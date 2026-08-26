from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_2.json"


def _record_exists_or_is_retained(record: dict[str, object]) -> bool:
    direct = ROOT / str(record["path"])
    candidates = [direct]
    retained = (
        ROOT
        / "benchmarks"
        / "scientific_longmemeval_v31_final"
        / "retained_partials"
    )
    if retained.is_dir():
        candidates.extend(retained.rglob(direct.name))
    return any(
        path.is_file()
        and path.stat().st_size == record["bytes"]
        and file_sha256(path) == record["sha256"]
        for path in candidates
    )


def test_v31_longmem_second_failure_is_pre_outcome_and_preserved():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "infrastructure_failed_before_outcomes"
    assert payload["infrastructure_failure_sequence"] == 2
    assert payload["logical_full_run_count"] == 1
    assert payload["failure"]["cause_type"] == "ModuleNotFoundError"
    assert payload["failure"]["cause_message"] == "No module named 'PIL'"
    assert payload["failure"]["scientific_gate_evaluated"] is False
    state = payload["observed_state"]
    assert state["one_time_compilation_completed"] is True
    assert state["answers_generated"] is False
    assert state["outcome_scores_opened"] is False
    assert state["per_question_files"] == 0
    assert state["aggregated_metrics_files"] == 0
    for key in ("marker", "run_args", "console_log"):
        assert _record_exists_or_is_retained(state[key])


def test_v31_longmem_second_failure_allows_only_declared_dependency_install():
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    dependency = payload["official_dependency_evidence"]
    policy = payload["continuation_policy"]

    assert dependency["repository_sha"] == (
        "2cc8c540bdb87fe6761629b585e727e1c4704520"
    )
    assert dependency["dependency_name"] == "pillow"
    assert dependency["declared_by_official_repository"] is True
    assert dependency["module_available_at_failure"] is False
    assert policy["same_logical_run_required"] is True
    assert policy["harness_unchanged_required"] is True
    assert policy["candidate_unchanged_required"] is True
    assert policy["thresholds_unchanged_required"] is True
    assert policy["attempts_count_as_scientific_runs"] == 1
    assert "Pillow" in policy["permitted_environment_change"]
