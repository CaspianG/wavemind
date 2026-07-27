from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse


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
    namespace: str = "default"
    owner: str | None = None
    source_uri: str | None = None
    encoder: str | None = None
    model_revision: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    derived_from: tuple[str, ...] = ()
    provenance: tuple[dict[str, object], ...] = ()

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
            "namespace": self.namespace,
            "owner": self.owner,
            "source_uri": self.source_uri,
            "encoder": self.encoder,
            "model_revision": self.model_revision,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "derived_from": list(self.derived_from),
            "provenance": [dict(item) for item in self.provenance],
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
            "asset_namespace": self.namespace,
            **({"asset_kind": self.kind} if self.kind else {}),
            **({"asset_owner": self.owner} if self.owner else {}),
            **({"asset_source_uri": self.source_uri} if self.source_uri else {}),
            **({"asset_encoder": self.encoder} if self.encoder else {}),
            **(
                {"asset_model_revision": self.model_revision}
                if self.model_revision
                else {}
            ),
            **({"asset_created_at": self.created_at} if self.created_at else {}),
            **({"asset_expires_at": self.expires_at} if self.expires_at else {}),
            **(
                {"asset_derived_from": list(self.derived_from)}
                if self.derived_from
                else {}
            ),
            **(
                {"asset_provenance": [dict(item) for item in self.provenance]}
                if self.provenance
                else {}
            ),
        }

    def is_expired(self, *, at: datetime | None = None) -> bool:
        if not self.expires_at:
            return False
        return _parse_utc_timestamp(self.expires_at) <= _coerce_utc_datetime(at)


