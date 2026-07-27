from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

from wavemind import (
    FilesystemAssetStore,
    S3AssetStore,
    S3SnapshotStore,
    parse_object_store_uri,
)


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.counter = 0

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.counter += 1
        self.objects[(bucket, key)] = {
            "Body": Path(filename).read_bytes(),
            "ContentType": (ExtraArgs or {}).get("ContentType"),
            "Metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        self.counter += 1
        payload = Body.read() if hasattr(Body, "read") else Body
        self.objects[(Bucket, Key)] = {
            "Body": bytes(payload),
            "ContentType": ContentType,
            "Metadata": dict(Metadata or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)]["Body"])

    def head_object(self, Bucket, Key):
        payload = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(payload["Body"]),
            "Metadata": dict(payload["Metadata"]),
            "ContentType": payload.get("ContentType"),
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

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}


def test_parse_object_store_uri_requires_s3_bucket_and_key():
    location = parse_object_store_uri("s3://wavemind-backups/prod/snapshot.tar.gz")

    assert location.bucket == "wavemind-backups"
    assert location.key == "prod/snapshot.tar.gz"
    assert location.uri == "s3://wavemind-backups/prod/snapshot.tar.gz"

    with pytest.raises(ValueError):
        parse_object_store_uri("https://example.com/backups")
    with pytest.raises(ValueError):
        parse_object_store_uri("s3:///missing-bucket")
    with pytest.raises(ValueError):
        parse_object_store_uri("s3://bucket")


def test_s3_snapshot_store_uploads_verifies_and_downloads_archive(tmp_path):
    archive = tmp_path / "snapshot.tar.gz"
    archive.write_bytes(b"snapshot-bytes")
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/prod",
        client=client,
    )

    report = store.upload_archive(archive)
    downloaded = store.download_archive(report.uri, tmp_path / "downloaded")

    assert report.uri == "s3://wavemind-backups/prod/snapshot.tar.gz"
    assert report.total_bytes == len(b"snapshot-bytes")
    assert report.verified is True
    assert report.etag == '"fake-etag"'
    assert store.verify_archive_object(
        key=report.key,
        sha256=report.sha256,
        total_bytes=report.total_bytes,
    )
    assert downloaded.read_bytes() == b"snapshot-bytes"


def test_s3_snapshot_store_accepts_exact_archive_uri(tmp_path):
    archive = tmp_path / "local-name.tar.gz"
    archive.write_bytes(b"exact-key")
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/exact/remote-name.tar.gz",
        client=client,
    )

    report = store.upload_archive(archive)

    assert report.key == "exact/remote-name.tar.gz"
    assert report.uri == "s3://wavemind-backups/exact/remote-name.tar.gz"


def test_s3_snapshot_store_describes_exact_archive(tmp_path):
    archive = tmp_path / "snapshot.tar.gz"
    archive.write_bytes(b"describe-me")
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/prod",
        client=client,
    )
    upload = store.upload_archive(archive)

    described = store.describe_archive(upload.uri)

    assert described.uri == upload.uri
    assert described.key == upload.key
    assert described.total_bytes == upload.total_bytes
    assert described.sha256 == upload.sha256
    assert described.verified is True


def test_s3_snapshot_store_lists_latest_and_prunes_archives(tmp_path):
    client = FakeS3Client()
    store = S3SnapshotStore.from_uri(
        "s3://wavemind-backups/prod",
        client=client,
    )

    reports = []
    for index in range(3):
        archive = tmp_path / f"snapshot-{index}.tar.gz"
        archive.write_bytes(f"snapshot-{index}".encode("utf-8"))
        reports.append(store.upload_archive(archive))

    archives = store.list_archives()
    latest = store.latest_archive()
    pruned = store.prune_archives(keep_last=1)
    remaining = store.list_archives()

    assert [archive.key for archive in archives] == [
        reports[2].key,
        reports[1].key,
        reports[0].key,
    ]
    assert latest is not None
    assert latest.key == reports[2].key
    assert all(archive.verified for archive in archives)
    assert [archive.key for archive in pruned] == [reports[1].key, reports[0].key]
    assert [archive.key for archive in remaining] == [reports[2].key]


