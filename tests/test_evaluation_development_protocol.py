from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from wavemind.evaluation_development_protocol import (
    ERROR_TAXONOMY,
    build_evaluation_development_protocol,
    validate_evaluation_development_protocol,
)
from wavemind.evidence import attach_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks/evaluation_dataset_manifest_v1.json"
SPLIT = ROOT / "benchmarks/evaluation_split_manifest_results.json"
JUDGES = ROOT / "benchmarks/evaluation_judge_policy_results.json"


def _build() -> dict:
    return build_evaluation_development_protocol(
        project_root=ROOT,
        dataset_manifest_path=DATASET,
        split_manifest_path=SPLIT,
        judge_policy_path=JUDGES,
    )


def _resign(payload: dict) -> dict:
    payload.pop("integrity", None)
    return attach_artifact_integrity(payload)


def test_development_protocol_freezes_only_development_units():
    payload = _build()
    assert validate_evaluation_development_protocol(
        payload,
        project_root=ROOT,
        dataset_manifest_path=DATASET,
        split_manifest_path=SPLIT,
        judge_policy_path=JUDGES,
    ) == []
    assert payload["heldout_access"] == "forbidden"
    units = payload["bounded_sample"]["units"]
    assert len(units) == 40
    counts = Counter((unit["dataset"], unit["stratum"]) for unit in units)
    assert all(
        count == 5
        for (dataset, _), count in counts.items()
        if dataset in {"state-bench", "memops"}
    )


def test_protocol_has_complete_taxonomy_and_two_candidate_stop_rule():
    payload = _build()
    assert payload["error_taxonomy"] == list(ERROR_TAXONOMY)
    assert payload["bounded_go_no_go"]["candidate_limit_per_hypothesis"] == 2
    assert (
        payload["run_requirements"]["product_tuning_before_baseline_error_taxonomy"]
        is False
    )
    memops = next(
        family for family in payload["families"] if family["id"] == "memops-lifecycle"
    )
    assert memops["primary_metric"] == "operation_state_transition"
    assert "not_stale_leakage" in memops["primary_metric_definition"]["pass_when_all"]


def test_protocol_rejects_heldout_access_even_when_resigned():
    payload = _build()
    payload["heldout_access"] = "allowed"
    errors = validate_evaluation_development_protocol(
        _resign(payload),
        project_root=ROOT,
        dataset_manifest_path=DATASET,
        split_manifest_path=SPLIT,
        judge_policy_path=JUDGES,
    )
    assert "development protocol does not forbid held-out access" in errors


def test_protocol_rejects_sample_replacement_and_threshold_drift():
    payload = _build()
    payload["bounded_sample"]["units"][0]["unit_id"] = "final:injected"
    payload["bounded_go_no_go"]["candidate_limit_per_hypothesis"] = 3
    errors = validate_evaluation_development_protocol(
        _resign(payload),
        project_root=ROOT,
        dataset_manifest_path=DATASET,
        split_manifest_path=SPLIT,
        judge_policy_path=JUDGES,
    )
    assert "development protocol bounded selection changed" in errors
    assert "development protocol candidate stop rule changed" in errors


def test_protocol_rejects_dependency_substitution(tmp_path):
    payload = _build()
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    dataset["integrity"]["payload_sha256"] = "0" * 64
    changed = tmp_path / "dataset.json"
    changed.write_text(json.dumps(dataset), encoding="utf-8")
    errors = validate_evaluation_development_protocol(
        payload,
        project_root=ROOT,
        dataset_manifest_path=changed,
        split_manifest_path=SPLIT,
        judge_policy_path=JUDGES,
    )
    assert any("dataset_manifest_payload_sha256" in error for error in errors)


def test_protocol_declares_state_lane_ineligible_until_agent_is_pinned():
    payload = _build()
    state = next(
        family
        for family in payload["families"]
        if family["id"] == "state-bench-agent-learning"
    )
    assert state["quality_claim_eligible"] is False
    assert "open-weight tool-calling agent profile" in state["blocked_until"]