@dataclass(frozen=True)
class AssetTombstone:
    uri: str
    asset_uri: str
    namespace: str
    asset_key: str
    sha256: str
    deleted_at: str
    reason: str
    status: str
    verified: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "asset_uri": self.asset_uri,
            "namespace": self.namespace,
            "asset_key": self.asset_key,
            "sha256": self.sha256,
            "deleted_at": self.deleted_at,
            "reason": self.reason,
            "status": self.status,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class AssetBackupReport:
    path: str
    namespace: str
    asset_count: int
    total_bytes: int
    sha256: str
    verified: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "namespace": self.namespace,
            "asset_count": self.asset_count,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class AssetCleanupReport:
    namespace: str
    reason: str
    dry_run: bool
    candidates: tuple[str, ...]
    deleted: tuple[str, ...]
    tombstones: tuple[AssetTombstone, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "candidates": list(self.candidates),
            "deleted": list(self.deleted),
            "tombstones": [item.as_dict() for item in self.tombstones],
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


ASSET_MANIFEST_SCHEMA = "wavemind.asset-manifest.v1"
ASSET_TOMBSTONE_SCHEMA = "wavemind.asset-tombstone.v1"
ASSET_BACKUP_SCHEMA = "wavemind.asset-backup.v1"
DEFAULT_MAX_ASSET_BYTES = 512 * 1024 * 1024
SUPPORTED_ASSET_KINDS = frozenset(
    {"text", "image", "audio", "video", "3d", "table", "event", "graph"}
)


class _AssetLifecycleMixin:
    namespace: str

    def backup_namespace(
        self,
        destination: str | Path,
        *,
        include_expired: bool = True,
    ) -> AssetBackupReport:
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination / (
                f"wavemind-assets-{_namespace_token(self.namespace)}.zip"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)

        reports = self.list_assets(include_expired=include_expired)
        manifest_assets: list[dict[str, object]] = []
        total_bytes = 0
        with zipfile.ZipFile(
            destination,
            mode="w",
            compression=zipfile.ZIP_STORED,
        ) as archive:
            for index, report in enumerate(reports):
                payload = self.get_asset_bytes(
                    report.uri,
                    expected_sha256=report.sha256,
                )
                archive_name = f"objects/{index:08d}-{report.sha256}"
                archive.writestr(archive_name, payload)
                row = report.as_dict()
                row["archive_name"] = archive_name
                manifest_assets.append(row)
                total_bytes += len(payload)
            manifest = {
                "schema": ASSET_BACKUP_SCHEMA,
                "namespace": self.namespace,
                "asset_count": len(manifest_assets),
                "total_bytes": total_bytes,
                "assets": manifest_assets,
            }
            archive.writestr(
                "manifest.json",
                _canonical_json_bytes(manifest),
            )

        digest = _sha256_file(destination)
        verified = self.verify_backup(destination)
        return AssetBackupReport(
            path=str(destination),
            namespace=self.namespace,
            asset_count=len(manifest_assets),
            total_bytes=total_bytes,
            sha256=digest,
            verified=verified,
        )

    def verify_backup(self, archive_path: str | Path) -> bool:
        archive_path = Path(archive_path)
        try:
            with zipfile.ZipFile(archive_path, mode="r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("schema") != ASSET_BACKUP_SCHEMA:
                    return False
                if manifest.get("namespace") != self.namespace:
                    return False
                assets = manifest.get("assets")
                if not isinstance(assets, list):
                    return False
                total_bytes = 0
                for row in assets:
                    if not isinstance(row, dict):
                        return False
                    archive_name = str(row.get("archive_name") or "")
                    if not _safe_backup_member(archive_name):
                        return False
                    payload = archive.read(archive_name)
                    if hashlib.sha256(payload).hexdigest() != row.get("sha256"):
                        return False
                    if len(payload) != int(row.get("total_bytes", -1)):
                        return False
                    total_bytes += len(payload)
                return (
                    len(assets) == int(manifest.get("asset_count", -1))
                    and total_bytes == int(manifest.get("total_bytes", -1))
                )
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            return False

    def restore_namespace(
        self,
        archive_path: str | Path,
    ) -> tuple[ObjectStoreAssetReport, ...]:
        archive_path = Path(archive_path)
        if not self.verify_backup(archive_path):
            raise ValueError("asset backup failed checksum or namespace validation")
        restored: list[ObjectStoreAssetReport] = []
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            for row in manifest["assets"]:
                payload = archive.read(row["archive_name"])
                restored_report = self.put_asset_bytes(
                    payload,
                    filename=Path(str(row["key"])).name,
                    media_type=str(row["media_type"]),
                    kind=str(row["kind"]) if row.get("kind") else None,
                    owner=str(row["owner"]) if row.get("owner") else None,
                    source_uri=(
                        str(row["source_uri"]) if row.get("source_uri") else None
                    ),
                    encoder=str(row["encoder"]) if row.get("encoder") else None,
                    model_revision=(
                        str(row["model_revision"])
                        if row.get("model_revision")
                        else None
                    ),
                    created_at=(
                        str(row["created_at"]) if row.get("created_at") else None
                    ),
                    expires_at=(
                        str(row["expires_at"]) if row.get("expires_at") else None
                    ),
                    derived_from=tuple(row.get("derived_from") or ()),
                    provenance=tuple(row.get("provenance") or ()),
                )
                if restored_report.sha256 != row["sha256"]:
                    raise ValueError(
                        "restored asset checksum differs from backup manifest"
                    )
                restored.append(restored_report)
        return tuple(restored)

    def find_orphan_assets(
        self,
        referenced_uris_or_keys: Iterable[str],
        *,
        include_expired: bool = True,
    ) -> tuple[ObjectStoreAssetReport, ...]:
        referenced = {
            self._key_from_uri_or_key(value)
            for value in referenced_uris_or_keys
        }
        return tuple(
            report
            for report in self.list_assets(include_expired=include_expired)
            if report.key not in referenced
        )

    def cleanup_orphans(
        self,
        referenced_uris_or_keys: Iterable[str],
        *,
        dry_run: bool = True,
        reason: str = "orphan-cleanup",
    ) -> AssetCleanupReport:
        candidates = self.find_orphan_assets(referenced_uris_or_keys)
        tombstones: list[AssetTombstone] = []
        deleted: list[str] = []
        if not dry_run:
            for report in candidates:
                tombstone = self.delete_asset(
                    report.uri,
                    expected_sha256=report.sha256,
                    reason=reason,
                )
                tombstones.append(tombstone)
                deleted.append(report.uri)
        return AssetCleanupReport(
            namespace=self.namespace,
            reason=reason,
            dry_run=dry_run,
            candidates=tuple(item.uri for item in candidates),
            deleted=tuple(deleted),
            tombstones=tuple(tombstones),
        )

    def cleanup_expired(
        self,
        *,
        at: datetime | None = None,
        dry_run: bool = True,
        reason: str = "ttl-expired",
    ) -> AssetCleanupReport:
        now = _coerce_utc_datetime(at)
        candidates = tuple(
            report
            for report in self.list_assets(include_expired=True)
            if report.is_expired(at=now)
        )
        tombstones: list[AssetTombstone] = []
        deleted: list[str] = []
        if not dry_run:
            for report in candidates:
                tombstone = self.delete_asset(
                    report.uri,
                    expected_sha256=report.sha256,
                    reason=reason,
                )
                tombstones.append(tombstone)
                deleted.append(report.uri)
        return AssetCleanupReport(
            namespace=self.namespace,
            reason=reason,
            dry_run=dry_run,
            candidates=tuple(item.uri for item in candidates),
            deleted=tuple(deleted),
            tombstones=tuple(tombstones),
        )


class S3AssetStore(_AssetLifecycleMixin):
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
        namespace: str = "default",
        owner: str | None = None,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
        allowed_media_types: Iterable[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if not bucket:
            raise ValueError("bucket is required")
        if scheme not in {"s3", "file"}:
            raise ValueError("asset stores support only s3 or file schemes")
        self.namespace = _validate_namespace(namespace)
        self.owner = _optional_text(owner)
        self.max_asset_bytes = _validate_max_asset_bytes(max_asset_bytes)
        self.allowed_media_types = _normalize_allowed_media_types(
            allowed_media_types
        )
        self._clock = clock or _utc_now
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
        namespace: str = "default",
        owner: str | None = None,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
        allowed_media_types: Iterable[str] | None = None,
        clock: Callable[[], datetime] | None = None,
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
            namespace=namespace,
            owner=owner,
            max_asset_bytes=max_asset_bytes,
            allowed_media_types=allowed_media_types,
            clock=clock,
        )

    def upload_asset(
        self,
        asset_path: str | Path,
        *,
        media_type: str | None = None,
        kind: str | None = None,
        key: str | None = None,
        metadata: dict[str, str] | None = None,
        owner: str | None = None,
        source_uri: str | None = None,
        encoder: str | None = None,
        model_revision: str | None = None,
        ttl_seconds: float | None = None,
        created_at: str | datetime | None = None,
        expires_at: str | datetime | None = None,
        derived_from: Sequence[str] = (),
        provenance: Sequence[Mapping[str, object]] = (),
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
        resolved_kind = _validate_asset_payload(
            total_bytes=total_bytes,
            media_type=resolved_media_type,
            kind=kind,
            max_asset_bytes=self.max_asset_bytes,
            allowed_media_types=self.allowed_media_types,
        )
        resolved_key = self._resolve_asset_key(
            key=key,
            digest=digest,
            suffix=path.suffix,
        )
        manifest = self._build_manifest(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=resolved_kind,
            metadata=metadata,
            owner=owner,
            source_uri=source_uri or path.resolve().as_uri(),
            encoder=encoder,
            model_revision=model_revision,
            ttl_seconds=ttl_seconds,
            created_at=created_at,
            expires_at=expires_at,
            derived_from=derived_from,
            provenance=provenance,
        )
        self._upload_file(
            path,
            key=resolved_key,
            media_type=resolved_media_type,
            total_bytes=total_bytes,
            sha256=digest,
            kind=resolved_kind,
            metadata=self._head_metadata(manifest),
        )
        self._put_manifest(resolved_key, manifest)
        return self._report(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=resolved_kind,
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
        owner: str | None = None,
        source_uri: str | None = None,
        encoder: str | None = None,
        model_revision: str | None = None,
        ttl_seconds: float | None = None,
        created_at: str | datetime | None = None,
        expires_at: str | datetime | None = None,
        derived_from: Sequence[str] = (),
        provenance: Sequence[Mapping[str, object]] = (),
        verify: bool = True,
    ) -> ObjectStoreAssetReport:
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        total_bytes = len(payload)
        suffix = Path(filename).suffix
        resolved_media_type = media_type or _guess_media_type(filename)
        resolved_kind = _validate_asset_payload(
            total_bytes=total_bytes,
            media_type=resolved_media_type,
            kind=kind,
            max_asset_bytes=self.max_asset_bytes,
            allowed_media_types=self.allowed_media_types,
        )
        resolved_key = self._resolve_asset_key(
            key=key,
            digest=digest,
            suffix=suffix,
        )
        manifest = self._build_manifest(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=resolved_kind,
            metadata=metadata,
            owner=owner,
            source_uri=source_uri,
            encoder=encoder,
            model_revision=model_revision,
            ttl_seconds=ttl_seconds,
            created_at=created_at,
            expires_at=expires_at,
            derived_from=derived_from,
            provenance=provenance,
        )
        self._upload_bytes(
            payload,
            key=resolved_key,
            media_type=resolved_media_type,
            total_bytes=total_bytes,
            sha256=digest,
            kind=resolved_kind,
            metadata=self._head_metadata(manifest),
        )
        self._put_manifest(resolved_key, manifest)
        return self._report(
            key=resolved_key,
            total_bytes=total_bytes,
            sha256=digest,
            media_type=resolved_media_type,
            kind=resolved_kind,
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
        manifest = self._get_manifest(key)
        if manifest.get("namespace") != self.namespace:
            raise PermissionError("asset does not belong to this namespace")
        total_bytes = int(head.get("ContentLength", -1))
        sha256 = str(manifest.get("sha256") or metadata.get("wavemind-sha256", ""))
        media_type = str(manifest.get("media_type") or "") or str(
            metadata.get("wavemind-media-type") or
            head.get("ContentType") or "application/octet-stream"
        )
        verified = True
        if verify_metadata:
            verified = (
                total_bytes >= 0
                and bool(sha256)
                and metadata.get("wavemind-bytes") == str(total_bytes)
                and bool(media_type)
                and _manifest_matches_object(
                    manifest,
                    key=key,
                    namespace=self.namespace,
                    sha256=sha256,
                    total_bytes=total_bytes,
                    media_type=media_type,
                )
            )
        return _asset_report_from_manifest(
            manifest,
            uri=self._uri(key),
            bucket=self.bucket,
            key=key,
            total_bytes=total_bytes,
            sha256=sha256,
            media_type=media_type,
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

    def get_asset_bytes(
        self,
        uri_or_key: str,
        *,
        expected_sha256: str | None = None,
    ) -> bytes:
        report = self.describe_asset(uri_or_key)
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=report.key,
        )
        body = response["Body"]
        payload = body.read() if hasattr(body, "read") else body
        data = bytes(payload)
        digest = hashlib.sha256(data).hexdigest()
        expected = expected_sha256 or report.sha256
        if digest != expected or len(data) != report.total_bytes:
            raise ValueError("asset content failed checksum or byte-size validation")
        return data

    def download_asset(
        self,
        uri_or_key: str,
        destination: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        report = self.describe_asset(uri_or_key)
        destination = Path(destination)
        if destination.suffix:
            target = destination
        else:
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / Path(report.key).name
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.get_asset_bytes(
            report.uri,
            expected_sha256=expected_sha256,
        )
        target.write_bytes(payload)
        return target

    def list_assets(
        self,
        *,
        include_expired: bool = False,
    ) -> tuple[ObjectStoreAssetReport, ...]:
        reports: list[ObjectStoreAssetReport] = []
        token: str | None = None
        prefix = self._asset_prefix()
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            response = dict(self.client.list_objects_v2(**kwargs))
            for item in response.get("Contents") or []:
                key = str(item.get("Key") or "")
                if not _is_asset_object_key(key):
                    continue
                report = self.describe_asset(key)
                if include_expired or not report.is_expired(at=self._clock()):
                    reports.append(report)
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
            if not token:
                break
        return tuple(sorted(reports, key=lambda report: report.key))

    def delete_asset(
        self,
        uri_or_key: str,
        *,
        expected_sha256: str,
        reason: str,
    ) -> AssetTombstone:
        report = self.describe_asset(uri_or_key)
        if report.sha256 != expected_sha256:
            raise ValueError("asset checksum does not match delete precondition")
        deleted_at = _format_utc_timestamp(self._clock())
        tombstone_key = self._tombstone_key(report.key, report.sha256)
        payload = {
            "schema": ASSET_TOMBSTONE_SCHEMA,
            "asset_uri": report.uri,
            "asset_key": report.key,
            "namespace": self.namespace,
            "sha256": report.sha256,
            "deleted_at": deleted_at,
            "reason": _required_text(reason, name="reason"),
            "status": "pending",
        }
        self._put_json(tombstone_key, payload)
        self.client.delete_object(Bucket=self.bucket, Key=report.key)
        self.client.delete_object(
            Bucket=self.bucket,
            Key=self._manifest_key(report.key),
        )
        payload["status"] = "deleted"
        self._put_json(tombstone_key, payload)
        tombstone = self.read_tombstone(tombstone_key)
        if self._object_exists(report.key):
            raise RuntimeError("asset object still exists after physical deletion")
        return tombstone

    def read_tombstone(self, uri_or_key: str) -> AssetTombstone:
        key = self._tombstone_key_from_uri_or_key(uri_or_key)
        payload = self._get_json(key)
        return _asset_tombstone_from_payload(
            payload,
            uri=self._uri(key),
        )

    def list_tombstones(self) -> tuple[AssetTombstone, ...]:
        prefix = self._tombstone_prefix()
        response = dict(
            self.client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
            )
        )
        tombstones = [
            self.read_tombstone(str(item["Key"]))
            for item in response.get("Contents") or []
            if str(item.get("Key") or "").endswith(".json")
        ]
        return tuple(
            sorted(tombstones, key=lambda item: (item.deleted_at, item.asset_key))
        )

    def _resolve_asset_key(self, *, key: str | None, digest: str, suffix: str) -> str:
        prefix = self._asset_prefix()
        if key:
            relative = _safe_relative_key(key)
            return f"{prefix}custom/{relative}"
        suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
        filename = f"{digest}{suffix}"
        return f"{prefix}{digest[:2]}/{filename}"

    def _build_manifest(
        self,
        *,
        key: str,
        total_bytes: int,
        sha256: str,
        media_type: str,
        kind: str | None,
        metadata: Mapping[str, str] | None,
        owner: str | None,
        source_uri: str | None,
        encoder: str | None,
        model_revision: str | None,
        ttl_seconds: float | None,
        created_at: str | datetime | None,
        expires_at: str | datetime | None,
        derived_from: Sequence[str],
        provenance: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        created, expires = _resolve_lifecycle_timestamps(
            clock=self._clock,
            created_at=created_at,
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
        )
        resolved_owner = _resolve_bound_owner(self.owner, owner)
        return {
            "schema": ASSET_MANIFEST_SCHEMA,
            "key": key,
            "namespace": self.namespace,
            "namespace_token": _namespace_token(self.namespace),
            "owner": resolved_owner,
            "source_uri": _optional_text(source_uri),
            "media_type": media_type,
            "kind": kind,
            "sha256": sha256,
            "total_bytes": total_bytes,
            "encoder": _optional_text(encoder),
            "model_revision": _optional_text(model_revision),
            "created_at": created,
            "expires_at": expires,
            "derived_from": _normalize_derived_from(derived_from),
            "provenance": _normalize_provenance(provenance),
            "metadata": _validate_custom_metadata(metadata),
        }

    def _head_metadata(self, manifest: Mapping[str, object]) -> dict[str, str]:
        metadata = {
            "wavemind-sha256": str(manifest["sha256"]),
            "wavemind-bytes": str(manifest["total_bytes"]),
            "wavemind-media-type": str(manifest["media_type"]),
            "wavemind-namespace": str(manifest["namespace"]),
            "wavemind-namespace-token": str(manifest["namespace_token"]),
            "wavemind-manifest-key": self._manifest_key(str(manifest["key"])),
        }
        if manifest.get("kind"):
            metadata["wavemind-asset-kind"] = str(manifest["kind"])
        if manifest.get("owner"):
            metadata["wavemind-owner"] = str(manifest["owner"])
        return metadata

    def _put_manifest(
        self,
        asset_key: str,
        manifest: Mapping[str, object],
    ) -> None:
        self._put_json(self._manifest_key(asset_key), manifest)

    def _get_manifest(self, asset_key: str) -> dict[str, object]:
        payload = self._get_json(self._manifest_key(asset_key))
        if payload.get("schema") != ASSET_MANIFEST_SCHEMA:
            raise ValueError("asset manifest schema is unsupported")
        return payload

    def _put_json(
        self,
        key: str,
        payload: Mapping[str, object],
    ) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=_canonical_json_bytes(payload),
            ContentType="application/json",
            Metadata={
                "wavemind-schema": str(payload.get("schema") or ""),
                "wavemind-namespace": self.namespace,
            },
        )

    def _get_json(self, key: str) -> dict[str, object]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        data = body.read() if hasattr(body, "read") else body
        payload = json.loads(bytes(data))
        if not isinstance(payload, dict):
            raise ValueError("asset lifecycle document must be a JSON object")
        if payload.get("namespace") != self.namespace:
            raise PermissionError(
                "asset lifecycle document does not belong to this namespace"
            )
        return payload

    def _asset_prefix(self) -> str:
        base = f"{self.prefix.rstrip('/')}/" if self.prefix else ""
        return f"{base}namespaces/{_namespace_token(self.namespace)}/objects/"

    def _tombstone_prefix(self) -> str:
        base = f"{self.prefix.rstrip('/')}/" if self.prefix else ""
        return f"{base}namespaces/{_namespace_token(self.namespace)}/tombstones/"

    def _manifest_key(self, asset_key: str) -> str:
        return f"{asset_key}.wavemind.json"

    def _tombstone_key(self, asset_key: str, sha256: str) -> str:
        identity = hashlib.sha256(asset_key.encode("utf-8")).hexdigest()[:24]
        return f"{self._tombstone_prefix()}{sha256}-{identity}.json"

    def _tombstone_key_from_uri_or_key(self, uri_or_key: str) -> str:
        if uri_or_key.startswith("s3://"):
            location = parse_object_store_uri(uri_or_key)
            if location.bucket != self.bucket:
                raise ValueError(
                    f"object bucket mismatch: expected {self.bucket!r}, "
                    f"got {location.bucket!r}"
                )
            key = location.key
        else:
            key = uri_or_key.strip("/")
        if not key.startswith(self._tombstone_prefix()):
            raise PermissionError("tombstone does not belong to this namespace")
        return key

    def _object_exists(self, key: str) -> bool:
        try:
            self._head(key)
        except Exception as exc:
            if _is_object_not_found(exc):
                return False
            raise
        return True

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
        if verify:
            report = self.describe_asset(key)
            if (
                report.total_bytes != int(total_bytes)
                or report.sha256 != sha256
                or report.media_type != media_type
                or report.kind != kind
            ):
                raise ValueError(
                    "stored asset differs from the requested asset manifest"
                )
            return report
        manifest = self._get_manifest(key)
        return _asset_report_from_manifest(
            manifest,
            uri=self._uri(key),
            bucket=self.bucket,
            key=key,
            total_bytes=total_bytes,
            sha256=sha256,
            media_type=media_type,
            verified=False,
            etag=None,
        )

    def _key_from_uri_or_key(self, uri_or_key: str) -> str:
        if uri_or_key.startswith("s3://"):
            location = parse_object_store_uri(uri_or_key)
            if location.bucket != self.bucket:
                raise ValueError(
                    f"object bucket mismatch: expected {self.bucket!r}, got {location.bucket!r}"
                )
            key = location.key
        else:
            key = uri_or_key.strip("/")
        if not key.startswith(self._asset_prefix()):
            raise PermissionError("asset does not belong to this namespace")
        if not _is_asset_object_key(key):
            raise ValueError("asset key points to lifecycle metadata, not an asset")
        return key

    def _head(self, key: str) -> dict[str, Any]:
        return dict(self.client.head_object(Bucket=self.bucket, Key=key))

    def _uri(self, key: str) -> str:
        return f"{self.scheme}://{self.bucket}/{key}"


class FilesystemAssetStore(S3AssetStore):
    """Namespace-bound local filesystem asset lifecycle.

    Files and lifecycle documents use the same manifest contract as the
    S3-compatible backend. The root is resolved once, and every key is checked
    to remain beneath it before any read, write, list, or delete operation.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        prefix: str = "assets",
        namespace: str = "default",
        owner: str | None = None,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
        allowed_media_types: Iterable[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        super().__init__(
            bucket="filesystem",
            prefix=prefix,
            client=_FilesystemObjectClient(self.root),
            scheme="file",
            namespace=namespace,
            owner=owner,
            max_asset_bytes=max_asset_bytes,
            allowed_media_types=allowed_media_types,
            clock=clock,
        )

    def _uri(self, key: str) -> str:
        return self._filesystem_path(key).as_uri()

    def _key_from_uri_or_key(self, uri_or_key: str) -> str:
        key = self._filesystem_key(uri_or_key)
        if not key.startswith(self._asset_prefix()):
            raise PermissionError("asset does not belong to this namespace")
        if not _is_asset_object_key(key):
            raise ValueError("asset key points to lifecycle metadata, not an asset")
        return key

    def _tombstone_key_from_uri_or_key(self, uri_or_key: str) -> str:
        key = self._filesystem_key(uri_or_key)
        if not key.startswith(self._tombstone_prefix()):
            raise PermissionError("tombstone does not belong to this namespace")
        return key

    def _filesystem_key(self, uri_or_key: str) -> str:
        if uri_or_key.startswith("file:"):
            parsed = urlparse(uri_or_key)
            raw_path = unquote(parsed.path)
            if os.name == "nt" and len(raw_path) >= 3:
                if raw_path[0] == "/" and raw_path[2] == ":":
                    raw_path = raw_path[1:]
            candidate = Path(raw_path)
            if parsed.netloc:
                candidate = Path(f"//{parsed.netloc}{raw_path}")
            candidate = candidate.resolve()
            try:
                return candidate.relative_to(self.root).as_posix()
            except ValueError as exc:
                raise PermissionError(
                    "file URI is outside the asset-store root"
                ) from exc
        return _safe_relative_key(uri_or_key)

    def _filesystem_path(self, key: str) -> Path:
        candidate = (self.root / Path(*key.split("/"))).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("asset path escaped the store root") from exc
        return candidate


class _FilesystemObjectClient:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.metadata_root = self.root / ".wavemind-object-metadata"
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: Mapping[str, object] | None = None,
    ) -> None:
        del bucket
        extra = dict(ExtraArgs or {})
        self._write_object(
            key,
            Path(filename).read_bytes(),
            content_type=str(
                extra.get("ContentType") or "application/octet-stream"
            ),
            metadata=dict(extra.get("Metadata") or {}),
        )

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: Any,
        ContentType: str | None = None,
        Metadata: Mapping[str, str] | None = None,
    ) -> None:
        del Bucket
        payload = Body.read() if hasattr(Body, "read") else Body
        self._write_object(
            Key,
            bytes(payload),
            content_type=ContentType or "application/octet-stream",
            metadata=dict(Metadata or {}),
        )

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        from io import BytesIO

        return {"Body": BytesIO(self._path(Key).read_bytes())}

    def download_file(
        self,
        bucket: str,
        key: str,
        filename: str,
    ) -> None:
        del bucket
        target = Path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), target)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        path = self._path(Key)
        payload = path.read_bytes()
        metadata = self._read_metadata(Key)
        return {
            "ContentLength": len(payload),
            "Metadata": dict(metadata.get("metadata") or {}),
            "ContentType": metadata.get("content_type"),
            "ETag": f'"{hashlib.sha256(payload).hexdigest()}"',
            "LastModified": datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ),
        }

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str = "",
        ContinuationToken: str | None = None,
    ) -> dict[str, object]:
        del Bucket, ContinuationToken
        contents: list[dict[str, object]] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or self.metadata_root in path.parents:
                continue
            key = path.relative_to(self.root).as_posix()
            if not key.startswith(Prefix):
                continue
            payload = path.read_bytes()
            contents.append(
                {
                    "Key": key,
                    "Size": len(payload),
                    "LastModified": datetime.fromtimestamp(
                        path.stat().st_mtime,
                        tz=timezone.utc,
                    ),
                    "ETag": f'"{hashlib.sha256(payload).hexdigest()}"',
                }
            )
        return {
            "Contents": sorted(contents, key=lambda item: str(item["Key"])),
            "IsTruncated": False,
        }

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        path = self._path(Key)
        path.unlink(missing_ok=True)
        self._metadata_path(Key).unlink(missing_ok=True)
        _remove_empty_parents(path.parent, stop=self.root)
        return {}

    def _write_object(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        meta_path = self._metadata_path(key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_bytes(
            _canonical_json_bytes(
                {
                    "key": key,
                    "content_type": content_type,
                    "metadata": dict(metadata),
                }
            )
        )

    def _read_metadata(self, key: str) -> dict[str, object]:
        payload = json.loads(self._metadata_path(key).read_bytes())
        if not isinstance(payload, dict) or payload.get("key") != key:
            raise ValueError("filesystem object metadata is invalid")
        return payload

    def _metadata_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.metadata_root / digest[:2] / f"{digest}.json"

    def _path(self, key: str) -> Path:
        relative = _safe_relative_key(key)
        candidate = (self.root / Path(*relative.split("/"))).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("filesystem object key escaped root") from exc
        return candidate


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


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_relative_key(value: str) -> str:
    key = str(value).replace("\\", "/").strip("/")
    if not key:
        raise ValueError("asset key must not be empty")
    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("asset key must be a safe relative path")
    if any("\x00" in part for part in parts):
        raise ValueError("asset key must not contain NUL bytes")
    return "/".join(parts)


def _safe_backup_member(value: str) -> bool:
    try:
        key = _safe_relative_key(value)
    except ValueError:
        return False
    return key.startswith("objects/")


def _validate_namespace(namespace: str) -> str:
    value = _required_text(namespace, name="namespace")
    if len(value.encode("utf-8")) > 512:
        raise ValueError("namespace must be at most 512 UTF-8 bytes")
    if "\x00" in value:
        raise ValueError("namespace must not contain NUL bytes")
    return value


def _namespace_token(namespace: str) -> str:
    return hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:32]


def _validate_max_asset_bytes(value: int) -> int:
    resolved = int(value)
    if resolved <= 0:
        raise ValueError("max_asset_bytes must be positive")
    return resolved


def _normalize_allowed_media_types(
    values: Iterable[str] | None,
) -> frozenset[str] | None:
    if values is None:
        return None
    resolved = frozenset(
        _required_text(value, name="allowed media type").lower()
        for value in values
    )
    if not resolved:
        raise ValueError("allowed_media_types must not be empty")
    return resolved


def _validate_asset_payload(
    *,
    total_bytes: int,
    media_type: str,
    kind: str | None,
    max_asset_bytes: int,
    allowed_media_types: frozenset[str] | None,
) -> str | None:
    if total_bytes <= 0:
        raise ValueError("asset payload must not be empty")
    if total_bytes > max_asset_bytes:
        raise ValueError(
            f"asset payload exceeds max_asset_bytes={max_asset_bytes}"
        )
    resolved_media_type = _required_text(
        media_type,
        name="media_type",
    ).lower()
    if "/" not in resolved_media_type:
        raise ValueError("media_type must be a valid MIME type")
    if allowed_media_types is not None and not _media_type_allowed(
        resolved_media_type,
        allowed_media_types,
    ):
        raise ValueError(
            f"media_type {resolved_media_type!r} is not allowed by this store"
        )
    resolved_kind = _optional_text(kind)
    if resolved_kind is not None:
        resolved_kind = normalize_asset_kind(resolved_kind)
        if not _media_type_matches_kind(resolved_media_type, resolved_kind):
            raise ValueError(
                f"media_type {resolved_media_type!r} is incompatible "
                f"with asset kind {resolved_kind!r}"
            )
    return resolved_kind


def normalize_asset_kind(kind: str) -> str:
    value = _required_text(kind, name="kind").lower()
    aliases = {
        "model": "3d",
        "model3d": "3d",
        "mesh": "3d",
        "structured": "table",
        "temporal": "event",
        "knowledge-graph": "graph",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_ASSET_KINDS:
        raise ValueError(
            f"unsupported asset kind {kind!r}; expected one of "
            f"{sorted(SUPPORTED_ASSET_KINDS)}"
        )
    return value


def _media_type_allowed(
    media_type: str,
    allowed: frozenset[str],
) -> bool:
    return any(
        item == media_type
        or (item.endswith("/*") and media_type.startswith(item[:-1]))
        for item in allowed
    )


def _media_type_matches_kind(media_type: str, kind: str) -> bool:
    if kind in {"text", "image", "audio", "video"}:
        return media_type.startswith(f"{kind}/")
    if kind == "3d":
        return media_type.startswith("model/") or media_type in {
            "application/sla",
            "application/vnd.ms-pki.stl",
            "application/x-3ds",
        }
    if kind == "table":
        return (
            media_type.startswith("text/")
            or media_type
            in {
                "application/json",
                "application/vnd.apache.parquet",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
    if kind in {"event", "graph"}:
        return media_type == "application/json" or media_type.startswith("text/")
    return False


def _required_text(value: object, *, name: str) -> str:
    resolved = str(value).strip()
    if not resolved:
        raise ValueError(f"{name} is required")
    return resolved


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _resolve_bound_owner(
    bound_owner: str | None,
    requested_owner: str | None,
) -> str | None:
    requested = _optional_text(requested_owner)
    if bound_owner is not None and requested not in {None, bound_owner}:
        raise PermissionError("asset owner differs from the store owner")
    return bound_owner or requested


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc_datetime(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _parse_utc_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return _coerce_utc_datetime(value)
    text = _required_text(value, name="timestamp").replace("Z", "+00:00")
    return _coerce_utc_datetime(datetime.fromisoformat(text))


def _format_utc_timestamp(value: datetime) -> str:
    return (
        _coerce_utc_datetime(value)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _resolve_lifecycle_timestamps(
    *,
    clock: Callable[[], datetime],
    created_at: str | datetime | None,
    expires_at: str | datetime | None,
    ttl_seconds: float | None,
) -> tuple[str, str | None]:
    if ttl_seconds is not None and expires_at is not None:
        raise ValueError("provide ttl_seconds or expires_at, not both")
    created = (
        _parse_utc_timestamp(created_at)
        if created_at is not None
        else _coerce_utc_datetime(clock())
    )
    expires: datetime | None = None
    if ttl_seconds is not None:
        ttl = float(ttl_seconds)
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        expires = created + timedelta(seconds=ttl)
    elif expires_at is not None:
        expires = _parse_utc_timestamp(expires_at)
    if expires is not None and expires <= created:
        raise ValueError("asset expiration must be later than creation")
    return (
        _format_utc_timestamp(created),
        _format_utc_timestamp(expires) if expires is not None else None,
    )


def _normalize_derived_from(values: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _required_text(value, name="derived_from value")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_provenance(
    values: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if len(values) > 4096:
        raise ValueError("provenance chain is limited to 4096 entries")
    normalized: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("each provenance entry must be a mapping")
        row = {str(key): item for key, item in value.items()}
        try:
            json.dumps(row, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("provenance entries must be JSON serializable") from exc
        normalized.append(row)
    return normalized


def _validate_custom_metadata(
    metadata: Mapping[str, str] | None,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in dict(metadata or {}).items():
        normalized_key = _required_text(key, name="metadata key").lower()
        if normalized_key.startswith("wavemind-"):
            raise ValueError("custom metadata must not use reserved wavemind-* keys")
        resolved[normalized_key] = str(value)
    encoded = _canonical_json_bytes(resolved)
    if len(encoded) > 64 * 1024:
        raise ValueError("custom metadata is limited to 64 KiB")
    return resolved


def _manifest_matches_object(
    manifest: Mapping[str, object],
    *,
    key: str,
    namespace: str,
    sha256: str,
    total_bytes: int,
    media_type: str,
) -> bool:
    return (
        manifest.get("schema") == ASSET_MANIFEST_SCHEMA
        and manifest.get("key") == key
        and manifest.get("namespace") == namespace
        and manifest.get("namespace_token") == _namespace_token(namespace)
        and manifest.get("sha256") == sha256
        and int(manifest.get("total_bytes", -1)) == int(total_bytes)
        and manifest.get("media_type") == media_type
    )


def _asset_report_from_manifest(
    manifest: Mapping[str, object],
    *,
    uri: str,
    bucket: str,
    key: str,
    total_bytes: int,
    sha256: str,
    media_type: str,
    verified: bool,
    etag: str | None,
) -> ObjectStoreAssetReport:
    provenance = tuple(
        dict(item)
        for item in manifest.get("provenance") or ()
        if isinstance(item, Mapping)
    )
    return ObjectStoreAssetReport(
        uri=uri,
        bucket=bucket,
        key=key,
        total_bytes=total_bytes,
        sha256=sha256,
        media_type=media_type,
        kind=_optional_text(manifest.get("kind")),
        verified=verified,
        etag=etag,
        namespace=str(manifest.get("namespace") or "default"),
        owner=_optional_text(manifest.get("owner")),
        source_uri=_optional_text(manifest.get("source_uri")),
        encoder=_optional_text(manifest.get("encoder")),
        model_revision=_optional_text(manifest.get("model_revision")),
        created_at=_optional_text(manifest.get("created_at")),
        expires_at=_optional_text(manifest.get("expires_at")),
        derived_from=tuple(
            str(item) for item in manifest.get("derived_from") or ()
        ),
        provenance=provenance,
    )


def _asset_tombstone_from_payload(
    payload: Mapping[str, object],
    *,
    uri: str,
) -> AssetTombstone:
    verified = (
        payload.get("schema") == ASSET_TOMBSTONE_SCHEMA
        and payload.get("status") == "deleted"
        and bool(payload.get("asset_uri"))
        and bool(payload.get("asset_key"))
        and bool(payload.get("namespace"))
        and bool(payload.get("sha256"))
        and bool(payload.get("deleted_at"))
        and bool(payload.get("reason"))
    )
    return AssetTombstone(
        uri=uri,
        asset_uri=str(payload.get("asset_uri") or ""),
        namespace=str(payload.get("namespace") or ""),
        asset_key=str(payload.get("asset_key") or ""),
        sha256=str(payload.get("sha256") or ""),
        deleted_at=str(payload.get("deleted_at") or ""),
        reason=str(payload.get("reason") or ""),
        status=str(payload.get("status") or ""),
        verified=verified,
    )


def _is_asset_object_key(key: str) -> bool:
    return not key.endswith(".wavemind.json")


def _remove_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _is_object_not_found(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return True
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return False
    error = response.get("Error")
    metadata = response.get("ResponseMetadata")
    code = str(error.get("Code") or "") if isinstance(error, Mapping) else ""
    status = (
        int(metadata.get("HTTPStatusCode", 0))
        if isinstance(metadata, Mapping)
        else 0
    )
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
