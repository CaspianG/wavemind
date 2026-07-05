import fnmatch

from wavemind import (
    HashingTextEncoder,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    QueryResult,
    RedisHotMemoryCache,
    ReplicatedSnapshotWorker,
    ReplicatedWaveMind,
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


def test_replicated_snapshot_worker_mirrors_offsite_and_restores(tmp_path):
    memory = ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=[
            {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
            {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
            {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
        ],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    restored = None
    try:
        memory.remember("offsite snapshot keeps production memory", namespace="tenant:ops")
        report = ReplicatedSnapshotWorker(memory).run_once(
            destination=tmp_path / "snapshots",
            offsite_destination=tmp_path / "offsite",
            keep_last=2,
        )

        restored, restore_report = ReplicatedWaveMind.restore_snapshot(
            report.offsite_path,
            tmp_path / "restored",
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )

        assert report.ok
        assert report.offsite_path is not None
        assert report.offsite_path.exists()
        assert report.offsite_verified is True
        assert len(restore_report.restored_files) == 3
        assert restored.query("production memory", namespace="tenant:ops", top_k=1)[0].text == (
            "offsite snapshot keeps production memory"
        )
    finally:
        memory.close()
        if restored is not None:
            restored.close()


def test_replicated_snapshot_worker_prunes_local_and_offsite_retention(tmp_path):
    memory = ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        worker = ReplicatedSnapshotWorker(memory)
        reports = []
        for index in range(3):
            memory.remember(f"retention memory {index}", namespace="tenant:ops")
            reports.append(
                worker.run_once(
                    destination=tmp_path / "snapshots",
                    offsite_destination=tmp_path / "offsite",
                    keep_last=2,
                    prefix="ops",
                )
            )

        local_snapshots = sorted((tmp_path / "snapshots").glob("ops-*"))
        offsite_snapshots = sorted((tmp_path / "offsite").glob("ops-*"))

        assert len(local_snapshots) == 2
        assert len(offsite_snapshots) == 2
        assert reports[-1].pruned_local
        assert reports[-1].pruned_offsite
        assert all((path / "manifest.json").exists() for path in local_snapshots)
        assert all((path / "manifest.json").exists() for path in offsite_snapshots)
    finally:
        memory.close()
