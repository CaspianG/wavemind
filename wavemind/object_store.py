from __future__ import annotations

import hashlib
import mimetypes
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


@dataclass(frozen=True)
class ObjectStoreAssetReport:
    uri: str
    bucket: str
    key: str
    total_bytes: int
    sha256: str
    media_type: str
    verified: bool
    kind: str | None = None
    etag: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "bucket": self.bucket,
            "key": self.key,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "verified": self.verified,
            "kind": self.kind,
            "etag": self.etag,
        }

    def payload_metadata(self) -> dict[str, object]:
        return {
            "asset_uri": self.uri,
            "asset_bucket": self.bucket,
            "asset_key": self.key,
            "asset_bytes": self.total_bytes,
            "asset_sha256": self.sha256,
            "asset_media_type": self.media_type,
            "asset_verified": self.verified,
            **({"asset_kind": self.kind} if self.kind else {}),
        }


@dataclass(frozen=True)
class ObjectStoreArchive:
    uri: str
    bucket: str
    key: str
    total_bytes: int
    sha256: str | None
    verified: bool
    last_modified: str | None = None
    etag: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "bucket": self.bucket,
            "key": self.key,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "verified": self.verified,
            "last_modified": self.last_modified,
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

    def list_archives(
        self,
        *,
        prefix: str | None = None,
        verify_metadata: bool = True,
    ) -> tuple[ObjectStoreArchive, ...]:
        list_prefix = self._list_prefix(prefix)
        archives: list[ObjectStoreArchive] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": list_prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            response = dict(self.client.list_objects_v2(**kwargs))
            for item in response.get("Contents") or []:
                key = str(item.get("Key") or "")
                if not _is_snapshot_archive_key(key):
                    continue
                head = self._head(key) if verify_metadata else {}
                metadata = {
                    str(k).lower(): str(v)
                    for k, v in dict(head.get("Metadata") or {}).items()
                }
                total_bytes = int(
                    head.get("ContentLength", item.get("Size", -1))
                )
                sha256 = metadata.get("wavemind-sha256")
                metadata_bytes = metadata.get("wavemind-bytes")
                verified = True
                if verify_metadata:
                    verified = (
                        total_bytes >= 0
                        and bool(sha256)
                        and metadata_bytes == str(total_bytes)
                    )
                archives.append(
                    ObjectStoreArchive(
                        uri=f"{self.scheme}://{self.bucket}/{key}",
                        bucket=self.bucket,
                        key=key,
                        total_bytes=total_bytes,
                        sha256=sha256,
                        verified=verified,
                        last_modified=_format_last_modified(
                            item.get("LastModified")
                        ),
                        etag=str(head.get("ETag") or item.get("ETag") or "")
                        or None,
                    )
                )
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
            if not token:
                break
        return tuple(
            sorted(
                archives,
                key=lambda archive: (archive.last_modified or "", archive.key),
                reverse=True,
            )
        )

    def latest_archive(
        self,
        *,
        prefix: str | None = None,
        verify_metadata: bool = True,
    ) -> ObjectStoreArchive | None:
        archives = self.list_archives(
            prefix=prefix,
            verify_metadata=verify_metadata,
        )
        return archives[0] if archives else None

    def describe_archive(
        self,
        uri_or_key: str,
        *,
        verify_metadata: bool = True,
    ) -> ObjectStoreArchive:
        key = self._key_from_uri_or_key(uri_or_key)
        head = self._head(key)
        metadata = {
            str(k).lower(): str(v)
            for k, v in dict(head.get("Metadata") or {}).items()
        }
        total_bytes = int(head.get("ContentLength", -1))
        sha256 = metadata.get("wavemind-sha256")
        metadata_bytes = metadata.get("wavemind-bytes")
        verified = True
        if verify_metadata:
            verified = (
                total_bytes >= 0
                and bool(sha256)
                and metadata_bytes == str(total_bytes)
            )
        return ObjectStoreArchive(
            uri=f"{self.scheme}://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            total_bytes=total_bytes,
            sha256=sha256,
            verified=verified,
            last_modified=_format_last_modified(head.get("LastModified")),
            etag=str(head.get("ETag") or "") or None,
        )

    def prune_archives(
        self,
        *,
        keep_last: int,
        prefix: str | None = None,
        verify_metadata: bool = True,
    ) -> tuple[ObjectStoreArchive, ...]:
        keep_last = max(0, int(keep_last))
        archives = self.list_archives(
            prefix=prefix,
            verify_metadata=verify_metadata,
        )
        removable = archives[keep_last:]
        if not removable:
            return ()
        objects = [{"Key": archive.key} for archive in removable]
        if hasattr(self.client, "delete_objects"):
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": objects, "Quiet": True},
            )
        else:
            for item in objects:
                self.client.delete_object(Bucket=self.bucket, Key=item["Key"])
        return tuple(removable)

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

    def _list_prefix(self, prefix: str | None) -> str:
        if prefix is None:
            prefix = self.prefix
        prefix = prefix.strip("/")
        return prefix


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class S3AssetStore:
    """S3-compatible content-addressed storage for multimodal memory assets.

    WaveMind keeps vectors, text descriptors, and metadata in the memory store.
    Large media files should live in object storage and be referenced by a
    verified sha256/byte-size manifest. This class intentionally uses the same
    S3-compatible client contract as S3SnapshotStore, so AWS S3, R2, MinIO, and
    tests can share the same operational path.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "assets",
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
    ) -> "S3AssetStore":
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

    def upload_asset(
        self,
        asset_path: str | Path,
        *,
        media_type: str | None = None,
        kind: str | None = None,
        key: str | None = None,
        metadata: dict[str, str] | None = None,
        verify: bool = True,
    ) -> ObjectStoreAssetReport:
        path = Path(asset_path)
        if not path.exists():
            raise FileNotFoundError(f"asset does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"asset path is not a file: {path}")
        digest = _sha256_file(path)
        total_bytes = path.stat().st_size
        resolved_media_type = media_type or _guess_media_type(path.name)
        resolved_key = self._resolve_asset_key(
            key=key,
            digest=digest,
            suffix=path.suffix,
        )
        self._upload_file(
            path,
            key=resolved_key,
            media_type=resolved_media_type,
            total_bytes=total_bytes,
            sha256=digest,
            kind=kind,
            metadata=metadata,
        )
        return self._report(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=kind,
            verify=verify,
        )

    def put_asset_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        media_type: str | None = None,
        kind: str | None = None,
        key: str | None = None,
        metadata: dict[str, str] | None = None,
        verify: bool = True,
    ) -> ObjectStoreAssetReport:
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        total_bytes = len(payload)
        suffix = Path(filename).suffix
        resolved_media_type = media_type or _guess_media_type(filename)
        resolved_key = self._resolve_asset_key(
            key=key,
            digest=digest,
            suffix=suffix,
        )
        self._upload_bytes(
            payload,
            key=resolved_key,
            media_type=resolved_media_type,
            total_bytes=total_bytes,
            sha256=digest,
            kind=kind,
            metadata=metadata,
        )
        return self._report(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=kind,
            verify=verify,
        )

    def describe_asset(
        self,
        uri_or_key: str,
        *,
        verify_metadata: bool = True,
    ) -> ObjectStoreAssetReport:
        key = self._key_from_uri_or_key(uri_or_key)
        head = self._head(key)
        metadata = _lower_metadata(head)
        total_bytes = int(head.get("ContentLength", -1))
        sha256 = metadata.get("wavemind-sha256", "")
        media_type = metadata.get("wavemind-media-type") or str(
            head.get("ContentType") or "application/octet-stream"
        )
        verified = True
        if verify_metadata:
            verified = (
                total_bytes >= 0
                and bool(sha256)
                and metadata.get("wavemind-bytes") == str(total_bytes)
                and bool(media_type)
            )
        return ObjectStoreAssetReport(
            uri=f"{self.scheme}://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            total_bytes=total_bytes,
            sha256=sha256,
            media_type=media_type,
            kind=metadata.get("wavemind-asset-kind") or None,
            verified=verified,
            etag=str(head.get("ETag") or "") or None,
        )

    def verify_asset_object(
        self,
        *,
        key: str,
        sha256: str,
        total_bytes: int,
    ) -> bool:
        report = self.describe_asset(key)
        return (
            report.sha256 == sha256
            and report.total_bytes == int(total_bytes)
            and report.verified
        )

    def _resolve_asset_key(self, *, key: str | None, digest: str, suffix: str) -> str:
        if key:
            return key.strip("/")
        suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
        filename = f"{digest}{suffix}"
        return f"{self.prefix.rstrip('/')}/{digest[:2]}/{filename}" if self.prefix else f"{digest[:2]}/{filename}"

    def _upload_bytes(
        self,
        data: bytes,
        *,
        key: str,
        media_type: str,
        total_bytes: int,
        sha256: str,
        kind: str | None,
        metadata: dict[str, str] | None,
    ) -> None:
        object_metadata = {
            "wavemind-sha256": sha256,
            "wavemind-bytes": str(total_bytes),
            "wavemind-media-type": media_type,
        }
        if kind:
            object_metadata["wavemind-asset-kind"] = str(kind)
        object_metadata.update(metadata or {})
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            Metadata=object_metadata,
        )

    def _upload_file(
        self,
        path: Path,
        *,
        key: str,
        media_type: str,
        total_bytes: int,
        sha256: str,
        kind: str | None,
        metadata: dict[str, str] | None,
    ) -> None:
        object_metadata = {
            "wavemind-sha256": sha256,
            "wavemind-bytes": str(total_bytes),
            "wavemind-media-type": media_type,
        }
        if kind:
            object_metadata["wavemind-asset-kind"] = str(kind)
        object_metadata.update(metadata or {})
        extra_args = {
            "ContentType": media_type,
            "Metadata": object_metadata,
        }
        if hasattr(self.client, "upload_file"):
            self.client.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs=extra_args,
            )
            return
        with path.open("rb") as handle:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=handle.read(),
                ContentType=media_type,
                Metadata=object_metadata,
            )

    def _report(
        self,
        *,
        key: str,
        total_bytes: int,
        sha256: str,
        media_type: str,
        kind: str | None,
        verify: bool,
    ) -> ObjectStoreAssetReport:
        head = self._head(key) if verify else {}
        metadata = _lower_metadata(head)
        verified = True
        if verify:
            verified = (
                int(head.get("ContentLength", -1)) == int(total_bytes)
                and metadata.get("wavemind-sha256") == sha256
                and metadata.get("wavemind-bytes") == str(int(total_bytes))
                and metadata.get("wavemind-media-type") == media_type
            )
        return ObjectStoreAssetReport(
            uri=f"{self.scheme}://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            total_bytes=total_bytes,
            sha256=sha256,
            media_type=media_type,
            kind=kind,
            verified=verified,
            etag=head.get("ETag") if head else None,
        )

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


def _is_snapshot_archive_key(key: str) -> bool:
    return key.endswith(".tar.gz") or key.endswith(".tgz")


def _guess_media_type(filename: str) -> str:
    media_type, _encoding = mimetypes.guess_type(filename)
    return media_type or "application/octet-stream"


def _lower_metadata(head: dict[str, Any]) -> dict[str, str]:
    return {
        str(k).lower(): str(v)
        for k, v in dict(head.get("Metadata") or {}).items()
    }


def _format_last_modified(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)
