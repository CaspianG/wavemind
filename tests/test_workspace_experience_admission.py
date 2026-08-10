from __future__ import annotations

import json
from pathlib import Path

from wavemind.workspace_experience_admission import (
    WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA,
    WORKSPACE_EXPERIENCE_PROTOCOL_SHA256,
    evaluate_workspace_experience_admission_matrix,
    render_workspace_experience_admission_markdown,
    workspace_experience_protocol_manifest,
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
        "implemented": 8,
        "partial": 0,
        "missing": 1,
        "failed": 2,
        "blocked": 1,
        "required_current": 1,
        "total": 13,
    }
    rows = {row["id"]: row for row in payload["rows"]}
    assert rows["historical-v3-checksum-selection-experiment"]["status"] == "failed"
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
    assert rows["frozen-real-work-benchmark-v4"]["status"] == "failed"
    assert (
        rows["frozen-real-work-benchmark-v4"]["details"]["methodology_status"]
        == "historical_invalid_not_admission_evidence"
    )
    assert "hardcoded" in " ".join(
        rows["frozen-real-work-benchmark-v4"]["details"]["invalid_reasons"]
    )
    assert rows["frozen-real-work-benchmark-v5"]["status"] == "missing"
    assert rows["workspace-experience-admission"]["status"] == "blocked"
    assert rows["safe-product-regression"]["status"] == "required_current"
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
    assert "| `workspace-experience-admission` | `blocked` |" in markdown
    assert "Goal 7 gap audit" in markdown
    assert render_workspace_experience_admission_markdown(payload) == markdown