def test_s3_asset_store_uploads_content_addressed_asset(tmp_path):
    asset = tmp_path / "demo.mp4"
    asset.write_bytes(b"video-bytes")
    client = FakeS3Client()
    store = S3AssetStore.from_uri("s3://wavemind-assets/media", client=client)

    report = store.upload_asset(asset, kind="video")
    described = store.describe_asset(report.uri)

    assert report.uri.startswith("s3://wavemind-assets/media/")
    assert report.key.endswith(".mp4")
    assert report.sha256 in report.key
    assert report.media_type == "video/mp4"
    assert report.kind == "video"
    assert report.total_bytes == len(b"video-bytes")
    assert report.verified is True
    assert described == report
    assert store.verify_asset_object(
        key=report.key,
        sha256=report.sha256,
        total_bytes=report.total_bytes,
    )
    payload_metadata = report.payload_metadata()
    assert payload_metadata["asset_uri"] == report.uri
    assert payload_metadata["asset_bucket"] == "wavemind-assets"
    assert payload_metadata["asset_key"] == report.key
    assert payload_metadata["asset_bytes"] == report.total_bytes
    assert payload_metadata["asset_sha256"] == report.sha256
    assert payload_metadata["asset_media_type"] == "video/mp4"
    assert payload_metadata["asset_verified"] is True
    assert payload_metadata["asset_kind"] == "video"
    assert payload_metadata["asset_namespace"] == "default"
    assert payload_metadata["asset_source_uri"] == asset.resolve().as_uri()
    assert payload_metadata["asset_created_at"].endswith("Z")


def test_s3_asset_store_puts_bytes_with_custom_media_type():
    client = FakeS3Client()
    store = S3AssetStore.from_uri("s3://wavemind-assets/assets", client=client)

    report = store.put_asset_bytes(
        b"glb-bytes",
        filename="robot.glb",
        media_type="model/gltf-binary",
        kind="3d",
    )

    assert report.media_type == "model/gltf-binary"
    assert report.kind == "3d"
    assert report.key.endswith(".glb")
    assert store.describe_asset(report.key).verified is True


def test_s3_asset_store_enforces_namespace_owner_and_provenance():
    client = FakeS3Client()
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    store_a = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=client,
        namespace="tenant:a",
        owner="user:a",
        clock=lambda: now,
    )
    store_b = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=client,
        namespace="tenant:b",
        owner="user:b",
        clock=lambda: now,
    )

    report_a = store_a.put_asset_bytes(
        b"image-bytes",
        filename="frame.png",
        kind="image",
        source_uri="file:///capture/frame.png",
        encoder="openclip",
        model_revision="ViT-B-32@abc123",
        derived_from=("event:1",),
        provenance=(
            {"event_id": "event:1", "operation": "screen-capture"},
        ),
    )
    report_b = store_b.put_asset_bytes(
        b"image-bytes",
        filename="frame.png",
        kind="image",
    )

    assert report_a.key != report_b.key
    assert report_a.namespace == "tenant:a"
    assert report_a.owner == "user:a"
    assert report_a.encoder == "openclip"
    assert report_a.model_revision == "ViT-B-32@abc123"
    assert report_a.derived_from == ("event:1",)
    assert report_a.provenance[0]["operation"] == "screen-capture"
    assert store_a.get_asset_bytes(report_a.uri) == b"image-bytes"
    with pytest.raises(PermissionError):
        store_b.describe_asset(report_a.uri)
    with pytest.raises(PermissionError):
        store_a.put_asset_bytes(
            b"other",
            filename="other.png",
            kind="image",
            owner="user:b",
        )


def test_s3_asset_store_detects_tampering_and_validates_limits_and_types():
    client = FakeS3Client()
    store = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=client,
        namespace="tenant:a",
        max_asset_bytes=12,
        allowed_media_types={"image/*", "model/gltf-binary"},
    )
    report = store.put_asset_bytes(
        b"image-bytes",
        filename="frame.png",
        kind="image",
    )
    client.objects[(report.bucket, report.key)]["Body"] = b"tampered"

    with pytest.raises(ValueError, match="checksum"):
        store.get_asset_bytes(report.uri)
    with pytest.raises(ValueError, match="max_asset_bytes"):
        store.put_asset_bytes(
            b"x" * 13,
            filename="large.png",
            kind="image",
        )
    with pytest.raises(ValueError, match="incompatible"):
        store.put_asset_bytes(
            b"image",
            filename="wrong.png",
            media_type="image/png",
            kind="audio",
        )
    with pytest.raises(ValueError, match="not allowed"):
        store.put_asset_bytes(
            b"audio",
            filename="sample.wav",
            kind="audio",
        )
    with pytest.raises(ValueError, match="reserved"):
        store.put_asset_bytes(
            b"image",
            filename="frame.png",
            kind="image",
            metadata={"wavemind-owner": "override"},
        )


