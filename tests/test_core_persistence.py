import json
import warnings
from pathlib import Path

import numpy as np

from wavemind import HashingTextEncoder, QueryResult, SQLiteMemoryStore, WaveField, WaveMind


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
