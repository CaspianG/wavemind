from __future__ import annotations

from pathlib import Path

from wavemind.evidence import attach_artifact_integrity, build_source_manifest, repository_commit
from wavemind.upgrade_admission import evaluate_upgrade_admission


def _artifact(root: Path, schema: str, payload: dict) -> dict:
    return attach_artifact_integrity(
        {
            "schema": schema,
            "status": "admitted",
            "source_sha": repository_commit(root),
            "generated_at": "2026-08-16T00:00:00+00:00",
            "environment": {
                "profile": "test",
                "python": "3.13.2",
                "implementation": "CPython",
                "platform": "test-platform",
            },
            "inputs": {"fixture": True},
            "source_manifest": build_source_manifest(root, ["wavemind/upgrade.py"]),
            **payload,
        }
    )


def _inputs(root: Path) -> tuple[dict, dict, dict]:
    cases = [
        "test_disk_full_preflight_blocks_without_touching_state",
        "test_active_writer_blocks_before_backup",
        "test_external_python_process_holding_database_is_reported",
        "test_downgrade_requires_explicit_opt_in",
        "test_repeated_upgrade_is_idempotent",
        "test_interrupted_journal_is_recovered_before_retry",
        "test_live_upgrade_lock_rejects_second_operator",
        "test_checksum_mismatch_is_fail_closed",
        "test_docker_local_wheel_checksum_is_verified_before_docker_mutation",
        "test_offline_rollback_wheel_requires_expected_checksum",
        "test_production_command_runner_applies_a_hard_timeout",
        "test_process_preflight_never_queries_docker_command_line",
        "test_same_version_upgrade_adopts_legacy_ledgers_and_preserves_all_state",
        "test_incompatible_future_schema_is_rolled_back",
        "test_failure_injection_restores_both_databases_and_config[health]",
        "test_python_installation_failure_reinstalls_verified_source_wheel",
        "test_python_package_health_failure_reinstalls_verified_source_wheel",
    ]
    operational = _artifact(
        root,
        "wavemind.upgrade_operational_evidence.v1",
        {
            "metrics": {"failed": 0, "skipped": 0},
            "cases": [{"name": name, "status": "passed"} for name in cases],
        },
    )
    cross = _artifact(
        root,
        "wavemind.upgrade_python_cross_version.v1",
        {
            "candidate": {"version": "2.12.1"},
            "fixtures": [
                {
                    "source_version": "2.10.0",
                    "passed": True,
                    "rollback_probe": None,
                },
                {
                    "source_version": "2.11.0",
                    "passed": True,
                    "rollback_probe": {"passed": True},
                },
            ],
        },
    )
    docker = _artifact(
        root,
        "wavemind.upgrade_docker_compose.v1",
        {
            "candidate": {"wheel": {"version": "2.12.1"}},
            "checks": {
                "forgotten_state_preserved": True,
                "immutable_target_digest": True,
                "core_state_preserved": True,
                "experience_state_preserved": True,
                "target_container_recreated": True,
                "failed_health_rolled_back": True,
                "previous_container_recreated": True,
            },
        },
    )
    return operational, cross, docker


def test_upgrade_admission_requires_all_exact_sha_evidence():
    root = Path(__file__).resolve().parents[1]
    source_sha = repository_commit(root)
    operational, cross, docker = _inputs(root)

    report = evaluate_upgrade_admission(
        operational=operational,
        cross_version=cross,
        docker_compose=docker,
        project_root=root,
        expected_source_sha=source_sha,
    )

    assert report["status"] == "admitted"
    assert report["score"] == {"passed": 18, "total": 18}


def test_upgrade_admission_blocks_tampered_or_failed_evidence():
    root = Path(__file__).resolve().parents[1]
    source_sha = repository_commit(root)
    operational, cross, docker = _inputs(root)
    docker["checks"]["failed_health_rolled_back"] = False

    report = evaluate_upgrade_admission(
        operational=operational,
        cross_version=cross,
        docker_compose=docker,
        project_root=root,
        expected_source_sha=source_sha,
    )

    assert report["status"] == "blocked"
    assert report["rows"]["exact_sha_evidence"] is False
    assert report["rows"]["docker_failed_health_rollback"] is False
