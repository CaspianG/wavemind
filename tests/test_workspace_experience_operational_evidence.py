from __future__ import annotations

from pathlib import Path

from benchmarks.workspace_experience_operational_evidence import (
    main,
    run_workspace_operational_evidence,
    validate_workspace_operational_evidence,
)


def test_workspace_operational_evidence_runs_registry_auth_and_cross_surface(
    tmp_path: Path,
) -> None:
    payload = run_workspace_operational_evidence(temp_root=tmp_path)

    errors = validate_workspace_operational_evidence(
        payload,
        project_root=Path.cwd(),
        expected_source_sha=payload["source_sha"],
    )

    assert errors == []
    assert payload["status"] == "admitted"
    assert payload["summary"] == {"checks_passed": 9, "checks_total": 9}
    assert payload["metrics"]["workspace_namespace_leakage"] == 0
    assert payload["metrics"]["mandatory_event_capture"] == 1.0
    assert payload["metrics"]["cross_client_citation_state_parity"] == 1.0
    assert payload["metrics"]["packet_selection_p95_ms"] <= 100.0


def test_workspace_operational_evidence_validator_rejects_tampering(
    tmp_path: Path,
) -> None:
    payload = run_workspace_operational_evidence(temp_root=tmp_path)
    payload["metrics"]["workspace_namespace_leakage"] = 1

    errors = validate_workspace_operational_evidence(
        payload,
        project_root=Path.cwd(),
        expected_source_sha=payload["source_sha"],
    )

    assert "artifact payload digest mismatch" in errors
    assert "workspace operational namespace leakage is not zero" in errors


def test_workspace_operational_evidence_cli_stdout_is_secret_safe(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "operational.json"

    exit_code = main(
        [
            "--output",
            str(output),
            "--temp-root",
            str(tmp_path),
            "--require-admitted",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.exists()
    assert "sk-operational-secret" not in captured.out
    assert "api_key" not in captured.out
    assert "token" not in captured.out.lower()
    assert "artifact_path" in captured.out
