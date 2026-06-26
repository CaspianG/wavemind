from pathlib import Path

from wavemind import HashingTextEncoder, QueryResult, WaveMind


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


def test_close_releases_sqlite_file(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    mind = make_mind(db_path)
    mind.remember("Windows should be able to delete this SQLite file")
    mind.close()

    db_path.unlink()
    assert not db_path.exists()
