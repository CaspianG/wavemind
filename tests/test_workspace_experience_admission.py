from __future__ import annotations

import json
from pathlib import Path

import wavemind.workspace_experience_admission as admission
from benchmarks.workspace_experience_operational_evidence import (
    OPERATIONAL_SOURCE_FILES,
    REQUIRED_CHECKS,
    SCHEMA as OPERATIONAL_SCHEMA,
)
from wavemind.evidence import attach_artifact_integrity, build_source_manifest
from wavemind.safe_product_admission import EXPECTED_CHECKS, SCHEMA as SAFE_PRODUCT_SCHEMA
from wavemind.workspace_experience_admission import (
    WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA,
    WORKSPACE_EXPERIENCE_PROTOCOL_SHA256,
    evaluate_workspace_experience_admission_matrix,
    render_workspace_experience_admission_markdown,
    workspace_experience_protocol_manifest,
    write_workspace_experience_admission_artifacts,
    write_workspace_experience_admission_matrix,
)


def test_workspace_experience_protocol_is_frozen() -> None:
    protocol = workspace_experience_protocol_manifest()

    assert protocol["revision"] == "workspace-experience-v1-frozen-20260810"
    assert protocol["sha256"] == WORKSPACE_EXPERIENCE_PROTOCOL_SHA256
    assert protocol["thresholds"]["task_success_lift_pp_min"] == 15.0
    assert protocol["thresholds"]["false_procedure_injection_max"] == 0.01
    assert "universal model-quality" in protocol["claim_boundary"]


def test_workspace_experience_gap_matrix_is_not_final_admission() -> None:
    payload = evaluate_workspace_experience_admission_matrix(
        root=Path.cwd(),
        baseline_source_sha="baseline-sha",
    )

    assert payload["schema"] == WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["baseline_source_sha"] == "baseline-sha"
    assert payload["summary"] == {
        "implemented": 9,
        "partial": 0,
        "missing": 0,
        "failed": 0,
        "blocked": 1,
        "historical": 2,
        "required_current": 2,
        "total": 14,
    }
    rows = {row["id"]: row for row in payload["rows"]}
    assert rows["historical-v3-checksum-selection-experiment"]["status"] == "historical"
    assert rows["historical-v3-checksum-selection-experiment"]["details"]["failed_gates"] == [
        "task_success_lift_pp",
        "repeated_known_error_reduction",
    ]
    assert (
        rows["historical-v3-checksum-selection-experiment"]["details"][
            "methodology_status"
        ]
        == "historical_failed_checksum_selection_not_real_work"
    )
    assert rows["frozen-real-work-benchmark-v4"]["status"] == "historical"
    assert (
        rows["frozen-real-work-benchmark-v4"]["details"]["methodology_status"]
        == "historical_invalid_not_admission_evidence"
    )
    assert "hardcoded" in " ".join(
        rows["frozen-real-work-benchmark-v4"]["details"]["invalid_reasons"]
    )
    assert rows["frozen-real-work-benchmark-v5"]["status"] == "implemented"
    assert rows["frozen-real-work-benchmark-v5"]["details"]["result_status"] == "passed"
    assert rows["frozen-real-work-benchmark-v5"]["details"]["split"] == "heldout"
    assert rows["frozen-real-work-benchmark-v5"]["details"]["failed_gates"] == []
    assert rows["frozen-real-work-benchmark-v5"]["details"]["evidence_scope"] == "frozen_quality"
    freshness = rows["frozen-real-work-benchmark-v5"]["details"]["freshness"]
    assert freshness["quality_fresh"] is True
    assert freshness["allowed_operational_changes"]
    assert rows["current-workspace-operational-evidence"]["status"] == "required_current"
    assert rows["workspace-experience-admission"]["status"] == "blocked"
    assert rows["safe-product-regression"]["status"] == "required_current"
    assert "not current" in rows["safe-product-regression"]["details"]["reason"]
    assert rows["workspace-identity-isolation"]["artifact"]
    assert rows["workspace-identity-isolation"]["test"]
    assert payload["source_manifest"]["files"]
    assert payload["source_manifest"]["digest"]


