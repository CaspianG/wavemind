import fnmatch
import tarfile
from io import BytesIO
from pathlib import Path

from wavemind import (
    CachePrewarmWorker,
    HashingTextEncoder,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    QueryResult,
    RedisHotMemoryCache,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedSnapshotWorker,
    ReplicatedWaveMind,
    S3SnapshotStore,
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
