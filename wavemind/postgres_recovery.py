from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


DEFAULT_DSN_ENV = "WAVEMIND_POSTGRES_DSN"
DEFAULT_BASEBACKUP_ENV = "WAVEMIND_POSTGRES_BASEBACKUP_DIR"
DEFAULT_WAL_ARCHIVE_ENV = "WAVEMIND_POSTGRES_WAL_ARCHIVE_DIR"
DEFAULT_RESTORE_DATA_ENV = "WAVEMIND_POSTGRES_RESTORE_DATA_DIR"
DEFAULT_RESTORE_TARGET_ENV = "WAVEMIND_POSTGRES_RESTORE_TARGET_TIME"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_ref(name: str) -> str:
    return "${" + name + "}"


@dataclass(frozen=True)
class PostgresPITRCommand:
    phase: str
    name: str
    command: str
    validates: tuple[str, ...] = ()
    destructive: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "name": self.name,
            "command": self.command,
            "validates": list(self.validates),
            "destructive": self.destructive,
        }


@dataclass(frozen=True)
class PostgresPITRValidationReport:
    status: str
    checks: dict[str, bool]
    missing_env: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ready"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "checks": dict(self.checks),
            "missing_env": list(self.missing_env),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PostgresPITRPlan:
    schema: str
    generated_at: str
    status: str
    retention_hours: int
    dsn_env: str
    basebackup_env: str
    wal_archive_env: str
    restore_data_env: str
    restore_target_env: str
    required_env: tuple[str, ...]
    missing_env: tuple[str, ...]
    postgresql_settings: dict[str, str]
    commands: tuple[PostgresPITRCommand, ...]
    verification_queries: tuple[str, ...]
    safety_notes: tuple[str, ...]
    validation: PostgresPITRValidationReport = field(repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "status": self.status,
            "retention_hours": self.retention_hours,
            "required_env": list(self.required_env),
            "missing_env": list(self.missing_env),
            "environment_status": "ready" if not self.missing_env else "missing_env",
            "postgresql_settings": dict(self.postgresql_settings),
            "commands": [command.as_dict() for command in self.commands],
            "verification_queries": list(self.verification_queries),
            "safety_notes": list(self.safety_notes),
            "validation": self.validation.as_dict(),
        }


