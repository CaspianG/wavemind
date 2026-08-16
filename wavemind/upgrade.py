from __future__ import annotations

import contextlib
import email.parser
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from packaging.version import InvalidVersion, Version

from . import __version__
from .schema_migrations import (
    CORE_COMPONENT,
    EXPERIENCE_COMPONENT,
    ensure_schema_migration,
    read_schema_version,
)


UPGRADE_JOURNAL_SCHEMA = "wavemind.upgrade_journal.v1"
UPGRADE_BACKUP_SCHEMA = "wavemind.upgrade_backup.v1"
UPGRADE_RELEASE_SCHEMA = "wavemind.upgrade_release.v1"
TERMINAL_STATUSES = frozenset({"complete", "rolled_back", "recovered"})
DEFAULT_PYPI_URL = "https://pypi.org/pypi/wavemind"
DEFAULT_IMAGE = "ghcr.io/caspiang/wavemind"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 600


class UpgradeError(RuntimeError):
    pass


class UpgradeBlocked(UpgradeError):
    pass


class UpgradeArtifactError(UpgradeError):
    pass


class UpgradeRollbackError(UpgradeError):
    pass


@dataclass(frozen=True)
class ReleaseArtifact:
    version: str
    path: Path
    sha256: str
    source_url: str
    filename: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": UPGRADE_RELEASE_SCHEMA,
            "version": self.version,
            "path": str(self.path),
            "sha256": self.sha256,
            "source_url": self.source_url,
            "filename": self.filename,
        }


@dataclass(frozen=True)
class UpgradeOptions:
    core_db: Path
    experience_db: Path
    target: str = "latest"
    mode: str = "python"
    backup_dir: Path = Path(".wavemind/backups")
    state_dir: Path = Path(".wavemind/upgrade")
    config_paths: tuple[Path, ...] = ()
    object_manifest_paths: tuple[Path, ...] = ()
    target_artifact: Path | None = None
    current_artifact: Path | None = None
    expected_sha256: str | None = None
    current_expected_sha256: str | None = None
    allow_downgrade: bool = False
    dry_run: bool = False
    compose_file: Path | None = None
    compose_env_file: Path | None = None
    compose_service: str = "wavemind"
    image_repository: str = DEFAULT_IMAGE
    target_image: str | None = None
    expected_image_digest: str | None = None
    minimum_free_bytes: int | None = None
    health_command: tuple[str, ...] = ()
    failure_phase: str | None = None


@dataclass
class UpgradeJournal:
    path: Path
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        source_version: str,
        target_version: str,
        mode: str,
        options: UpgradeOptions,
    ) -> "UpgradeJournal":
        now = time.time()
        payload: dict[str, Any] = {
            "schema": UPGRADE_JOURNAL_SCHEMA,
            "operation_id": uuid.uuid4().hex,
            "status": "started",
            "phase": "started",
            "source_version": source_version,
            "target_version": target_version,
            "mode": mode,
            "started_at": now,
            "updated_at": now,
            "paths": {
                "core_db": str(options.core_db.resolve()),
                "experience_db": str(options.experience_db.resolve()),
                "config": [str(path.resolve()) for path in options.config_paths],
                "object_manifests": [
                    str(path.resolve()) for path in options.object_manifest_paths
                ],
            },
            "compose": (
                {
                    "file": str(options.compose_file.resolve())
                    if options.compose_file
                    else None,
                    "env_file": str(options.compose_env_file.resolve())
                    if options.compose_env_file
                    else None,
                    "service": options.compose_service,
                }
                if mode == "docker-compose"
                else None
            ),
            "events": [],
        }
        journal = cls(path=path, payload=payload)
        journal.write()
        return journal

    @classmethod
    def load(cls, path: Path) -> "UpgradeJournal":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpgradeBlocked(f"upgrade journal is unreadable: {path}") from exc
        if payload.get("schema") != UPGRADE_JOURNAL_SCHEMA:
            raise UpgradeBlocked(f"unsupported upgrade journal: {path}")
        return cls(path=path, payload=payload)

    def event(self, phase: str, **details: Any) -> None:
        now = time.time()
        self.payload["phase"] = phase
        self.payload["updated_at"] = now
        self.payload.setdefault("events", []).append(
            {"phase": phase, "at": now, **details}
        )
        self.write()

    def set_status(self, status: str, **details: Any) -> None:
        self.payload["status"] = status
        self.payload.update(details)
        self.event(status)

    def write(self) -> None:
        _atomic_write_json(self.path, self.payload)


@dataclass(frozen=True)
class UpgradeReport:
    status: str
    source_version: str
    target_version: str
    mode: str
    backup_path: str | None
    journal_path: str
    schema_versions: Mapping[str, int]
    artifact_sha256: str | None = None
    image_digest: str | None = None
    parity: bool = False
    rolled_back: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "mode": self.mode,
            "backup_path": self.backup_path,
            "journal_path": self.journal_path,
            "schema_versions": dict(self.schema_versions),
            "artifact_sha256": self.artifact_sha256,
            "image_digest": self.image_digest,
            "parity": self.parity,
            "rolled_back": self.rolled_back,
            "details": dict(self.details),
        }


CommandRunner = Callable[[Sequence[str], Path | None], subprocess.CompletedProcess[str]]


