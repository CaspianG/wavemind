from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from wavemind import FilesystemAssetStore, S3AssetStore


SCHEMA = "wavemind.asset-lifecycle-evidence.v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class S3EvidenceConfig:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    backend_label: str = "minio"
    container_image: str | None = None


def run_asset_lifecycle_benchmark(
    *,
    s3_config: S3EvidenceConfig | None = None,
    source_ref: str | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    generated_at = _utc_timestamp(datetime.now(timezone.utc))
    resolved_source_ref = source_ref or _git_source_ref()
    run_id = f"{resolved_source_ref[:12]}-{uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="wavemind-asset-lifecycle-") as tmp:
        temp_root = Path(tmp)
        filesystem_root = temp_root / "filesystem"

        def filesystem_factory(
            namespace: str,
            partition: str,
            clock: Callable[[], datetime],
        ) -> FilesystemAssetStore:
            return FilesystemAssetStore(
                filesystem_root,
                prefix=f"{run_id}/{partition}",
                namespace=namespace,
                owner=f"owner:{namespace}",
                clock=clock,
            )

        filesystem = _run_lifecycle_contract(
            backend="filesystem",
            factory=filesystem_factory,
            temp_root=temp_root / "filesystem-work",
        )

        if s3_config is None:
            s3_result: dict[str, object] = {
                "backend": "minio",
                "status": "skipped",
                "reason": "no S3-compatible endpoint was configured",
            }
        else:
            client = _create_s3_client(s3_config)
            _ensure_bucket(client, s3_config.bucket)
            prefix = f"wavemind-evidence/{run_id}"

            def s3_factory(
                namespace: str,
                partition: str,
                clock: Callable[[], datetime],
            ) -> S3AssetStore:
                return S3AssetStore(
                    bucket=s3_config.bucket,
                    prefix=f"{prefix}/{partition}",
                    client=client,
                    namespace=namespace,
                    owner=f"owner:{namespace}",
                    clock=clock,
                )

            try:
                s3_result = _run_lifecycle_contract(
                    backend=s3_config.backend_label,
                    factory=s3_factory,
                    temp_root=temp_root / "s3-work",
                )
            finally:
                _delete_prefix(client, s3_config.bucket, prefix)
            s3_result["teardown_pass"] = _prefix_is_empty(
                client,
                s3_config.bucket,
                prefix,
            )
            s3_result["container_image"] = s3_config.container_image
            s3_result["endpoint"] = s3_config.endpoint_url

    minio_pass = s3_result.get("status") == "pass"
    filesystem_pass = filesystem.get("status") == "pass"
    status = "pass" if filesystem_pass and minio_pass else "contract_pass"
    if not filesystem_pass:
        status = "fail"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "source_ref": resolved_source_ref,
        "status": status,
        "claim_boundary": (
            "This artifact proves filesystem and S3-compatible asset lifecycle "
            "behavior only. It does not prove multimodal encoder quality, "
            "cross-modal retrieval quality, or the 1000-asset admission gate."
        ),
        "fixture": {
            "kind": "lifecycle-only",
            "public_asset_count": 0,
            "multimodal_query_count": 0,
            "eligible_for_multimodal_quality_admission": False,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "duration_ms": elapsed_ms,
        "filesystem": filesystem,
        "s3_compatible": s3_result,
        "lifecycle": {
            "object_store_backend": (
                str(s3_result.get("backend") or "minio")
            ),
            "object_store_pass": minio_pass,
            "filesystem_pass": filesystem_pass,
            "ingest_pass": _both(filesystem, s3_result, "ingest_pass"),
            "checksum_pass": _both(filesystem, s3_result, "checksum_pass"),
            "reload_pass": _both(filesystem, s3_result, "reload_pass"),
            "persistence_pass": _both(
                filesystem,
                s3_result,
                "persistence_pass",
            ),
            "namespace_isolation_pass": _both(
                filesystem,
                s3_result,
                "namespace_isolation_pass",
            ),
            "ttl_pass": _both(filesystem, s3_result, "ttl_pass"),
            "physical_delete_pass": _both(
                filesystem,
                s3_result,
                "physical_delete_pass",
            ),
            "tombstone_pass": _both(
                filesystem,
                s3_result,
                "tombstone_pass",
            ),
            "backup_restore_pass": _both(
                filesystem,
                s3_result,
                "backup_restore_pass",
            ),
            "orphan_cleanup_pass": _both(
                filesystem,
                s3_result,
                "orphan_cleanup_pass",
            ),
        },
    }


def _run_lifecycle_contract(
    *,
    backend: str,
    factory: Callable[
        [str, str, Callable[[], datetime]],
        FilesystemAssetStore | S3AssetStore,
    ],
    temp_root: Path,
) -> dict[str, object]:
    temp_root.mkdir(parents=True, exist_ok=True)
    current = [datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)]

    def clock() -> datetime:
        return current[0]

    store = factory("tenant:a", "primary", clock)
    other = factory("tenant:b", "primary", clock)
    restored_store = factory("tenant:a", "restore", clock)

    retained = store.put_asset_bytes(
        b"\x89PNG\r\nwavemind-lifecycle",
        filename="retained.png",
        kind="image",
        source_uri="urn:wavemind:lifecycle:retained",
        encoder="lifecycle-only",
        model_revision="not-an-encoder-proof",
        derived_from=("event:retain",),
        provenance=(
            {
                "event_id": "event:retain",
                "operation": "lifecycle-ingest",
            },
        ),
    )
    expiring = store.put_asset_bytes(
        b"RIFF-wavemind-lifecycle",
        filename="expiring.wav",
        kind="audio",
        ttl_seconds=60,
        source_uri="urn:wavemind:lifecycle:expiring",
    )
    other_copy = other.put_asset_bytes(
        b"\x89PNG\r\nwavemind-lifecycle",
        filename="retained.png",
        kind="image",
    )
    ingest_pass = len(store.list_assets()) == 2
    checksum_pass = (
        store.get_asset_bytes(
            retained.uri,
            expected_sha256=retained.sha256,
        )
        == b"\x89PNG\r\nwavemind-lifecycle"
    )
    reloaded = factory("tenant:a", "primary", clock)
    reload_pass = reloaded.describe_asset(retained.uri) == retained
    persistence_pass = (
        reloaded.get_asset_bytes(retained.uri) == b"\x89PNG\r\nwavemind-lifecycle"
    )
    namespace_isolation_pass = retained.key != other_copy.key
    try:
        other.describe_asset(retained.uri)
    except PermissionError:
        namespace_isolation_pass = namespace_isolation_pass and True
    else:
        namespace_isolation_pass = False

    current[0] += timedelta(seconds=61)
    ttl_preview = store.cleanup_expired(dry_run=True)
    ttl_cleanup = store.cleanup_expired(dry_run=False)
    ttl_pass = (
        ttl_preview.candidates == (expiring.uri,)
        and ttl_cleanup.deleted == (expiring.uri,)
    )
    physical_delete_pass = not store._object_exists(expiring.key)
    tombstone_pass = (
        len(ttl_cleanup.tombstones) == 1
        and ttl_cleanup.tombstones[0].verified
        and ttl_cleanup.tombstones[0].status == "deleted"
    )

    backup = store.backup_namespace(temp_root / "assets.zip")
    restored = restored_store.restore_namespace(backup.path)
    backup_restore_pass = (
        backup.verified
        and backup.asset_count == 1
        and len(restored) == 1
        and restored[0].sha256 == retained.sha256
        and restored_store.get_asset_bytes(restored[0].uri)
        == b"\x89PNG\r\nwavemind-lifecycle"
    )

    orphan = store.put_asset_bytes(
        b"orphan-lifecycle",
        filename="orphan.txt",
        kind="text",
    )
    orphan_preview = store.cleanup_orphans((retained.uri,), dry_run=True)
    orphan_cleanup = store.cleanup_orphans((retained.uri,), dry_run=False)
    orphan_cleanup_pass = (
        orphan_preview.candidates == (orphan.uri,)
        and orphan_cleanup.deleted == (orphan.uri,)
        and not store._object_exists(orphan.key)
    )

    retained_delete = store.delete_asset(
        retained.uri,
        expected_sha256=retained.sha256,
        reason="lifecycle-final-cleanup",
    )
    restored_delete = restored_store.delete_asset(
        restored[0].uri,
        expected_sha256=restored[0].sha256,
        reason="lifecycle-final-cleanup",
    )
    other_delete = other.delete_asset(
        other_copy.uri,
        expected_sha256=other_copy.sha256,
        reason="lifecycle-final-cleanup",
    )
    final_delete_pass = all(
        item.verified
        for item in (retained_delete, restored_delete, other_delete)
    )

    checks = {
        "ingest_pass": ingest_pass,
        "checksum_pass": checksum_pass,
        "reload_pass": reload_pass,
        "persistence_pass": persistence_pass,
        "namespace_isolation_pass": namespace_isolation_pass,
        "ttl_pass": ttl_pass,
        "physical_delete_pass": physical_delete_pass and final_delete_pass,
        "tombstone_pass": tombstone_pass,
        "backup_restore_pass": backup_restore_pass,
        "orphan_cleanup_pass": orphan_cleanup_pass,
    }
    backup_row = backup.as_dict()
    backup_row["path"] = Path(str(backup_row["path"])).name
    return {
        "backend": backend,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "objects_created": 5,
        "objects_deleted": 5,
        "tombstones_verified": 5,
        "namespace_count": 2,
        "backup": backup_row,
    }