def test_workspace_experience_admission_markdown_and_write(tmp_path: Path) -> None:
    json_path = tmp_path / "matrix.json"
    md_path = tmp_path / "matrix.md"

    payload = write_workspace_experience_admission_matrix(
        root=Path.cwd(),
        output=json_path,
        markdown_output=md_path,
        baseline_source_sha="baseline-sha",
    )

    written = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert written["source_manifest"]["digest"] == payload["source_manifest"]["digest"]
    assert "| `current-workspace-operational-evidence` | `required_current` |" in markdown
    assert "| `workspace-experience-admission` | `blocked` |" in markdown
    assert "| `safe-product-regression` | `required_current` |" in markdown
    assert "Evidence Snapshot Source SHA" in markdown
    assert "Exact Current Verdict: CI artifact on the current PR/main SHA" in markdown
    assert "Goal 7 evidence snapshot" in markdown
    assert render_workspace_experience_admission_markdown(payload) == markdown


def test_workspace_experience_admission_artifact_writer_keeps_canonical_files_in_sync(
    tmp_path: Path,
) -> None:
    matrix_json = tmp_path / "workspace_experience_admission_matrix.json"
    matrix_md = tmp_path / "WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md"
    result_json = tmp_path / "workspace_experience_admission_results.json"
    report_md = tmp_path / "WORKSPACE_EXPERIENCE_ADMISSION.md"

    payload = write_workspace_experience_admission_artifacts(
        root=Path.cwd(),
        matrix_output=matrix_json,
        matrix_markdown_output=matrix_md,
        result_output=result_json,
        report_output=report_md,
        baseline_source_sha="baseline-sha",
    )

    matrix = json.loads(matrix_json.read_text(encoding="utf-8"))
    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert matrix == result == payload
    assert matrix_md.read_text(encoding="utf-8").startswith(
        "# Workspace Experience Admission Matrix"
    )
    assert report_md.read_text(encoding="utf-8").startswith("# Workspace Experience Admission")
    for row in payload["rows"]:
        row_markdown = f"| `{row['id']}` | `{row['status']}` |"
        assert row_markdown in matrix_md.read_text(encoding="utf-8")
        assert row_markdown in report_md.read_text(encoding="utf-8")


def test_checked_in_workspace_admission_artifacts_are_consistent() -> None:
    root = Path.cwd()
    matrix_path = root / "benchmarks" / "workspace_experience_admission_matrix.json"
    result_path = root / "benchmarks" / "workspace_experience_admission_results.json"
    matrix_md_path = root / "benchmarks" / "WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md"
    report_md_path = root / "benchmarks" / "WORKSPACE_EXPERIENCE_ADMISSION.md"

    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert matrix["schema"] == result["schema"] == WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA
    assert matrix["status"] == result["status"]
    assert matrix["source_sha"] == result["source_sha"]
    assert matrix["protocol"] == result["protocol"]
    assert matrix["source_manifest"] == result["source_manifest"]

    matrix_rows = [(row["id"], row["status"]) for row in matrix["rows"]]
    result_rows = [(row["id"], row["status"]) for row in result["rows"]]
    assert matrix_rows == result_rows

    rows = {row["id"]: row for row in matrix["rows"]}
    assert rows["workspace-experience-admission"]["artifact"] == (
        "benchmarks/workspace_experience_admission_results.json"
    )
    assert rows["workspace-experience-admission"]["status"] == "blocked"
    assert rows["current-workspace-operational-evidence"]["status"] == "required_current"
    assert rows["safe-product-regression"]["status"] == "required_current"
    referenced = json.loads(
        (root / rows["workspace-experience-admission"]["artifact"]).read_text(
            encoding="utf-8"
        )
    )
    assert [(row["id"], row["status"]) for row in referenced["rows"]] == matrix_rows

    matrix_md = matrix_md_path.read_text(encoding="utf-8")
    report_md = report_md_path.read_text(encoding="utf-8")
    assert "Exact Current Verdict: CI artifact on the current PR/main SHA" in matrix_md
    assert "Exact Current Verdict: CI artifact on the current PR/main SHA" in report_md
    for row_id, status in matrix_rows:
        row_markdown = f"| `{row_id}` | `{status}` |"
        assert row_markdown in matrix_md
        assert row_markdown in report_md


