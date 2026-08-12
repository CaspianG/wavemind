from __future__ import annotations

import copy
import json
from pathlib import Path

from wavemind.evaluation_contracts import backend_query_view, validate_dataset_manifest
from wavemind.evaluation_validity_admission import (
    EXPECTED_ROWS,
    run_evaluation_validity_admission,
)
from wavemind.evidence import attach_artifact_integrity
from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
DATASET_MANIFEST = ROOT / "benchmarks/evaluation_dataset_manifest_v1.json"


def _manifest() -> dict:
    return json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))


def _resign(payload: dict) -> dict:
    payload.pop("integrity", None)
    return attach_artifact_integrity(payload)


def test_dataset_manifest_has_pinned_sources_and_native_task_semantics():
    assert validate_dataset_manifest(_manifest()) == []


def test_salvage_manifest_is_integrity_protected_and_keeps_failed_lane_historical():
    payload = json.loads(
        (ROOT / "benchmarks/evaluation_salvage_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_artifact_integrity(payload) == []
    assert payload["heldout_status"] == "not_opened"
    assert any(
        item["component"] == "bounded_candidate_2"
        and item["decision"] == "preserve_failed_evidence"
        for item in payload["historical_only"]
    )


def test_long_range_task_cannot_be_coerced_into_retrieval():
    payload = copy.deepcopy(_manifest())
    mapping = next(
        item
        for item in payload["task_mappings"]
        if item["id"] == "memory-agent-bench.long-range-understanding"
    )
    mapping["layer"] = "retrieval"
    mapping["generated_answer"] = False
    errors = validate_dataset_manifest(_resign(payload))
    assert "MemoryAgentBench long-range task was coerced into retrieval" in errors


def test_dataset_manifest_rejects_wrong_revision_and_tampering():
    payload = copy.deepcopy(_manifest())
    payload["sources"][0]["revision"] = "main"
    errors = validate_dataset_manifest(payload)
    assert "artifact payload digest mismatch" in errors
    assert any("not an exact SHA" in error for error in errors)


def test_backend_query_view_strips_gold_and_evaluator_metadata():
    payload = _manifest()
    case = {
        "query": "What is current?",
        "namespace": "tenant:a",
        "gold_answer": "secret",
        "gold_evidence": ["secret"],
        "question_type": "update",
        "case_id": "row-1",
        "split": "final",
    }
    view = backend_query_view(case, payload["backend_query_contract"])
    assert view == {"query": "What is current?", "namespace": "tenant:a"}


def test_backend_contract_rejects_forbidden_field_in_allowlist():
    payload = _manifest()
    contract = copy.deepcopy(payload["backend_query_contract"])
    contract["allowed_fields"].append("gold_answer")
    try:
        backend_query_view({"gold_answer": "secret"}, contract)
    except ValueError as exc:
        assert "exposes a forbidden field" in str(exc)
    else:
        raise AssertionError("forbidden backend field was accepted")


def test_initial_admission_is_fail_closed_with_only_contract_rows_implemented():
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
    )
    rows = {row["id"]: row for row in report["rows"]}
    assert tuple(row["id"] for row in report["rows"]) == EXPECTED_ROWS
    assert report["status"] == "blocked"
    assert report["admitted"] is False
    assert rows["dataset-provenance"]["status"] == "implemented"
    assert rows["native-metric-mapping"]["status"] == "implemented"
    assert rows["multiple-comparison-policy"]["status"] == "implemented"
    assert rows["backend-blinding"]["status"] == "implemented"
    assert rows["exact-sha-integrity"]["status"] == "implemented"
    assert rows["positive-controls"]["status"] == "blocked"
    assert rows["safety-admissions-preserved"]["status"] == "blocked"


def test_admission_rejects_wrong_expected_source_sha():
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        expected_source_sha="0" * 40,
    )
    row = next(item for item in report["rows"] if item["id"] == "exact-sha-integrity")
    assert row["status"] == "blocked"


def test_missing_control_artifacts_cannot_be_inferred_from_protocol():
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
    )
    blocked = {row["id"] for row in report["rows"] if row["status"] == "blocked"}
    assert {
        "split-isolation",
        "positive-controls",
        "negative-controls",
        "control-ordering",
        "metric-range",
        "power-and-mde",
        "paired-clustered-statistics",
        "judge-calibration",
        "deterministic-verdict",
        "per-case-completeness",
        "safety-admissions-preserved",
    }.issubset(blocked)
