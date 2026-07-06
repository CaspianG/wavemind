import fnmatch
import tarfile
from io import BytesIO
from pathlib import Path

import numpy as np

from wavemind import (
    CachePrewarmWorker,
    DistributedRepairWorker,
    DistributedShardedWaveMind,
    HashingTextEncoder,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    MemoryOSWorker,
    QueryVectorCache,
    QueryResult,
    RedisHotMemoryCache,
    RedisQueryVectorCache,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedSnapshotWorker,
    ReplicatedWaveMind,
    S3SnapshotStore,
    WaveMind,
    query_with_cache,
    query_with_vector_cache,
)


class SystemsEncoder:
    vector_dim = 4

    def encode_vector(self, text: str) -> np.ndarray:
        lowered = text.lower()
        if any(token in lowered for token in ("rust", "compiler", "systems", "programming")):
            return self._unit([1.0, 0.0, 0.0, 0.0])
        return self._unit([0.0, 1.0, 0.0, 0.0])

    def _unit(self, values):
        vector = np.asarray(values, dtype=np.float32)
        return vector / (float(np.linalg.norm(vector)) + 1e-9)


class CountingEncoder:
    vector_dim = 4

    def __init__(self):
        self.calls = 0

    def encode_vector(self, text: str) -> np.ndarray:
        self.calls += 1
        lowered = text.lower()
        if "budget" in lowered:
            return self._unit([1.0, 0.0, 0.0, 0.0])
        return self._unit([0.0, 1.0, 0.0, 0.0])

    def _unit(self, values):
        vector = np.asarray(values, dtype=np.float32)
        return vector / (float(np.linalg.norm(vector)) + 1e-9)


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


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.counter = 0

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.counter += 1
        self.objects[(bucket, key)] = {
            "Body": Path(filename).read_bytes(),
            "Metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def head_object(self, Bucket, Key):
        payload = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(payload["Body"]),
            "Metadata": dict(payload["Metadata"]),
            "ETag": '"fake-etag"',
        }

    def get_object(self, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)]["Body"])}

    def list_objects_v2(self, Bucket, Prefix="", ContinuationToken=None):
        contents = []
        for (bucket, key), payload in self.objects.items():
            if bucket == Bucket and key.startswith(Prefix):
                contents.append(
                    {
                        "Key": key,
                        "Size": len(payload["Body"]),
                        "LastModified": payload["LastModified"],
                        "ETag": '"fake-etag"',
                    }
                )
        return {"Contents": sorted(contents, key=lambda item: item["Key"])}

    def delete_objects(self, Bucket, Delete):
        deleted = []
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop((Bucket, key), None)
            deleted.append({"Key": key})
        return {"Deleted": deleted}


