from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SOURCE_MANIFEST_SCHEMA = "wavemind.source_manifest.v1"
ARTIFACT_INTEGRITY_SCHEMA = "wavemind.artifact_integrity.v1"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class EvidenceError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_commit(root: Path) -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(root),
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("cannot resolve repository HEAD") from exc
    if not GIT_SHA_RE.fullmatch(value):
        raise EvidenceError("repository HEAD is not an exact 40-character git SHA")
    return value


def commit_relation(root: Path, source_sha: str, expected_sha: str) -> str:
    if not GIT_SHA_RE.fullmatch(source_sha):
        return "invalid"
    if not GIT_SHA_RE.fullmatch(expected_sha):
        return "invalid-expected"
    if source_sha == expected_sha:
        return "exact"
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{source_sha}^{{commit}}"],
            cwd=Path(root),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return "missing"
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_sha, expected_sha],
        cwd=Path(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return "ancestor" if result.returncode == 0 else "unrelated"


def build_source_manifest(root: Path, paths: Iterable[Path | str]) -> dict[str, Any]:
    root = Path(root).resolve()
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_path in paths:
        candidate = Path(raw_path)
        absolute = candidate if candidate.is_absolute() else root / candidate
        absolute = absolute.resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvidenceError(f"manifest path escapes repository: {raw_path}") from exc
        if relative in seen:
            continue
        if not absolute.is_file():
            raise EvidenceError(f"manifest source file is missing: {relative}")
        seen.add(relative)
        files.append({"path": relative, "sha256": file_sha256(absolute)})
    files.sort(key=lambda item: item["path"])
    if not files:
        raise EvidenceError("source manifest must contain at least one file")
    return {
        "schema": SOURCE_MANIFEST_SCHEMA,
        "algorithm": "sha256",
        "files": files,
        "digest": sha256_bytes(canonical_json_bytes(files)),
    }


def validate_source_manifest(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    require_current_files: bool,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != SOURCE_MANIFEST_SCHEMA:
        errors.append("source manifest schema is invalid")
    if manifest.get("algorithm") != "sha256":
        errors.append("source manifest algorithm is not sha256")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("source manifest has no files")
        return errors
    expected_digest = sha256_bytes(canonical_json_bytes(files))
    if manifest.get("digest") != expected_digest:
        errors.append("source manifest digest mismatch")

    root = Path(root).resolve()
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("source manifest file entry is invalid")
            continue
        relative = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            errors.append("source manifest file path is missing")
            continue
        if relative in seen:
            errors.append(f"source manifest contains duplicate path: {relative}")
            continue
        seen.add(relative)
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"source manifest path escapes repository: {relative}")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"source manifest hash is invalid: {relative}")
            continue
        if require_current_files:
            if not candidate.is_file():
                errors.append(f"source manifest file is missing: {relative}")
            elif file_sha256(candidate) != digest:
                errors.append(f"source manifest file hash mismatch: {relative}")
    return errors


def attach_artifact_integrity(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("integrity", None)
    result["integrity"] = {
        "schema": ARTIFACT_INTEGRITY_SCHEMA,
        "algorithm": "sha256",
        "payload_sha256": sha256_bytes(canonical_json_bytes(result)),
    }
    return result


def validate_artifact_integrity(payload: Mapping[str, Any]) -> list[str]:
    integrity = payload.get("integrity")
    if not isinstance(integrity, Mapping):
        return ["artifact integrity block is missing"]
    errors: list[str] = []
    if integrity.get("schema") != ARTIFACT_INTEGRITY_SCHEMA:
        errors.append("artifact integrity schema is invalid")
    if integrity.get("algorithm") != "sha256":
        errors.append("artifact integrity algorithm is not sha256")
    content = dict(payload)
    content.pop("integrity", None)
    expected = sha256_bytes(canonical_json_bytes(content))
    if integrity.get("payload_sha256") != expected:
        errors.append("artifact payload digest mismatch")
    return errors


def execution_environment(*, profile: str) -> dict[str, Any]:
    return {
        "profile": profile,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": Path(sys.executable).name,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_runner_os": os.environ.get("RUNNER_OS"),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
