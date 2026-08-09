from __future__ import annotations

import json
import platform
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.product_persistence_admission.v1"


def _docker(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _require_docker(*args: str, timeout: float = 120.0) -> str:
    result = _docker(*args, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"docker {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer persistence-admission-key",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_ready(base_url: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _request(base_url, "GET", "/healthz")
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.5)
    raise RuntimeError("container did not become healthy before timeout")


def _start_container(
    *,
    name: str,
    image: str,
    data_dir: Path,
    port: int,
) -> str:
    principals = json.dumps(
        {
            "persistence-admission-key": {
                "identity": "persistence-admission",
                "role": "admin",
                "namespace_prefixes": ["*"],
            }
        },
        separators=(",", ":"),
    )
    return _require_docker(
        "run",
        "-d",
        "--name",
        name,
        "-p",
        f"127.0.0.1:{port}:8000",
        "-v",
        f"{data_dir.resolve()}:/data",
        "-e",
        "WAVEMIND_DB=/data/wavemind.sqlite3",
        "-e",
        "WAVEMIND_EXPERIENCE_DB=/data/wavemind-experience.sqlite3",
        "-e",
        "WAVEMIND_BACKUP_ROOT=/data/backups",
        "-e",
        f"WAVEMIND_API_PRINCIPALS={principals}",
        image,
        "wavemind",
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--allow-public",
    )


def _remove_container(name: str) -> None:
    _docker("rm", "-f", name, timeout=30)


def _write_first_instance(base_url: str) -> dict[str, Any]:
    memory = _request(
        base_url,
        "POST",
        "/remember",
        payload={
            "text": "Container recreation preserves trusted product state.",
            "namespace": "tenant:persistence:core",
            "idempotency_key": "persistence-admission-request",
        },
    )
    run = _request(
        base_url,
        "POST",
        "/experience/runtime/runs",
        payload={
            "query": "verify product persistence",
            "objective": "verify product persistence",
            "domain": "quality",
            "task_type": "container-recreate",
            "namespace": "tenant:persistence:experience",
            "run_id": "persistence-admission-run",
            "session_id": "persistence-admission-session",
            "task_id": "persistence-admission-task",
            "tools": ["health"],
        },
    )
    _request(
        base_url,
        "POST",
        "/experience/runtime/events",
        payload={
            "id": "persistence-admission-call",
            "namespace": "tenant:persistence:experience",
            "run_id": "persistence-admission-run",
            "session_id": "persistence-admission-session",
            "task_id": "persistence-admission-task",
            "kind": "tool.call",
            "sequence": 3,
            "tool_name": "health",
            "payload": {"input": {"api_key": "must-not-leak"}},
        },
    )
    _request(
        base_url,
        "POST",
        "/experience/runtime/events",
        payload={
            "id": "persistence-admission-result",
            "namespace": "tenant:persistence:experience",
            "run_id": "persistence-admission-run",
            "session_id": "persistence-admission-session",
            "task_id": "persistence-admission-task",
            "kind": "tool.result",
            "sequence": 4,
            "parent_event_id": "persistence-admission-call",
            "tool_name": "health",
            "payload": {"success": True, "output": {"status": "healthy"}},
        },
    )
    verification = _request(
        base_url,
        "POST",
        "/experience/runtime/runs/persistence-admission-run/verify",
        payload={
            "namespace": "tenant:persistence:experience",
            "evidence_id": "persistence-admission-evidence",
            "source": "environment",
            "verifier": "container-recreate",
            "success": True,
            "score": 1.0,
            "reference": "local://health?api_key=must-not-leak",
            "metadata": {"password": "must-not-leak"},
        },
    )
    backup = _request(
        base_url,
        "POST",
        "/backup",
        payload={},
    )
    return {"memory": memory, "run": run, "verification": verification, "backup": backup}


def _read_second_instance(base_url: str) -> dict[str, Any]:
    query = _request(
        base_url,
        "POST",
        "/query",
        payload={
            "text": "How is trusted product state preserved after container recreation?",
            "namespace": "tenant:persistence:core",
            "top_k": 3,
        },
    )
    replay = _request(
        base_url,
        "POST",
        "/remember",
        payload={
            "text": "Container recreation preserves trusted product state.",
            "namespace": "tenant:persistence:core",
            "idempotency_key": "persistence-admission-request",
        },
    )
    experience = _request(
        base_url,
        "GET",
        "/experience/runtime/runs/persistence-admission-run"
        "?namespace=tenant%3Apersistence%3Aexperience",
    )
    return {"query": query, "replay": replay, "experience": experience}


def run_product_persistence_admission(
    *,
    image: str,
    project_root: str | Path,
    state_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run_token = uuid.uuid4().hex[:10]
    names = [f"wavemind-persistence-a-{run_token}", f"wavemind-persistence-b-{run_token}"]
    owned_temp = None
    if state_root is None:
        owned_temp = tempfile.TemporaryDirectory(prefix="wavemind-product-persistence-")
        data_dir = Path(owned_temp.name) / "data"
    else:
        data_dir = Path(state_root).resolve() / f"run-{run_token}" / "data"
    data_dir.mkdir(parents=True, exist_ok=False)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    container_ids: list[str] = []
    try:
        container_ids.append(
            _start_container(name=names[0], image=image, data_dir=data_dir, port=port)
        )
        _wait_ready(base_url)
        first = _write_first_instance(base_url)
        _remove_container(names[0])
        container_ids.append(
            _start_container(name=names[1], image=image, data_dir=data_dir, port=port)
        )
        _wait_ready(base_url)
        second = _read_second_instance(base_url)
    finally:
        for name in names:
            _remove_container(name)

    query_results = second["query"].get("results") or []
    experience = second["experience"]
    serialized_experience = json.dumps(experience, ensure_ascii=False)
    checks = {
        "distinct_containers": len(container_ids) == 2 and container_ids[0] != container_ids[1],
        "core_memory_after_recreate": bool(query_results)
        and query_results[0].get("id") == first["memory"].get("id"),
        "experience_after_recreate": len(experience.get("verifications") or []) == 1
        and len(experience.get("events") or []) >= 9,
        "verification_after_recreate": bool(
            (experience.get("verifications") or [{}])[0].get("successful")
        ),
        "idempotent_retry_after_recreate": second["replay"].get("idempotent_replay") is True
        and second["replay"].get("id") == first["memory"].get("id"),
        "product_backup_persisted": any((data_dir / "backups").glob("*.wavemind.zip")),
        "core_database_persisted": (data_dir / "wavemind.sqlite3").is_file(),
        "experience_database_persisted": (
            data_dir / "wavemind-experience.sqlite3"
        ).is_file(),
        "secret_leakage_zero": "must-not-leak" not in serialized_experience,
    }
    image_id = _require_docker("image", "inspect", image, "--format", "{{.Id}}")
    report = {
        "schema": SCHEMA,
        "status": "admitted" if all(checks.values()) else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": repository_commit(root),
        "image": {"reference": image, "id": image_id},
        "environment": {
            "platform": platform.platform(),
            "docker": _require_docker("version", "--format", "{{.Server.Version}}"),
        },
        "container_ids": container_ids,
        "checks": checks,
        "metrics": {
            "events_after_recreate": len(experience.get("events") or []),
            "verifications_after_recreate": len(experience.get("verifications") or []),
            "backups_after_recreate": len(list((data_dir / "backups").glob("*.wavemind.zip"))),
        },
        "source_manifest": build_source_manifest(
            root,
            [
                "Dockerfile",
                "docker-compose.yml",
                "wavemind/api.py",
                "wavemind/experience_runtime.py",
                "wavemind/product_backup.py",
                "wavemind/product_persistence_admission.py",
            ],
        ),
    }
    if owned_temp is not None:
        owned_temp.cleanup()
    return attach_artifact_integrity(report)


def validate_product_persistence_artifact(
    report: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(report)
    if report.get("schema") != SCHEMA:
        errors.append("product persistence schema is invalid")
    if report.get("source_sha") != expected_source_sha:
        errors.append("product persistence source SHA mismatch")
    manifest = report.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("product persistence source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root),
                manifest,
                require_current_files=True,
            )
        )
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not checks or not all(checks.values()):
        errors.append("product persistence checks are not all passing")
    if report.get("status") != "admitted":
        errors.append("product persistence status is not admitted")
    return errors
