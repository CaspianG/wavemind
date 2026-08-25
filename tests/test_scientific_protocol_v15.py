from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name).read_text(encoding="utf-8"))


def test_v15_protocol_preserves_v14_and_binds_only_fresh_development_units():
    payload = _load("scientific_memory_protocol_v15.json")
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest() == digest

    immutable = payload["immutable_v14_evidence"]
    outcome_path = ROOT / immutable["outcome_path"]
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(outcome) == []
    assert file_sha256(outcome_path) == immutable["outcome_file_sha256"]
    assert immutable["official_gate_pass"] is False
    assert immutable["opened_units_may_be_reused_for_official_gate"] is False

    v14 = _load("scientific_memory_protocol_v14.json")
    assert payload["candidate"]["memory_algorithm"] == v14["candidate"]["memory_algorithm"]
    assert payload["frozen_parameters"] == v14["frozen_parameters"]
    old_gate = dict(v14["frozen_development_gate"])
    new_gate = dict(payload["frozen_development_gate"])
    old_families = old_gate.pop("families")
    new_families = new_gate.pop("families")
    assert new_gate == old_gate

    manifest = _load("memoryagentbench_split_manifest_results.json")
    units = {unit["unit_id"]: unit for unit in manifest["units"]}
    old_ids = set(old_families["memoryagentbench_summarization"]["unit_ids"])
    ids = new_families["memoryagentbench_summarization"]["unit_ids"]
    assert len(ids) == 10
    assert old_ids.isdisjoint(ids)
    assert all(units[unit_id]["split"] == "development" for unit_id in ids)
    old_hashes = {units[unit_id]["context_sha256"] for unit_id in old_ids}
    new_hashes = {units[unit_id]["context_sha256"] for unit_id in ids}
    assert len(new_hashes) == 10
    assert old_hashes.isdisjoint(new_hashes)

    split_manifest = _load("evaluation_split_manifest_results.json")
    subject_splits: dict[str, set[str]] = {}
    for unit in split_manifest["units"]:
        subject_id = unit.get("subject_id")
        if subject_id is not None:
            subject_splits.setdefault(subject_id, set()).add(unit["split"])
    old_subjects = set(old_families["memops_longitudinal_operation"]["subjects"])
    subjects = new_families["memops_longitudinal_operation"]["subjects"]
    assert len(subjects) == 5
    assert old_subjects.isdisjoint(subjects)
    assert all(subject_splits[subject] == {"development"} for subject in subjects)


def test_v15_harness_repair_is_the_preregistered_binding_only_change():
    payload = _load("scientific_memory_protocol_v15.json")
    repair = payload["harness_repair"]
    assert repair["candidate_algorithm_changed_from_v14"] is False
    assert repair["gate_thresholds_changed_from_v14"] is False
    assert repair["frozen_protocol_key"] == "minimum_independent_clusters_per_family"
