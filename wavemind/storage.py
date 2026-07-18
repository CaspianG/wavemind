from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

import numpy as np


@dataclass
class MemoryRecord:
    text: str
    vector: np.ndarray
    pattern: np.ndarray
    namespace: str = "default"
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    priority: float = 1.0
    access_count: int = 0
    id: int | None = None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()


@dataclass(frozen=True)
class AuditEvent:
    action: str
    created_at: float
    namespace: str | None = None
    memory_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True)
class RecoveryJournalReport:
    journal_path: str
    destination_path: str
    until: float | None
    applied_entries: int
    skipped_entries: int
    remembered_records: int
    deleted_records: int
    restored_records: int

    @property
    def ok(self) -> bool:
        return self.applied_entries > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "journal_path": self.journal_path,
            "destination_path": self.destination_path,
            "until": self.until,
            "applied_entries": self.applied_entries,
            "skipped_entries": self.skipped_entries,
            "remembered_records": self.remembered_records,
            "deleted_records": self.deleted_records,
            "restored_records": self.restored_records,
            "ok": self.ok,
        }


def _array_to_blob(array: np.ndarray) -> bytes:
    return np.asarray(array, dtype=np.float32).tobytes()


def _array_from_blob(blob: bytes, shape: Iterable[int]) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy().reshape(tuple(shape))


def _array_to_payload(array: np.ndarray) -> dict[str, Any]:
    array = np.asarray(array, dtype=np.float32)
    return {
        "shape": list(array.shape),
        "data_b64": base64.b64encode(_array_to_blob(array)).decode("ascii"),
    }


def _array_from_payload(payload: dict[str, Any]) -> np.ndarray:
    return _array_from_blob(
        base64.b64decode(str(payload["data_b64"]).encode("ascii")),
        tuple(int(value) for value in payload["shape"]),
    )


def _record_to_journal_payload(record: MemoryRecord) -> dict[str, Any]:
    if record.id is None:
        raise ValueError("Recovery journal records require a persisted memory id")
    return {
        "id": int(record.id),
        "namespace": record.namespace,
        "text": record.text,
        "vector": _array_to_payload(record.vector),
        "pattern": _array_to_payload(record.pattern),
        "tags": list(record.tags),
        "metadata": record.metadata,
        "created_at": float(record.created_at),
        "updated_at": float(record.updated_at),
        "expires_at": record.expires_at,
        "priority": float(record.priority),
        "access_count": int(record.access_count),
    }


def _record_from_journal_payload(payload: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        id=int(payload["id"]),
        namespace=str(payload["namespace"]),
        text=str(payload["text"]),
        vector=_array_from_payload(payload["vector"]),
        pattern=_array_from_payload(payload["pattern"]),
        tags=tuple(str(tag) for tag in payload.get("tags", [])),
        metadata=dict(payload.get("metadata") or {}),
        created_at=float(payload["created_at"]),
        updated_at=float(payload["updated_at"]),
        expires_at=payload.get("expires_at"),
        priority=float(payload.get("priority", 1.0)),
        access_count=int(payload.get("access_count", 0)),
    )


