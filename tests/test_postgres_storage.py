import sys
from types import SimpleNamespace

import numpy as np
import pytest

from wavemind import HashingTextEncoder, PostgresMemoryStore, WaveMind, create_memory_store
from wavemind.storage import MemoryRecord


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakePostgresConnection:
    def __init__(self, dsn):
        self.dsn = dsn
        self.memories = {}
        self.audit_events = {}
        self.next_memory_id = 1
        self.next_audit_id = 1
        self.calls = []
        self.closed = False
        self.committed = False

    def execute(self, sql, params=None):
        params = list(params or [])
        compact = " ".join(sql.split())
        self.calls.append((compact, params))
        if "CREATE TABLE" in compact or "CREATE INDEX" in compact:
            return FakeResult()
        if "INSERT INTO wm_memories" in compact:
            return self._insert_memory(params)
        if compact.startswith("SELECT * FROM wm_memories"):
            return FakeResult(self._filter_memories(compact, params))
        if compact.startswith("DELETE FROM wm_memories") and "RETURNING id" in compact:
            return self._purge_expired(params)
        if compact.startswith("DELETE FROM wm_memories"):
            rows = self._filter_memories(compact, params)
            for row in rows:
                self.memories.pop(row["id"], None)
            return FakeResult()
        if compact.startswith("UPDATE wm_memories"):
            id = int(params[2])
            row = self.memories[id]
            row["access_count"] += 1
            row["priority"] += float(params[0])
            row["updated_at"] = float(params[1])
            return FakeResult()
        if "INSERT INTO wm_audit" in compact:
            return self._insert_audit(params)
        if compact.startswith("SELECT * FROM wm_audit"):
            return FakeResult(self._filter_audit(compact, params))
        if compact.startswith("SELECT COUNT(*) AS count FROM wm_audit"):
            return FakeResult([{"count": len(self._filter_audit(compact, params))}])
        raise AssertionError(f"Unhandled SQL: {compact}")

    def _insert_memory(self, params):
        id = self.next_memory_id
        self.next_memory_id += 1
        row = {
            "id": id,
            "namespace": params[0],
            "text": params[1],
            "vector": params[2],
            "vector_dim": params[3],
            "pattern": params[4],
            "pattern_shape": params[5],
            "tags": params[6],
            "metadata": params[7],
            "created_at": params[8],
            "updated_at": params[9],
            "expires_at": params[10],
            "priority": params[11],
            "access_count": params[12],
        }
        self.memories[id] = row
        return FakeResult([{"id": id}])

    def _filter_memories(self, sql, params):
        rows = list(self.memories.values())
        param_index = 0
        if "id = %s" in sql:
            id = int(params[param_index])
            param_index += 1
            rows = [row for row in rows if int(row["id"]) == id]
        if "text = %s" in sql:
            text = params[param_index]
            param_index += 1
            rows = [row for row in rows if row["text"] == text]
        if "namespace = %s" in sql:
            namespace = params[param_index]
            param_index += 1
            rows = [row for row in rows if row["namespace"] == namespace]
        if "expires_at IS NULL OR expires_at > %s" in sql:
            cutoff = float(params[param_index])
            rows = [
                row
                for row in rows
                if row["expires_at"] is None or float(row["expires_at"]) > cutoff
            ]
        return rows

    def _purge_expired(self, params):
        cutoff = float(params[0])
        expired = [
            row
            for row in list(self.memories.values())
            if row["expires_at"] is not None and float(row["expires_at"]) <= cutoff
        ]
        for row in expired:
            self.memories.pop(row["id"], None)
        return FakeResult([{"id": row["id"]} for row in expired])

    def _insert_audit(self, params):
        id = self.next_audit_id
        self.next_audit_id += 1
        self.audit_events[id] = {
            "id": id,
            "created_at": params[0],
            "action": params[1],
            "namespace": params[2],
            "memory_id": params[3],
            "metadata": params[4],
        }
        return FakeResult([{"id": id}])

    def _filter_audit(self, sql, params):
        rows = list(self.audit_events.values())
        param_index = 0
        if "namespace = %s" in sql:
            namespace = params[param_index]
            param_index += 1
            rows = [row for row in rows if row["namespace"] == namespace]
        if "action = %s" in sql:
            action = params[param_index]
            rows = [row for row in rows if row["action"] == action]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        if params and isinstance(params[-1], int):
            rows = rows[: params[-1]]
        return rows

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class FakePsycopg:
    def __init__(self):
        self.connections = []

    def connect(self, dsn, autocommit=True, row_factory=None):
        connection = FakePostgresConnection(dsn)
        connection.autocommit = autocommit
        connection.row_factory = row_factory
        self.connections.append(connection)
        return connection


