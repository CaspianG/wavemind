from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name).read_text(encoding="utf-8"))


def test_v17_protocol_binds_failed_v16_positive_diagnostic_and_fresh_subjects():
    payload = _load("scientific_memory_protocol_v17.json")
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest() == digest
    for key in ("immutable_v16_evidence", "opened_diagnostic_evidence"):
        record = payload[key]
        path = ROOT / record["outcome_path"]
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert validate_artifact_integrity(artifact) == []
        assert file_sha256(path) == record["outcome_file_sha256"]
    assert payload["opened_diagnostic_evidence"]["official_gate_decision"] is False

    v16 = _load("scientific_memory_protocol_v16.json")
    old_gate = dict(v16["frozen_development_gate"])
    new_gate = dict(payload["frozen_development_gate"])
    old_families = old_gate.pop("families")
    new_families = new_gate.pop("families")
    assert new_gate == old_gate
    assert new_families["memoryagentbench_summarization"]["unit_ids"] == (
        old_families["memoryagentbench_summarization"]["unit_ids"]
    )
    assert payload["immutable_v16_evidence"]["mab_units_were_opened"] is False
    old_subjects = set(old_families["memops_longitudinal_operation"]["subjects"])
    subjects = new_families["memops_longitudinal_operation"]["subjects"]
    assert old_subjects.isdisjoint(subjects)
    manifest = _load("evaluation_split_manifest_results.json")
    selected = [unit for unit in manifest["units"] if unit.get("subject_id") in subjects]
    assert len(selected) == 25
    assert all(unit["split"] == "development" for unit in selected)
    assert all(sum(unit.get("subject_id") == subject for unit in selected) == 5 for subject in subjects)


def test_v17_keeps_gate_and_freezes_noop_and_trajectory_safety():
    payload = _load("scientific_memory_protocol_v17.json")
    gate = payload["frozen_development_gate"]
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    assert gate["required_reproducible_runs"] == 3
    assert gate["stop_on_first_failed_required_run"] is True
    parameters = payload["frozen_parameters"]
    assert parameters["causal_noop_fallback"] is True
    assert parameters["memops_trajectory_sequence_coverage"] is True
    assert parameters["memops_question_selection"] == "state-verification-v4"