def _journal_entries(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Recovery journal does not exist: {path}")
    entries = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("schema") != "wavemind.recovery_journal.v1":
                raise ValueError(
                    f"Unsupported recovery journal schema at {path}:{line_number}"
                )
            entries.append(payload)
    return entries


def append_recovery_journal_entry(
    path: str | Path,
    action: str,
    records: Iterable[MemoryRecord],
    *,
    created_at: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action not in {"remember", "forget", "purge_expired"}:
        raise ValueError(
            "Recovery journal action must be remember, forget, or purge_expired"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema": "wavemind.recovery_journal.v1",
        "created_at": float(created_at or time.time()),
        "action": action,
        "records": [_record_to_journal_payload(record) for record in records],
        "metadata": metadata or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def restore_recovery_journal(
    journal_path: str | Path,
    destination: str | Path,
    *,
    until: float | None = None,
    overwrite: bool = False,
) -> RecoveryJournalReport:
    journal_path = Path(journal_path)
    destination = Path(destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Destination already exists: {destination}. Pass overwrite=True to replace it."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    store = SQLiteMemoryStore(destination)
    applied = 0
    skipped = 0
    remembered = 0
    deleted = 0
    try:
        for entry in _journal_entries(journal_path):
            if until is not None and float(entry["created_at"]) > float(until):
                skipped += 1
                continue
            applied += 1
            records = [
                _record_from_journal_payload(payload)
                for payload in entry.get("records", [])
            ]
            if entry["action"] == "remember":
                for record in records:
                    store.insert_recovered(record)
                    remembered += 1
            elif entry["action"] in {"forget", "purge_expired"}:
                for record in records:
                    deleted += len(store.delete(id=record.id))
            else:
                raise ValueError(f"Unsupported recovery journal action: {entry['action']}")
        restored = store.count(include_expired=True)
    finally:
        store.close()

    return RecoveryJournalReport(
        journal_path=str(journal_path),
        destination_path=str(destination),
        until=until,
        applied_entries=applied,
        skipped_entries=skipped,
        remembered_records=remembered,
        deleted_records=deleted,
        restored_records=restored,
    )


def _safe_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} must be a simple SQL identifier")
    return value


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key)


def _serialized_sqlite(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._connection_lock:
            return method(self, *args, **kwargs)

    return wrapped


class SQLiteMemoryStore:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or ":memory:")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection_lock = RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._closed = False
        self._configure_connection()
        self.ensure_schema()

    def __enter__(self) -> "SQLiteMemoryStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @_serialized_sqlite
    def _configure_connection(self) -> None:
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")

    @_serialized_sqlite
    def ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL,
                vector_dim INTEGER NOT NULL,
                pattern BLOB NOT NULL,
                pattern_shape TEXT NOT NULL,
                tags TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                priority REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at)")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                action TEXT NOT NULL,
                namespace TEXT,
                memory_id INTEGER,
                metadata TEXT NOT NULL
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_namespace ON audit_events(namespace)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at)")
        self.conn.commit()

    @_serialized_sqlite
    def insert(self, record: MemoryRecord) -> int:
        now = time.time()
        record.created_at = record.created_at or now
        record.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO memories (
                namespace, text, vector, vector_dim, pattern, pattern_shape,
                tags, metadata, created_at, updated_at, expires_at, priority, access_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.namespace,
                record.text,
                _array_to_blob(record.vector),
                int(record.vector.shape[0]),
                _array_to_blob(record.pattern),
                json.dumps(list(record.pattern.shape)),
                json.dumps(list(record.tags), ensure_ascii=False),
                json.dumps(record.metadata, ensure_ascii=False),
                record.created_at,
                record.updated_at,
                record.expires_at,
                float(record.priority),
                int(record.access_count),
            ),
        )
        self.conn.commit()
        record.id = int(cur.lastrowid)
        return record.id

    @_serialized_sqlite
    def insert_recovered(self, record: MemoryRecord) -> int:
        if record.id is None:
            raise ValueError("Recovered records require an explicit id")
        self.conn.execute(
            """
            INSERT INTO memories (
                id, namespace, text, vector, vector_dim, pattern, pattern_shape,
                tags, metadata, created_at, updated_at, expires_at, priority, access_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(record.id),
                record.namespace,
                record.text,
                _array_to_blob(record.vector),
                int(record.vector.shape[0]),
                _array_to_blob(record.pattern),
                json.dumps(list(record.pattern.shape)),
                json.dumps(list(record.tags), ensure_ascii=False),
                json.dumps(record.metadata, ensure_ascii=False),
                float(record.created_at),
                float(record.updated_at),
                record.expires_at,
                float(record.priority),
                int(record.access_count),
            ),
        )
        self.conn.commit()
        return int(record.id)

    @_serialized_sqlite
    def get(self, id: int) -> MemoryRecord | None:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (int(id),)).fetchone()
        return self._row_to_record(row) if row else None

    @_serialized_sqlite
    def list(
        self,
        namespace: str | None = None,
        include_expired: bool = False,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = ?")
            params.append(namespace)
        if not include_expired:
            where.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(time.time())
        sql = "SELECT * FROM memories"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.conn.execute(sql, params).fetchall()
        records = [self._row_to_record(row) for row in rows]
        required_tags = set(tags or [])
        if required_tags:
            records = [
                record
                for record in records
                if required_tags.issubset(set(record.tags))
            ]
        return records

    @_serialized_sqlite
    def delete(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str | None = None,
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = []
        if id is not None:
            where.append("id = ?")
            params.append(int(id))
        if text is not None:
            where.append("text = ?")
            params.append(text)
        if namespace is not None:
            where.append("namespace = ?")
            params.append(namespace)
        if not where:
            raise ValueError("delete requires id or text")

        sql_where = " AND ".join(where)
        rows = self.conn.execute(f"SELECT * FROM memories WHERE {sql_where}", params).fetchall()
        records = [self._row_to_record(row) for row in rows]
        self.conn.execute(f"DELETE FROM memories WHERE {sql_where}", params)
        self.conn.commit()
        return records

    @_serialized_sqlite
    def purge_expired(self) -> int:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (time.time(),),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            self.conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", ids)
            self.conn.commit()
        return len(ids)

    @_serialized_sqlite
    def touch(self, id: int, priority_delta: float = 0.05) -> None:
        self.conn.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1,
                priority = priority + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (float(priority_delta), time.time(), int(id)),
        )
        self.conn.commit()

    @_serialized_sqlite
    def update_memory_state(
        self,
        id: int,
        *,
        priority: float | None = None,
        access_count: int | None = None,
    ) -> None:
        fields = []
        params: list[Any] = []
        if priority is not None:
            fields.append("priority = ?")
            params.append(float(priority))
        if access_count is not None:
            fields.append("access_count = ?")
            params.append(int(access_count))
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(time.time())
        params.append(int(id))
        self.conn.execute(
            f"UPDATE memories SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self.conn.commit()

    @_serialized_sqlite
    def log_audit_event(
        self,
        action: str,
        namespace: str | None = None,
        memory_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO audit_events (
                created_at, action, namespace, memory_id, metadata
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                action,
                namespace,
                int(memory_id) if memory_id is not None else None,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    @_serialized_sqlite
    def apply_feedback_batch(self, updates: Iterable[dict[str, Any]]) -> None:
        rows = list(updates)
        if not rows:
            return
        now = time.time()
        with self.conn:
            self.conn.executemany(
                """
                UPDATE memories
                SET priority = ?,
                    access_count = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                [
                    (
                        float(row["priority"]),
                        int(row["access_count"]),
                        now,
                        int(row["id"]),
                    )
                    for row in rows
                ],
            )
            self.conn.executemany(
                """
                INSERT INTO audit_events (
                    created_at, action, namespace, memory_id, metadata
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        now,
                        "feedback",
                        row.get("namespace"),
                        int(row["id"]),
                        json.dumps(row.get("metadata") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )

    @_serialized_sqlite
    def list_audit_events(
        self,
        namespace: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = ?")
            params.append(namespace)
        if action is not None:
            where.append("action = ?")
            params.append(action)
        sql = "SELECT * FROM audit_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(0, int(limit)))
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_audit_event(row) for row in rows]

    @_serialized_sqlite
    def audit_count(
        self,
        namespace: str | None = None,
        action: str | None = None,
    ) -> int:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = ?")
            params.append(namespace)
        if action is not None:
            where.append("action = ?")
            params.append(action)
        sql = "SELECT COUNT(*) FROM audit_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return int(self.conn.execute(sql, params).fetchone()[0])

    @_serialized_sqlite
    def count(self, namespace: str | None = None, include_expired: bool = False) -> int:
        return len(self.list(namespace=namespace, include_expired=include_expired))

    @_serialized_sqlite
    def backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        with target:
            self.conn.backup(target)
        target.close()
        return destination

    def backup_timestamped(
        self,
        directory: str | Path,
        prefix: str = "wavemind",
        keep_last: int | None = None,
    ) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destination = directory / f"{prefix}-{timestamp}.sqlite3"
        if destination.exists():
            destination = directory / f"{prefix}-{timestamp}-{time.time_ns()}.sqlite3"
        path = self.backup(destination)
        if keep_last is not None:
            self.prune_backups(directory, prefix=prefix, keep_last=keep_last)
        return path

    @staticmethod
    def prune_backups(
        directory: str | Path,
        prefix: str = "wavemind",
        keep_last: int = 10,
    ) -> list[Path]:
        keep_last = max(0, int(keep_last))
        directory = Path(directory)
        if not directory.exists():
            return []
        backups = sorted(
            directory.glob(f"{prefix}-*.sqlite3"),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        deleted = []
        for path in backups[keep_last:]:
            path.unlink()
            deleted.append(path)
        return deleted

    @staticmethod
    def restore_backup(
        source: str | Path,
        destination: str | Path,
        overwrite: bool = False,
    ) -> Path:
        source = Path(source)
        destination = Path(destination)
        if not source.exists():
            raise FileNotFoundError(f"Backup does not exist: {source}")
        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"Destination already exists: {destination}. Pass overwrite=True to replace it."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(source)) as source_conn:
            source_conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        if destination.exists():
            destination.unlink()
        shutil.copy2(source, destination)
        return destination

    restore_recovery_journal = staticmethod(restore_recovery_journal)

    @_serialized_sqlite
    def commit(self) -> None:
        self.conn.commit()

    @_serialized_sqlite
    def close(self) -> None:
        if self._closed:
            return
        self.conn.close()
        self._closed = True

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        pattern_shape = json.loads(row["pattern_shape"])
        vector_dim = int(row["vector_dim"])
        return MemoryRecord(
            id=int(row["id"]),
            namespace=row["namespace"],
            text=row["text"],
            vector=_array_from_blob(row["vector"], (vector_dim,)),
            pattern=_array_from_blob(row["pattern"], pattern_shape),
            tags=tuple(json.loads(row["tags"])),
            metadata=json.loads(row["metadata"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            expires_at=row["expires_at"],
            priority=float(row["priority"]),
            access_count=int(row["access_count"]),
        )

    def _row_to_audit_event(self, row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=int(row["id"]),
            created_at=float(row["created_at"]),
            action=row["action"],
            namespace=row["namespace"],
            memory_id=int(row["memory_id"]) if row["memory_id"] is not None else None,
            metadata=json.loads(row["metadata"]),
        )


class PostgresMemoryStore:
    def __init__(
        self,
        dsn: str | None = None,
        memories_table: str | None = None,
        audit_table: str | None = None,
    ):
        self.dsn = dsn or os.environ.get("WAVEMIND_POSTGRES_DSN")
        if not self.dsn:
            raise ValueError(
                "Set WAVEMIND_POSTGRES_DSN to use the postgres storage backend"
            )
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise ImportError(
                'Install PostgreSQL support with: pip install "wavemind[postgres]"'
            ) from exc
        self._psycopg = psycopg
        self.memories_table = _safe_identifier(
            memories_table
            or os.environ.get("WAVEMIND_POSTGRES_MEMORIES_TABLE", "wavemind_memories"),
            "WAVEMIND_POSTGRES_MEMORIES_TABLE",
        )
        self.audit_table = _safe_identifier(
            audit_table
            or os.environ.get("WAVEMIND_POSTGRES_AUDIT_TABLE", "wavemind_audit_events"),
            "WAVEMIND_POSTGRES_AUDIT_TABLE",
        )
        self.conn = psycopg.connect(
            self.dsn,
            autocommit=True,
            row_factory=dict_row,
        )
        self._closed = False
        self.ensure_schema()

    def __enter__(self) -> "PostgresMemoryStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def ensure_schema(self) -> None:
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.memories_table} (
                id BIGSERIAL PRIMARY KEY,
                namespace TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BYTEA NOT NULL,
                vector_dim INTEGER NOT NULL,
                pattern BYTEA NOT NULL,
                pattern_shape TEXT NOT NULL,
                tags TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                expires_at DOUBLE PRECISION,
                priority DOUBLE PRECISION NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.memories_table}_namespace_idx "
            f"ON {self.memories_table} (namespace)"
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.memories_table}_expires_at_idx "
            f"ON {self.memories_table} (expires_at)"
        )
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.audit_table} (
                id BIGSERIAL PRIMARY KEY,
                created_at DOUBLE PRECISION NOT NULL,
                action TEXT NOT NULL,
                namespace TEXT,
                memory_id BIGINT,
                metadata TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.audit_table}_action_idx "
            f"ON {self.audit_table} (action)"
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.audit_table}_namespace_idx "
            f"ON {self.audit_table} (namespace)"
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.audit_table}_created_at_idx "
            f"ON {self.audit_table} (created_at)"
        )

    def insert(self, record: MemoryRecord) -> int:
        now = time.time()
        record.created_at = record.created_at or now
        record.updated_at = now
        row = self.conn.execute(
            f"""
            INSERT INTO {self.memories_table} (
                namespace, text, vector, vector_dim, pattern, pattern_shape,
                tags, metadata, created_at, updated_at, expires_at, priority, access_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                record.namespace,
                record.text,
                _array_to_blob(record.vector),
                int(record.vector.shape[0]),
                _array_to_blob(record.pattern),
                json.dumps(list(record.pattern.shape)),
                json.dumps(list(record.tags), ensure_ascii=False),
                json.dumps(record.metadata, ensure_ascii=False),
                record.created_at,
                record.updated_at,
                record.expires_at,
                float(record.priority),
                int(record.access_count),
            ),
        ).fetchone()
        record.id = int(_row_get(row, "id"))
        return record.id

    def get(self, id: int) -> MemoryRecord | None:
        row = self.conn.execute(
            f"SELECT * FROM {self.memories_table} WHERE id = %s",
            (int(id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list(
        self,
        namespace: str | None = None,
        include_expired: bool = False,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if not include_expired:
            where.append("(expires_at IS NULL OR expires_at > %s)")
            params.append(time.time())
        sql = f"SELECT * FROM {self.memories_table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.conn.execute(sql, params).fetchall()
        records = [self._row_to_record(row) for row in rows]
        required_tags = set(tags or [])
        if required_tags:
            records = [
                record
                for record in records
                if required_tags.issubset(set(record.tags))
            ]
        return records

    def delete(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str | None = None,
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = []
        if id is not None:
            where.append("id = %s")
            params.append(int(id))
        if text is not None:
            where.append("text = %s")
            params.append(text)
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if not where:
            raise ValueError("delete requires id or text")

        sql_where = " AND ".join(where)
        rows = self.conn.execute(
            f"SELECT * FROM {self.memories_table} WHERE {sql_where}",
            params,
        ).fetchall()
        records = [self._row_to_record(row) for row in rows]
        self.conn.execute(
            f"DELETE FROM {self.memories_table} WHERE {sql_where}",
            params,
        )
        return records

    def purge_expired(self) -> int:
        rows = self.conn.execute(
            f"""
            DELETE FROM {self.memories_table}
            WHERE expires_at IS NOT NULL AND expires_at <= %s
            RETURNING id
            """,
            (time.time(),),
        ).fetchall()
        return len(rows)

    def touch(self, id: int, priority_delta: float = 0.05) -> None:
        self.conn.execute(
            f"""
            UPDATE {self.memories_table}
            SET access_count = access_count + 1,
                priority = priority + %s,
                updated_at = %s
            WHERE id = %s
            """,
            (float(priority_delta), time.time(), int(id)),
        )

    def update_memory_state(
        self,
        id: int,
        *,
        priority: float | None = None,
        access_count: int | None = None,
    ) -> None:
        fields = []
        params: list[Any] = []
        if priority is not None:
            fields.append("priority = %s")
            params.append(float(priority))
        if access_count is not None:
            fields.append("access_count = %s")
            params.append(int(access_count))
        if not fields:
            return
        fields.append("updated_at = %s")
        params.append(time.time())
        params.append(int(id))
        self.conn.execute(
            f"UPDATE {self.memories_table} SET {', '.join(fields)} WHERE id = %s",
            params,
        )

    def log_audit_event(
        self,
        action: str,
        namespace: str | None = None,
        memory_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        row = self.conn.execute(
            f"""
            INSERT INTO {self.audit_table} (
                created_at, action, namespace, memory_id, metadata
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                time.time(),
                action,
                namespace,
                int(memory_id) if memory_id is not None else None,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        ).fetchone()
        return int(_row_get(row, "id"))

    def apply_feedback_batch(self, updates: Iterable[dict[str, Any]]) -> None:
        rows = list(updates)
        if not rows:
            return
        now = time.time()
        transaction = getattr(self.conn, "transaction", None)
        context = transaction() if callable(transaction) else None
        if context is None:
            for row in rows:
                self._apply_feedback_batch_row(row, now)
            return
        with context:
            for row in rows:
                self._apply_feedback_batch_row(row, now)

    def _apply_feedback_batch_row(self, row: dict[str, Any], now: float) -> None:
        self.conn.execute(
            f"""
            UPDATE {self.memories_table}
            SET priority = %s,
                access_count = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                float(row["priority"]),
                int(row["access_count"]),
                now,
                int(row["id"]),
            ),
        )
        self.conn.execute(
            f"""
            INSERT INTO {self.audit_table} (
                created_at, action, namespace, memory_id, metadata
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                now,
                "feedback",
                row.get("namespace"),
                int(row["id"]),
                json.dumps(row.get("metadata") or {}, ensure_ascii=False),
            ),
        )

    def list_audit_events(
        self,
        namespace: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if action is not None:
            where.append("action = %s")
            params.append(action)
        sql = f"SELECT * FROM {self.audit_table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(max(0, int(limit)))
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_audit_event(row) for row in rows]

    def audit_count(
        self,
        namespace: str | None = None,
        action: str | None = None,
    ) -> int:
        params: list[Any] = []
        where = []
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if action is not None:
            where.append("action = %s")
            params.append(action)
        sql = f"SELECT COUNT(*) AS count FROM {self.audit_table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        row = self.conn.execute(sql, params).fetchone()
        return int(_row_get(row, "count"))

    def count(self, namespace: str | None = None, include_expired: bool = False) -> int:
        return len(self.list(namespace=namespace, include_expired=include_expired))

    def commit(self) -> None:
        commit = getattr(self.conn, "commit", None)
        if callable(commit):
            commit()

    def close(self) -> None:
        if self._closed:
            return
        self.conn.close()
        self._closed = True

    def _row_to_record(self, row: Any) -> MemoryRecord:
        pattern_shape = json.loads(_row_get(row, "pattern_shape"))
        vector_dim = int(_row_get(row, "vector_dim"))
        return MemoryRecord(
            id=int(_row_get(row, "id")),
            namespace=_row_get(row, "namespace"),
            text=_row_get(row, "text"),
            vector=_array_from_blob(_row_get(row, "vector"), (vector_dim,)),
            pattern=_array_from_blob(_row_get(row, "pattern"), pattern_shape),
            tags=tuple(json.loads(_row_get(row, "tags"))),
            metadata=json.loads(_row_get(row, "metadata")),
            created_at=float(_row_get(row, "created_at")),
            updated_at=float(_row_get(row, "updated_at")),
            expires_at=_row_get(row, "expires_at"),
            priority=float(_row_get(row, "priority")),
            access_count=int(_row_get(row, "access_count")),
        )

    def _row_to_audit_event(self, row: Any) -> AuditEvent:
        memory_id = _row_get(row, "memory_id")
        return AuditEvent(
            id=int(_row_get(row, "id")),
            created_at=float(_row_get(row, "created_at")),
            action=_row_get(row, "action"),
            namespace=_row_get(row, "namespace"),
            memory_id=int(memory_id) if memory_id is not None else None,
            metadata=json.loads(_row_get(row, "metadata")),
        )


def create_memory_store(
    kind: str | None = None,
    path: str | Path | None = None,
    postgres_dsn: str | None = None,
):
    kind = (kind or os.environ.get("WAVEMIND_STORE", "sqlite")).lower()
    if kind in {"sqlite", "local"}:
        return SQLiteMemoryStore(path)
    if kind in {"postgres", "postgresql"}:
        return PostgresMemoryStore(dsn=postgres_dsn)
    raise ValueError(
        f"Unknown memory store kind: {kind}. Choose an explicit store: sqlite or postgres."
    )