def test_s3_asset_store_ttl_delete_tombstone_and_orphan_cleanup():
    client = FakeS3Client()
    current = [datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)]
    store = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=client,
        namespace="tenant:a",
        clock=lambda: current[0],
    )
    retained = store.put_asset_bytes(
        b"retained",
        filename="retained.txt",
        kind="text",
    )
    expiring = store.put_asset_bytes(
        b"expiring",
        filename="expiring.txt",
        kind="text",
        ttl_seconds=60,
    )

    assert len(store.list_assets()) == 2
    current[0] += timedelta(seconds=61)
    assert store.list_assets() == (retained,)
    assert len(store.list_assets(include_expired=True)) == 2
    preview = store.cleanup_expired(dry_run=True)
    assert preview.candidates == (expiring.uri,)
    assert preview.deleted == ()

    deleted = store.cleanup_expired(dry_run=False)

    assert deleted.deleted == (expiring.uri,)
    assert deleted.tombstones[0].verified is True
    assert deleted.tombstones[0].status == "deleted"
    assert store.list_assets(include_expired=True) == (retained,)
    assert store.list_tombstones() == deleted.tombstones
    with pytest.raises(KeyError):
        client.head_object(Bucket=store.bucket, Key=expiring.key)

    orphan_preview = store.cleanup_orphans((), dry_run=True)
    assert orphan_preview.candidates == (retained.uri,)
    orphan_cleanup = store.cleanup_orphans((), dry_run=False)
    assert orphan_cleanup.deleted == (retained.uri,)
    assert len(store.list_tombstones()) == 2


def test_s3_asset_store_delete_requires_matching_checksum():
    client = FakeS3Client()
    store = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=client,
        namespace="tenant:a",
    )
    report = store.put_asset_bytes(
        b"important",
        filename="important.txt",
        kind="text",
    )

    with pytest.raises(ValueError, match="precondition"):
        store.delete_asset(
            report.uri,
            expected_sha256="0" * 64,
            reason="requested",
        )

    assert store.describe_asset(report.uri).verified is True


def test_s3_asset_store_backup_and_restore_preserve_lifecycle(tmp_path):
    source_client = FakeS3Client()
    source = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=source_client,
        namespace="tenant:a",
        owner="user:a",
    )
    reports = (
        source.put_asset_bytes(
            b"note",
            filename="note.txt",
            kind="text",
            source_uri="file:///notes/note.txt",
            encoder="text-encoder",
            model_revision="rev-1",
            derived_from=("session:1",),
            provenance=({"session": "session:1"},),
        ),
        source.put_asset_bytes(
            b"image",
            filename="image.png",
            kind="image",
        ),
    )
    backup = source.backup_namespace(tmp_path / "backup.zip")

    target_client = FakeS3Client()
    target = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=target_client,
        namespace="tenant:a",
        owner="user:a",
    )
    restored = target.restore_namespace(backup.path)

    assert backup.asset_count == 2
    assert backup.total_bytes == len(b"noteimage")
    assert backup.verified is True
    assert {item.sha256 for item in restored} == {
        item.sha256 for item in reports
    }
    restored_note = next(item for item in restored if item.kind == "text")
    assert restored_note.source_uri == "file:///notes/note.txt"
    assert restored_note.provenance == ({"session": "session:1"},)
    assert all(
        target.get_asset_bytes(item.uri) in {b"note", b"image"}
        for item in restored
    )

    other_namespace = S3AssetStore.from_uri(
        "s3://wavemind-assets/assets",
        client=target_client,
        namespace="tenant:b",
    )
    with pytest.raises(ValueError, match="namespace"):
        other_namespace.restore_namespace(backup.path)


def test_filesystem_asset_store_persists_and_isolates_namespaces(tmp_path):
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    store = FilesystemAssetStore(
        tmp_path / "assets",
        namespace="tenant:a",
        owner="user:a",
        clock=lambda: now,
    )
    report = store.put_asset_bytes(
        b"audio-bytes",
        filename="sample.wav",
        kind="audio",
        ttl_seconds=3600,
        provenance=({"operation": "record"},),
    )

    reloaded = FilesystemAssetStore(
        tmp_path / "assets",
        namespace="tenant:a",
        owner="user:a",
        clock=lambda: now,
    )
    other = FilesystemAssetStore(
        tmp_path / "assets",
        namespace="tenant:b",
        owner="user:b",
        clock=lambda: now,
    )

    assert reloaded.describe_asset(report.uri) == report
    assert reloaded.get_asset_bytes(report.uri) == b"audio-bytes"
    assert reloaded.list_assets() == (report,)
    assert other.list_assets() == ()
    with pytest.raises(PermissionError):
        other.describe_asset(report.uri)
    with pytest.raises(ValueError, match="safe relative"):
        reloaded.put_asset_bytes(
            b"x",
            filename="x.txt",
            kind="text",
            key="../escape.txt",
        )

    tombstone = reloaded.delete_asset(
        report.uri,
        expected_sha256=report.sha256,
        reason="user-request",
    )

    assert tombstone.verified is True
    assert reloaded.list_assets(include_expired=True) == ()
    assert reloaded._object_exists(report.key) is False