def test_exact_current_workspace_admission_requires_current_operational_and_safe_product(
    tmp_path: Path,
) -> None:
    root = Path.cwd()
    source_sha = _current_sha(root)
    safe_product = _safe_product_fixture(root, source_sha)
    operational = _operational_fixture(root, source_sha)
    safe_path = tmp_path / "safe-product.json"
    operational_path = tmp_path / "workspace-operational.json"
    safe_path.write_text(json.dumps(safe_product), encoding="utf-8")
    operational_path.write_text(json.dumps(operational), encoding="utf-8")

    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=operational_path,
    )

    rows = {row["id"]: row for row in payload["rows"]}
    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"] == {
        "implemented": 12,
        "partial": 0,
        "missing": 0,
        "failed": 0,
        "blocked": 0,
        "historical": 2,
        "required_current": 0,
        "total": 14,
    }
    assert rows["current-workspace-operational-evidence"]["status"] == "implemented"
    assert rows["safe-product-regression"]["status"] == "implemented"
    assert rows["workspace-experience-admission"]["status"] == "implemented"


def test_workspace_admission_rejects_wrong_sha_tampered_or_missing_manifest_operational_evidence(
    tmp_path: Path,
) -> None:
    root = Path.cwd()
    source_sha = _current_sha(root)
    safe_product = _safe_product_fixture(root, source_sha)
    safe_path = tmp_path / "safe-product.json"
    safe_path.write_text(json.dumps(safe_product), encoding="utf-8")

    wrong_sha = _operational_fixture(root, "0" * 40)
    wrong_path = tmp_path / "wrong-operational.json"
    wrong_path.write_text(json.dumps(wrong_sha), encoding="utf-8")
    wrong_payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=wrong_path,
    )
    wrong_row = {
        row["id"]: row for row in wrong_payload["rows"]
    }["current-workspace-operational-evidence"]
    assert wrong_row["status"] == "failed"
    assert "source SHA mismatch" in " ".join(wrong_row["details"]["validator_errors"])

    tampered = _operational_fixture(root, source_sha)
    tampered["metrics"]["workspace_namespace_leakage"] = 1
    tampered_path = tmp_path / "tampered-operational.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    tampered_payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=tampered_path,
    )
    tampered_errors = {
        row["id"]: row for row in tampered_payload["rows"]
    }["current-workspace-operational-evidence"]["details"]["validator_errors"]
    assert "artifact payload digest mismatch" in tampered_errors
    assert "workspace operational namespace leakage is not zero" in tampered_errors

    missing_manifest = _operational_fixture(root, source_sha)
    missing_manifest.pop("source_manifest")
    missing_manifest = attach_artifact_integrity(missing_manifest)
    missing_path = tmp_path / "missing-manifest-operational.json"
    missing_path.write_text(json.dumps(missing_manifest), encoding="utf-8")
    missing_payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=missing_path,
    )
    missing_errors = {
        row["id"]: row for row in missing_payload["rows"]
    }["current-workspace-operational-evidence"]["details"]["validator_errors"]
    assert "workspace operational source manifest is missing" in missing_errors


def test_workspace_admission_blocks_unallowlisted_quality_critical_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path.cwd()
    source_sha = _current_sha(root)
    safe_path, operational_path = _write_exact_current_fixtures(tmp_path, root, source_sha)
    real_blob = admission._git_blob_id  # noqa: SLF001 - direct freshness regression.

    def fake_blob(selected_root: Path, selected_sha: str, relative: str) -> str:
        if relative == "wavemind/experience_runtime.py":
            return "changed-runtime-blob"
        return real_blob(selected_root, selected_sha, relative)

    monkeypatch.setattr(admission, "_git_blob_id", fake_blob)

    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=operational_path,
    )

    rows = {row["id"]: row for row in payload["rows"]}
    assert payload["status"] == "blocked"
    assert rows["frozen-real-work-benchmark-v5"]["status"] == "blocked"
    freshness = rows["frozen-real-work-benchmark-v5"]["details"]["freshness"]
    assert freshness["quality_fresh"] is False
    assert freshness["unallowed_quality_changes"][0]["path"] == "wavemind/experience_runtime.py"
    assert "new independent quality evidence required" in rows["frozen-real-work-benchmark-v5"]["details"][
        "not_admission_evidence_reason"
    ]