class LocalShardServiceClient:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.minds = {}

    def remember(
        self,
        address,
        *,
        text,
        namespace,
        tags=(),
        ttl_seconds=None,
        metadata=None,
        priority=1.0,
    ):
        return self._mind(address).remember(
            text,
            namespace=namespace,
            tags=tags,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            priority=priority,
        )

    def query(self, address, *, text, namespace, top_k=3, tags=(), min_score=None):
        return self._mind(address).query(
            text,
            namespace=namespace,
            top_k=top_k,
            tags=tags,
            min_score=min_score,
        )

    def forget(self, address, *, namespace, id=None, text=None):
        return self._mind(address).forget(id=id, text=text, namespace=namespace)

    def export_namespace_state(
        self,
        address,
        *,
        namespace,
        limit=1000,
        include_expired=False,
        tags=(),
        include_tombstones=True,
    ):
        records = self._mind(address).store.list(
            namespace=namespace,
            include_expired=include_expired,
            tags=tags,
        )[:limit]
        tombstones = []
        if include_tombstones:
            tombstones = [
                {
                    "record_keys": list(event.metadata.get("record_keys", [])),
                    "texts": list(event.metadata.get("texts", [])),
                }
                for event in self._mind(address).audit_events(
                    namespace=namespace,
                    action="distributed_tombstone",
                    limit=10_000,
                )
            ]
        return {
            "records": [
                {
                    "id": record.id,
                    "text": record.text,
                    "namespace": record.namespace,
                    "tags": list(record.tags),
                    "metadata": record.metadata,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "expires_at": record.expires_at,
                    "priority": record.priority,
                    "access_count": record.access_count,
                }
                for record in records
            ],
            "tombstones": tombstones,
        }

    def log_tombstone(self, address, *, namespace, record_keys=(), texts=()):
        return self._mind(address).store.log_audit_event(
            "distributed_tombstone",
            namespace=namespace,
            metadata={
                "record_keys": sorted(record_keys),
                "texts": sorted(texts),
            },
        )

    def close(self):
        for mind in self.minds.values():
            mind.close()
        self.minds.clear()

    def _mind(self, address):
        mind = self.minds.get(address)
        if mind is None:
            mind = WaveMind(
                db_path=self.root / f"{address}.sqlite3",
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            self.minds[address] = mind
        return mind


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


def test_query_vector_cache_reuses_encoded_query_vectors(tmp_path):
    encoder = CountingEncoder()
    memory = WaveMind(
        db_path=tmp_path / "query-vector-cache.sqlite3",
        encoder=encoder,
        width=16,
        height=16,
        layers=1,
    )
    vector_cache = QueryVectorCache(capacity=4, ttl_seconds=60)
    try:
        memory.remember("budget recall should be fast", namespace="tenant:a")
        encoder.calls = 0

        first = query_with_vector_cache(
            memory,
            vector_cache,
            "budget recall",
            namespace="tenant:a",
            top_k=1,
        )
        second = query_with_vector_cache(
            memory,
            vector_cache,
            "budget recall",
            namespace="tenant:a",
            top_k=1,
        )

        assert first[0].text == second[0].text
        assert encoder.calls == 1
        assert vector_cache.stats().misses == 1
        assert vector_cache.stats().hits == 1
    finally:
        memory.close()


def test_redis_query_vector_cache_is_shared_across_workers(tmp_path):
    encoder = CountingEncoder()
    client = FakeRedis()
    writer_cache = RedisQueryVectorCache(client, prefix="wm:qvec", ttl_seconds=45)
    reader_cache = RedisQueryVectorCache(client, prefix="wm:qvec", ttl_seconds=45)
    memory = WaveMind(
        db_path=tmp_path / "redis-query-vector-cache.sqlite3",
        encoder=encoder,
        width=16,
        height=16,
        layers=1,
    )
    try:
        memory.remember("budget recall should cross workers", namespace="tenant:a")
        encoder.calls = 0

        first = query_with_vector_cache(
            memory,
            writer_cache,
            "budget recall",
            namespace="tenant:a",
            top_k=1,
        )
        second = query_with_vector_cache(
            memory,
            reader_cache,
            "budget recall",
            namespace="tenant:a",
            top_k=1,
        )

        assert first[0].text == second[0].text
        assert encoder.calls == 1
        assert writer_cache.stats().misses == 1
        assert reader_cache.stats().hits == 1
        assert next(iter(client.expirations.values())) == 45
    finally:
        memory.close()


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


def test_cache_prewarm_worker_warms_hot_queries_from_audit(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "prewarm.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    cache = HotMemoryCache(capacity=8, ttl_seconds=60)
    try:
        memory.remember("hot budget preference memory", namespace="tenant:hot")
        memory.query("budget preference", namespace="tenant:hot", top_k=1)
        memory.query("budget preference", namespace="tenant:hot", top_k=1)

        assert cache.get("tenant:hot", "budget preference", top_k=1) is None

        report = CachePrewarmWorker(memory, cache).run_once(
            namespace="tenant:hot",
            audit_limit=10,
            max_queries=4,
            min_frequency=2,
            top_k=1,
        )
        cached = cache.get("tenant:hot", "budget preference", top_k=1)

        assert report.ok
        assert report.scanned_events >= 2
        assert report.candidates == 1
        assert report.warmed == 1
        assert cached is not None
        assert cached[0].text == "hot budget preference memory"
    finally:
        memory.close()


def test_memory_os_worker_prefetches_consolidates_and_recommends(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os.sqlite3",
        encoder=SystemsEncoder(),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
        graph_weight=1.0,
        graph_steps=2,
        graph_expand_k=10,
        rerank_k=10,
    )
    cache = HotMemoryCache(capacity=8, ttl_seconds=60)
    try:
        memory.remember(
            "User likes Rust systems programming",
            namespace="agent",
            tags=["systems"],
        )
        memory.remember(
            "User studies compiler internals",
            namespace="agent",
            tags=["systems"],
        )
        memory.remember("expired stale note", namespace="agent", ttl_seconds=-1)
        memory.query("systems programming", namespace="agent", top_k=1)
        memory.query("systems programming", namespace="agent", top_k=1)

        report = MemoryOSWorker(memory, cache).run_once(
            namespace="agent",
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=2,
            top_k=1,
            consolidate_steps=2,
            min_concept_energy=0.01,
            min_concept_size=2,
            max_concepts=1,
            memory_pressure_threshold=2,
        )
        cached = cache.get("agent", "systems programming", top_k=1)
        concept_results = memory.query(
            "systems programming",
            namespace="agent",
            tags=["concept"],
            top_k=1,
        )
        audit = memory.audit_events(namespace="agent", action="memory_os", limit=1)

        assert report.ok
        assert report.expired_purged == 1
        assert report.hot_queries[0].query == "systems programming"
        assert report.hot_queries[0].frequency >= 2
        assert report.prewarm.warmed == 1
        assert cached is not None
        assert report.predictive_prefetch.generated_queries >= 1
        assert report.predictive_prefetch.warmed >= 1
        assert report.predictive_prefetch.queries
        predictive_cached = cache.get(
            "agent",
            report.predictive_prefetch.queries[0],
            top_k=1,
        )
        assert predictive_cached is not None
        assert report.priority_predictions >= 1
        assert report.priority_boost_total > 0.0
        assert "predict_priority" in report.actions
        assert all(memory.store.get(id) is not None for id in report.priority_boosted_ids)
        assert report.concepts_created == 1
        assert concept_results
        assert "prewarm_cache" in report.actions
        assert "predictive_prefetch" in report.actions
        assert "consolidate_concepts" in report.actions
        assert any("persisted ANN backend" in item for item in report.recommendations)
        assert audit and audit[0].metadata["ok"] is True
        assert audit[0].metadata["priority_predictions"] >= 1
        assert audit[0].metadata["predictive_prefetch_warmed"] >= 1
    finally:
        memory.close()


def test_memory_os_worker_embeds_architecture_advice_for_production_targets(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-architecture.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        memory.remember("architecture advisor memory", namespace="tenant:scale")

        report = MemoryOSWorker(memory).run_once(
            namespace="tenant:scale",
            consolidate_steps=0,
            consolidate_concepts=False,
            target_memories=2_000_000,
            namespace_count=4096,
            node_count=2,
            replication_factor=3,
            read_quorum=1,
            read_fanout=1,
            target_qps=250.0,
            deployment="production",
            multimodal=True,
        )
        advice = report.architecture_advice
        recommendation_ids = {
            item["id"]
            for item in advice.get("recommendations", [])
            if isinstance(item, dict)
        }

        assert report.ok
        assert advice["status"] == "architecture_required"
        assert advice["deployment"] == "production"
        assert "advise_architecture" in report.actions
        assert "namespace-sharding" in recommendation_ids
        assert "service-index" in recommendation_ids
        assert "production-controls" in recommendation_ids
        assert "load-test" in recommendation_ids
        assert any("Architecture advisor:" in item for item in report.recommendations)
    finally:
        memory.close()


def test_memory_os_worker_predicts_priority_from_hot_queries(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-priority.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        id = memory.remember("priority predictor should learn hot recall", namespace="agent")
        memory.query("hot recall", namespace="agent", top_k=1)
        memory.query("hot recall", namespace="agent", top_k=1)
        before = memory.store.get(id).priority

        report = MemoryOSWorker(memory).run_once(
            namespace="agent",
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=2,
            top_k=1,
            consolidate_steps=0,
            consolidate_concepts=False,
            priority_boost_per_hit=0.25,
            max_priority_boost=0.5,
        )
        after = memory.store.get(id).priority

        assert report.ok
        assert report.priority_boosted_ids == (id,)
        assert report.priority_predictions == 1
        assert report.priority_boost_total > 0.0
        assert after > before
        assert "predict_priority" in report.actions
    finally:
        memory.close()


def test_memory_os_worker_demotes_cold_memories_from_usage_patterns(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-forgetting.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        hot_id = memory.remember("hot recall alpha memory", namespace="agent")
        cold_id = memory.remember("unused cold beta memory", namespace="agent", priority=2.0)
        memory.query("hot recall alpha", namespace="agent", top_k=1)
        memory.query("hot recall alpha", namespace="agent", top_k=1)
        cold_before = memory.store.get(cold_id).priority
        hot_before = memory.store.get(hot_id).priority

        report = MemoryOSWorker(memory).run_once(
            namespace="agent",
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=2,
            top_k=1,
            consolidate_steps=0,
            consolidate_concepts=False,
            forgetting_min_age_seconds=0.0,
            forgetting_priority_decay=0.25,
            forgetting_max_access_count=0,
        )

        assert report.ok
        assert cold_id in report.forgetting_demoted_ids
        assert hot_id not in report.forgetting_demoted_ids
        assert report.forgetting_demotions == 1
        assert report.forgetting_decay_total > 0.0
        assert memory.store.get(cold_id).priority < cold_before
        assert memory.store.get(hot_id).priority >= hot_before
        assert "adaptive_forgetting" in report.actions
    finally:
        memory.close()


def test_distributed_repair_worker_repairs_service_mode_namespaces(tmp_path):
    client = LocalShardServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        client=client,
    )
    try:
        repair_namespace = "tenant:worker-repair"
        repair_write = memory.remember(
            "worker repair copies missing service replica",
            namespace=repair_namespace,
        )
        missing_node = next(node for node in repair_write.writes if node != repair_write.primary_node)
        client._mind(missing_node).forget(
            namespace=repair_namespace,
            text="worker repair copies missing service replica",
        )

        tombstone_namespace = "tenant:worker-tombstone"
        tombstone_text = "worker repair must not resurrect deleted service memory"
        memory.remember(tombstone_text, namespace=tombstone_namespace)
        tombstone_placement = memory.placement(tombstone_namespace)
        missed_delete = tombstone_placement.replicas[-1]
        memory.set_node_available(missed_delete, False)
        memory.forget(namespace=tombstone_namespace, text=tombstone_text)
        memory.set_node_available(missed_delete, True)

        report = DistributedRepairWorker(memory).run_once(
            namespaces=(repair_namespace, tombstone_namespace)
        )

        assert report.ok
        assert report.repaired_total == 1
        assert report.tombstone_deleted == 1
        assert set(report.reports) == {repair_namespace, tombstone_namespace}
        assert client._mind(missing_node).store.count(namespace=repair_namespace) == 1
        assert client._mind(missed_delete).store.count(namespace=tombstone_namespace) == 0
        assert memory.query("deleted service memory", namespace=tombstone_namespace, top_k=1) == []
    finally:
        client.close()


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


def test_replicated_snapshot_worker_archives_and_restores(tmp_path):
    memory = ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    restored = None
    try:
        memory.remember("portable archive keeps replicated memory", namespace="tenant:archive")
        report = ReplicatedSnapshotWorker(memory).run_once(
            destination=tmp_path / "snapshots",
            archive_destination=tmp_path / "archives",
            keep_last=2,
        )

        restored, restore_report = ReplicatedWaveMind.restore_snapshot_archive(
            report.archive_path,
            tmp_path / "restored-from-archive",
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )

        assert report.ok
        assert report.archive_path is not None
        assert report.archive_path.name.endswith(".tar.gz")
        assert report.archive_verified is True
        assert len(restore_report.restored_files) == 3
        assert restored.query("replicated memory", namespace="tenant:archive", top_k=1)[0].text == (
            "portable archive keeps replicated memory"
        )
    finally:
        memory.close()
        if restored is not None:
            restored.close()


def test_replicated_snapshot_worker_prunes_archives(tmp_path):
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
            memory.remember(f"archive retention memory {index}", namespace="tenant:archive")
            reports.append(
                worker.run_once(
                    destination=tmp_path / "snapshots",
                    archive_destination=tmp_path / "archives",
                    keep_last=2,
                    prefix="ops",
                )
            )

        archives = sorted((tmp_path / "archives").glob("ops-*.tar.gz"))

        assert len(archives) == 2
        assert reports[-1].pruned_archives
        assert all(
            ReplicatedWaveMind.verify_snapshot_archive(path)["healthy"]
            for path in archives
        )
    finally:
        memory.close()


def test_replicated_snapshot_worker_uploads_archive_to_object_store(tmp_path):
    memory = ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/prod",
        client=client,
    )
    for index in range(2):
        old_archive = tmp_path / f"old-{index}.tar.gz"
        old_archive.write_bytes(f"old-{index}".encode("utf-8"))
        store.upload_archive(old_archive)
    try:
        memory.remember("object store keeps replicated memory", namespace="tenant:s3")
        report = ReplicatedSnapshotWorker(memory).run_once(
            destination=tmp_path / "snapshots",
            object_store_destination="s3://wavemind-backups/prod",
            object_store=store,
            keep_last=2,
            object_store_keep_last=1,
        )

        upload = report.object_store_upload
        remaining = store.list_archives()

        assert report.ok
        assert report.archive_path is not None
        assert report.archive_verified is True
        assert upload is not None
        assert upload.verified is True
        assert upload.uri.startswith("s3://wavemind-backups/prod/")
        assert upload.key.endswith(".tar.gz")
        assert [archive.key for archive in report.pruned_object_store] == [
            "prod/old-1.tar.gz",
            "prod/old-0.tar.gz",
        ]
        assert [archive.key for archive in remaining] == [upload.key]
        assert ("wavemind-backups", upload.key) in client.objects
    finally:
        memory.close()


def test_replicated_object_store_drill_restores_downloaded_archive(tmp_path):
    memory = ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/prod",
        client=client,
    )
    try:
        memory.remember("drill restores replicated memory", namespace="tenant:dr")
        ReplicatedSnapshotWorker(memory).run_once(
            destination=tmp_path / "snapshots",
            object_store_destination="s3://wavemind-backups/prod",
            object_store=store,
        )

        report = ReplicatedObjectStoreDrillWorker(store).run_once(
            source="s3://wavemind-backups/prod",
            destination=tmp_path / "drill-restore",
            download_destination=tmp_path / "downloads",
            namespace="tenant:dr",
            query="restores replicated",
            expected_text="drill restores replicated memory",
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )

        assert report.ok
        assert report.selected_archive.uri.startswith("s3://wavemind-backups/prod/")
        assert report.downloaded_archive_path.exists()
        assert report.download_matches_object is True
        assert report.archive_verified is True
        assert report.restored_files == 3
        assert report.primary_node_disabled is not None
        assert report.recalled_after_primary_loss is True
        assert report.expected_text_found is True
    finally:
        memory.close()


def test_replicated_snapshot_archive_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("bad", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(payload, arcname="../escape.txt")

    try:
        ReplicatedWaveMind.verify_snapshot_archive(archive_path)
    except Exception as exc:
        assert "Unsafe archive path" in str(exc)
    else:
        raise AssertionError("unsafe archive was accepted")
