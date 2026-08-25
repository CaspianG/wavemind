from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name).read_text(encoding="utf-8"))


def test_v16_protocol_binds_positive_diagnostic_and_fresh_full_subjects():
    payload = _load("scientific_memory_protocol_v16.json")
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest() == digest

    for key in ("immutable_v15_evidence", "opened_diagnostic_evidence"):
        record = payload[key]
        path = ROOT / record["outcome_path"]
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert validate_artifact_integrity(artifact) == []
        assert file_sha256(path) == record["outcome_file_sha256"]
    assert payload["opened_diagnostic_evidence"]["official_gate_decision"] is False

    v15 = _load("scientific_memory_protocol_v15.json")
    old_gate = dict(v15["frozen_development_gate"])
    new_gate = dict(payload["frozen_development_gate"])
    old_families = old_gate.pop("families")
    new_families = new_gate.pop("families")
    assert new_gate == old_gate
    assert new_families["memoryagentbench_summarization"]["unit_ids"] == (
        old_families["memoryagentbench_summarization"]["unit_ids"]
    )
    assert payload["immutable_v15_evidence"]["mab_units_were_opened"] is False

    old_subjects = set(old_families["memops_longitudinal_operation"]["subjects"])
    subjects = new_families["memops_longitudinal_operation"]["subjects"]
    assert len(subjects) == 5
    assert old_subjects.isdisjoint(subjects)
    manifest = _load("evaluation_split_manifest_results.json")
    per_subject: dict[str, list[dict]] = {subject: [] for subject in subjects}
    for unit in manifest["units"]:
        if unit.get("subject_id") in per_subject:
            per_subject[unit["subject_id"]].append(unit)
    assert all(len(units) == 5 for units in per_subject.values())
    assert all(
        unit["split"] == "development"
        for units in per_subject.values()
        for unit in units
    )


def test_v16_retains_strict_gate_and_gold_free_state_selection_contract():
    payload = _load("scientific_memory_protocol_v16.json")
    gate = payload["frozen_development_gate"]
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    assert gate["stop_on_first_failed_required_run"] is True
    assert payload["frozen_parameters"]["memops_question_selection"] == (
        "state-verification-v3"
    )
    assert "gold" in payload["candidate"]["routing_inputs"]
    assert "forbidden" in payload["candidate"]["routing_inputs"]
