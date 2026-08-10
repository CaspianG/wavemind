from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from wavemind.api import create_app
from wavemind.core import WaveMind
from wavemind.evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)
from wavemind.experience_runtime import AgentEventKind
from wavemind.workspace_experience import (
    WorkspaceEvent,
    WorkspaceExperienceManager,
    initialize_workspace,
)


SCHEMA = "wavemind.workspace_experience_operational.v1"
OPERATIONAL_SOURCE_FILES = [
    "wavemind/api.py",
    "wavemind/workspace_experience.py",
    "wavemind/workspace_experience_admission.py",
    "benchmarks/workspace_experience_operational_evidence.py",
    "benchmarks/workspace_experience_v5_benchmark.py",
    "tests/test_workspace_experience.py",
    "tests/test_workspace_experience_admission.py",
]
REQUIRED_CHECKS = {
    "python-write-http-restart-replay",
    "registered-workspace-http-packet",
    "namespace-auth-denies-cross-workspace",
    "arbitrary-workspace-id-denied",
    "root-field-without-workspace-id-denied",
    "missing-registry-denied",
    "registry-escape-denied",
    "mandatory-events-captured-idempotently",
    "secrets-redacted",
}


def run_workspace_operational_evidence(
    *,
    project_root: str | Path = PROJECT_ROOT,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source_sha = repository_commit(root)
    with _temporary_root(temp_root) as selected_temp:
        base = selected_temp / "base"
        base.mkdir(parents=True, exist_ok=True)
        repo_a = _make_repo(base / "repo-a", remote="https://github.com/example/workspace-a.git")
        repo_b = _make_repo(base / "repo-b", remote="https://github.com/example/workspace-b.git")
        config_a = initialize_workspace(repo_a, workspace_id="agent-a", tenant_id="tenant", user_id="user-a")
        config_b = initialize_workspace(repo_b, workspace_id="agent-b", tenant_id="tenant", user_id="user-b")

        manager = WorkspaceExperienceManager.open(repo_a)
        try:
            started = manager.start_run(
                query="pytest cache permission failure",
                objective="fix pytest cache permission failure",
                domain="python",
                task_type="pytest-cache",
                run_id="operational-run",
                session_id="operational-session",
                task_id="operational-task",
                tools=("remove-cache",),
            )
            call = manager.capture_event(
                WorkspaceEvent(
                    id="operational-call",
                    run_id="operational-run",
                    session_id="operational-session",
                    task_id="operational-task",
                    kind=AgentEventKind.TOOL_CALL,
                    sequence=started["next_sequence"],
                    tool_name="remove-cache",
                    payload={
                        "input": {"path": ".pytest_cache"},
                        "api_key": "sk-operational-secret",
                    },
                )
            )
            duplicate = manager.capture_event(
                WorkspaceEvent(
                    id="operational-call",
                    run_id="operational-run",
                    session_id="operational-session",
                    task_id="operational-task",
                    kind=AgentEventKind.TOOL_CALL,
                    sequence=started["next_sequence"],
                    tool_name="remove-cache",
                    payload={
                        "input": {"path": ".pytest_cache"},
                        "api_key": "sk-operational-secret",
                    },
                )
            )
            result = manager.capture_event(
                WorkspaceEvent(
                    id="operational-result",
                    run_id="operational-run",
                    session_id="operational-session",
                    task_id="operational-task",
                    kind=AgentEventKind.TOOL_RESULT,
                    sequence=started["next_sequence"] + 1,
                    parent_event_id="operational-call",
                    tool_name="remove-cache",
                    payload={"success": True, "output": {"removed": ".pytest_cache"}},
                )
            )
            verified = manager.verify_run(
                run_id="operational-run",
                evidence_id="operational-pytest-pass",
                source="test",
                verifier="pytest",
                success=True,
                score=1.0,
                reference="pytest://tests/test_workspace_experience.py",
            )
            candidate_id = verified["candidate_ids"][0]
            approved = manager.edit_and_approve(
                candidate_id,
                evidence_id="operator-edit-approve",
                reason="make operational runbook deterministic",
                title="Pytest cache permission recovery",
                content=(
                    "When pytest cache permission fails, remove .pytest_cache "
                    "and rerun pytest before changing product code."
                ),
            )
            edited_id = approved["experience_id"]
            python_packet = manager.packet(
                "pytest cache permission failure",
                domain="python",
                task_type="pytest-cache",
                tools=("remove-cache",),
                top_k=1,
                token_budget=180,
            )
        finally:
            manager.close()

        # Simulate process restart before client B reads over HTTP.
        restarted = WorkspaceExperienceManager.open(repo_a)
        selection_latencies_ms: list[float] = []
        try:
            restart_packet = restarted.packet(
                "pytest cache permission failure",
                domain="python",
                task_type="pytest-cache",
                tools=("remove-cache",),
                top_k=1,
                token_budget=180,
            )
            for _ in range(20):
                started_at = time.perf_counter()
                restarted.packet(
                    "pytest cache permission failure",
                    domain="python",
                    task_type="pytest-cache",
                    tools=("remove-cache",),
                    top_k=1,
                    token_budget=180,
                )
                selection_latencies_ms.append((time.perf_counter() - started_at) * 1000)
        finally:
            restarted.close()

        principals = {
            "token-a": {
                "identity": "agent-a",
                "role": "admin",
                "namespace_prefixes": [config_a.identity.namespace],
            },
            "token-b": {
                "identity": "agent-b",
                "role": "admin",
                "namespace_prefixes": [config_b.identity.namespace],
            },
        }
        checks: list[dict[str, Any]] = []
        http_latencies_ms: list[float] = []
        with _temporary_env({"WAVEMIND_API_PRINCIPALS": json.dumps(principals)}):
            mind = WaveMind(db_path=selected_temp / "api-memory.sqlite3")
            try:
                app = create_app(
                    mind=mind,
                    workspace_registry={"workspace-a": repo_a, "workspace-b": repo_b},
                    workspace_base_roots=[base],
                )
                headers_a = {"Authorization": "Bearer token-a"}
                with TestClient(app) as client:
                    for _ in range(5):
                        started_at = time.perf_counter()
                        http_packet = client.post(
                            "/workspace/packet",
                            headers=headers_a,
                            json={
                                "workspace_id": "workspace-a",
                                "query": "pytest cache permission failure",
                                "domain": "python",
                                "task_type": "pytest-cache",
                                "tools": ["remove-cache"],
                                "top_k": 1,
                                "token_budget": 180,
                            },
                        )
                        http_latencies_ms.append((time.perf_counter() - started_at) * 1000)
                    checks.append(
                        _check(
                            "registered-workspace-http-packet",
                            http_packet.status_code == 200
                            and http_packet.json().get("selected_citations")
                            == [f"experience:{edited_id}@v2"],
                            {
                                "status_code": http_packet.status_code,
                                "selected_citations": _json_or_empty(http_packet).get("selected_citations"),
                            },
                        )
                    )
                    checks.append(
                        _check(
                            "python-write-http-restart-replay",
                            python_packet["selected_citations"]
                            == restart_packet["selected_citations"]
                            == _json_or_empty(http_packet).get("selected_citations"),
                            {
                                "python": python_packet["selected_citations"],
                                "restart": restart_packet["selected_citations"],
                                "http": _json_or_empty(http_packet).get("selected_citations"),
                            },
                        )
                    )
                    cross = client.post(
                        "/workspace/packet",
                        headers=headers_a,
                        json={
                            "workspace_id": "workspace-b",
                            "query": "pytest cache permission failure",
                        },
                    )
                    checks.append(
                        _check(
                            "namespace-auth-denies-cross-workspace",
                            cross.status_code == 403,
                            {"status_code": cross.status_code},
                        )
                    )
                    absolute = client.post(
                        "/workspace/packet",
                        headers=headers_a,
                        json={
                            "workspace_id": str(repo_a),
                            "query": "pytest cache permission failure",
                        },
                    )
                    checks.append(
                        _check(
                            "arbitrary-workspace-id-denied",
                            absolute.status_code == 403,
                            {"status_code": absolute.status_code},
                        )
                    )
                    root_only = client.post(
                        "/workspace/packet",
                        headers=headers_a,
                        json={
                            "root": str(repo_a),
                            "query": "pytest cache permission failure",
                        },
                    )
                    checks.append(
                        _check(
                            "root-field-without-workspace-id-denied",
                            root_only.status_code == 422,
                            {"status_code": root_only.status_code},
                        )
                    )
            finally:
                mind.close()

            missing_mind = WaveMind(db_path=selected_temp / "missing-registry-memory.sqlite3")
            try:
                with TestClient(create_app(mind=missing_mind, workspace_base_roots=[base])) as client:
                    missing = client.post(
                        "/workspace/packet",
                        headers={"Authorization": "Bearer token-a"},
                        json={
                            "workspace_id": "workspace-a",
                            "query": "pytest cache permission failure",
                        },
                    )
                checks.append(
                    _check(
                        "missing-registry-denied",
                        missing.status_code == 403,
                        {"status_code": missing.status_code},
                    )
                )
            finally:
                missing_mind.close()

            outside = selected_temp / "outside"
            outside_repo = _make_repo(outside / "repo-outside", remote="https://github.com/example/outside.git")
            initialize_workspace(outside_repo, workspace_id="agent-a", tenant_id="tenant", user_id="user-a")
            escape_root = outside_repo
            symlink_created = False
            link = base / "linked-outside"
            try:
                link.symlink_to(outside_repo, target_is_directory=True)
                escape_root = link
                symlink_created = True
            except OSError:
                pass
            escape_mind = WaveMind(db_path=selected_temp / "escape-memory.sqlite3")
            try:
                with TestClient(
                    create_app(
                        mind=escape_mind,
                        workspace_registry={"escape": escape_root},
                        workspace_base_roots=[base],
                    )
                ) as client:
                    escape = client.post(
                        "/workspace/packet",
                        headers={"Authorization": "Bearer token-a"},
                        json={
                            "workspace_id": "escape",
                            "query": "pytest cache permission failure",
                        },
                    )
                checks.append(
                    _check(
                        "registry-escape-denied",
                        escape.status_code == 403,
                        {
                            "status_code": escape.status_code,
                            "symlink_created": symlink_created,
                        },
                    )
                )
            finally:
                escape_mind.close()

        checks.append(
            _check(
                "mandatory-events-captured-idempotently",
                call["inserted"] is True
                and result["inserted"] is True
                and duplicate["inserted"] is False,
                {
                    "tool_call_inserted": call["inserted"],
                    "tool_result_inserted": result["inserted"],
                    "duplicate_replayed": duplicate["inserted"] is False,
                },
            )
        )
        checks.append(
            _check(
                "secrets-redacted",
                call["event"]["payload"].get("api_key") == "[REDACTED]",
                {"api_key": call["event"]["payload"].get("api_key")},
            )
        )
        p95 = _percentile(selection_latencies_ms, 95)
        p99 = _percentile(selection_latencies_ms, 99)
        latency_passed = p95 <= 100.0 and p99 <= 250.0
        passed_checks = sum(1 for check in checks if check["passed"])
        admitted = passed_checks == len(checks) and latency_passed
        report = {
            "schema": SCHEMA,
            "status": "admitted" if admitted else "blocked",
            "admitted": admitted,
            "source_sha": source_sha,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": execution_environment(profile="workspace-operational-local"),
            "summary": {"checks_passed": passed_checks, "checks_total": len(checks)},
            "checks": checks,
            "metrics": {
                "workspace_namespace_leakage": 0 if _check_passed(checks, "namespace-auth-denies-cross-workspace") else 1,
                "mandatory_event_capture": 1.0 if _check_passed(checks, "mandatory-events-captured-idempotently") else 0.0,
                "cross_client_citation_state_parity": 1.0 if _check_passed(checks, "python-write-http-restart-replay") else 0.0,
                "packet_selection_p95_ms": p95,
                "packet_selection_p99_ms": p99,
                "packet_selection_latency_samples_ms": selection_latencies_ms,
                "http_replay_p95_ms": _percentile(http_latencies_ms, 95),
                "http_replay_latency_samples_ms": http_latencies_ms,
            },
            "evidence": {
                "workspace_namespace": config_a.identity.namespace,
                "experience_id": edited_id,
                "selected_citations": python_packet["selected_citations"],
            },
            "source_manifest": build_source_manifest(root, OPERATIONAL_SOURCE_FILES),
            "claim_boundary": (
                "Exact-current operational workspace proof for server-side registry, "
                "authenticated namespace enforcement, restart persistence, and HTTP replay. "
                "It is not the frozen real-work quality benchmark."
            ),
        }
        return attach_artifact_integrity(report)


def validate_workspace_operational_evidence(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    root = Path(project_root).resolve()
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCHEMA:
        errors.append("workspace operational schema is invalid")
    if payload.get("status") != "admitted" or payload.get("admitted") is not True:
        errors.append("workspace operational evidence is not admitted")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("workspace operational source SHA mismatch")
    checks = {
        str(check.get("id")): check
        for check in payload.get("checks") or []
        if isinstance(check, Mapping)
    }
    missing = sorted(REQUIRED_CHECKS - set(checks))
    if missing:
        errors.append(f"workspace operational checks missing: {', '.join(missing)}")
    failed = sorted(check_id for check_id, check in checks.items() if check.get("passed") is not True)
    if failed:
        errors.append(f"workspace operational checks failed: {', '.join(failed)}")
    metrics = payload.get("metrics") or {}
    if int(metrics.get("workspace_namespace_leakage", -1)) != 0:
        errors.append("workspace operational namespace leakage is not zero")
    if float(metrics.get("mandatory_event_capture", 0.0)) < 0.99:
        errors.append("workspace operational mandatory event capture is below threshold")
    if float(metrics.get("cross_client_citation_state_parity", 0.0)) != 1.0:
        errors.append("workspace operational cross-client parity is not 1.0")
    if float(metrics.get("packet_selection_p95_ms", 999999.0)) > 100.0:
        errors.append("workspace operational p95 latency exceeds threshold")
    if float(metrics.get("packet_selection_p99_ms", 999999.0)) > 250.0:
        errors.append("workspace operational p99 latency exceeds threshold")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("workspace operational source manifest is missing")
    else:
        errors.extend(validate_source_manifest(root, manifest, require_current_files=True))
    return errors


def write_artifact(
    *,
    output: str | Path,
    project_root: str | Path = PROJECT_ROOT,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = run_workspace_operational_evidence(project_root=project_root, temp_root=temp_root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _make_repo(path: Path, *, remote: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname = \"workspace-evidence\"\n", encoding="utf-8")
    (path / "README.md").write_text("# Workspace evidence\n", encoding="utf-8")
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "ci@example.com"], cwd=path)
    _run(["git", "config", "user.name", "WaveMind CI"], cwd=path)
    _run(["git", "add", "."], cwd=path)
    _run(["git", "commit", "-m", "Initial workspace evidence"], cwd=path)
    _run(["git", "remote", "add", "origin", remote], cwd=path)
    return path


def _run(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr[-400:]}")


def _check(check_id: str, passed: bool, details: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "details": dict(details)}


def _check_passed(checks: list[dict[str, Any]], check_id: str) -> bool:
    return any(check["id"] == check_id and check["passed"] is True for check in checks)


def _json_or_empty(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    return float(statistics.quantiles(ordered, n=100, method="inclusive")[percentile - 1])


@contextmanager
def _temporary_env(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _temporary_root(temp_root: str | Path | None) -> Iterator[Path]:
    if temp_root is None:
        with tempfile.TemporaryDirectory(prefix="wm-workspace-operational-") as tmp:
            yield Path(tmp)
        return
    path = Path(temp_root)
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wm-workspace-operational-", dir=str(path)) as tmp:
        yield Path(tmp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("benchmarks/workspace_experience_operational_results.json"))
    parser.add_argument("--temp-root", type=Path, default=None)
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args(argv)
    payload = write_artifact(output=args.output, temp_root=args.temp_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and not payload["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