def test_workspace_admission_blocks_v5_runner_or_result_tamper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path.cwd()
    source_sha = _current_sha(root)
    safe_path, operational_path = _write_exact_current_fixtures(tmp_path, root, source_sha)
    real_blob = admission._git_blob_id  # noqa: SLF001 - direct freshness regression.

    def fake_blob(selected_root: Path, selected_sha: str, relative: str) -> str:
        if relative in {
            "benchmarks/workspace_experience_v5_benchmark.py",
            "benchmarks/workspace_experience_v5_benchmark_results.json",
        }:
            return f"tampered-{relative}"
        return real_blob(selected_root, selected_sha, relative)

    monkeypatch.setattr(admission, "_git_blob_id", fake_blob)

    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        safe_product_path=safe_path,
        operational_evidence_path=operational_path,
    )

    row = {
        item["id"]: item for item in payload["rows"]
    }["frozen-real-work-benchmark-v5"]
    freshness = row["details"]["freshness"]
    assert row["status"] == "blocked"
    assert freshness["v5_result_blob_ok"] is False
    assert any(
        item["path"] == "benchmarks/workspace_experience_v5_benchmark.py"
        for item in freshness["unallowed_quality_changes"]
    )


def _current_sha(root: Path) -> str:
    import subprocess

    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _write_exact_current_fixtures(
    tmp_path: Path,
    root: Path,
    source_sha: str,
) -> tuple[Path, Path]:
    safe_path = tmp_path / "safe-product.json"
    operational_path = tmp_path / "workspace-operational.json"
    safe_path.write_text(
        json.dumps(_safe_product_fixture(root, source_sha)),
        encoding="utf-8",
    )
    operational_path.write_text(
        json.dumps(_operational_fixture(root, source_sha)),
        encoding="utf-8",
    )
    return safe_path, operational_path


def _safe_product_fixture(root: Path, source_sha: str) -> dict:
    checked_in = json.loads(
        (root / "benchmarks" / "safe_product_admission_results.json").read_text(
            encoding="utf-8"
        )
    )
    source_paths = [
        entry["path"] for entry in checked_in["source_manifest"]["files"]
    ]
    payload = {
        "schema": SAFE_PRODUCT_SCHEMA,
        "status": "admitted",
        "admitted": True,
        "source_sha": source_sha,
        "summary": {
            "checks_passed": len(EXPECTED_CHECKS),
            "checks_total": len(EXPECTED_CHECKS),
        },
        "checks": [
            {"id": check_id, "status": "pass", "passed": True}
            for check_id in sorted(EXPECTED_CHECKS)
        ],
        "source_manifest": build_source_manifest(root, source_paths),
        "claim_boundary": "test fixture",
    }
    return attach_artifact_integrity(payload)


def _operational_fixture(root: Path, source_sha: str) -> dict:
    payload = {
        "schema": OPERATIONAL_SCHEMA,
        "status": "admitted",
        "admitted": True,
        "source_sha": source_sha,
        "summary": {
            "checks_passed": len(REQUIRED_CHECKS),
            "checks_total": len(REQUIRED_CHECKS),
        },
        "checks": [
            {"id": check_id, "passed": True, "details": {}}
            for check_id in sorted(REQUIRED_CHECKS)
        ],
        "metrics": {
            "workspace_namespace_leakage": 0,
            "mandatory_event_capture": 1.0,
            "cross_client_citation_state_parity": 1.0,
            "packet_selection_p95_ms": 10.0,
            "packet_selection_p99_ms": 20.0,
        },
        "source_manifest": build_source_manifest(root, OPERATIONAL_SOURCE_FILES),
        "claim_boundary": "test fixture",
    }
    return attach_artifact_integrity(payload)
