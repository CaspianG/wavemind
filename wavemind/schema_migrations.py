from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from typing import Mapping


MIGRATION_TABLE = "wavemind_schema_migrations"
CORE_COMPONENT = "core"
EXPERIENCE_COMPONENT = "experience"
CURRENT_SCHEMA_VERSION = 1


class SchemaMigrationError(RuntimeError):
    """Raised when a database cannot be migrated without risking user data."""


@dataclass(frozen=True)
class SchemaMigrationState:
    component: str
    current_version: int
    target_version: int
    applied_versions: tuple[int, ...]


_REQUIRED_COLUMNS: Mapping[str, Mapping[str, frozenset[str]]] = {
    CORE_COMPONENT: {
        "memories": frozenset(
            {
                "id",
                "namespace",
                "text",
                "vector",
                "vector_dim",
                "pattern",
                "pattern_shape",
                "tags",
                "metadata",
                "created_at",
                "updated_at",
                "expires_at",
                "priority",
                "access_count",
            }
        ),
        "audit_events": frozenset(
            {"id", "created_at", "action", "namespace", "memory_id", "metadata"}
        ),
    },
    EXPERIENCE_COMPONENT: {
        "experience_records": frozenset(
            {
                "id",
                "namespace",
                "kind",
                "title",
                "content",
                "applicability_json",
                "outcome_json",
                "confidence",
                "trust",
                "source_json",
                "observed_at",
                "created_at",
                "updated_at",
                "trajectory_id",
                "trajectory_json",
                "expires_at",
                "version",
                "status",
                "supersedes_id",
                "rollback_of_id",
                "metadata_json",
                "content_sha256",
                "dedupe_key",
            }
        ),
        "experience_trajectories": frozenset(
            {
                "id",
                "namespace",
                "provider",
                "source_sha256",
                "started_at",
                "ended_at",
                "metadata_json",
                "raw_event_count",
                "created_at",
            }
        ),
        "experience_trajectory_steps": frozenset(
            {
                "trajectory_id",
                "step_id",
                "sequence",
                "kind",
                "name",
                "input_json",
                "output_json",
                "success",
                "started_at",
                "finished_at",
                "parent_id",
                "metadata_json",
            }
        ),
        "experience_audit_events": frozenset(
            {
                "id",
                "action",
                "created_at",
                "experience_id",
                "trajectory_id",
                "metadata_json",
            }
        ),
        "experience_candidate_validations": frozenset(
            {
                "id",
                "experience_id",
                "evidence_id",
                "successful",
                "score",
                "created_at",
                "metadata_json",
            }
        ),
    },
}


def _migration_checksum(component: str, version: int) -> str:
    tables = _REQUIRED_COLUMNS[component]
    contract = "|".join(
        f"{table}:{','.join(sorted(columns))}" for table, columns in sorted(tables.items())
    )
    return hashlib.sha256(f"{component}:{version}:{contract}".encode("utf-8")).hexdigest()


def _table_columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    escaped = table.replace('"', '""')
    return frozenset(
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()
    )


def validate_component_schema(connection: sqlite3.Connection, component: str) -> None:
    if component not in _REQUIRED_COLUMNS:
        raise ValueError(f"unknown schema component: {component}")
    for table, required in _REQUIRED_COLUMNS[component].items():
        actual = _table_columns(connection, table)
        if not actual:
            raise SchemaMigrationError(f"{component} database is missing table {table}")
        missing = sorted(required - actual)
        if missing:
            raise SchemaMigrationError(
                f"{component} table {table} is missing columns: {', '.join(missing)}"
            )


def ensure_schema_migration(
    connection: sqlite3.Connection,
    component: str,
    *,
    release: str,
    target_version: int = CURRENT_SCHEMA_VERSION,
) -> SchemaMigrationState:
    """Validate the schema and record each applied migration transactionally.

    Version 1 adopts the existing WaveMind SQLite schema. Future releases append
    explicit migration steps here instead of silently changing tables on open.
    """

    if target_version != CURRENT_SCHEMA_VERSION:
        raise SchemaMigrationError(
            f"unsupported {component} target schema {target_version}; "
            f"this build supports {CURRENT_SCHEMA_VERSION}"
        )
    validate_component_schema(connection, component)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            release TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at REAL NOT NULL,
            PRIMARY KEY(component, version)
        )
        """
    )
    rows = connection.execute(
        f"SELECT version, checksum FROM {MIGRATION_TABLE} "
        "WHERE component = ? ORDER BY version",
        (component,),
    ).fetchall()
    applied = tuple(int(row[0]) for row in rows)
    if applied and applied != tuple(range(1, max(applied) + 1)):
        raise SchemaMigrationError(f"{component} migration ledger has a version gap")
    if applied and max(applied) > target_version:
        raise SchemaMigrationError(
            f"{component} schema {max(applied)} is newer than supported {target_version}"
        )
    for version, checksum in rows:
        expected = _migration_checksum(component, int(version))
        if str(checksum) != expected:
            raise SchemaMigrationError(
                f"{component} migration {version} checksum does not match this release"
            )
    newly_applied: list[int] = []
    for version in range((max(applied) if applied else 0) + 1, target_version + 1):
        connection.execute(
            f"INSERT INTO {MIGRATION_TABLE} "
            "(component, version, release, checksum, applied_at) VALUES (?, ?, ?, ?, ?)",
            (component, version, release, _migration_checksum(component, version), time.time()),
        )
        newly_applied.append(version)
    return SchemaMigrationState(
        component=component,
        current_version=target_version,
        target_version=target_version,
        applied_versions=tuple(newly_applied),
    )


def read_schema_version(connection: sqlite3.Connection, component: str) -> int:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if MIGRATION_TABLE not in tables:
        return 0
    row = connection.execute(
        f"SELECT MAX(version) FROM {MIGRATION_TABLE} WHERE component = ?",
        (component,),
    ).fetchone()
    return int(row[0] or 0)


def validate_runtime_schema(connection: sqlite3.Connection, component: str) -> int:
    """Validate an opened database without applying migrations implicitly."""

    validate_component_schema(connection, component)
    version = read_schema_version(connection, component)
    if version == 0:
        # Legacy v1 databases remain readable until the operator runs
        # ``wavemind upgrade`` and adopts the explicit ledger.
        return 0
    if version != CURRENT_SCHEMA_VERSION:
        direction = "newer" if version > CURRENT_SCHEMA_VERSION else "older"
        raise SchemaMigrationError(
            f"{component} schema {version} is {direction} than supported "
            f"{CURRENT_SCHEMA_VERSION}; run wavemind upgrade with the matching release"
        )
    rows = connection.execute(
        f"SELECT version, checksum FROM {MIGRATION_TABLE} "
        "WHERE component = ? ORDER BY version",
        (component,),
    ).fetchall()
    applied = tuple(int(row[0]) for row in rows)
    if applied != tuple(range(1, CURRENT_SCHEMA_VERSION + 1)):
        raise SchemaMigrationError(f"{component} migration ledger has a version gap")
    for applied_version, checksum in rows:
        expected = _migration_checksum(component, int(applied_version))
        if str(checksum) != expected:
            raise SchemaMigrationError(
                f"{component} migration {applied_version} checksum does not match this release"
            )
    return version