def _run_command(command: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
        timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as destination:
        destination.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _parse_version(value: str, *, label: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise UpgradeBlocked(f"invalid {label} version: {value}") from exc


def _wheel_identity(path: Path) -> tuple[str, str]:
    if not path.is_file() or path.suffix != ".whl":
        raise UpgradeArtifactError(f"upgrade artifact is not a wheel: {path}")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            metadata_names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise UpgradeArtifactError("wheel must contain exactly one METADATA file")
            message = email.parser.Parser().parsestr(
                archive.read(metadata_names[0]).decode("utf-8")
            )
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise UpgradeArtifactError(f"invalid wheel artifact: {path}") from exc
    name = str(message.get("Name", "")).strip()
    version = str(message.get("Version", "")).strip()
    if name.lower().replace("_", "-") != "wavemind" or not version:
        raise UpgradeArtifactError("wheel release identity is not WaveMind")
    _parse_version(version, label="wheel")
    return name, version


def verify_release_artifact(
    path: Path,
    *,
    expected_version: str,
    expected_sha256: str | None,
    source_url: str,
) -> ReleaseArtifact:
    resolved = path.resolve()
    _name, wheel_version = _wheel_identity(resolved)
    if Version(wheel_version) != Version(expected_version):
        raise UpgradeArtifactError(
            f"wheel version {wheel_version} does not match target {expected_version}"
        )
    digest = _sha256(resolved)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise UpgradeArtifactError(
            f"wheel checksum mismatch: expected {expected_sha256}, got {digest}"
        )
    return ReleaseArtifact(
        version=wheel_version,
        path=resolved,
        sha256=digest,
        source_url=source_url,
        filename=resolved.name,
    )


def _load_pypi_release(version: str | None = None) -> tuple[str, dict[str, Any]]:
    url = DEFAULT_PYPI_URL + (f"/{version}/json" if version else "/json")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        raise UpgradeBlocked(f"cannot resolve WaveMind release from {url}") from exc
    selected = str(payload.get("info", {}).get("version", ""))
    _parse_version(selected, label="PyPI")
    return selected, payload


def resolve_target_version(target: str) -> tuple[str, dict[str, Any] | None]:
    if target == "latest":
        version, payload = _load_pypi_release()
        return version, payload
    normalized = str(_parse_version(target, label="target"))
    version, payload = _load_pypi_release(normalized)
    if Version(version) != Version(normalized):
        raise UpgradeBlocked(f"PyPI returned {version} for requested {normalized}")
    return version, payload


def _select_wheel(payload: Mapping[str, Any], version: str) -> Mapping[str, Any]:
    candidates = [
        row
        for row in payload.get("urls", [])
        if isinstance(row, Mapping)
        and row.get("packagetype") == "bdist_wheel"
        and str(row.get("filename", "")).endswith("py3-none-any.whl")
    ]
    if len(candidates) != 1:
        raise UpgradeBlocked(
            f"release {version} must publish exactly one py3-none-any wheel"
        )
    return candidates[0]


def download_release_artifact(
    version: str,
    cache_dir: Path,
    *,
    payload: Mapping[str, Any] | None = None,
) -> ReleaseArtifact:
    if payload is None:
        _resolved, payload = _load_pypi_release(version)
    row = _select_wheel(payload, version)
    filename = str(row["filename"])
    url = str(row["url"])
    expected = str(row.get("digests", {}).get("sha256", ""))
    if not expected:
        raise UpgradeBlocked(f"release {version} does not publish a SHA-256 digest")
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / filename
    if not target.exists() or _sha256(target) != expected:
        temporary = target.with_name(f".{target.name}.{os.getpid()}.download")
        try:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                with temporary.open("wb") as destination:
                    shutil.copyfileobj(response, destination)
            os.replace(temporary, target)
        except OSError as exc:
            raise UpgradeBlocked(f"cannot download WaveMind {version} wheel") from exc
        finally:
            temporary.unlink(missing_ok=True)
    return verify_release_artifact(
        target,
        expected_version=version,
        expected_sha256=expected,
        source_url=url,
    )


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise UpgradeBlocked("psutil is required for the upgrade lock") from exc
    # ``os.kill(pid, 0)`` is a safe existence probe on POSIX, but Python can
    # route it through TerminateProcess on Windows and end the inspected PID.
    return bool(psutil.pid_exists(pid))


@contextlib.contextmanager
def upgrade_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "created_at": time.time()}
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            owner = int(current.get("pid", 0))
        except (OSError, ValueError, json.JSONDecodeError):
            owner = 0
        if owner and _process_alive(owner):
            raise UpgradeBlocked(f"another WaveMind upgrade is running (pid {owner})")
        path.unlink(missing_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, json.dumps(payload).encode("utf-8"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)


def _open_processes(paths: Iterable[Path]) -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise UpgradeBlocked("psutil is required for the active-process preflight") from exc
    wanted = {os.path.normcase(str(path.resolve())) for path in paths if path.exists()}
    blockers: list[dict[str, Any]] = []
    # Only retrieve the cheap process name during enumeration. In particular,
    # never ask Docker Desktop (or every other unrelated process) for handles or
    # command lines: those calls have blocked indefinitely on Windows hosts.
    for process in psutil.process_iter(["pid", "name"]):
        if process.pid == os.getpid():
            continue
        process_name = str(process.info.get("name") or "").lower()
        # WaveMind state is opened by Python application servers or the
        # packaged CLI. Docker Desktop handle enumeration can block indefinitely
        # on Windows; Compose is stopped explicitly and SQLite writer locks are
        # checked below instead.
        if not any(
            token in process_name
            for token in ("python", "wavemind", "uvicorn", "gunicorn")
        ):
            continue
        try:
            command = [str(part) for part in (process.cmdline() or [])]
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
        normalized_command = os.path.normcase(" ".join(command))
        matched = sorted(
            path
            for path in wanted
            if any(
                variant in normalized_command
                for variant in (
                    path,
                    path.replace("\\", "\\\\"),
                    path.replace("\\", "/"),
                )
            )
        )
        command_identifies_wavemind = any(
            token in normalized_command
            for token in ("-m wavemind", "wavemind serve", "uvicorn", "gunicorn")
        )
        if matched or command_identifies_wavemind:
            blockers.append(
                {
                    "pid": process.pid,
                    "name": process.info.get("name"),
                    "files": matched,
                    "command": command[:8],
                }
            )
    return blockers


def _assert_sqlite_writer_available(path: Path) -> None:
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=0.05, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 50")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        raise UpgradeBlocked(f"active writer detected for {path}") from exc
    finally:
        connection.close()


def _assert_disk_space(options: UpgradeOptions, artifact_bytes: int = 0) -> int:
    state_bytes = sum(
        path.stat().st_size for path in (options.core_db, options.experience_db) if path.exists()
    ) + sum(
        path.stat().st_size
        for path in (*options.config_paths, *options.object_manifest_paths)
        if path.exists()
    )
    required = options.minimum_free_bytes
    if required is None:
        required = max(64 * 1024 * 1024, state_bytes * 5 + artifact_bytes * 2)
    free = shutil.disk_usage(options.state_dir.parent.resolve()).free
    if free < required:
        raise UpgradeBlocked(
            f"insufficient disk space: need {required} bytes, only {free} available"
        )
    return required


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _encode_cell(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, float):
        return {"float": value.hex()}
    return value


def database_inventory(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise UpgradeBlocked(f"SQLite integrity check failed: {path}")
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            if str(row[0]) != "wavemind_schema_migrations"
        ]
        inventory: dict[str, Any] = {}
        for table in tables:
            columns = [
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table)})"
                ).fetchall()
            ]
            digest = hashlib.sha256()
            count = 0
            try:
                cursor = connection.execute(
                    f"SELECT * FROM {_quote_identifier(table)} ORDER BY rowid"
                )
            except sqlite3.OperationalError:
                cursor = connection.execute(f"SELECT * FROM {_quote_identifier(table)}")
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    encoded = json.dumps(
                        [_encode_cell(value) for value in row],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
                    count += 1
            inventory[table] = {
                "columns": columns,
                "rows": count,
                "sha256": digest.hexdigest(),
            }
        return {"integrity": "ok", "tables": inventory}
    finally:
        connection.close()


def _database_state(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "existed": resolved.exists(),
        "inventory": database_inventory(resolved) if resolved.exists() else None,
    }


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    source_connection = sqlite3.connect(source, timeout=5)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _initialize_database(path: Path, component: str) -> None:
    if component == CORE_COMPONENT:
        from .storage import SQLiteMemoryStore

        with SQLiteMemoryStore(path):
            return
    if component == EXPERIENCE_COMPONENT:
        from .experience import SQLiteExperienceStore

        with SQLiteExperienceStore(path):
            return
    raise ValueError(component)


def _prepare_database_copy(source: Path, destination: Path, component: str) -> bool:
    existed = source.exists()
    if existed:
        _sqlite_snapshot(source, destination)
    else:
        _initialize_database(destination, component)
    return existed


def migrate_database(path: Path, component: str, *, release: str) -> int:
    connection = sqlite3.connect(path)
    try:
        with connection:
            state = ensure_schema_migration(connection, component, release=release)
        return state.current_version
    finally:
        connection.close()


def _backup_assets(options: UpgradeOptions) -> list[tuple[str, Path, str]]:
    assets: list[tuple[str, Path, str]] = [
        ("core.sqlite3", options.core_db, "sqlite-core"),
        ("experience.sqlite3", options.experience_db, "sqlite-experience"),
    ]
    for index, path in enumerate(options.config_paths):
        assets.append((f"config/{index:03d}-{path.name}", path, "config"))
    for index, path in enumerate(options.object_manifest_paths):
        assets.append((f"object-manifest/{index:03d}-{path.name}", path, "object-manifest"))
    return assets


def create_upgrade_backup(
    options: UpgradeOptions,
    destination: Path,
    *,
    source_version: str,
    target_version: str,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wavemind-upgrade-backup-", dir=destination.parent) as raw:
        staging = Path(raw)
        entries: list[dict[str, Any]] = []
        for archive_path, source, kind in _backup_assets(options):
            staged = staging / archive_path
            staged.parent.mkdir(parents=True, exist_ok=True)
            existed = source.exists()
            if kind == "sqlite-core":
                _prepare_database_copy(source, staged, CORE_COMPONENT)
                database_inventory(staged)
            elif kind == "sqlite-experience":
                _prepare_database_copy(source, staged, EXPERIENCE_COMPONENT)
                database_inventory(staged)
            elif existed:
                shutil.copy2(source, staged)
            else:
                staged.write_bytes(b"")
            entries.append(
                {
                    "archive_path": archive_path,
                    "target_path": str(source.resolve()),
                    "kind": kind,
                    "existed": existed,
                    "size_bytes": staged.stat().st_size,
                    "sha256": _sha256(staged),
                }
            )
        manifest = {
            "schema": UPGRADE_BACKUP_SCHEMA,
            "created_at": time.time(),
            "source_version": source_version,
            "target_version": target_version,
            "files": entries,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(manifest_path, "manifest.json")
                for entry in entries:
                    archive.write(staging / entry["archive_path"], entry["archive_path"])
            with temporary.open("rb+") as archive_file:
                os.fsync(archive_file.fileno())
            os.replace(temporary, destination)
            with contextlib.suppress(OSError):
                destination.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
    verify_upgrade_backup(destination)
    return destination


def verify_upgrade_backup(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("schema") != UPGRADE_BACKUP_SCHEMA:
                raise UpgradeArtifactError("unsupported upgrade backup schema")
            expected = {"manifest.json"}
            for entry in manifest.get("files", []):
                archive_path = str(entry.get("archive_path", ""))
                expected.add(archive_path)
                payload = archive.read(archive_path)
                if len(payload) != int(entry.get("size_bytes", -1)):
                    raise UpgradeArtifactError(f"backup size mismatch: {archive_path}")
                if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
                    raise UpgradeArtifactError(f"backup checksum mismatch: {archive_path}")
            if set(archive.namelist()) != expected:
                raise UpgradeArtifactError("upgrade backup has unexpected files")
            return manifest
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        if isinstance(exc, UpgradeArtifactError):
            raise
        raise UpgradeArtifactError(f"invalid upgrade backup: {path}") from exc


def restore_upgrade_backup(path: Path) -> None:
    manifest = verify_upgrade_backup(path)
    with tempfile.TemporaryDirectory(prefix="wavemind-upgrade-restore-") as raw:
        staging = Path(raw)
        rollback = staging / "rollback"
        rollback.mkdir()
        replaced: list[tuple[Path, Path | None]] = []
        try:
            with zipfile.ZipFile(path, "r") as archive:
                for index, entry in enumerate(manifest["files"]):
                    target = Path(str(entry["target_path"]))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    previous: Path | None = None
                    if target.exists():
                        previous = rollback / f"{index:04d}-{target.name}"
                        shutil.copy2(target, previous)
                    replaced.append((target, previous))
                    if bool(entry["existed"]):
                        candidate = staging / f"restore-{index:04d}"
                        candidate.write_bytes(archive.read(str(entry["archive_path"])))
                        if str(entry["kind"]).startswith("sqlite"):
                            database_inventory(candidate)
                        os.replace(candidate, target)
                    else:
                        target.unlink(missing_ok=True)
        except Exception as exc:
            failures: list[str] = []
            for target, previous in reversed(replaced):
                try:
                    if previous is None:
                        target.unlink(missing_ok=True)
                    else:
                        shutil.copy2(previous, target)
                except OSError as rollback_exc:
                    failures.append(f"{target}: {rollback_exc}")
            if failures:
                raise UpgradeRollbackError("; ".join(failures)) from exc
            raise


def _inject_failure(options: UpgradeOptions, phase: str) -> None:
    if options.failure_phase == phase:
        raise UpgradeError(f"injected failure at {phase}")


def _installed_version() -> str:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('wavemind'))",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
            timeout=30,
        )
        isolated = result.stdout.strip()
        if isolated:
            _parse_version(isolated, label="installed")
            return isolated
    except (OSError, subprocess.SubprocessError, UpgradeBlocked):
        pass
    try:
        return importlib.metadata.version("wavemind")
    except importlib.metadata.PackageNotFoundError:
        return __version__


def _install_wheel(artifact: ReleaseArtifact, runner: CommandRunner) -> None:
    runner(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            str(artifact.path),
        ],
        None,
    )


def _python_health_command(options: UpgradeOptions, target_version: str) -> list[str]:
    if options.health_command:
        return list(options.health_command)
    script = (
        "import json, sqlite3, wavemind; "
        f"assert wavemind.__version__ == {target_version!r}, wavemind.__version__; "
        f"core={str(options.core_db.resolve())!r}; exp={str(options.experience_db.resolve())!r}; "
        "a=sqlite3.connect(core); b=sqlite3.connect(exp); "
        "assert a.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
        "assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
        "m=a.execute('SELECT id,text,tags,metadata,vector FROM memories ORDER BY id LIMIT 1').fetchone(); "
        "e=b.execute('SELECT id,source_json,metadata_json FROM experience_records ORDER BY id LIMIT 1').fetchone(); "
        "json.loads(m[2]) if m else None; json.loads(m[3]) if m else None; "
        "assert (m is None or (m[0] is not None and m[1] is not None and len(m[4])>0)); "
        "json.loads(e[1]) if e else None; json.loads(e[2]) if e else None; "
        "a.close(); b.close(); "
        "print(json.dumps({'version':wavemind.__version__,'integrity':['ok','ok'],'core_sample':m is not None,'experience_sample':e is not None}))"
    )
    return [sys.executable, "-I", "-c", script]


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def _write_env_value(path: Path, key: str, value: str) -> None:
    lines, values = _read_env(path)
    values[key] = value
    output: list[str] = []
    seen = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            current_key = stripped.split("=", 1)[0].strip()
            if current_key == key:
                if not seen:
                    output.append(f"{key}={value}")
                    seen = True
                continue
        output.append(line)
    if not seen:
        output.append(f"{key}={value}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _file_inventory(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        existed = resolved.exists()
        rows.append(
            {
                "path": str(resolved),
                "existed": existed,
                "size_bytes": resolved.stat().st_size if existed else 0,
                "sha256": _sha256(resolved) if existed else None,
            }
        )
    return rows


def _env_without_key(path: Path, key: str) -> list[str]:
    if not path.exists():
        return []
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            if stripped.split("=", 1)[0].strip() == key:
                continue
        output.append(line)
    return output


def _compose_base(options: UpgradeOptions) -> list[str]:
    if options.compose_file is None or options.compose_env_file is None:
        raise UpgradeBlocked("Docker Compose mode requires --compose-file and --compose-env-file")
    command = ["docker", "compose"]
    if options.compose_env_file.exists():
        command.extend(["--env-file", str(options.compose_env_file.resolve())])
    command.extend(["-f", str(options.compose_file.resolve())])
    return command


def _inspect_image_digest(image: str, runner: CommandRunner) -> str:
    result = runner(
        ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
        None,
    )
    try:
        digests = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise UpgradeArtifactError(f"cannot read digest for image {image}") from exc
    if not isinstance(digests, list) or not digests:
        raise UpgradeArtifactError(f"image {image} has no immutable repository digest")
    digest = str(digests[0]).split("@", 1)[-1]
    if not digest.startswith("sha256:"):
        raise UpgradeArtifactError(f"invalid image digest for {image}: {digest}")
    return digest


def _prepare_compose_image(
    options: UpgradeOptions,
    *,
    target_version: str,
    runner: CommandRunner,
) -> tuple[str, str | None, str, str]:
    assert options.compose_env_file is not None
    _lines, values = _read_env(options.compose_env_file)
    previous_image = values.get("WAVEMIND_IMAGE")
    if previous_image is None:
        base = _compose_base(options)
        rendered = runner(
            [*base, "config", "--images"],
            options.compose_file.parent if options.compose_file else None,
        )
        images = [line.strip() for line in rendered.stdout.splitlines() if line.strip()]
        if len(images) != 1:
            raise UpgradeBlocked(
                "cannot determine one current Docker image for automatic rollback"
            )
        previous_image = images[0]
    current_id = runner(
        ["docker", "image", "inspect", previous_image, "--format", "{{.Id}}"],
        None,
    ).stdout.strip()
    if not current_id.startswith("sha256:"):
        raise UpgradeBlocked(f"cannot pin current Docker image {previous_image}")
    rollback_image = f"wavemind-upgrade-rollback:{os.getpid()}"
    runner(["docker", "tag", current_id, rollback_image], None)
    try:
        target_image = options.target_image or f"{options.image_repository}:{target_version}"
        runner(["docker", "pull", target_image], None)
        digest = _inspect_image_digest(target_image, runner)
        if options.expected_image_digest and digest != options.expected_image_digest:
            raise UpgradeArtifactError(
                f"image digest mismatch: expected {options.expected_image_digest}, got {digest}"
            )
    except Exception:
        with contextlib.suppress(Exception):
            runner(["docker", "image", "rm", rollback_image], None)
        raise
    return digest, previous_image, target_image, rollback_image


def _compose_current_version(options: UpgradeOptions, runner: CommandRunner) -> str:
    base = _compose_base(options)
    try:
        result = runner(
            [*base, "exec", "-T", options.compose_service, "wavemind", "--version"],
            options.compose_file.parent if options.compose_file else None,
        )
        match = re.search(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b", result.stdout)
        if match:
            return str(_parse_version(match.group(1), label="container"))
    except (OSError, subprocess.SubprocessError):
        pass
    rendered = runner(
        [*base, "config", "--images"],
        options.compose_file.parent if options.compose_file else None,
    )
    images = [line.strip() for line in rendered.stdout.splitlines() if line.strip()]
    if len(images) == 1:
        tag = images[0].rsplit(":", 1)[-1]
        try:
            return str(_parse_version(tag, label="container image"))
        except UpgradeBlocked:
            pass
    raise UpgradeBlocked("cannot determine the running WaveMind container version")


def _verify_compose_health(
    options: UpgradeOptions,
    *,
    expected_version: str,
    runner: CommandRunner,
) -> None:
    base = _compose_base(options)
    result = runner(
        [*base, "exec", "-T", options.compose_service, "wavemind", "--version"],
        options.compose_file.parent if options.compose_file else None,
    )
    if expected_version not in result.stdout:
        raise UpgradeError(
            "recreated container reports unexpected version: "
            f"expected {expected_version}, got {result.stdout.strip()}"
        )
    health_script = (
        "import json,os,sqlite3,wavemind; "
        f"assert wavemind.__version__=={expected_version!r}; "
        "a=sqlite3.connect(os.environ['WAVEMIND_DB']); "
        "b=sqlite3.connect(os.environ['WAVEMIND_EXPERIENCE_DB']); "
        "assert a.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
        "assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
        "m=a.execute('SELECT id,text,tags,metadata,vector FROM memories ORDER BY id LIMIT 1').fetchone(); "
        "e=b.execute('SELECT id,source_json,metadata_json FROM experience_records ORDER BY id LIMIT 1').fetchone(); "
        "json.loads(m[2]) if m else None; json.loads(m[3]) if m else None; "
        "assert (m is None or (m[0] is not None and m[1] is not None and len(m[4])>0)); "
        "json.loads(e[1]) if e else None; json.loads(e[2]) if e else None; "
        "a.close(); b.close(); print('upgrade-health-ok')"
    )
    runner(
        [*base, "exec", "-T", options.compose_service, "python", "-c", health_script],
        options.compose_file.parent if options.compose_file else None,
    )


def _start_compose(
    options: UpgradeOptions,
    *,
    target_version: str,
    runner: CommandRunner,
) -> None:
    base = _compose_base(options)
    expected_image = options.target_image or f"{options.image_repository}:{target_version}"
    rendered = runner(
        [*base, "config", "--images"],
        options.compose_file.parent if options.compose_file else None,
    )
    images = [line.strip() for line in rendered.stdout.splitlines() if line.strip()]
    if images != [expected_image]:
        raise UpgradeBlocked(
            "Compose service does not consume WAVEMIND_IMAGE; "
            f"expected {expected_image}, rendered {images}"
        )
    runner(
        [
            *base,
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--wait",
            options.compose_service,
        ],
        options.compose_file.parent if options.compose_file else None,
    )
    _verify_compose_health(
        options,
        expected_version=target_version,
        runner=runner,
    )


def _rollback_compose(
    options: UpgradeOptions,
    previous_image: str | None,
    rollback_image: str | None,
    expected_version: str,
    runner: CommandRunner,
) -> None:
    if not previous_image or not rollback_image or options.compose_env_file is None:
        raise UpgradeRollbackError("previous Docker image is unavailable")
    runner(["docker", "tag", rollback_image, previous_image], None)
    base = _compose_base(options)
    runner(
        [*base, "up", "-d", "--no-deps", "--force-recreate", "--wait", options.compose_service],
        options.compose_file.parent if options.compose_file else None,
    )
    _verify_compose_health(
        options,
        expected_version=expected_version,
        runner=runner,
    )


def _stage_and_validate_databases(
    options: UpgradeOptions,
    staging: Path,
    *,
    target_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for name, source, component in (
        ("core", options.core_db, CORE_COMPONENT),
        ("experience", options.experience_db, EXPERIENCE_COMPONENT),
    ):
        target = staging / f"{name}.sqlite3"
        _prepare_database_copy(source, target, component)
        before[name] = database_inventory(target)
        migrate_database(target, component, release=target_version)
        after[name] = database_inventory(target)
        if before[name] != after[name]:
            raise UpgradeError(f"{name} data parity failed on staged migration")
    return before, after


def _activate_databases(options: UpgradeOptions, staging: Path) -> dict[str, int]:
    versions: dict[str, int] = {}
    for name, target, component in (
        ("core", options.core_db, CORE_COMPONENT),
        ("experience", options.experience_db, EXPERIENCE_COMPONENT),
    ):
        candidate = staging / f"{name}.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        replacement = target.with_name(f".{target.name}.{os.getpid()}.upgrade")
        shutil.copy2(candidate, replacement)
        os.replace(replacement, target)
        connection = sqlite3.connect(target)
        try:
            versions[name] = read_schema_version(connection, component)
        finally:
            connection.close()
    return versions


def _recover_interrupted(
    journal: UpgradeJournal,
    *,
    options: UpgradeOptions,
    runner: CommandRunner,
) -> None:
    if journal.payload.get("status") in TERMINAL_STATUSES:
        return
    backup_value = journal.payload.get("backup_path")
    if backup_value:
        backup = Path(str(backup_value))
        if not backup.exists():
            raise UpgradeBlocked(
                f"interrupted upgrade requires missing rollback archive: {backup}"
            )
        expected_backup_sha256 = journal.payload.get("backup_sha256")
        if expected_backup_sha256 and _sha256(backup) != expected_backup_sha256:
            raise UpgradeBlocked(
                "interrupted upgrade rollback archive checksum does not match the journal"
            )
        restore_upgrade_backup(backup)
    source_artifact = journal.payload.get("source_artifact")
    if journal.payload.get("mode") == "python" and source_artifact:
        artifact = ReleaseArtifact(
            version=str(source_artifact["version"]),
            path=Path(str(source_artifact["path"])),
            sha256=str(source_artifact["sha256"]),
            source_url=str(source_artifact["source_url"]),
            filename=str(source_artifact["filename"]),
        )
        verify_release_artifact(
            artifact.path,
            expected_version=artifact.version,
            expected_sha256=artifact.sha256,
            source_url=artifact.source_url,
        )
        _install_wheel(artifact, runner)
    if journal.payload.get("mode") == "docker-compose":
        recorded = journal.payload.get("compose") or {}
        current = {
            "file": str(options.compose_file.resolve()) if options.compose_file else None,
            "env_file": str(options.compose_env_file.resolve())
            if options.compose_env_file
            else None,
            "service": options.compose_service,
        }
        if recorded != current:
            raise UpgradeBlocked(
                "interrupted Docker upgrade must be resumed with the original "
                "Compose file, environment file, and service"
            )
        previous_image = journal.payload.get("previous_image")
        rollback_image = journal.payload.get("rollback_image")
        if previous_image or rollback_image:
            _rollback_compose(
                options,
                str(previous_image) if previous_image else None,
                str(rollback_image) if rollback_image else None,
                str(journal.payload.get("source_version", "")),
                runner,
            )
            if rollback_image:
                with contextlib.suppress(Exception):
                    runner(["docker", "image", "rm", str(rollback_image)], None)
    journal.set_status("recovered", recovered_at=time.time())


def run_upgrade(
    options: UpgradeOptions,
    *,
    runner: CommandRunner = _run_command,
) -> UpgradeReport:
    if options.mode not in {"python", "docker-compose"}:
        raise UpgradeBlocked(f"unsupported upgrade mode: {options.mode}")
    core = options.core_db.resolve()
    experience = options.experience_db.resolve()
    if core == experience:
        raise UpgradeBlocked("Core and Verified Experience databases must differ")
    options = UpgradeOptions(
        **{
            **options.__dict__,
            "core_db": core,
            "experience_db": experience,
            "backup_dir": options.backup_dir.resolve(),
            "state_dir": options.state_dir.resolve(),
        }
    )
    options.state_dir.mkdir(parents=True, exist_ok=True)
    options.backup_dir.mkdir(parents=True, exist_ok=True)
    journal_path = options.state_dir / "journal.json"
    lock_path = options.state_dir / "upgrade.lock"
    with upgrade_lock(lock_path):
        if journal_path.exists():
            previous = UpgradeJournal.load(journal_path)
            _recover_interrupted(previous, options=options, runner=runner)

        preverified_target_artifact: ReleaseArtifact | None = None
        if options.target_artifact is not None:
            if not options.expected_sha256:
                raise UpgradeArtifactError(
                    "--artifact requires --expected-sha256 to establish release identity"
                )
            _name, target_version = _wheel_identity(options.target_artifact)
            preverified_target_artifact = verify_release_artifact(
                options.target_artifact,
                expected_version=target_version,
                expected_sha256=options.expected_sha256,
                source_url="local",
            )
            target_payload = None
        else:
            target_version, target_payload = resolve_target_version(options.target)
        source_version = (
            _installed_version()
            if options.mode == "python"
            else _compose_current_version(options, runner)
        )
        source_key = _parse_version(source_version, label="installed")
        target_key = _parse_version(target_version, label="target")
        if target_key < source_key and not options.allow_downgrade:
            raise UpgradeBlocked(
                f"refusing downgrade {source_version} -> {target_version}; use --allow-downgrade"
            )

        journal = UpgradeJournal.create(
            journal_path,
            source_version=source_version,
            target_version=target_version,
            mode=options.mode,
            options=options,
        )
        target_artifact: ReleaseArtifact | None = preverified_target_artifact
        source_artifact: ReleaseArtifact | None = None
        image_digest: str | None = None
        previous_image: str | None = None
        target_image: str | None = None
        rollback_image: str | None = None
        compose_stopped = False
        backup_path: Path | None = None
        schema_versions: dict[str, int] = {}
        activated = False
        state_before: dict[str, Any] | None = None
        config_before: list[dict[str, Any]] = []
        object_manifests_before: list[dict[str, Any]] = []
        try:
            protected_assets = [*options.config_paths, *options.object_manifest_paths]
            if options.mode == "python":
                protected_assets[0:0] = [options.core_db, options.experience_db]
            blockers = _open_processes(protected_assets)
            if blockers:
                raise UpgradeBlocked(
                    "WaveMind state is open in another process: "
                    + json.dumps(blockers, ensure_ascii=False)
                )
            if options.mode == "python":
                _assert_sqlite_writer_available(options.core_db)
                _assert_sqlite_writer_available(options.experience_db)

            cache_dir = options.state_dir / "artifacts"
            if options.mode == "python":
                if options.target_artifact is not None:
                    assert target_artifact is not None
                else:
                    target_artifact = download_release_artifact(
                        target_version,
                        cache_dir,
                        payload=target_payload,
                    )
                    if options.expected_sha256 and target_artifact.sha256 != options.expected_sha256:
                        raise UpgradeArtifactError("downloaded wheel does not match --expected-sha256")
                if target_key != source_key:
                    if options.current_artifact is not None:
                        if not options.current_expected_sha256:
                            raise UpgradeArtifactError(
                                "--current-artifact requires --current-expected-sha256 "
                                "to establish rollback release identity"
                            )
                        source_artifact = verify_release_artifact(
                            options.current_artifact,
                            expected_version=source_version,
                            expected_sha256=options.current_expected_sha256,
                            source_url="local",
                        )
                    else:
                        source_artifact = download_release_artifact(source_version, cache_dir)
                    journal.payload["source_artifact"] = source_artifact.as_dict()
                journal.payload["target_artifact"] = target_artifact.as_dict()
                journal.write()
                artifact_bytes = target_artifact.path.stat().st_size + (
                    source_artifact.path.stat().st_size if source_artifact else 0
                )
            else:
                if options.target_artifact is not None:
                    assert target_artifact is not None
                    journal.payload["target_artifact"] = target_artifact.as_dict()
                    journal.write()
                    artifact_bytes = target_artifact.path.stat().st_size
                else:
                    artifact_bytes = 0
                image_digest, previous_image, target_image, rollback_image = _prepare_compose_image(
                    options,
                    target_version=target_version,
                    runner=runner,
                )
                journal.payload["previous_image"] = previous_image
                journal.payload["target_image"] = target_image
                journal.payload["image_digest"] = image_digest
                journal.payload["rollback_image"] = rollback_image
                journal.write()
            required_bytes = _assert_disk_space(options, artifact_bytes)
            journal.event(
                "preflight_passed",
                free_space_required=required_bytes,
                active_processes=0,
            )
            _inject_failure(options, "preflight")

            if options.dry_run:
                journal.set_status("complete", dry_run=True)
                if rollback_image:
                    with contextlib.suppress(Exception):
                        runner(["docker", "image", "rm", rollback_image], None)
                return UpgradeReport(
                    status="dry_run",
                    source_version=source_version,
                    target_version=target_version,
                    mode=options.mode,
                    backup_path=None,
                    journal_path=str(journal_path),
                    schema_versions={},
                    artifact_sha256=target_artifact.sha256 if target_artifact else None,
                    parity=False,
                    details={"preflight": "pass"},
                )

            if options.mode == "docker-compose":
                base = _compose_base(options)
                # A timed-out stop can still have stopped the container. Mark
                # the transition before invoking Docker so rollback always
                # attempts to recreate the pinned source image.
                compose_stopped = True
                runner(
                    [*base, "stop", options.compose_service],
                    options.compose_file.parent if options.compose_file else None,
                )
                journal.event("container_stopped")
                blockers = _open_processes([options.core_db, options.experience_db])
                if blockers:
                    raise UpgradeBlocked(
                        "WaveMind state remains open after Compose stop: "
                        + json.dumps(blockers, ensure_ascii=False)
                    )
                _assert_sqlite_writer_available(options.core_db)
                _assert_sqlite_writer_available(options.experience_db)

            state_before = {
                "core": _database_state(options.core_db),
                "experience": _database_state(options.experience_db),
            }
            config_before = _file_inventory(options.config_paths)
            object_manifests_before = _file_inventory(options.object_manifest_paths)
            compose_env_without_image = (
                _env_without_key(options.compose_env_file, "WAVEMIND_IMAGE")
                if options.mode == "docker-compose" and options.compose_env_file
                else []
            )
            journal.payload["config_migrations"] = [
                {
                    "version": 1,
                    "action": (
                        "set-WAVEMIND_IMAGE"
                        if options.mode == "docker-compose"
                        and options.compose_env_file
                        and row["path"] == str(options.compose_env_file.resolve())
                        else "preserve"
                    ),
                    "before": row,
                }
                for row in config_before
            ]
            journal.payload["object_manifests_before"] = object_manifests_before
            journal.write()

            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup_path = options.backup_dir / (
                f"upgrade-{source_version}-to-{target_version}-{stamp}-"
                f"{journal.payload['operation_id'][:8]}.wavemind-upgrade.zip"
            )
            create_upgrade_backup(
                options,
                backup_path,
                source_version=source_version,
                target_version=target_version,
            )
            journal.payload["backup_path"] = str(backup_path)
            journal.payload["backup_sha256"] = _sha256(backup_path)
            journal.event("backup_verified", sha256=journal.payload["backup_sha256"])
            _inject_failure(options, "backup")

            with tempfile.TemporaryDirectory(
                prefix="wavemind-upgrade-stage-", dir=options.state_dir
            ) as raw:
                staging = Path(raw)
                before, after = _stage_and_validate_databases(
                    options,
                    staging,
                    target_version=target_version,
                )
                journal.event(
                    "staged_migration_validated",
                    before=before,
                    after=after,
                )
                _inject_failure(options, "staged_migration")

                if options.mode == "python" and target_key != source_key:
                    assert target_artifact is not None
                    # pip may uninstall the source distribution before failing.
                    # Treat the package as mutated as soon as installation starts.
                    activated = True
                    _install_wheel(target_artifact, runner)
                    journal.event("package_activated", artifact=target_artifact.as_dict())
                elif options.mode == "docker-compose":
                    assert options.compose_env_file is not None
                    assert target_image is not None
                    _write_env_value(
                        options.compose_env_file,
                        "WAVEMIND_IMAGE",
                        target_image,
                    )
                    activated = True
                    journal.event("container_activated", image_digest=image_digest)
                _inject_failure(options, "code_activation")

                schema_versions = _activate_databases(options, staging)
                journal.event("data_activated", schema_versions=schema_versions)
                _inject_failure(options, "data_activation")

                if options.mode == "docker-compose":
                    _start_compose(
                        options,
                        target_version=target_version,
                        runner=runner,
                    )
                    compose_stopped = False
                    journal.event("container_started", image_digest=image_digest)

            live_after = {
                "core": database_inventory(options.core_db),
                "experience": database_inventory(options.experience_db),
            }
            if live_after != after:
                raise UpgradeError("live state does not match the validated staged migration")
            config_after = _file_inventory(options.config_paths)
            object_manifests_after = _file_inventory(options.object_manifest_paths)
            if object_manifests_after != object_manifests_before:
                raise UpgradeError("object-store reference manifests changed during upgrade")
            for before_row, after_row in zip(config_before, config_after):
                is_compose_env = (
                    options.mode == "docker-compose"
                    and options.compose_env_file is not None
                    and before_row["path"] == str(options.compose_env_file.resolve())
                )
                if is_compose_env:
                    if _env_without_key(options.compose_env_file, "WAVEMIND_IMAGE") != compose_env_without_image:
                        raise UpgradeError("Compose environment changed outside WAVEMIND_IMAGE")
                elif before_row != after_row:
                    raise UpgradeError(f"configuration changed unexpectedly: {before_row['path']}")
            journal.payload["config_after"] = config_after
            journal.payload["object_manifests_after"] = object_manifests_after
            journal.write()

            if options.mode == "python":
                runner(_python_health_command(options, target_version), None)
            else:
                base = _compose_base(options)
                runner(
                    [*base, "exec", "-T", options.compose_service, "wavemind", "--version"],
                    options.compose_file.parent if options.compose_file else None,
                )
            _inject_failure(options, "health")
            journal.set_status(
                "complete",
                completed_at=time.time(),
                schema_versions=schema_versions,
                parity=True,
            )
            if rollback_image:
                with contextlib.suppress(Exception):
                    runner(["docker", "image", "rm", rollback_image], None)
            return UpgradeReport(
                status="complete",
                source_version=source_version,
                target_version=target_version,
                mode=options.mode,
                backup_path=str(backup_path),
                journal_path=str(journal_path),
                schema_versions=schema_versions,
                artifact_sha256=target_artifact.sha256 if target_artifact else None,
                image_digest=image_digest,
                parity=True,
                details={"operation_id": journal.payload["operation_id"]},
            )
        except Exception as exc:
            journal.payload["error"] = f"{type(exc).__name__}: {exc}"
            journal.set_status("rolling_back")
            rollback_errors: list[str] = []
            if backup_path is not None and backup_path.exists():
                try:
                    restore_upgrade_backup(backup_path)
                except Exception as rollback_exc:
                    rollback_errors.append(f"state: {rollback_exc}")
            if activated and options.mode == "python" and source_artifact is not None:
                try:
                    _install_wheel(source_artifact, runner)
                except Exception as rollback_exc:
                    rollback_errors.append(f"package: {rollback_exc}")
            if (activated or compose_stopped) and options.mode == "docker-compose":
                try:
                    _rollback_compose(
                        options,
                        previous_image,
                        rollback_image,
                        source_version,
                        runner,
                    )
                    if rollback_image:
                        with contextlib.suppress(Exception):
                            runner(["docker", "image", "rm", rollback_image], None)
                except Exception as rollback_exc:
                    rollback_errors.append(f"container: {rollback_exc}")
            elif options.mode == "docker-compose" and rollback_image:
                with contextlib.suppress(Exception):
                    runner(["docker", "image", "rm", rollback_image], None)
            if backup_path is not None and state_before is not None:
                try:
                    rollback_state = {
                        "core": _database_state(options.core_db),
                        "experience": _database_state(options.experience_db),
                    }
                    rollback_config = _file_inventory(options.config_paths)
                    rollback_manifests = _file_inventory(options.object_manifest_paths)
                    if rollback_state != state_before:
                        raise UpgradeRollbackError(
                            "database rollback parity does not match pre-upgrade state"
                        )
                    if rollback_config != config_before:
                        raise UpgradeRollbackError(
                            "configuration rollback parity does not match pre-upgrade state"
                        )
                    if rollback_manifests != object_manifests_before:
                        raise UpgradeRollbackError(
                            "object manifest rollback parity does not match pre-upgrade state"
                        )
                    journal.payload["rollback_parity"] = {
                        "databases": True,
                        "configuration": True,
                        "object_manifests": True,
                    }
                    journal.write()
                except Exception as rollback_exc:
                    rollback_errors.append(f"parity: {rollback_exc}")
            if rollback_errors:
                journal.set_status("rollback_failed", rollback_errors=rollback_errors)
                raise UpgradeRollbackError(
                    f"upgrade failed ({exc}); rollback also failed: {'; '.join(rollback_errors)}"
                ) from exc
            journal.set_status(
                "rolled_back",
                rolled_back_at=time.time(),
                rollback_parity_verified=backup_path is not None and state_before is not None,
            )
            raise UpgradeError(f"upgrade rolled back: {exc}") from exc
