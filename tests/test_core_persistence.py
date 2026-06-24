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


def test_close_releases_sqlite_file(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    mind = make_mind(db_path)
    mind.remember("Windows should be able to delete this SQLite file")
    mind.close()

    db_path.unlink()
    assert not db_path.exists()
