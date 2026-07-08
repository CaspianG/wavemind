import fnmatch
import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from wavemind import (
    ActiveActiveSyncWorker,
    CachePrewarmWorker,
    DistributedRepairWorker,
    DistributedShardedWaveMind,
    HashingTextEncoder,
    HotMemoryCache,
    HTTPActiveActiveSyncWorker,
    MemoryMaintenanceWorker,
    MemoryOSScheduler,
    MemoryOSWorker,
    QueryVectorCache,
    QueryResult,
    RedisHotMemoryCache,
    RedisMemoryOSLock,
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

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.items:
            return False
        self.items[key] = value
        self.expirations[key] = ex
        return True

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


class FakeHTTPActiveActiveClient:
    def __init__(self, regions: dict[str, ReplicatedWaveMind]):
        self.regions = regions
        self.exports: list[tuple[str, str, float | None, int | None]] = []
        self.imports: list[tuple[str, str]] = []

    def export_namespace_delta(
        self,
        address: str,
        *,
        namespace: str,
        since: float | None = None,
        limit: int | None = None,
    ):
        self.exports.append((address, namespace, since, limit))
        return self.regions[address].export_namespace_delta(
            namespace,
            since=since,
            limit=limit,
        )

    def import_namespace_delta(
        self,
        address: str,
        *,
        delta,
        namespace: str | None = None,
    ):
        self.imports.append((address, namespace or str(delta["namespace"])))
        report = self.regions[address].import_namespace_delta(delta, namespace=namespace)
        return {
            "namespace": report.namespace,
            "imported_records": report.imported_records,
            "skipped_records": report.skipped_records,
            "deleted_records": report.deleted_records,
            "imported_tombstones": report.imported_tombstones,
            "failed_nodes": dict(report.failed_nodes),
        }


class FailingHTTPActiveActiveClient(FakeHTTPActiveActiveClient):
    def import_namespace_delta(
        self,
        address: str,
        *,
        delta,
        namespace: str | None = None,
    ):
        raise TimeoutError(f"region {address} unavailable")


def _active_region(tmp_path: Path, name: str) -> ReplicatedWaveMind:
    return ReplicatedWaveMind(
        root_path=tmp_path / name,
        nodes=[
            {"id": f"{name}-a", "address": f"{name}-a.internal", "zone": "zone-a"},
            {"id": f"{name}-b", "address": f"{name}-b.internal", "zone": "zone-b"},
            {"id": f"{name}-c", "address": f"{name}-c.internal", "zone": "zone-c"},
        ],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )


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
        suggestion_ids = {suggestion.id for suggestion in report.suggestions}
        assert "review-consolidated-concepts" in suggestion_ids
        assert "predictive-prefetch-active" in suggestion_ids
        assert "priority-learning-active" in suggestion_ids
        assert any(
            suggestion.evidence.get("namespace") == "agent"
            for suggestion in report.suggestions
        )
        assert all(suggestion.action for suggestion in report.suggestions)
        assert report.as_dict()["suggestions"][0]["id"] in suggestion_ids
        assert report.policy_manifest.status == "action_required"
        policy_ids = {
            decision.id for decision in report.policy_manifest.decisions
        }
        assert {
            "prefetch-policy",
            "priority-policy",
            "forgetting-policy",
            "consolidation-policy",
            "scale-policy",
            "coordination-policy",
        }.issubset(policy_ids)
        policy_by_id = {
            decision.id: decision for decision in report.policy_manifest.decisions
        }
        assert policy_by_id["prefetch-policy"].strategy == (
            "hot-query-and-transition-prefetch"
        )
        assert policy_by_id["priority-policy"].status == "ok"
        assert policy_by_id["consolidation-policy"].status == "ok"
        assert policy_by_id["forgetting-policy"].status == "action_required"
        assert policy_by_id["scale-policy"].status == "action_required"
        assert policy_by_id["scale-policy"].evidence["recommendation_ids"]
        assert report.as_dict()["policy_manifest"]["decision_count"] >= 6
        assert report.policy_history.previous_runs == 0
        assert report.policy_history.trend == "first_run"
        assert report.as_dict()["policy_history"]["trend"] == "first_run"
        assert any("persisted ANN backend" in item for item in report.recommendations)
        assert audit and audit[0].metadata["ok"] is True
        assert audit[0].metadata["priority_predictions"] >= 1
        assert audit[0].metadata["predictive_prefetch_warmed"] >= 1
        assert audit[0].metadata["policy_status"] == "action_required"
        assert "prefetch-policy" in audit[0].metadata["policy_decision_ids"]
        assert audit[0].metadata["policy_decision_status_by_id"]["prefetch-policy"] == "ok"
        assert audit[0].metadata["policy_history_trend"] == "first_run"
    finally:
        memory.close()


def test_memory_os_worker_learns_repeated_policy_required_from_history(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-policy-history.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        memory.remember("budget preference hot memory", namespace="agent")
        memory.query("budget preference", namespace="agent", top_k=1)
        memory.query("budget preference", namespace="agent", top_k=1)

        worker = MemoryOSWorker(memory, cache=None)
        first = worker.run_once(
            namespace="agent",
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=2,
            top_k=1,
            consolidate_steps=0,
            consolidate_concepts=False,
            adaptive_forgetting=False,
            memory_pressure_threshold=1000,
        )
        second = worker.run_once(
            namespace="agent",
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=2,
            top_k=1,
            consolidate_steps=0,
            consolidate_concepts=False,
            adaptive_forgetting=False,
            memory_pressure_threshold=1000,
        )
        audit = memory.audit_events(namespace="agent", action="memory_os", limit=1)

        assert first.policy_history.previous_runs == 0
        assert first.policy_history.trend == "first_run"
        assert first.policy_manifest.as_dict()["decisions"]
        assert second.policy_history.previous_runs == 1
        assert second.policy_history.trend == "repeated_action_required"
        assert "prefetch-policy" in second.policy_history.repeated_action_required_ids
        assert "prefetch-policy" in second.policy_history.repeated_required_ids
        assert second.policy_history.status_counts["action_required"] >= 2
        assert second.as_dict()["policy_history"]["previous_runs"] == 1
        assert "escalate_policy_history" in second.actions
        assert any(
            "prefetch-policy repeated" in recommendation
            for recommendation in second.recommendations
        )
        history_suggestion = next(
            suggestion
            for suggestion in second.suggestions
            if suggestion.id == "policy-history:prefetch-policy"
        )
        assert history_suggestion.severity == "action_required"
        assert history_suggestion.evidence["history_trend"] == (
            "repeated_action_required"
        )
        assert history_suggestion.evidence["previous_runs"] == 1
        assert audit[0].metadata["policy_history_trend"] == "repeated_action_required"
        assert "prefetch-policy" in audit[0].metadata["policy_repeated_required_ids"]
        assert audit[0].metadata["policy_history_escalations"] >= 1
    finally:
        memory.close()


def test_memory_os_worker_prefetches_observed_follow_up_queries(tmp_path):
    namespace = "tenant:sequence"
    memory = WaveMind(
        db_path=tmp_path / "memory-os-transitions.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    cache = HotMemoryCache(capacity=8, ttl_seconds=60)
    try:
        memory.remember("budget recall primary memory", namespace=namespace)
        memory.remember("risk limits follow up memory", namespace=namespace)
        for query in (
            "budget recall",
            "risk limits",
            "budget recall",
            "risk limits",
            "budget recall",
        ):
            memory.query(query, namespace=namespace, top_k=1)

        report = MemoryOSWorker(memory, cache).run_once(
            namespace=namespace,
            audit_limit=10,
            max_hot_queries=4,
            min_frequency=3,
            top_k=1,
            consolidate_steps=0,
            consolidate_concepts=False,
            predict_priorities=False,
            adaptive_forgetting=False,
            max_predictive_queries=4,
            predictive_terms_per_hot_query=0,
            transition_prefetch_window_seconds=60,
            architecture_advice=False,
        )
        cached_follow_up = cache.get(namespace, "risk limits", top_k=1)

        assert report.ok
        assert [query.query for query in report.hot_queries] == ["budget recall"]
        assert report.predictive_prefetch.transition_queries == ("risk limits",)
        assert "risk limits" in report.predictive_prefetch.queries
        assert len(report.predictive_prefetch.transition_edges) == 1
        edge = report.predictive_prefetch.transition_edges[0]
        assert edge.namespace == namespace
        assert edge.from_query == "budget recall"
        assert edge.to_query == "risk limits"
        assert edge.count == 2
        assert edge.probability == 1.0
        assert edge.as_dict()["to_query"] == "risk limits"
        assert cached_follow_up is not None
        assert cached_follow_up[0].text == "risk limits follow up memory"
        assert "predictive_prefetch" in report.actions
    finally:
        memory.close()


def test_memory_os_transition_edges_rank_probability_and_skip_hot_targets():
    worker = object.__new__(MemoryOSWorker)
    namespace = "tenant:sequence"
    hot_queries = [
        SimpleNamespace(namespace=namespace, query="budget recall"),
        SimpleNamespace(namespace=namespace, query="status update"),
    ]
    events = [
        SimpleNamespace(id=1, namespace=namespace, created_at=1.0, metadata={"query": "budget recall"}),
        SimpleNamespace(id=2, namespace=namespace, created_at=2.0, metadata={"query": "risk limits"}),
        SimpleNamespace(id=3, namespace=namespace, created_at=3.0, metadata={"query": "budget recall"}),
        SimpleNamespace(id=4, namespace=namespace, created_at=4.0, metadata={"query": "risk limits"}),
        SimpleNamespace(id=5, namespace=namespace, created_at=5.0, metadata={"query": "budget recall"}),
        SimpleNamespace(id=6, namespace=namespace, created_at=6.0, metadata={"query": "status update"}),
        SimpleNamespace(id=7, namespace=namespace, created_at=7.0, metadata={"query": "tax planning"}),
    ]

    edges = worker._transition_edges(
        events,
        hot_queries,
        max_queries=4,
        window_seconds=60,
    )

    assert [(edge.from_query, edge.to_query) for edge in edges] == [
        ("status update", "tax planning"),
        ("budget recall", "risk limits"),
    ]
    assert edges[0].count == 1
    assert edges[0].probability == 1.0
    assert edges[1].count == 2
    assert edges[1].probability == 2 / 3
    assert all(edge.to_query != "status update" for edge in edges)


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
        suggestion_ids = {suggestion.id for suggestion in report.suggestions}
        suggestion_severities = {suggestion.severity for suggestion in report.suggestions}
        assert "architecture:namespace-sharding" in suggestion_ids
        assert "architecture:service-index" in suggestion_ids
        assert "architecture:production-controls" in suggestion_ids
        assert "architecture_required" in suggestion_severities
        assert all(suggestion.evidence for suggestion in report.suggestions)
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


def test_redis_memory_os_lock_is_single_flight_and_owner_checked():
    redis = FakeRedis()
    first = RedisMemoryOSLock(redis, key="wavemind:memory-os:lock:agent", ttl_seconds=30, owner="one")
    second = RedisMemoryOSLock(redis, key="wavemind:memory-os:lock:agent", ttl_seconds=30, owner="two")

    assert first.acquire() is True
    assert second.acquire() is False
    assert redis.items["wavemind:memory-os:lock:agent"] == "one"
    assert second.release() is False
    assert redis.items["wavemind:memory-os:lock:agent"] == "one"
    assert first.release() is True
    assert second.acquire() is True


def test_memory_os_worker_required_lock_without_lock_skips_mutation(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-required-lock.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        id = memory.remember("required lock should protect priority", namespace="agent", priority=1.0)
        before = memory.store.get(id).priority

        report = MemoryOSWorker(memory).run_once(
            namespace="agent",
            lock_required=True,
            priority_boost_per_hit=1.0,
            forgetting_min_age_seconds=0.0,
        )

        assert not report.ok
        assert report.lock.required is True
        assert report.lock.acquired is False
        assert report.lock.reason == "lock_required_without_lock"
        assert report.actions == ("lock_skipped",)
        assert memory.store.get(id).priority == before
    finally:
        memory.close()


def test_memory_os_worker_busy_redis_lock_skips_cycle(tmp_path):
    redis = FakeRedis()
    held = RedisMemoryOSLock(redis, key="wavemind:memory-os:lock:agent", ttl_seconds=30, owner="owner-a")
    contender = RedisMemoryOSLock(redis, key="wavemind:memory-os:lock:agent", ttl_seconds=30, owner="owner-b")
    assert held.acquire() is True

    memory = WaveMind(
        db_path=tmp_path / "memory-os-busy-lock.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        id = memory.remember("busy lock should skip priority mutation", namespace="agent", priority=1.0)
        memory.query("priority mutation", namespace="agent", top_k=1)
        memory.query("priority mutation", namespace="agent", top_k=1)
        before = memory.store.get(id).priority

        report = MemoryOSWorker(memory).run_once(
            namespace="agent",
            lock=contender,
            lock_required=True,
            priority_boost_per_hit=1.0,
            consolidate_steps=0,
            consolidate_concepts=False,
        )

        assert not report.ok
        assert report.lock.required is True
        assert report.lock.acquired is False
        assert report.lock.reason == "lock_already_held"
        assert report.actions == ("lock_skipped",)
        assert memory.store.get(id).priority == before
        assert redis.items["wavemind:memory-os:lock:agent"] == "owner-a"
    finally:
        held.release()
        memory.close()


def test_memory_os_scheduler_plans_production_workers_without_mutation(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-scheduler.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        audit_queries=True,
    )
    try:
        memory.remember("scheduler should prewarm budget recall", namespace="ops")
        memory.remember("scheduler should preserve cold note", namespace="ops")
        for _ in range(3):
            memory.query("budget recall", namespace="ops", top_k=1)
        before_stats = memory.stats(namespace="ops")

        plan = MemoryOSScheduler(memory).plan(
            namespace="ops",
            audit_limit=20,
            max_hot_queries=8,
            min_frequency=2,
            top_k=1,
            target_memories=2_000_000,
            namespace_count=4096,
            node_count=2,
            deployment="production",
            cache_mode="auto",
            target_qps=500.0,
            observed_p99_ms=150.0,
            multimodal=True,
        )
        after_stats = memory.stats(namespace="ops")
        task_by_id = {task.id: task for task in plan.tasks}

        assert plan.status == "architecture_required"
        assert plan.effective_cache_mode == "redis"
        assert plan.worker_count >= 5
        assert plan.hot_query_count == 1
        assert "Redis-compatible shared hot-query cache" in plan.required_infrastructure
        assert task_by_id["memory-os"].enabled is True
        assert task_by_id["memory-os"].requires_distributed_lock is True
        assert "--redis-url $WAVEMIND_REDIS_URL" in task_by_id["memory-os"].command
        assert task_by_id["cache-prewarm"].enabled is True
        assert task_by_id["predictive-prefetch"].enabled is True
        assert task_by_id["architecture-advice"].enabled is True
        assert "service-index" in {
            item["id"]
            for item in plan.architecture_advice["recommendations"]
            if isinstance(item, dict)
        }
        assert before_stats["active_memories"] == after_stats["active_memories"]
        assert memory.audit_events(namespace="ops", action="memory_os", limit=1) == []
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


def test_active_active_sync_worker_converges_incremental_writes_and_tombstones(tmp_path):
    region_a = _active_region(tmp_path, "region-a")
    region_b = _active_region(tmp_path, "region-b")
    try:
        namespace = "tenant:active-active-worker"
        region_a.remember("region a user prefers low latency recall", namespace=namespace)
        region_b.remember("region b user budget is 2000", namespace=namespace)
        worker = ActiveActiveSyncWorker({"region-a": region_a, "region-b": region_b})

        first = worker.run_once([namespace])
        second = worker.run_once(namespaces=[namespace])

        assert first.ok
        assert first.records_imported == 6
        assert first.failed_pairs == 0
        assert len(worker.cursors) == 2
        assert second.ok
        assert second.records_imported == 0
        assert second.tombstones_imported == 0
        assert region_a.query("budget 2000", namespace=namespace, top_k=1)[0].text == (
            "region b user budget is 2000"
        )
        assert region_b.query("low latency recall", namespace=namespace, top_k=1)[0].text == (
            "region a user prefers low latency recall"
        )

        region_a.remember("region a user wants weekly market summaries", namespace=namespace)
        incremental = worker.run_once(namespaces=[namespace])

        assert incremental.ok
        assert incremental.records_imported == 3
        assert region_b.query("weekly market summaries", namespace=namespace, top_k=1)[0].text == (
            "region a user wants weekly market summaries"
        )

        region_b.forget(text="region b user budget is 2000", namespace=namespace)
        tombstone = worker.run_once(namespaces=[namespace])
        region_a_results = region_a.query("budget 2000", namespace=namespace, top_k=3)
        region_b_results = region_b.query("budget 2000", namespace=namespace, top_k=3)

        assert tombstone.ok
        assert tombstone.deleted_records >= 3
        assert tombstone.tombstones_imported >= 1
        assert all(result.text != "region b user budget is 2000" for result in region_a_results)
        assert all(result.text != "region b user budget is 2000" for result in region_b_results)
    finally:
        region_a.close()
        region_b.close()


def test_active_active_sync_worker_reports_failed_region_pair(tmp_path):
    region_a = _active_region(tmp_path, "region-a")
    region_b = _active_region(tmp_path, "region-b")
    try:
        namespace = "tenant:active-active-failure"
        region_a.remember("region a memory cannot reach unavailable target", namespace=namespace)
        placement = region_b.placement(namespace)
        for node_id in placement.replicas[:2]:
            region_b.set_node_available(node_id, False)
        worker = ActiveActiveSyncWorker({"region-a": region_a, "region-b": region_b})

        report = worker.run_once(namespaces=[namespace])

        assert not report.ok
        assert report.failed_pairs == 1
        failed = [pair for pair in report.pair_reports if not pair.ok]
        assert len(failed) == 1
        assert failed[0].source_region == "region-a"
        assert failed[0].target_region == "region-b"
        assert "quorum" in str(failed[0].error).lower()
    finally:
        region_a.close()
        region_b.close()


def test_http_active_active_sync_worker_syncs_service_regions_incrementally(tmp_path):
    region_a = _active_region(tmp_path, "http-region-a")
    region_b = _active_region(tmp_path, "http-region-b")
    try:
        namespace = "tenant:http-active-active"
        region_a.remember("http region a remembers trading budget", namespace=namespace)
        region_b.remember("http region b remembers concise answers", namespace=namespace)
        client = FakeHTTPActiveActiveClient({"https://a": region_a, "https://b": region_b})
        worker = HTTPActiveActiveSyncWorker(
            {"region-a": "https://a/", "region-b": "https://b"},
            client=client,
        )

        first = worker.run_once(namespaces=[namespace])
        second = worker.run_once(namespaces=[namespace])

        region_a_results = region_a.query("concise answers", namespace=namespace, top_k=3)
        region_b_results = region_b.query("trading budget", namespace=namespace, top_k=3)

        assert first.ok
        assert len(first.pair_reports) == 2
        assert sum(pair.exported_records for pair in first.pair_reports) >= 2
        assert first.records_imported >= 6
        assert len(worker.cursors) == 2
        assert all(pair.to_cursor is not None for pair in first.pair_reports)
        assert second.ok
        assert second.records_imported == 0
        assert client.exports[0] == ("https://a", namespace, None, None)
        assert client.exports[2][2] is not None
        assert any(result.text == "http region b remembers concise answers" for result in region_a_results)
        assert any(result.text == "http region a remembers trading budget" for result in region_b_results)
    finally:
        region_a.close()
        region_b.close()


def test_http_active_active_sync_worker_reports_unavailable_service_region(tmp_path):
    region_a = _active_region(tmp_path, "http-region-fail-a")
    region_b = _active_region(tmp_path, "http-region-fail-b")
    try:
        namespace = "tenant:http-active-active-failure"
        region_a.remember("http active active source write", namespace=namespace)
        client = FailingHTTPActiveActiveClient({"https://a": region_a, "https://b": region_b})
        worker = HTTPActiveActiveSyncWorker(
            {"region-a": "https://a", "region-b": "https://b"},
            client=client,
        )

        report = worker.run_once(namespaces=[namespace], fail_fast=True)

        assert not report.ok
        assert report.failed_pairs == 1
        assert len(report.pair_reports) == 1
        failed = report.pair_reports[0]
        assert failed.source_region == "region-a"
        assert failed.target_region == "region-b"
        assert "unavailable" in str(failed.error)
    finally:
        region_a.close()
        region_b.close()


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
