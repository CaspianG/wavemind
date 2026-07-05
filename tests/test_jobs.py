from wavemind import HashingTextEncoder, HotMemoryCache, MemoryMaintenanceWorker, WaveMind, query_with_cache


def test_hot_memory_cache_reuses_query_results(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "cache.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    cache = HotMemoryCache(capacity=4, ttl_seconds=60)
    try:
        memory.remember("Andrey prefers concise trading updates", namespace="tenant:a")

        first = query_with_cache(memory, cache, "concise trading", namespace="tenant:a", top_k=1)
        second = query_with_cache(memory, cache, "concise trading", namespace="tenant:a", top_k=1)

        assert first[0].text == second[0].text
        assert cache.stats().hits == 1
        assert cache.stats().misses == 1
    finally:
        memory.close()


def test_hot_memory_cache_evicts_least_recent_queries():
    cache = HotMemoryCache(capacity=1, ttl_seconds=60)

    cache.put("a", "one", [], top_k=1)
    cache.put("a", "two", [], top_k=1)

    assert cache.get("a", "one", top_k=1) is None
    assert cache.stats().evictions == 1


def test_maintenance_worker_purges_expired_and_invalidates_cache(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "worker.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    cache = HotMemoryCache(capacity=8, ttl_seconds=60)
    try:
        memory.remember("expired memory", namespace="tenant:a", ttl_seconds=-1)
        memory.remember("active memory", namespace="tenant:a")
        query_with_cache(memory, cache, "active", namespace="tenant:a", top_k=1)

        report = MemoryMaintenanceWorker(memory, cache).run_once(namespace="tenant:a")

        assert report.expired_purged == 1
        assert report.cache_invalidated == 1
        assert memory.stats(namespace="tenant:a")["active_memories"] == 1
    finally:
        memory.close()
