from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from wavemind import S3SnapshotStore, parse_object_store_uri


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

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)]["Body"])

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
