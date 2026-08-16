from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.upgrade_admission.v1"


def _artifact_valid(
    artifact: Mapping[str, Any],
    *,
    schema: str,
    root: Path,
    expected_source_sha: str,
) -> tuple[bool, list[str]]:
    errors = validate_artifact_integrity(artifact)
    if artifact.get("schema") != schema:
        errors.append(f"expected {schema}")
    if artifact.get("source_sha") != expected_source_sha:
        errors.append("source SHA mismatch")
    environment = artifact.get("environment")
    if not isinstance(environment, Mapping):
        errors.append("environment manifest is missing")
    else:
        for key in ("profile", "python", "implementation", "platform"):
            if not environment.get(key):
                errors.append(f"environment manifest is missing {key}")
    if not isinstance(artifact.get("inputs"), Mapping):
        errors.append("artifact inputs are missing")
    manifest = artifact.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("source manifest is missing")
    else:
        errors.extend(validate_source_manifest(root, manifest, require_current_files=True))
    if artifact.get("status") != "admitted":
        errors.append("artifact is not admitted")
    return not errors, errors


def evaluate_upgrade_admission(
    *,
    operational: Mapping[str, Any],
    cross_version: Mapping[str, Any],
    docker_compose: Mapping[str, Any],
    project_root: str | Path,
    expected_source_sha: str,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    operational_ok, operational_errors = _artifact_valid(
        operational,
        schema="wavemind.upgrade_operational_evidence.v1",
        root=root,
        expected_source_sha=expected_source_sha,
    )
    cross_ok, cross_errors = _artifact_valid(
        cross_version,
        schema="wavemind.upgrade_python_cross_version.v1",
        root=root,
        expected_source_sha=expected_source_sha,
    )
    docker_ok, docker_errors = _artifact_valid(
        docker_compose,
        schema="wavemind.upgrade_docker_compose.v1",
        root=root,
        expected_source_sha=expected_source_sha,
    )
    case_names = {
        str(row.get("name"))
        for row in operational.get("cases", [])
        if isinstance(row, Mapping) and row.get("status") == "passed"
    }
    fixtures = [
        row
        for row in cross_version.get("fixtures", [])
        if isinstance(row, Mapping)
    ]
    distinct_sources = {str(row.get("source_version")) for row in fixtures}
    rollback_fixtures = [
        row
        for row in fixtures
        if isinstance(row.get("rollback_probe"), Mapping)
        and row["rollback_probe"].get("passed") is True
    ]
    docker_checks = docker_compose.get("checks", {})
    target_versions = {
        str(cross_version.get("candidate", {}).get("version")),
        str(docker_compose.get("candidate", {}).get("wheel", {}).get("version")),
    }

    def has(prefix: str) -> bool:
        return any(name.startswith(prefix) for name in case_names)

    rows = {
        "exact_sha_evidence": operational_ok and cross_ok and docker_ok,
        "environment_and_inputs_manifest": all(
            isinstance(artifact.get("environment"), Mapping)
            and isinstance(artifact.get("inputs"), Mapping)
            for artifact in (operational, cross_version, docker_compose)
        ),
        "bounded_subprocess_and_safe_process_enumeration": has(
            "test_production_command_runner_applies_a_hard_timeout"
        )
        and has("test_process_preflight_never_queries_docker_command_line"),
        "preflight_version_disk_writer_process": has("test_disk_full_preflight")
        and has("test_active_writer")
        and has("test_external_python_process")
        and has("test_downgrade_requires"),
        "exclusive_lock_and_idempotent_journal": has("test_repeated_upgrade")
        and has("test_interrupted_journal")
        and has("test_live_upgrade_lock"),
        "verified_release_identity_and_checksum": has("test_checksum_mismatch")
        and has("test_docker_local_wheel_checksum"),
        "core_experience_config_object_backup": has("test_same_version_upgrade"),
        "explicit_core_experience_schema_ledger": has("test_same_version_upgrade")
        and has("test_incompatible_future_schema"),
        "staged_migration_and_logical_parity": has("test_same_version_upgrade")
        and has("test_failure_injection"),
        "forgotten_state_not_resurrected": has("test_same_version_upgrade")
        and bool(docker_checks.get("forgotten_state_preserved")),
        "python_n_minus_two_and_n_minus_one": len(fixtures) >= 2
        and len(distinct_sources) >= 2
        and all(row.get("passed") is True for row in fixtures),
        "python_real_package_rollback": bool(rollback_fixtures),
        "complete_install_health_and_state_rollback": has(
            "test_python_installation_failure_reinstalls_verified_source_wheel"
        )
        and has("test_python_package_health_failure_reinstalls_verified_source_wheel")
        and has("test_failure_injection")
        and bool(docker_checks.get("failed_health_rolled_back")),
        "docker_immutable_digest": bool(docker_checks.get("immutable_target_digest")),
        "docker_both_databases_recreated": bool(docker_checks.get("core_state_preserved"))
        and bool(docker_checks.get("experience_state_preserved"))
        and bool(docker_checks.get("target_container_recreated")),
        "docker_failed_health_rollback": bool(docker_checks.get("failed_health_rolled_back"))
        and bool(docker_checks.get("previous_container_recreated")),
        "same_candidate_across_python_and_docker": len(target_versions) == 1
        and "None" not in target_versions,
        "no_skipped_or_deleted_failures": operational.get("metrics", {}).get("failed") == 0
        and operational.get("metrics", {}).get("skipped") == 0,
    }
    status = "admitted" if all(rows.values()) else "blocked"
    report = {
        "schema": SCHEMA,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": repository_commit(root),
        "expected_source_sha": expected_source_sha,
        "rows": rows,
        "score": {"passed": sum(rows.values()), "total": len(rows)},
        "inputs": {
            "operational_integrity": operational.get("integrity", {}).get("payload_sha256"),
            "cross_version_integrity": cross_version.get("integrity", {}).get("payload_sha256"),
            "docker_compose_integrity": docker_compose.get("integrity", {}).get("payload_sha256"),
        },
        "input_errors": {
            "operational": operational_errors,
            "cross_version": cross_errors,
            "docker_compose": docker_errors,
        },
        "source_versions": sorted(distinct_sources),
        "target_versions": sorted(target_versions),
        "source_manifest": build_source_manifest(
            root,
            [
                "Dockerfile",
                "docker-compose.yml",
                "pyproject.toml",
                "wavemind/upgrade.py",
                "wavemind/schema_migrations.py",
                "wavemind/upgrade_admission.py",
                "tests/test_upgrade.py",
                "benchmarks/upgrade_operational_evidence.py",
                "benchmarks/upgrade_python_cross_version.py",
                "benchmarks/upgrade_docker_compose.py",
                "benchmarks/upgrade_admission.py",
                ".github/workflows/upgrade-admission.yml",
            ],
        ),
    }
    return attach_artifact_integrity(report)


def render_upgrade_admission_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Safe One-Command Upgrade Admission",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Source SHA: `{report.get('source_sha')}`",
        f"- Score: **{report.get('score', {}).get('passed')}/{report.get('score', {}).get('total')}**",
        "",
        "| Admission row | Result |",
        "|---|---:|",
    ]
    for name, passed in report.get("rows", {}).items():
        lines.append(f"| `{name}` | {'pass' if passed else 'blocked'} |")
    lines.extend(
        [
            "",
            "This admission is limited to supported local Python installs and Docker Compose.",
            "It does not claim PostgreSQL, Helm, Kubernetes, or remote multi-node upgrades.",
            "",
        ]
    )
    return "\n".join(lines)
