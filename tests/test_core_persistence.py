import json
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from wavemind import (
    HashingTextEncoder,
    MemoryRecord,
    QueryResult,
    SQLiteMemoryStore,
    WaveField,
    WaveMind,
)


def make_mind(db_path: Path, **kwargs) -> WaveMind:
    params = {
        "db_path": db_path,
        "width": 32,
        "height": 32,
        "layers": 2,
        "encoder": HashingTextEncoder(vector_dim=64),
        "score_threshold": 0.05,
    }
    params.update(kwargs)
    return WaveMind(**params)


def test_query_filters_exact_or_allowed_metadata_values(tmp_path):
    mind = make_mind(tmp_path / "metadata-filter.sqlite3", score_threshold=0.0)
    try:
        alpha = mind.remember(
            "shared workflow evidence",
            namespace="agent",
            metadata={"trajectory_id": "alpha", "state": "complete"},
        )
        beta = mind.remember(
            "shared workflow evidence",
            namespace="agent",
            metadata={"trajectory_id": "beta", "state": "complete"},
        )

        exact = mind.query(
            "workflow evidence",
            namespace="agent",
            top_k=5,
            metadata_filters={"trajectory_id": "alpha"},
        )
        allowed = mind.query(
            "workflow evidence",
            namespace="agent",
            top_k=5,
            metadata_filters={"trajectory_id": ("beta", "gamma")},
        )

        assert [row.id for row in exact] == [alpha]
        assert [row.id for row in allowed] == [beta]
    finally:
        mind.close()


def test_sqlite_store_serializes_shared_connection_access(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "concurrent.sqlite3")
    entered = threading.Event()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            with store._connection_lock:
                blocked = pool.submit(
                    lambda: (entered.set(), store.audit_count(namespace="concurrent"))[1]
                )
                assert entered.wait(timeout=1.0)
                time.sleep(0.02)
                assert not blocked.done()
            assert blocked.result(timeout=1.0) == 0

            def exercise(index: int) -> int:
                store.log_audit_event(
                    "concurrent",
                    namespace="concurrent",
                    metadata={"index": index},
                )
                return store.audit_count(namespace="concurrent")

            counts = list(pool.map(exercise, range(200)))

        assert len(counts) == 200
        assert store.audit_count(namespace="concurrent") == 200
        assert len(store.list_audit_events(namespace="concurrent", limit=250)) == 200
    finally:
        store.close()


def test_wave_field_evolve_remains_finite_after_repeated_strong_feedback():
    field = WaveField(width=16, height=16, layers=2)
    pattern = np.ones((16, 16), dtype=np.float32)

    for _ in range(100):
        field.feed(pattern, strength=9.0)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        field.evolve(8)
        energy = field.energy()

    assert np.all(np.isfinite(field.state))
    assert np.isfinite(energy)
    assert np.max(np.abs(field.state)) <= 12.0


def test_hash_encoder_skips_character_scan_when_weight_is_zero(monkeypatch):
    encoder = HashingTextEncoder(vector_dim=32, char_ngram_weight=0.0)
    features: list[str] = []
    original = encoder._add_feature

    def track_feature(vector, feature, weight):
        features.append(feature)
        original(vector, feature, weight)

    monkeypatch.setattr(encoder, "_add_feature", track_feature)
    encoder.encode_vector("alpha beta " * 1_000)

    assert features
    assert all(feature.startswith("tok:") for feature in features)


