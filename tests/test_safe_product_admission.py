from __future__ import annotations

import copy
from pathlib import Path

from wavemind.evidence import attach_artifact_integrity, build_source_manifest
from wavemind.safe_product_admission import (
    EXPECTED_CHECKS,
    SAFE_PRODUCT_SOURCE_FILES,
    SCHEMA,
    _backup_restore_rollback_check,
    _canonical_product_status_check,
    render_safe_product_markdown,
    validate_safe_product_artifact,
)


def _artifact(root: Path, source_sha: str):
    report = {
        "schema": SCHEMA,
        "status": "admitted",
        "admitted": True,
        "source_sha": source_sha,
        "summary": {
            "checks_passed": len(EXPECTED_CHECKS),
            "checks_total": len(EXPECTED_CHECKS),
        },
        "checks": [
            {"id": check_id, "passed": True, "status": "pass"}
            for check_id in sorted(EXPECTED_CHECKS)
        ],
        "claim_boundary": "repository-controlled evidence",
        "source_manifest": build_source_manifest(root, SAFE_PRODUCT_SOURCE_FILES),
    }
    return attach_artifact_integrity(report)


def test_safe_product_validator_requires_all_exact_sha_checks():
    root = Path.cwd()
    source_sha = "a" * 40
    report = _artifact(root, source_sha)
    assert (
        validate_safe_product_artifact(
            report, project_root=root, expected_source_sha=source_sha
        )
        == []
    )

    missing = copy.deepcopy(report)
    missing["checks"] = missing["checks"][:-1]
    missing = attach_artifact_integrity(missing)
    assert "safe product mandatory checks are not all passing" in (
        validate_safe_product_artifact(
            missing, project_root=root, expected_source_sha=source_sha
        )
    )

    tampered = copy.deepcopy(report)
    tampered["checks"][0]["status"] = "proxy"
    errors = validate_safe_product_artifact(
        tampered, project_root=root, expected_source_sha=source_sha
    )
    assert "artifact payload digest mismatch" in errors
    assert "safe product checks contain plan-only or proxy evidence" in errors


def test_safe_product_validator_rejects_signed_incomplete_source_manifest():
    root = Path.cwd()
    source_sha = "a" * 40
    report = _artifact(root, source_sha)
    incomplete = copy.deepcopy(report)
    incomplete["source_manifest"] = build_source_manifest(
        root, SAFE_PRODUCT_SOURCE_FILES[1:]
    )
    incomplete = attach_artifact_integrity(incomplete)

    errors = validate_safe_product_artifact(
        incomplete, project_root=root, expected_source_sha=source_sha
    )

    assert "safe product source manifest is incomplete or unexpected" in errors


def test_safe_product_markdown_lists_machine_checks():
    report = _artifact(Path.cwd(), "a" * 40)
    markdown = render_safe_product_markdown(report)
    assert "# Safe Product Admission" in markdown
    assert f"Checks: **{len(EXPECTED_CHECKS)}/{len(EXPECTED_CHECKS)}**" in markdown
    assert "`public-bind-fail-closed`" in markdown


def test_backup_restore_rollback_proves_both_sides_of_version_chain():
    evidence = _backup_restore_rollback_check()

    assert evidence["rollback_status"] == "rolled_back"
    assert evidence["restored_status"] == "active"
    assert evidence["core_survived_rollback"] is True
    assert evidence["core_restored"] is True
    assert evidence["experience_restored"] is True


def test_safe_product_reads_the_canonical_public_status():
    evidence = _canonical_product_status_check(Path.cwd())

    assert evidence["status_schema"] == "wavemind.product_status.v1"
    assert evidence["expected_version"] == "2.13.0"
    assert evidence["errors"] == []
