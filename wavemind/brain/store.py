"""Private SQLite state and the transaction boundary for every Brain operation."""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import BrainError


# Schema version 1. All child keys include brain_id; source/version references
# also include source_id. JSON payloads are versioned extension points for the
# source, reconciliation, context and experience modules, not authority inputs.
_SCHEMA = (
    """CREATE TABLE brains (
        id TEXT PRIMARY KEY, title TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('personal','team')),
        owner TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1)
    )""",
    """CREATE TABLE members (
        brain_id TEXT NOT NULL, identity TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('owner','editor','reader')),
        PRIMARY KEY(brain_id,identity),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE sources (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'text',
        status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','paused','revoked','quarantined','deleted')),
        readers_json TEXT DEFAULT NULL,
        created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE source_versions (
        brain_id TEXT NOT NULL, source_id TEXT NOT NULL, id TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
        digest TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'text',
        status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL DEFAULT 0,
        schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(brain_id,source_id,id), UNIQUE(brain_id,id),
        UNIQUE(brain_id,source_id,version), UNIQUE(brain_id,source_id,digest),
        FOREIGN KEY(brain_id,source_id) REFERENCES sources(brain_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE chunks (
        brain_id TEXT NOT NULL, source_id TEXT NOT NULL, version_id TEXT NOT NULL,
        id TEXT NOT NULL, ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal >= 0),
        text TEXT NOT NULL DEFAULT '', locator_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(brain_id,id),
        UNIQUE(brain_id,source_id,version_id,ordinal),
        FOREIGN KEY(brain_id,source_id,version_id)
            REFERENCES source_versions(brain_id,source_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE previews (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, principal_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', revision INTEGER NOT NULL DEFAULT 1,
        created_at REAL NOT NULL DEFAULT 0, expires_at REAL,
        schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE entities (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
            CHECK(status IN ('proposed','active','conflicted','superseded','revoked')),
        schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE claims (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
            CHECK(status IN ('proposed','active','conflicted','superseded','revoked')),
        valid_from REAL, valid_until REAL, recorded_at REAL NOT NULL DEFAULT 0,
        schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE relations (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
            CHECK(status IN ('proposed','active','conflicted','superseded','revoked')),
        schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE dependencies (
        brain_id TEXT NOT NULL, dependent_type TEXT NOT NULL, dependent_id TEXT NOT NULL,
        origin_type TEXT NOT NULL, origin_id TEXT NOT NULL, source_id TEXT NOT NULL,
        PRIMARY KEY(brain_id,dependent_type,dependent_id,origin_type,origin_id,source_id),
        FOREIGN KEY(brain_id,source_id) REFERENCES sources(brain_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE packets (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, principal_id TEXT NOT NULL,
        revision INTEGER NOT NULL, digest TEXT NOT NULL,
        created_at REAL NOT NULL DEFAULT 0, expires_at REAL,
        status TEXT NOT NULL DEFAULT 'active', schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE receipts (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, packet_id TEXT NOT NULL,
        principal_id TEXT NOT NULL, packet_digest TEXT NOT NULL,
        created_at REAL NOT NULL DEFAULT 0, schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id,packet_id) REFERENCES packets(brain_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE outcomes (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, receipt_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', verifier_id TEXT,
        created_at REAL NOT NULL DEFAULT 0, schema_version INTEGER NOT NULL DEFAULT 1,
        payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id,receipt_id) REFERENCES receipts(brain_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE outbox (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', source_id TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL DEFAULT 0,
        schema_version INTEGER NOT NULL DEFAULT 1, payload_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE,
        FOREIGN KEY(brain_id,source_id) REFERENCES sources(brain_id,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE tombstones (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        record_id TEXT NOT NULL, revision INTEGER NOT NULL,
        created_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE audit (
        brain_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
        record_id TEXT NOT NULL, revision INTEGER NOT NULL,
        created_at REAL NOT NULL, PRIMARY KEY(brain_id,id),
        FOREIGN KEY(brain_id) REFERENCES brains(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX members_identity ON members(identity,brain_id)",
    "CREATE INDEX dependencies_origin ON dependencies(brain_id,origin_type,origin_id)",
    "CREATE INDEX dependencies_source ON dependencies(brain_id,source_id)",
)


class BrainStore:
    """One authoritative database, with SQLite serialization across processes."""

    def __init__(self, state_dir: Path):
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "brain.sqlite3"
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(
            self.path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            with self.transaction(write=True) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in _SCHEMA:
                        conn.execute(statement)
                    conn.execute("PRAGMA user_version=1")
                elif version != 1:
                    raise BrainError(
                        "unsupported_schema", "Unsupported Brain schema version."
                    )
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self, *, write: bool = False):
        """Yield a single snapshot; writers obtain the lock before authorization.

        Never use executescript inside this boundary: sqlite3 would commit the
        current transaction before running the script. Nested transactions are
        rejected instead of accidentally committing their caller's changes.
        """
        with self._lock:
            if self._closed:
                raise BrainError("closed", "Brain store is closed.")
            if self._conn.in_transaction:
                raise BrainError(
                    "nested_transaction", "Nested Brain transactions are unsupported."
                )
            self._conn.execute("PRAGMA query_only=" + ("OFF" if write else "ON"))
            self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            finally:
                self._conn.execute("PRAGMA query_only=OFF")

    def close(self):
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def record_change(
    conn, *, brain_id: str, kind: str, record_id: str, increment: bool = True
):
    """Record only an operation type and opaque IDs in the caller's transaction."""
    if increment:
        conn.execute("UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,))
    conn.execute(
        """INSERT INTO audit(brain_id,id,kind,record_id,revision,created_at)
           SELECT id,?,?,?,revision,? FROM brains WHERE id=?""",
        (uuid4().hex, kind, record_id, time.time(), brain_id),
    )
