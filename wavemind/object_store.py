from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ObjectStoreLocation:
    scheme: str
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"{self.scheme}://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class ObjectStoreUploadReport:
    uri: str
    bucket: str
    key: str
    total_bytes: int
    sha256: str
    verified: bool
    etag: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "bucket": self.bucket,
            "key": self.key,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "verified": self.verified,
            "etag": self.etag,
        }


def parse_object_store_uri(uri: str) -> ObjectStoreLocation:
    parsed = urlparse(uri)
    if parsed.scheme not in {"s3"}:
        raise ValueError("object-store URI must use s3://")
    if not parsed.netloc:
        raise ValueError("object-store URI must include a bucket")
    key = parsed.path.lstrip("/")
    if not key:
        raise ValueError("object-store URI must include a key or prefix")
    return ObjectStoreLocation(
        scheme=parsed.scheme,
        bucket=parsed.netloc,
        key=key,
    )


class S3SnapshotStore:
    """S3-compatible storage for replicated snapshot archives.

    The same class works with AWS S3, Cloudflare R2, MinIO, and other
    S3-compatible APIs. Pass a preconfigured client in tests or create one from
    environment-backed boto3 credentials with `from_uri()`.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        client: Any,
        scheme: str = "s3",
    ):
        if not bucket:
            raise ValueError("bucket is required")
        if scheme != "s3":
            raise ValueError("only s3-compatible stores are supported")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client
        self.scheme = scheme

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: Any | None = None,
        **client_kwargs: Any,
    ) -> "S3SnapshotStore":
        location = parse_object_store_uri(uri)
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    'Install S3 support with: pip install "wavemind[s3]"'
                ) from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region_name,
                **client_kwargs,
            )
        return cls(
            bucket=location.bucket,
            prefix=location.key,
            client=client,
            scheme=location.scheme,
        )

    def upload_archive(
        self,
        archive_path: str | Path,
        *,
        key: str | None = None,
        verify: bool = True,
    ) -> ObjectStoreUploadReport:
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"snapshot archive does not exist: {archive_path}")
        resolved_key = self._resolve_key(key, default_name=archive_path.name)
        total_bytes = archive_path.stat().st_size
        digest = _sha256_file(archive_path)
        metadata = {
            "wavemind-sha256": digest,
            "wavemind-bytes": str(total_bytes),
        }
        extra_args = {
            "ContentType": "application/gzip",
            "Metadata": metadata,
        }
        if hasattr(self.client, "upload_file"):
            self.client.upload_file(
                str(archive_path),
                self.bucket,
                resolved_key,
                ExtraArgs=extra_args,
            )
        else:
            with archive_path.open("rb") as handle:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=resolved_key,
                    Body=handle.read(),
                    ContentType="application/gzip",
                    Metadata=metadata,
                )

        head = self._head(resolved_key) if verify else {}
        verified = True
        if verify:
            object_bytes = int(head.get("ContentLength", -1))
            object_metadata = {
                str(k).lower(): str(v)
                for k, v in dict(head.get("Metadata") or {}).items()
            }
            verified = (
                object_bytes == total_bytes
                and object_metadata.get("wavemind-sha256") == digest
                and object_metadata.get("wavemind-bytes") == str(total_bytes)
            )
        return ObjectStoreUploadReport(
            uri=f"{self.scheme}://{self.bucket}/{resolved_key}",
            bucket=self.bucket,
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            verified=verified,
            etag=head.get("ETag") if head else None,
        )

    def download_archive(
        self,
        uri_or_key: str,
        destination: str | Path,
    ) -> Path:
        key = self._key_from_uri_or_key(uri_or_key)
        destination = Path(destination)
        if destination.suffix:
            target = destination
        else:
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / Path(key).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(self.client, "download_file"):
            self.client.download_file(self.bucket, key, str(target))
        else:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            data = body.read() if hasattr(body, "read") else body
            target.write_bytes(data)
        return target

    def verify_archive_object(
        self,
        *,
        key: str,
        sha256: str,
        total_bytes: int,
    ) -> bool:
        head = self._head(key)
        metadata = {
            str(k).lower(): str(v)
            for k, v in dict(head.get("Metadata") or {}).items()
        }
        return (
            int(head.get("ContentLength", -1)) == int(total_bytes)
            and metadata.get("wavemind-sha256") == sha256
            and metadata.get("wavemind-bytes") == str(int(total_bytes))
        )

    def _resolve_key(self, key: str | None, *, default_name: str) -> str:
        if key:
            return key.strip("/")
        if self.prefix.endswith(".tar.gz") or self.prefix.endswith(".tgz"):
            return self.prefix
        return f"{self.prefix.rstrip('/')}/{default_name}" if self.prefix else default_name

    def _key_from_uri_or_key(self, uri_or_key: str) -> str:
        if uri_or_key.startswith("s3://"):
            location = parse_object_store_uri(uri_or_key)
            if location.bucket != self.bucket:
                raise ValueError(
                    f"object bucket mismatch: expected {self.bucket!r}, got {location.bucket!r}"
                )
            return location.key
        return uri_or_key.strip("/")

    def _head(self, key: str) -> dict[str, Any]:
        return dict(self.client.head_object(Bucket=self.bucket, Key=key))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
