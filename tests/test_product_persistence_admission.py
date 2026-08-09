from __future__ import annotations

import copy
from pathlib import Path

from wavemind.evidence import attach_artifact_integrity, build_source_manifest
from wavemind.product_persistence_admission import (
    SCHEMA,
    validate_product_persistence_artifact,
)


def _artifact(project_root, source_sha):
    checks = {
        "distinct_containers": True,
        "core_memory_after_recreate": True,
        "experience_after_recreate": True,
        "verification_after_recreate": True,
        "idempotent_retry_after_recreate": True,
        "product_backup_persisted": True,
        "core_database_persisted": True,
        "experience_database_persisted": True,
        "secret_leakage_zero": True,
    }
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "status": "admitted",
            "source_sha": source_sha,
            "checks": checks,
            "source_manifest": build_source_manifest(
                project_root,
                ["wavemind/product_persistence_admission.py"],
            ),
        }
    )


def test_product_persistence_artifact_requires_exact_sha_manifest_and_checks():
    project_root = Path.cwd()
    source_sha = "a" * 40
    report = _artifact(project_root, source_sha)

    assert validate_product_persistence_artifact(
        report,
        project_root=project_root,
        expected_source_sha=source_sha,
    ) == []

    wrong_sha = copy.deepcopy(report)
    wrong_sha["source_sha"] = "b" * 40
    wrong_sha = attach_artifact_integrity(wrong_sha)
    assert "product persistence source SHA mismatch" in validate_product_persistence_artifact(
        wrong_sha,
        project_root=project_root,
        expected_source_sha=source_sha,
    )

    tampered = copy.deepcopy(report)
    tampered["checks"]["secret_leakage_zero"] = False
    errors = validate_product_persistence_artifact(
        tampered,
        project_root=project_root,
        expected_source_sha=source_sha,
    )
    assert "artifact payload digest mismatch" in errors
    assert "product persistence checks are not all passing" in errors