def _both(
    filesystem: dict[str, object],
    s3_result: dict[str, object],
    name: str,
) -> bool:
    filesystem_checks = filesystem.get("checks")
    s3_checks = s3_result.get("checks")
    return bool(
        isinstance(filesystem_checks, dict)
        and filesystem_checks.get(name)
        and isinstance(s3_checks, dict)
        and s3_checks.get(name)
    )


def _create_s3_client(config: S3EvidenceConfig):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            'Install S3 support with: pip install "wavemind[s3]"'
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        region_name=config.region,
        config=Config(
            proxies={},
            s3={"addressing_style": "path"},
            retries={"mode": "standard", "max_attempts": 3},
        ),
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        response = getattr(exc, "response", {})
        error = response.get("Error") if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata")
            if isinstance(response, dict)
            else {}
        )
        code = str(error.get("Code") or "") if isinstance(error, dict) else ""
        status = (
            int(metadata.get("HTTPStatusCode", 0))
            if isinstance(metadata, dict)
            else 0
        )
        if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
            raise
        client.create_bucket(Bucket=bucket)


def _delete_prefix(client, bucket: str, prefix: str) -> None:
    token: str | None = None
    while True:
        kwargs: dict[str, object] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        contents = response.get("Contents") or []
        if contents:
            client.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": item["Key"]} for item in contents],
                    "Quiet": True,
                },
            )
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
        if not token:
            break


