from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    file_sha256,
    repository_commit,
    validate_artifact_integrity,
)
from .scientific_admission import REAL_BASELINE_PACKAGES
from .scientific_protocol import (
    load_scientific_protocol,
    validate_scientific_protocol,
)


SCIENTIFIC_PREFLIGHT_SCHEMA = "wavemind.scientific_memory_preflight.v1"
OFFICIAL_RUNNER_MANIFEST_SCHEMA = "wavemind.official_runner_manifest.v1"
DATASET_ENV = {
    "memory-agent-bench": "WAVEMIND_MEMORYAGENTBENCH_ROOT",
    "state-bench": "WAVEMIND_STATE_BENCH_ROOT",
    "memops": "WAVEMIND_MEMOPS_ROOT",
    "longmemeval-v2": "WAVEMIND_LONGMEMEVAL_V2_ROOT",
}
RUNNER_ENV = {
    "memoryagentbench": "WAVEMIND_MEMORYAGENTBENCH_RUNNER",
    "state-bench-agent-learning": "WAVEMIND_STATE_BENCH_RUNNER",
    "memops": "WAVEMIND_MEMOPS_RUNNER",
    "longmemeval-v2": "WAVEMIND_LONGMEMEVAL_V2_RUNNER",
}
SOURCE_REVISION_ENV = {
    "mem0-oss": "WAVEMIND_MEM0_SOURCE_REVISION",
    "langgraph": "WAVEMIND_LANGGRAPH_SOURCE_REVISION",
}
CREDENTIAL_ENV = {
    "official-judge-api-key": (
        "WAVEMIND_OFFICIAL_JUDGE_API_KEY",
        "OPENAI_API_KEY",
    ),
    "longmemeval-v2-reader-endpoint": (
        "WAVEMIND_LONGMEMEVAL_READER_BASE_URL",
    ),
    "longmemeval-v2-embedding-endpoint": (
        "WAVEMIND_LONGMEMEVAL_EMBEDDING_BASE_URL",
    ),
}


def _repository_state(root: Path) -> dict[str, Any]:
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        text=True,
        encoding="utf-8",
    )
    return {"sha": repository_commit(root), "clean": not bool(status.strip())}


def _installed_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package_name in REAL_BASELINE_PACKAGES.values():
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            versions[package_name] = None
    return versions


def _git_revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_root(path: Path) -> Path | None:
    selected = path if path.is_dir() else path.parent
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=selected,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    root = Path(value).resolve()
    return root if root.is_dir() else None


def _load_runner_manifest(
    path: Path,
    *,
    protocol_digest: str,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"official runner manifest cannot be loaded: {exc}"]
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != OFFICIAL_RUNNER_MANIFEST_SCHEMA:
        errors.append("official runner manifest schema is invalid")
    if payload.get("protocol_digest") != protocol_digest:
        errors.append("official runner manifest protocol digest mismatch")
    rows: dict[str, Mapping[str, Any]] = {}
    for row in payload.get("runners") or []:
        if not isinstance(row, Mapping):
            errors.append("official runner manifest row is invalid")
            continue
        family_id = str(row.get("family_id") or "")
        if not family_id or family_id in rows:
            errors.append("official runner manifest family ids are missing or duplicated")
            continue
        revision = str(row.get("revision") or "")
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            errors.append(f"official runner revision is invalid: {family_id}")
        entrypoints = row.get("entrypoints")
        if not isinstance(entrypoints, list) or not entrypoints:
            errors.append(f"official runner entrypoints are missing: {family_id}")
        rows[family_id] = row
    expected_families = set(RUNNER_ENV)
    if set(rows) != expected_families:
        errors.append("official runner manifest family set is incomplete or changed")
    return rows, errors


