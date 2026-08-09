from __future__ import annotations

import copy
from pathlib import Path

from wavemind.evidence import attach_artifact_integrity, build_source_manifest
from wavemind.quickstart_admission import SCHEMA, validate_quickstart_artifact


def _artifact(root: Path, source_sha: str):
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "status": "admitted",
            "source_sha": source_sha,
            "checks": [
                {"id": check_id, "passed": True}
                for check_id in (
                    "python-quickstart",
                    "mcp-quickstart",
                    "typescript-quickstart",
                    "docker-quickstart",
                )
            ],
            "source_manifest": build_source_manifest(
                root, ["wavemind/quickstart_admission.py"]
            ),
        }
    )


def test_quickstart_artifact_requires_all_paths_exact_sha_and_integrity():
    root = Path.cwd()
    source_sha = "a" * 40
    report = _artifact(root, source_sha)
    assert validate_quickstart_artifact(
        report, project_root=root, expected_source_sha=source_sha
    ) == []

    missing = copy.deepcopy(report)
    missing["checks"] = missing["checks"][:-1]
    missing = attach_artifact_integrity(missing)
    assert "all four quickstarts must pass" in validate_quickstart_artifact(
        missing, project_root=root, expected_source_sha=source_sha
    )

    tampered = copy.deepcopy(report)
    tampered["checks"][0]["passed"] = False
    assert "artifact payload digest mismatch" in validate_quickstart_artifact(
        tampered, project_root=root, expected_source_sha=source_sha
    )
