from __future__ import annotations

import copy
from pathlib import Path

from wavemind.evidence import attach_artifact_integrity, build_source_manifest
from wavemind.safe_product_admission import (
    EXPECTED_CHECKS,
    SCHEMA,
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
        "source_manifest": build_source_manifest(
            root, ["wavemind/safe_product_admission.py"]
        ),
    }
    return attach_artifact_integrity(report)


def test_safe_product_validator_requires_all_exact_sha_checks():
    root = Path.cwd()
    source_sha = "a" * 40
    report = _artifact(root, source_sha)
    assert validate_safe_product_artifact(
        report, project_root=root, expected_source_sha=source_sha
    ) == []

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


def test_safe_product_markdown_lists_machine_checks():
    report = _artifact(Path.cwd(), "a" * 40)
    markdown = render_safe_product_markdown(report)
    assert "# Safe Product Admission" in markdown
    assert f"Checks: **{len(EXPECTED_CHECKS)}/{len(EXPECTED_CHECKS)}**" in markdown
    assert "`public-bind-fail-closed`" in markdown