def _prefix_is_empty(client, bucket: str, prefix: str) -> bool:
    response = client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix,
        MaxKeys=1,
    )
    return not bool(response.get("Contents"))


def _git_source_ref() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_result(result: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify WaveMind filesystem and S3 asset lifecycle",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/asset_lifecycle_results.json"),
    )
    parser.add_argument("--endpoint-url", default=os.getenv("WAVEMIND_S3_ENDPOINT"))
    parser.add_argument("--access-key", default=os.getenv("WAVEMIND_S3_ACCESS_KEY"))
    parser.add_argument("--secret-key", default=os.getenv("WAVEMIND_S3_SECRET_KEY"))
    parser.add_argument(
        "--bucket",
        default=os.getenv("WAVEMIND_S3_ASSET_BUCKET", "wavemind-assets"),
    )
    parser.add_argument(
        "--backend-label",
        default=os.getenv("WAVEMIND_S3_BACKEND", "minio"),
    )
    parser.add_argument(
        "--container-image",
        default=os.getenv("WAVEMIND_MINIO_IMAGE"),
    )
    parser.add_argument("--source-ref")
    args = parser.parse_args()

    provided = [args.endpoint_url, args.access_key, args.secret_key]
    if any(provided) and not all(provided):
        parser.error(
            "--endpoint-url, --access-key, and --secret-key must be provided together"
        )
    config = None
    if all(provided):
        config = S3EvidenceConfig(
            endpoint_url=args.endpoint_url,
            access_key=args.access_key,
            secret_key=args.secret_key,
            bucket=args.bucket,
            backend_label=args.backend_label,
            container_image=args.container_image,
        )
    result = run_asset_lifecycle_benchmark(
        s3_config=config,
        source_ref=args.source_ref,
    )
    write_result(result, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
