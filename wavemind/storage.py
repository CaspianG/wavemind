from __future__ import annotations

import json
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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


def _array_to_blob(array: np.ndarray) -> bytes:
    return np.asarray(array, dtype=np.float32).tobytes()


def _array_from_blob(blob: bytes, shape: Iterable[int]) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy().reshape(tuple(shape))


class SQLiteMemoryStore:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or ":memory:")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._closed = False
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

    def get(self, id: int) -> MemoryRecord | None:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (int(id),)).fetchone()
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

    def count(self, namespace: str | None = None, include_expired: bool = False) -> int:
        return len(self.list(namespace=namespace, include_expired=include_expired))

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