def build_postgres_pitr_plan(
    *,
    dsn_env: str = DEFAULT_DSN_ENV,
    basebackup_env: str = DEFAULT_BASEBACKUP_ENV,
    wal_archive_env: str = DEFAULT_WAL_ARCHIVE_ENV,
    restore_data_env: str = DEFAULT_RESTORE_DATA_ENV,
    restore_target_env: str = DEFAULT_RESTORE_TARGET_ENV,
    retention_hours: int = 72,
    generated_at: str | None = None,
) -> PostgresPITRPlan:
    """Build a deterministic, secret-safe Postgres PITR runbook.

    The plan is intentionally a structural preflight. It does not connect to a
    database and it never embeds secret values from the environment. Real
    recovery drills should execute the emitted steps in a staging or production
    runbook with the referenced environment variables populated.
    """

    if retention_hours <= 0:
        raise ValueError("retention_hours must be positive")
    env_names = (dsn_env, basebackup_env, wal_archive_env, restore_data_env, restore_target_env)
    if any(not name or not name.strip() for name in env_names):
        raise ValueError("environment variable names must be non-empty")

    required_env = tuple(dict.fromkeys(env_names))
    missing_env = tuple(name for name in required_env if not os.environ.get(name))

    dsn = _env_ref(dsn_env)
    basebackup_dir = _env_ref(basebackup_env)
    wal_archive = _env_ref(wal_archive_env)
    restore_data = _env_ref(restore_data_env)
    restore_target = _env_ref(restore_target_env)

    settings = {
        "wal_level": "replica",
        "archive_mode": "on",
        "archive_command": f"test ! -f {wal_archive}/%f && cp %p {wal_archive}/%f",
        "restore_command": f"cp {wal_archive}/%f %p",
        "retention": f"retain base backups and WAL for at least {retention_hours} hours",
    }

    commands = (
        PostgresPITRCommand(
            phase="preflight",
            name="verify required environment",
            command=" && ".join(f'test -n "{_env_ref(name)}"' for name in required_env),
            validates=("required_env_present",),
        ),
        PostgresPITRCommand(
            phase="configure",
            name="enable WAL archiving",
            command=(
                "psql "
                f'"{dsn}" '
                "-c \"ALTER SYSTEM SET wal_level = 'replica';\" "
                "-c \"ALTER SYSTEM SET archive_mode = 'on';\" "
                f"-c \"ALTER SYSTEM SET archive_command = '{settings['archive_command']}';\" "
                "-c \"SELECT pg_reload_conf();\""
            ),
            validates=("wal_archiving_enabled",),
        ),
        PostgresPITRCommand(
            phase="backup",
            name="create streaming base backup",
            command=(
                "pg_basebackup "
                f'--dbname "{dsn}" '
                f'--pgdata "{basebackup_dir}" '
                "--format=tar --gzip --wal-method=stream --checkpoint=fast "
                "--label=wavemind-basebackup"
            ),
            validates=("base_backup_created", "wal_streamed_with_backup"),
        ),
        PostgresPITRCommand(
            phase="restore",
            name="extract base backup into restore data directory",
            command=f'mkdir -p "{restore_data}" && tar -xzf "{basebackup_dir}/base.tar.gz" -C "{restore_data}"',
            validates=("base_backup_restored",),
            destructive=True,
        ),
        PostgresPITRCommand(
            phase="restore",
            name="write recovery target config",
            command=(
                "printf \"%s\\n\" "
                f"\"restore_command = '{settings['restore_command']}'\" "
                f"\"recovery_target_time = '{restore_target}'\" "
                f"\"recovery_target_action = 'pause'\" "
                f'>> "{restore_data}/postgresql.auto.conf" && touch "{restore_data}/recovery.signal"'
            ),
            validates=("recovery_signal_present", "restore_target_time_configured"),
        ),
        PostgresPITRCommand(
            phase="verify",
            name="verify replay target before promotion",
            command=(
                f'pg_ctl start -D "{restore_data}" && '
                f'psql "{dsn}" -c "SELECT pg_is_in_recovery();" && '
                f'psql "{dsn}" -c "SELECT pg_last_wal_replay_lsn();"'
            ),
            validates=("restore_started", "wal_replay_observable"),
        ),
        PostgresPITRCommand(
            phase="promote",
            name="promote restored database after validation",
            command=f'psql "{dsn}" -c "SELECT pg_promote(wait_seconds => 60);"',
            validates=("promotion_completed",),
        ),
    )

    verification_queries = (
        "SELECT pg_is_in_recovery();",
        "SELECT pg_last_wal_replay_lsn();",
        "SELECT now() >= current_setting('recovery_target_time', true)::timestamptz;",
        "SELECT count(*) FROM wavemind_memories;",
        "SELECT count(*) FROM wavemind_audit_events;",
    )
    safety_notes = (
        "This plan stores only environment variable names, not secret values.",
        "Run restore into an isolated data directory before promoting.",
        "Keep regular managed snapshots or pg_basebackup artifacts plus WAL archives.",
        "Use SQLite recovery journals only for SQLite source-of-truth deployments.",
    )
    validation = validate_postgres_pitr_commands(
        required_env=required_env,
        missing_env=missing_env,
        commands=commands,
        verification_queries=verification_queries,
    )

    return PostgresPITRPlan(
        schema="wavemind.postgres_pitr_plan.v1",
        generated_at=generated_at or _utc_now(),
        status=validation.status,
        retention_hours=retention_hours,
        dsn_env=dsn_env,
        basebackup_env=basebackup_env,
        wal_archive_env=wal_archive_env,
        restore_data_env=restore_data_env,
        restore_target_env=restore_target_env,
        required_env=required_env,
        missing_env=missing_env,
        postgresql_settings=settings,
        commands=commands,
        verification_queries=verification_queries,
        safety_notes=safety_notes,
        validation=validation,
    )


def validate_postgres_pitr_commands(
    *,
    required_env: tuple[str, ...],
    missing_env: tuple[str, ...],
    commands: tuple[PostgresPITRCommand, ...],
    verification_queries: tuple[str, ...],
) -> PostgresPITRValidationReport:
    command_text = "\n".join(command.command for command in commands)
    phases = {command.phase for command in commands}
    checks = {
        "has_required_env_contract": bool(required_env),
        "has_wal_archiving_command": "archive_command" in command_text,
        "has_base_backup_command": "pg_basebackup" in command_text and "--wal-method=stream" in command_text,
        "has_restore_command": "restore_command" in command_text,
        "has_recovery_signal": "recovery.signal" in command_text,
        "has_restore_target_time": "recovery_target_time" in command_text,
        "has_replay_verification": any("pg_is_in_recovery" in query for query in verification_queries)
        and any("pg_last_wal_replay_lsn" in query for query in verification_queries),
        "has_promotion_command": "pg_promote" in command_text,
        "has_safe_restore_phase": any(command.destructive for command in commands if command.phase == "restore"),
        "has_full_phase_order": {"preflight", "configure", "backup", "restore", "verify", "promote"}.issubset(phases),
        "secret_values_not_embedded": all(
            os.environ.get(name, "") not in command_text
            for name in required_env
            if os.environ.get(name)
        ),
    }
    warnings: list[str] = []
    if missing_env:
        warnings.append("Environment variables are missing; this is a runnable runbook shape, not an executed drill.")
    status = "ready" if all(checks.values()) else "action_required"
    return PostgresPITRValidationReport(
        status=status,
        checks=checks,
        missing_env=missing_env,
        warnings=tuple(warnings),
    )
