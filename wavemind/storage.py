from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
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
        self.ensure_schema()

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

    def close(self) -> None:
        self.conn.close()

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

