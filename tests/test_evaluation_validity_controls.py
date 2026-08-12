from __future__ import annotations

import copy
import shutil
from pathlib import Path

from wavemind.evaluation_validity_controls import (
    CASES,
    SYSTEM_OUTPUTS,
    ControlCase,
    _evaluate_system,
    _score,
    run_evaluation_validity_controls,
)
from wavemind.evidence import validate_artifact_integrity, validate_source_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_control_scorers_keep_native_output_shapes():
    substring = ControlCase("a", "cluster", "substring_exact_match", "needle")
    top_five = ControlCase("b", "cluster", "recall_at_5", "item-7")
    structured = ControlCase("c", "cluster", "structured_exact", {"state": "ok"})
    assert _score(substring, "prefix needle suffix") == 1.0
    assert _score(top_five, ["item-1", "item-7"]) == 1.0
    assert _score(top_five, ["item-1"] * 5 + ["item-7"]) == 0.0
    assert _score(structured, {"state": "ok"}) == 1.0
    assert _score(structured, "ok") == 0.0


def test_controls_measure_expected_order_and_poison_isolation():
    report = run_evaluation_validity_controls(project_root=ROOT)
    assert report["positive_controls"]["passed"] is True
    assert report["negative_controls"]["passed"] is True
    assert report["control_ordering"]["passed"] is True
    assert report["deterministic_verdict"]["passed"] is True
    assert report["per_case_completeness"]["passed"] is True
    assert report["control_ordering"]["scores"] == {
        "oracle": 1.0,
        "strong_valid_baseline": 4 / 6,
        "random": 1 / 6,
        "no_memory": 0.0,
    }
    assert report["safety_probes"]["stale_poison"] == {
        "stale_leakage": 1.0,
        "namespace_leakage": 0.0,
        "deleted_evidence_resurfacing": 0.0,
    }
    assert validate_artifact_integrity(report) == []


def test_control_results_do_not_drop_failed_or_zero_score_rows():
    report = run_evaluation_validity_controls(project_root=ROOT)
    rows = [row for result in report["systems"].values() for row in result["rows"]]
    assert len(rows) == len(CASES) * len(SYSTEM_OUTPUTS)
    assert any(row["score"] == 0.0 for row in rows)
    assert all(row["status"] == "completed" for row in rows)
    assert report["per_case_completeness"]["filtered_rows"] == 0


def test_control_ordering_fails_if_strong_baseline_is_artificially_broken():
    outputs = copy.deepcopy(SYSTEM_OUTPUTS["strong_valid_baseline"])
    for case in CASES:
        outputs[case.case_id] = None
    broken = _evaluate_system("broken", outputs)
    assert broken["mean_score"] == 0.0
    assert (
        broken["mean_score"]
        <= _evaluate_system("random", SYSTEM_OUTPUTS["random"])["mean_score"]
    )


def test_control_source_manifest_detects_changed_source(tmp_path):
    report = run_evaluation_validity_controls(project_root=ROOT)
    for entry in report["source_manifest"]["files"]:
        source = ROOT / entry["path"]
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    source_entry = report["source_manifest"]["files"][0]
    source_path = tmp_path / source_entry["path"]
    source_path.write_text("tampered", encoding="utf-8")
    errors = validate_source_manifest(
        tmp_path, report["source_manifest"], require_current_files=True
    )
    assert any("hash mismatch" in error for error in errors)