@pytest.fixture
def fake_psycopg(monkeypatch):
    fake = FakePsycopg()
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setitem(sys.modules, "psycopg.rows", SimpleNamespace(dict_row=object()))
    monkeypatch.setenv("WAVEMIND_POSTGRES_DSN", "postgresql://unit-test")
    monkeypatch.setenv("WAVEMIND_POSTGRES_MEMORIES_TABLE", "wm_memories")
    monkeypatch.setenv("WAVEMIND_POSTGRES_AUDIT_TABLE", "wm_audit")
    return fake


def make_record(text="postgres memory", namespace="pg", expires_at=None):
    return MemoryRecord(
        text=text,
        namespace=namespace,
        tags=("db",),
        metadata={"source": "test"},
        vector=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        pattern=np.ones((2, 2), dtype=np.float32),
        expires_at=expires_at,
        priority=2.0,
    )


def test_postgres_store_requires_explicit_dsn(monkeypatch):
    monkeypatch.delenv("WAVEMIND_POSTGRES_DSN", raising=False)

    with pytest.raises(ValueError, match="WAVEMIND_POSTGRES_DSN"):
        create_memory_store("postgres")


def test_postgres_store_rejects_unsafe_table_names(fake_psycopg, monkeypatch):
    monkeypatch.setenv("WAVEMIND_POSTGRES_MEMORIES_TABLE", "bad-name")

    with pytest.raises(ValueError, match="WAVEMIND_POSTGRES_MEMORIES_TABLE"):
        create_memory_store("postgres")


def test_postgres_store_contract(fake_psycopg):
    store = create_memory_store("postgres")
    assert isinstance(store, PostgresMemoryStore)

    record = make_record()
    expired = make_record("expired memory", expires_at=0.0)
    id = store.insert(record)
    expired_id = store.insert(expired)

    assert id == 1
    assert store.get(id).text == "postgres memory"
    assert store.list(namespace="pg")[0].id == id
    assert store.list(namespace="pg", tags=["db"])[0].id == id
    assert store.count(namespace="pg") == 1

    store.touch(id, priority_delta=0.5)
    touched = store.get(id)
    assert touched.access_count == 1
    assert touched.priority == 2.5

    audit_id = store.log_audit_event(
        "remember",
        namespace="pg",
        memory_id=id,
        metadata={"ok": True},
    )
    assert audit_id == 1
    assert store.audit_count(namespace="pg") == 1
    assert store.list_audit_events(namespace="pg")[0].metadata == {"ok": True}

    assert store.purge_expired() == 1
    assert store.get(expired_id) is None

    deleted = store.delete(id=id, namespace="pg")
    assert deleted[0].id == id
    assert store.get(id) is None
    store.commit()
    store.close()
    assert fake_psycopg.connections[-1].committed is True
    assert fake_psycopg.connections[-1].closed is True


def test_wavemind_runs_on_postgres_store(fake_psycopg):
    memory = WaveMind(
        store_kind="postgres",
        encoder=HashingTextEncoder(vector_dim=32),
        width=16,
        height=16,
        layers=1,
        score_threshold=0.0,
    )
    memory_id = memory.remember("Andrey is a trader", namespace="pg")

    results = memory.query("trader", namespace="pg", top_k=1)

    assert results[0].id == memory_id
    assert results[0].text == "Andrey is a trader"
    assert memory.stats(namespace="pg")["active_memories"] == 1
    with pytest.raises(NotImplementedError, match="native backup"):
        memory.save("backup.sqlite3")
    memory.close()