def _check_runner(
    path: Path | None,
    manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    issues: list[str] = []
    if path is None or not path.is_file():
        issues.append("official runner entrypoint missing")
    if not isinstance(manifest, Mapping):
        issues.append("official runner provenance is missing")
    root = _git_root(path) if path and path.is_file() else None
    expected_revision = str((manifest or {}).get("revision") or "")
    observed_revision = _git_revision(root) if root else None
    if path and path.is_file() and root is None:
        issues.append("official runner is not inside a git checkout")
    elif root and observed_revision != expected_revision:
        issues.append("official runner git revision mismatch")

    selected_relative = None
    verified_entrypoints: list[dict[str, Any]] = []
    if root and isinstance(manifest, Mapping):
        try:
            selected_relative = path.resolve().relative_to(root).as_posix() if path else None
        except ValueError:
            issues.append("official runner escapes its repository")
        expected_paths: set[str] = set()
        for entry in manifest.get("entrypoints") or []:
            if not isinstance(entry, Mapping):
                issues.append("official runner entrypoint provenance is invalid")
                continue
            relative = str(entry.get("path") or "")
            expected_paths.add(relative)
            candidate = (root / relative).resolve()
            expected_hash = str(entry.get("sha256") or "")
            hash_matches = bool(
                candidate.is_file() and file_sha256(candidate) == expected_hash
            )
            verified_entrypoints.append(
                {
                    "path": relative,
                    "sha256": expected_hash,
                    "hash_matches": hash_matches,
                }
            )
            if not hash_matches:
                issues.append(f"official runner file hash mismatch: {relative}")
        if selected_relative not in expected_paths:
            issues.append("selected runner is not a pinned official entrypoint")
    return {
        "path": str(path) if path else None,
        "repository_root": str(root) if root else None,
        "expected_revision": expected_revision or None,
        "observed_revision": observed_revision,
        "selected_entrypoint": selected_relative,
        "verified_entrypoints": verified_entrypoints,
        "ready": not issues,
        "issues": issues,
        "issue": "; ".join(issues),
    }


def _check_dataset(root: Path | None, source: Mapping[str, Any]) -> dict[str, Any]:
    if root is None or not root.is_dir():
        return {
            "ready": False,
            "root": str(root) if root else None,
            "expected_revision": source.get("revision"),
            "observed_revision": None,
            "issues": ["pinned official dataset checkout is missing"],
        }
    issues: list[str] = []
    if source.get("kind") == "git_repository":
        observed = _git_revision(root)
        if observed != source.get("revision"):
            issues.append("official dataset git revision mismatch")
    else:
        observed = source.get("revision")
        for entry in source.get("content") or []:
            path = root / str(entry.get("path") or "")
            if not path.is_file():
                issues.append(f"dataset file missing: {entry.get('path')}")
            elif file_sha256(path) != entry.get("sha256"):
                issues.append(f"dataset file hash mismatch: {entry.get('path')}")
    return {
        "ready": not issues,
        "root": str(root),
        "expected_revision": source.get("revision"),
        "observed_revision": observed,
        "issues": issues,
    }


def evaluate_scientific_memory_preflight(
    *,
    project_root: str | Path,
    protocol_path: str | Path,
    dataset_manifest_path: str | Path,
    run_dir: str | Path,
    runner_manifest_path: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    package_versions: Mapping[str, str | None] | None = None,
    repository_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    env = dict(os.environ if environment is None else environment)
    protocol = load_scientific_protocol(protocol_path)
    protocol_errors = validate_scientific_protocol(protocol, project_root=root)
    source_manifest = json.loads(Path(dataset_manifest_path).read_text(encoding="utf-8"))
    selected_runner_manifest = Path(
        runner_manifest_path
        or root / "benchmarks" / "scientific_official_runner_manifest_v1.json"
    )
    runner_manifest, runner_manifest_errors = _load_runner_manifest(
        selected_runner_manifest,
        protocol_digest=str(protocol.get("protocol_digest") or ""),
    )
    sources = {
        str(source["id"]): source for source in source_manifest.get("sources") or []
    }
    state = dict(repository_state or _repository_state(root))
    packages = dict(
        _installed_versions() if package_versions is None else package_versions
    )

    dataset_manifest_errors = validate_artifact_integrity(source_manifest)
    if source_manifest.get("schema") != "wavemind.evaluation_dataset_manifest.v1":
        dataset_manifest_errors.append("evaluation dataset manifest schema is invalid")

    package_checks = {}
    for baseline_id, package_name in REAL_BASELINE_PACKAGES.items():
        revision_env = SOURCE_REVISION_ENV.get(baseline_id)
        source_revision = env.get(revision_env, "") if revision_env else None
        revision_ready = revision_env is None or (
            len(source_revision) == 40
            and all(char in "0123456789abcdef" for char in source_revision)
        )
        package_checks[baseline_id] = {
            "package": package_name,
            "version": packages.get(package_name),
            "source_revision_environment_variable": revision_env,
            "source_revision": source_revision,
            "ready": bool(packages.get(package_name)) and revision_ready,
        }
    dataset_checks: dict[str, Any] = {}
    for source_id, env_name in DATASET_ENV.items():
        raw_root = env.get(env_name)
        source = sources.get(source_id, {})
        dataset_checks[source_id] = _check_dataset(
            Path(raw_root).resolve() if raw_root else None,
            source,
        )
        dataset_checks[source_id]["environment_variable"] = env_name

    runner_checks: dict[str, Any] = {}
    for family_id, env_name in RUNNER_ENV.items():
        raw_path = env.get(env_name)
        path = Path(raw_path).resolve() if raw_path else None
        runner_checks[family_id] = {
            "environment_variable": env_name,
            **_check_runner(path, runner_manifest.get(family_id)),
        }

    credential_checks: dict[str, Any] = {}
    for credential_id, alternatives in CREDENTIAL_ENV.items():
        present = [name for name in alternatives if bool(env.get(name, "").strip())]
        credential_checks[credential_id] = {
            "accepted_environment_variables": list(alternatives),
            "present_environment_variables": present,
            "ready": bool(present),
            "issue": "" if present else "required credential or endpoint is missing",
        }

    run_paths = sorted(Path(run_dir).glob("*.json")) if Path(run_dir).is_dir() else []
    full_longmem_runs = 0
    for path in run_paths:
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        full_longmem_runs += int(bool(run.get("longmemeval_v2_full_run")))
    checks = {
        "protocol": {"ready": not protocol_errors, "issues": protocol_errors},
        "dataset_manifest": {
            "ready": not dataset_manifest_errors,
            "issues": dataset_manifest_errors,
        },
        "official_runner_manifest": {
            "ready": not runner_manifest_errors,
            "path": str(selected_runner_manifest.resolve()),
            "issues": runner_manifest_errors,
        },
        "clean_exact_sha": {
            "ready": bool(state.get("clean")) and bool(state.get("sha")),
            "source_sha": state.get("sha"),
            "clean": bool(state.get("clean")),
            "issue": "" if state.get("clean") else "worktree has uncommitted changes",
        },
        "real_baseline_packages": {
            "ready": all(row["ready"] for row in package_checks.values()),
            "packages": package_checks,
        },
        "official_datasets": {
            "ready": all(row["ready"] for row in dataset_checks.values()),
            "datasets": dataset_checks,
        },
        "official_runners": {
            "ready": all(row["ready"] for row in runner_checks.values()),
            "runners": runner_checks,
        },
        "official_credentials": {
            "ready": all(row["ready"] for row in credential_checks.values()),
            "credentials": credential_checks,
            "secret_values_recorded": False,
        },
        "longmemeval_v2_one_shot_unconsumed": {
            "ready": full_longmem_runs == 0,
            "observed_full_runs": full_longmem_runs,
            "maximum_before_admission": 0,
        },
    }
    ready = all(check["ready"] for check in checks.values())
    payload = {
        "schema": SCIENTIFIC_PREFLIGHT_SCHEMA,
        "status": "ready" if ready else "action_required",
        "ready": ready,
        "source_sha": state.get("sha"),
        "protocol_digest": protocol.get("protocol_digest"),
        "checks": checks,
        "claim_boundary": (
            "Preflight only. It does not execute held-out cases and is not scientific "
            "admission evidence."
        ),
    }
    return attach_artifact_integrity(payload)


def render_scientific_memory_preflight_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Scientific Memory Preflight",
        "",
        f"- Status: **{payload.get('status')}**",
        f"- Source SHA: `{payload.get('source_sha')}`",
        "",
        "| Check | Status |",
        "|---|---:|",
    ]
    for check_id, check in (payload.get("checks") or {}).items():
        lines.append(f"| `{check_id}` | {'ready' if check.get('ready') else 'action required'} |")
    lines.extend(["", f"> {payload.get('claim_boundary')}", ""])
    return "\n".join(lines)
