from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import WaveMind
from .experience import SQLiteExperienceStore


BACKUP_SCHEMA = "wavemind.product_backup.v1"
CORE_NAME = "core.sqlite3"
EXPERIENCE_NAME = "experience.sqlite3"
MANIFEST_NAME = "manifest.json"


class ProductBackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_ok(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")
    finally:
        connection.close()


def create_product_backup(
    mind: WaveMind,
    experience_store: SQLiteExperienceStore,
    destination: str | Path,
) -> Path:
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wavemind-product-backup-", dir=target.parent) as raw:
        staging = Path(raw)
        core_path = Path(mind.save(staging / CORE_NAME))
        experience_path = experience_store.backup(staging / EXPERIENCE_NAME)
        files = []
        for path in (core_path, experience_path):
            if not _database_ok(path):
                raise ProductBackupError(f"backup database failed integrity check: {path.name}")
            files.append(
                {
                    "path": path.name,
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        manifest: dict[str, Any] = {
            "schema": BACKUP_SCHEMA,
            "created_at": time.time(),
            "files": files,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in (MANIFEST_NAME, CORE_NAME, EXPERIENCE_NAME):
                    archive.write(staging / name, arcname=name)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def create_rotating_product_backup(
    mind: WaveMind,
    experience_store: SQLiteExperienceStore,
    destination: str | Path,
    *,
    prefix: str = "wavemind",
    keep_last: int | None = None,
) -> Path:
    selected = Path(destination)
    if selected.suffix.lower() == ".zip":
        return create_product_backup(mind, experience_store, selected)
    selected.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = selected / f"{prefix}-{timestamp}.wavemind.zip"
    created = create_product_backup(mind, experience_store, target)
    if keep_last is not None:
        backups = sorted(
            selected.glob(f"{prefix}-*.wavemind.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[max(0, int(keep_last)) :]:
            stale.unlink(missing_ok=True)
    return created


def _read_verified_archive(source: Path, staging: Path) -> dict[str, Path]:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = set(archive.namelist())
            expected = {MANIFEST_NAME, CORE_NAME, EXPERIENCE_NAME}
            if names != expected:
                raise ProductBackupError("product backup contains unexpected or missing files")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            if manifest.get("schema") != BACKUP_SCHEMA:
                raise ProductBackupError("unsupported product backup schema")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise ProductBackupError("product backup manifest is missing files")
            indexed = {
                str(entry.get("path")): entry
                for entry in entries
                if isinstance(entry, dict)
            }
            if set(indexed) != {CORE_NAME, EXPERIENCE_NAME}:
                raise ProductBackupError("product backup manifest file set is invalid")
            paths: dict[str, Path] = {}
            for name in (CORE_NAME, EXPERIENCE_NAME):
                payload = archive.read(name)
                path = staging / name
                path.write_bytes(payload)
                entry = indexed[name]
                if len(payload) != int(entry.get("size_bytes", -1)):
                    raise ProductBackupError(f"product backup size mismatch: {name}")
                if _sha256(path) != entry.get("sha256"):
                    raise ProductBackupError(f"product backup digest mismatch: {name}")
                if not _database_ok(path):
                    raise ProductBackupError(f"product backup database is corrupt: {name}")
                paths[name] = path
            return paths
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ProductBackupError("invalid product backup archive") from exc


def restore_product_backup(
    source: str | Path,
    *,
    core_destination: str | Path,
    experience_destination: str | Path,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    archive = Path(source).resolve()
    core_target = Path(core_destination).resolve()
    experience_target = Path(experience_destination).resolve()
    if core_target == experience_target:
        raise ProductBackupError("core and experience destinations must differ")
    for target in (core_target, experience_target):
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)

    common_parent = Path(os.path.commonpath([core_target.parent, experience_target.parent]))
    with tempfile.TemporaryDirectory(prefix="wavemind-product-restore-", dir=common_parent) as raw:
        staging = Path(raw)
        verified = _read_verified_archive(archive, staging)
        staged_core = core_target.with_name(f".{core_target.name}.{os.getpid()}.restore")
        staged_experience = experience_target.with_name(
            f".{experience_target.name}.{os.getpid()}.restore"
        )
        rollback_core = staging / "rollback-core.sqlite3"
        rollback_experience = staging / "rollback-experience.sqlite3"
        core_existed = core_target.exists()
        experience_existed = experience_target.exists()
        if core_existed:
            shutil.copy2(core_target, rollback_core)
        if experience_existed:
            shutil.copy2(experience_target, rollback_experience)
        shutil.copy2(verified[CORE_NAME], staged_core)
        shutil.copy2(verified[EXPERIENCE_NAME], staged_experience)
        try:
            os.replace(staged_core, core_target)
            os.replace(staged_experience, experience_target)
        except OSError:
            if core_existed:
                os.replace(rollback_core, core_target)
            else:
                core_target.unlink(missing_ok=True)
            if experience_existed:
                os.replace(rollback_experience, experience_target)
            else:
                experience_target.unlink(missing_ok=True)
            raise
        finally:
            staged_core.unlink(missing_ok=True)
            staged_experience.unlink(missing_ok=True)
    return core_target, experience_target
