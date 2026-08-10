from __future__ import annotations

import json
from pathlib import Path

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
        "implemented": 10,
        "partial": 0,
        "missing": 0,
        "failed": 0,
        "blocked": 0,
        "historical": 2,
        "required_current": 1,
        "total": 13,
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
    assert rows["workspace-experience-admission"]["status"] == "implemented"
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
    assert "| `workspace-experience-admission` | `implemented` |" in markdown
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
    assert rows["workspace-experience-admission"]["status"] == "implemented"
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
