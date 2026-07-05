from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from wavemind import S3SnapshotStore, parse_object_store_uri


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = {
            "Body": Path(filename).read_bytes(),
            "ContentType": (ExtraArgs or {}).get("ContentType"),
            "Metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
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
