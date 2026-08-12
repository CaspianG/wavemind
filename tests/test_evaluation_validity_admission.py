from __future__ import annotations

import copy
import json
from pathlib import Path

from benchmarks.workspace_experience_operational_evidence import (
    OPERATIONAL_SOURCE_FILES,
    REQUIRED_CHECKS as WORKSPACE_OPERATIONAL_CHECKS,
    SCHEMA as WORKSPACE_OPERATIONAL_SCHEMA,
)
from wavemind.evaluation_contracts import backend_query_view, validate_dataset_manifest
from wavemind.evaluation_validity_admission import (
    EXPECTED_ROWS,
    run_evaluation_validity_admission,
)
from wavemind.evaluation_validity_controls import run_evaluation_validity_controls
from wavemind.evaluation_judges import build_evaluation_judge_policy
from wavemind.evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    repository_commit,
    validate_artifact_integrity,
)
from wavemind.safe_product_admission import (
    EXPECTED_CHECKS as SAFE_PRODUCT_CHECKS,
    SAFE_PRODUCT_SOURCE_FILES,
    SCHEMA as SAFE_PRODUCT_SCHEMA,
)
from wavemind.workspace_experience_admission import (
    evaluate_workspace_experience_admission_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET_MANIFEST = ROOT / "benchmarks/evaluation_dataset_manifest_v1.json"


def _manifest() -> dict:
    return json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))


def _resign(payload: dict) -> dict:
    payload.pop("integrity", None)
    return attach_artifact_integrity(payload)


def _write_current_safety_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    source_sha = repository_commit(ROOT)
    safe_product = attach_artifact_integrity(
        {
            "schema": SAFE_PRODUCT_SCHEMA,
            "status": "admitted",
            "admitted": True,
            "source_sha": source_sha,
            "summary": {
                "checks_passed": len(SAFE_PRODUCT_CHECKS),
                "checks_total": len(SAFE_PRODUCT_CHECKS),
            },
            "checks": [
                {"id": check_id, "status": "pass", "passed": True}
                for check_id in sorted(SAFE_PRODUCT_CHECKS)
            ],
            "source_manifest": build_source_manifest(ROOT, SAFE_PRODUCT_SOURCE_FILES),
            "claim_boundary": "test fixture",
        }
    )
    operational = attach_artifact_integrity(
        {
            "schema": WORKSPACE_OPERATIONAL_SCHEMA,
            "status": "admitted",
            "admitted": True,
            "source_sha": source_sha,
            "summary": {
                "checks_passed": len(WORKSPACE_OPERATIONAL_CHECKS),
                "checks_total": len(WORKSPACE_OPERATIONAL_CHECKS),
            },
            "checks": [
                {"id": check_id, "passed": True, "details": {}}
                for check_id in sorted(WORKSPACE_OPERATIONAL_CHECKS)
            ],
            "metrics": {
                "workspace_namespace_leakage": 0,
                "mandatory_event_capture": 1.0,
                "cross_client_citation_state_parity": 1.0,
                "packet_selection_p95_ms": 10.0,
                "packet_selection_p99_ms": 20.0,
            },
            "source_manifest": build_source_manifest(ROOT, OPERATIONAL_SOURCE_FILES),
            "claim_boundary": "test fixture",
        }
    )
    safe_path = tmp_path / "safe-product.json"
    operational_path = tmp_path / "workspace-operational.json"
    workspace_path = tmp_path / "workspace-experience.json"
    safe_path.write_text(json.dumps(safe_product), encoding="utf-8")
    operational_path.write_text(json.dumps(operational), encoding="utf-8")
    workspace = evaluate_workspace_experience_admission_matrix(
        root=ROOT,
        safe_product_path=safe_path,
        operational_evidence_path=operational_path,
    )
    workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
    return safe_path, workspace_path


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


def test_signed_current_control_evidence_closes_only_measured_rows(tmp_path):
    evidence = run_evaluation_validity_controls(project_root=ROOT)
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        validity_evidence_path=path,
    )
    rows = {row["id"]: row for row in report["rows"]}
    for row_id in (
        "positive-controls",
        "negative-controls",
        "control-ordering",
        "metric-range",
        "power-and-mde",
        "paired-clustered-statistics",
        "deterministic-verdict",
        "per-case-completeness",
    ):
        assert rows[row_id]["status"] == "implemented"
    assert rows["split-isolation"]["status"] == "blocked"
    assert rows["judge-calibration"]["status"] == "blocked"
    assert rows["safety-admissions-preserved"]["status"] == "blocked"


def test_tampered_or_wrong_sha_control_evidence_is_rejected(tmp_path):
    evidence = run_evaluation_validity_controls(project_root=ROOT)
    evidence["source_sha"] = "0" * 40
    path = tmp_path / "tampered-controls.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        validity_evidence_path=path,
    )
    rows = {row["id"]: row for row in report["rows"]}
    assert rows["positive-controls"]["status"] == "blocked"
    assert (
        "artifact payload digest mismatch"
        in rows["positive-controls"]["evidence"]["errors"]
    )
    assert (
        "validity evidence source SHA mismatch"
        in rows["positive-controls"]["evidence"]["errors"]
    )


def test_missing_split_evidence_stays_blocked_even_with_valid_controls(tmp_path):
    evidence = run_evaluation_validity_controls(project_root=ROOT)
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        validity_evidence_path=path,
    )
    row = next(item for item in report["rows"] if item["id"] == "split-isolation")
    assert row["status"] == "blocked"
    assert row["evidence"]["errors"] == [
        "evaluation split evidence artifact is missing"
    ]


def test_valid_judge_policy_closes_judge_row_without_claiming_excluded_lanes(tmp_path):
    judge = build_evaluation_judge_policy(project_root=ROOT)
    path = tmp_path / "judge.json"
    path.write_text(json.dumps(judge), encoding="utf-8")
    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        judge_evidence_path=path,
    )
    row = next(item for item in report["rows"] if item["id"] == "judge-calibration")
    assert row["status"] == "implemented"
    assert len(row["evidence"]["active_primary_scorers"]) == 2
    assert len(row["evidence"]["excluded_native_judge_lanes"]) >= 4


def test_exact_current_safety_artifacts_close_safety_row(tmp_path):
    safe_path, workspace_path = _write_current_safety_artifacts(tmp_path)

    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        safe_product_path=safe_path,
        workspace_experience_path=workspace_path,
    )

    row = next(
        item for item in report["rows"] if item["id"] == "safety-admissions-preserved"
    )
    assert row["status"] == "implemented"
    assert row["evidence"]["safe_product"]["errors"] == []
    assert row["evidence"]["workspace_experience"]["errors"] == []


def test_resigned_non_admitted_workspace_artifact_blocks_safety_row(tmp_path):
    safe_path, workspace_path = _write_current_safety_artifacts(tmp_path)
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    workspace["status"] = "blocked"
    workspace["admitted"] = False
    workspace_path.write_text(json.dumps(_resign(workspace)), encoding="utf-8")

    report = run_evaluation_validity_admission(
        project_root=ROOT,
        dataset_manifest_path=DATASET_MANIFEST,
        safe_product_path=safe_path,
        workspace_experience_path=workspace_path,
    )

    row = next(
        item for item in report["rows"] if item["id"] == "safety-admissions-preserved"
    )
    assert row["status"] == "blocked"
    assert (
        "workspace experience admission is not admitted"
        in row["evidence"]["workspace_experience"]["errors"]
    )