def test_remember_query_persist_and_load(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    mind = make_mind(db_path)

    first_id = mind.remember(
        "кошка сидит на подоконнике",
        namespace="pets",
        tags=["animal", "home"],
        metadata={"source": "unit"},
    )
    mind.remember("собака лает во дворе", namespace="pets", tags=["animal"])
    mind.remember("market signal breaks resistance", namespace="markets", tags=["trading"])
    mind.save()

    results = mind.query("кошка", namespace="pets", top_k=2)
    assert isinstance(results[0], QueryResult)
    assert results[0].id == first_id
    assert results[0].text == "кошка сидит на подоконнике"
    assert results[0].namespace == "pets"
    assert set(results[0].tags) == {"animal", "home"}

    reloaded = make_mind(db_path)
    reloaded.load()
    reloaded_results = reloaded.query("кошка", namespace="pets", top_k=1)
    assert reloaded_results[0].text == "кошка сидит на подоконнике"


def test_remember_batch_persists_audits_and_journals_as_one_operation(tmp_path):
    db_path = tmp_path / "batch.sqlite3"
    journal_path = tmp_path / "batch.recovery.jsonl"
    mind = make_mind(
        db_path,
        recovery_journal_path=journal_path,
        evolve_on_feed=0,
    )
    try:
        ids = mind.remember_batch(
            [
                {
                    "text": "Andrey is a trader",
                    "namespace": "profile",
                    "tags": ["identity"],
                    "metadata": {"source": "batch"},
                },
                {
                    "text": "The budget is 2000 dollars",
                    "namespace": "profile",
                    "ttl_seconds": 60,
                    "priority": 2.0,
                },
            ]
        )

        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert mind.query("trader", namespace="profile", top_k=1)[0].id == ids[0]
        assert mind.store.get(ids[1]).priority == 2.0
        events = mind.audit_events(
            namespace="profile",
            action="remember",
            limit=10,
        )
        assert {event.memory_id for event in events} == set(ids)
        assert all(event.metadata["batch"] is True for event in events)
        journal_rows = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(journal_rows) == 1
        assert len(journal_rows[0]["records"]) == 2
        assert journal_rows[0]["metadata"] == {"batch": True, "count": 2}
    finally:
        mind.close()

    reloaded = make_mind(db_path, evolve_on_feed=0)
    try:
        assert reloaded.query("budget", namespace="profile", top_k=1)[0].id == ids[1]
    finally:
        reloaded.close()


def test_sqlite_insert_many_rolls_back_the_entire_batch(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "atomic-batch.sqlite3")
    good = MemoryRecord(
        text="valid",
        namespace="atomic",
        vector=np.ones(4, dtype=np.float32),
        pattern=np.ones((2, 2), dtype=np.float32),
    )
    invalid = MemoryRecord(
        text="invalid metadata",
        namespace="atomic",
        metadata={"not_json": object()},
        vector=np.ones(4, dtype=np.float32),
        pattern=np.ones((2, 2), dtype=np.float32),
    )
    try:
        with pytest.raises(TypeError):
            store.insert_many([good, invalid])

        assert store.count(namespace="atomic") == 0
        assert good.id is None
        assert invalid.id is None
    finally:
        store.close()


def test_namespace_tags_threshold_ttl_and_forget(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    mind = make_mind(db_path, score_threshold=0.20)

    keep_id = mind.remember("alpha project launch checklist", namespace="work", tags=["project"])
    mind.remember("alpha private journal note", namespace="personal", tags=["journal"])
    expired_id = mind.remember(
        "alpha obsolete task",
        namespace="work",
        tags=["project"],
        ttl_seconds=-1,
    )

    work_results = mind.query("alpha", namespace="work", tags=["project"], top_k=5)
    assert [result.id for result in work_results] == [keep_id]
    assert all(result.score >= 0.20 for result in work_results)

    stats = mind.stats(namespace="work")
    assert stats["active_memories"] == 1
    assert stats["expired_memories"] == 1

    removed = mind.forget(id=keep_id, namespace="work")
    assert removed == 1
    assert mind.query("alpha", namespace="work", top_k=5) == []

    purged = mind.purge_expired()
    assert purged == 1
    assert mind.store.get(expired_id) is None
    mind.close()


def test_purge_expired_avoids_full_store_scan_without_recovery_journal(tmp_path):
    mind = make_mind(tmp_path / "purge-no-journal.sqlite3")
    try:
        original_list = mind.store.list

        def reject_full_scan(*args, **kwargs):
            raise AssertionError("purge must not materialize the full store")

        mind.store.list = reject_full_scan
        assert mind.purge_expired() == 0
        mind.store.list = original_list
    finally:
        mind.close()


def test_feedback_batch_updates_state_and_rejects_bad_items(tmp_path):
    db_path = tmp_path / "feedback-batch.sqlite3"
    mind = make_mind(db_path, audit_queries=True)
    try:
        useful_id = mind.remember("batch feedback useful memory", namespace="tenant:batch")
        stale_id = mind.remember(
            "batch feedback stale memory",
            namespace="tenant:batch",
            priority=2.0,
        )
        before_useful = mind.store.get(useful_id)
        before_stale = mind.store.get(stale_id)
        assert before_useful is not None
        assert before_stale is not None
        before_useful_priority = before_useful.priority
        before_stale_priority = before_stale.priority

        report = mind.feedback_batch(
            [
                {
                    "id": useful_id,
                    "useful": True,
                    "strength": 0.5,
                    "query": "useful memory",
                    "reason": "accepted",
                },
                {
                    "id": stale_id,
                    "useful": False,
                    "strength": 0.25,
                    "query": "stale memory",
                    "reason": "rejected",
                },
                {"id": useful_id, "namespace": "wrong", "useful": True},
                {"id": 999999, "useful": True},
            ],
            namespace="tenant:batch",
        )

        assert report["accepted"] == 2
        assert report["rejected"] == 2
        assert report["accepted_ids"] == (useful_id, stale_id)
        assert report["rejected_ids"] == (useful_id, 999999)
        assert report["namespaces"] == ("tenant:batch",)
        assert mind.store.get(useful_id).priority > before_useful_priority
        assert mind.store.get(stale_id).priority < before_stale_priority

        events = mind.audit_events(namespace="tenant:batch", action="feedback", limit=4)
        assert len(events) == 2
        assert {event.memory_id for event in events} == {useful_id, stale_id}
        assert events[0].metadata["query"] in {"useful memory", "stale memory"}
    finally:
        mind.close()


def test_audit_events_track_mutations_without_query_audit_by_default(tmp_path):
    db_path = tmp_path / "audit.sqlite3"
    mind = make_mind(db_path)

    memory_id = mind.remember(
        "audit memory should record mutations",
        namespace="audit",
        tags=["ops"],
    )
    assert mind.query("audit memory", namespace="audit")
    assert mind.forget(id=memory_id, namespace="audit") == 1

    events = mind.audit_events(namespace="audit", limit=10)
    actions = [event.action for event in events]

    assert actions == ["forget", "remember"]
    assert events[0].memory_id == memory_id
    assert events[1].metadata["tags"] == ["ops"]
    filtered = mind.audit_events(namespace="audit", memory_id=memory_id, limit=1)
    assert len(filtered) == 1
    assert filtered[0].memory_id == memory_id
    assert mind.stats(namespace="audit")["audit_events"] == 2
    mind.close()


def test_query_audit_is_opt_in(tmp_path):
    mind = make_mind(tmp_path / "query-audit.sqlite3", audit_queries=True)

    mind.remember("query audit can be enabled", namespace="audit")
    mind.query("query audit", namespace="audit", top_k=1)

    query_events = mind.audit_events(namespace="audit", action="query", limit=5)

    assert len(query_events) == 1
    assert query_events[0].metadata["top_k"] == 1
    assert query_events[0].metadata["result_count"] == 1
    mind.close()


def test_query_and_feedback_audits_redact_secrets(tmp_path):
    mind = make_mind(tmp_path / "query-audit-secrets.sqlite3", audit_queries=True)
    try:
        memory_id = mind.remember("deployment credentials", namespace="audit")
        mind.query(
            "deployment api_key=private-value Bearer bearer-value sk-secretvalue",
            namespace="audit",
            top_k=1,
        )
        mind.feedback(
            id=memory_id,
            namespace="audit",
            useful=True,
            query="deployment token:private-token",
            reason="accepted password=private-password",
        )

        serialized = str(
            [event.metadata for event in mind.audit_events(namespace="audit", limit=10)]
        )
        assert "private-value" not in serialized
        assert "bearer-value" not in serialized
        assert "sk-secretvalue" not in serialized
        assert "private-token" not in serialized
        assert "private-password" not in serialized
        assert "[REDACTED]" in serialized
    finally:
        mind.close()


def test_index_health_and_rebuild_detect_index_drift(tmp_path):
    mind = make_mind(tmp_path / "index-health.sqlite3")
    try:
        first_id = mind.remember("index health first memory", namespace="ops")
        second_id = mind.remember("index health second memory", namespace="ops")

        assert mind.index_health()["healthy"] is True

        mind.index.remove(first_id)
        drifted = mind.index_health()

        assert drifted["healthy"] is False
        assert drifted["missing_count"] == 1
        assert drifted["missing_ids_sample"] == [first_id]

        repaired = mind.rebuild_index()

        assert repaired["healthy"] is True
        assert repaired["vector_count"] == 2
        assert mind.query("first memory", namespace="ops", top_k=1)[0].id == first_id
        assert mind.query("second memory", namespace="ops", top_k=1)[0].id == second_id
        assert mind.audit_events(action="index_rebuild", limit=1)[0].metadata["healthy"] is True
    finally:
        mind.close()


def test_shared_store_refresh_propagates_cross_worker_writes_and_deletes(tmp_path):
    db_path = tmp_path / "shared-store.sqlite3"
    writer = make_mind(db_path)
    reader = make_mind(db_path, shared_store_refresh_seconds=0)
    try:
        memory_id = writer.remember(
            "shared serverless state survives worker replacement",
            namespace="tenant:serverless",
        )

        results = reader.query(
            "worker replacement",
            namespace="tenant:serverless",
            top_k=1,
        )
        assert results[0].id == memory_id
        first_priority = reader._records_by_id[memory_id].priority
        reader.query(
            "worker replacement",
            namespace="tenant:serverless",
            top_k=1,
        )
        assert reader._records_by_id[memory_id].priority > first_priority

        assert writer.forget(id=memory_id, namespace="tenant:serverless") == 1
        assert reader.query(
            "worker replacement",
            namespace="tenant:serverless",
            top_k=1,
        ) == []
    finally:
        writer.close()
        reader.close()


def test_timestamped_backup_retention_and_restore(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    backup_dir = tmp_path / "backups"
    restored_path = tmp_path / "restored.sqlite3"
    mind = make_mind(db_path)

    memory_id = mind.remember("backup restore memory", namespace="ops")
    created = []
    for _ in range(3):
        created.append(mind.save(backup_dir, keep_last=2, backup_prefix="ops"))

    backups = sorted(backup_dir.glob("ops-*.sqlite3"))
    assert len(backups) == 2
    assert created[-1] in backups

    SQLiteMemoryStore.restore_backup(created[-1], restored_path)
    restored = make_mind(restored_path)
    try:
        results = restored.query("backup restore", namespace="ops", top_k=1)
        assert results[0].id == memory_id
        assert results[0].text == "backup restore memory"
    finally:
        mind.close()
        restored.close()


def test_restore_refuses_to_overwrite_without_explicit_flag(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    mind = make_mind(source)
    mind.remember("source memory")
    backup = mind.save(tmp_path / "backup.sqlite3")
    destination.write_text("existing", encoding="utf-8")

    try:
        try:
            SQLiteMemoryStore.restore_backup(backup, destination)
            raised = False
        except FileExistsError:
            raised = True
        assert raised is True

        restored = SQLiteMemoryStore.restore_backup(backup, destination, overwrite=True)
        assert restored == destination
    finally:
        mind.close()


def test_recovery_journal_restores_full_and_point_in_time(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    journal_path = tmp_path / "recovery.jsonl"
    full_restore_path = tmp_path / "full-restore.sqlite3"
    point_restore_path = tmp_path / "point-restore.sqlite3"
    mind = make_mind(db_path, recovery_journal_path=journal_path)
    full_restored = None
    point_restored = None

    try:
        first_id = mind.remember(
            "first point in time memory",
            namespace="ops",
            tags=["pitr"],
            metadata={"checkpoint": "first"},
        )
        first_checkpoint = json.loads(
            journal_path.read_text(encoding="utf-8").splitlines()[-1]
        )["created_at"]
        second_id = mind.remember(
            "second durable memory survives full replay",
            namespace="ops",
            tags=["pitr"],
        )
        assert mind.forget(id=first_id, namespace="ops") == 1

        full_report = SQLiteMemoryStore.restore_recovery_journal(
            journal_path,
            full_restore_path,
        )
        full_restored = make_mind(full_restore_path)
        full_results = full_restored.query("second durable", namespace="ops", top_k=1)

        assert full_report.ok is True
        assert full_report.applied_entries == 3
        assert full_report.remembered_records == 2
        assert full_report.deleted_records == 1
        assert full_report.restored_records == 1
        assert full_restored.store.get(first_id) is None
        assert full_results[0].id == second_id
        assert full_results[0].text == "second durable memory survives full replay"

        point_report = SQLiteMemoryStore.restore_recovery_journal(
            journal_path,
            point_restore_path,
            until=first_checkpoint,
        )
        point_restored = make_mind(point_restore_path)
        first_record = point_restored.store.get(first_id)

        assert point_report.applied_entries == 1
        assert point_report.skipped_entries == 2
        assert point_report.restored_records == 1
        assert first_record is not None
        assert first_record.text == "first point in time memory"
        assert first_record.tags == ("pitr",)
        assert first_record.metadata == {"checkpoint": "first"}
        assert point_restored.store.get(second_id) is None
    finally:
        mind.close()
        if full_restored is not None:
            full_restored.close()
        if point_restored is not None:
            point_restored.close()


def test_recovery_journal_replays_expired_purge_and_overwrite_guard(tmp_path):
    journal_path = tmp_path / "recovery.jsonl"
    destination = tmp_path / "restored.sqlite3"
    mind = make_mind(tmp_path / "source.sqlite3", recovery_journal_path=journal_path)
    restored = None

    try:
        expired_id = mind.remember(
            "expired journal memory",
            namespace="ops",
            ttl_seconds=-1,
        )
        keep_id = mind.remember("kept journal memory", namespace="ops")
        assert mind.purge_expired() == 1
        assert mind.store.get(expired_id) is None

        destination.write_text("existing", encoding="utf-8")
        try:
            SQLiteMemoryStore.restore_recovery_journal(journal_path, destination)
            raised = False
        except FileExistsError:
            raised = True
        assert raised is True

        report = SQLiteMemoryStore.restore_recovery_journal(
            journal_path,
            destination,
            overwrite=True,
        )
        restored = make_mind(destination)

        assert report.applied_entries == 3
        assert report.deleted_records == 1
        assert report.restored_records == 1
        assert restored.store.get(expired_id) is None
        assert restored.store.get(keep_id) is not None
    finally:
        mind.close()
        if restored is not None:
            restored.close()


def test_close_releases_sqlite_file(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    mind = make_mind(db_path)
    mind.remember("Windows should be able to delete this SQLite file")
    mind.close()

    db_path.unlink()
    assert not db_path.exists()
