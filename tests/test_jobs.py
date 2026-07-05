import fnmatch

from wavemind import (
    HashingTextEncoder,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    QueryResult,
    RedisHotMemoryCache,
    WaveMind,
    query_with_cache,
)


class FakeRedis:
    def __init__(self):
        self.items = {}
        self.expirations = {}

    def get(self, key):
        return self.items.get(key)

    def set(self, key, value, ex=None):
        self.items[key] = value
        self.expirations[key] = ex

    def scan_iter(self, match):
        for key in list(self.items):
            if fnmatch.fnmatch(key, match):
                yield key

    def delete(self, *keys):
        for key in keys:
            self.items.pop(key, None)
            self.expirations.pop(key, None)


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


def test_redis_hot_memory_cache_round_trips_query_results():
    client = FakeRedis()
    cache = RedisHotMemoryCache(client, prefix="wm:test", ttl_seconds=30)
    result = QueryResult(
        id=7,
        text="enterprise customer prefers audit exports",
        score=0.9,
        vector_score=0.8,
        field_score=0.1,
        graph_score=0.0,
        namespace="tenant:a",
        tags=("preference",),
        metadata={"source": "test"},
    )

    assert cache.get("tenant:a", "audit exports", top_k=1) is None
    cache.put("tenant:a", "audit exports", [result], top_k=1)
    cached = cache.get("tenant:a", "audit exports", top_k=1)

    assert cached == [result]
    assert cache.stats().hits == 1
    assert cache.stats().misses == 1
    assert next(iter(client.expirations.values())) == 30


def test_redis_hot_memory_cache_invalidates_namespace():
    client = FakeRedis()
    cache = RedisHotMemoryCache(client, prefix="wm:test", ttl_seconds=30)
    cache.put("tenant:a", "one", [], top_k=1)
    cache.put("tenant:b", "two", [], top_k=1)

    assert cache.invalidate_namespace("tenant:a") == 1

    assert cache.get("tenant:a", "one", top_k=1) is None
    assert cache.get("tenant:b", "two", top_k=1) == []


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
