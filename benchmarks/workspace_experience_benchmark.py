from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.experience_runtime import AgentEventKind, VerificationSource
from wavemind.workspace_experience import (
    WorkspaceEvent,
    WorkspaceExperienceManager,
    initialize_workspace,
)


MANIFEST_SCHEMA = "wavemind.workspace_experience_manifest.v1"
RESULT_SCHEMA = "wavemind.workspace_experience_benchmark.v1"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "workspace_experience_manifest.json"


class WorkspaceBenchmarkError(ValueError):
    pass


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_manifest(payload, require_checkout=False)
    return payload


def validate_manifest(
    payload: dict[str, Any],
    *,
    require_checkout: bool = False,
    cache_root: str | Path | None = None,
) -> dict[str, Any]:
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise WorkspaceBenchmarkError("manifest schema mismatch")
    expected_hash = _sha256({key: value for key, value in payload.items() if key != "sha256"})
    if payload.get("sha256") != expected_hash:
        raise WorkspaceBenchmarkError("manifest checksum mismatch")
    repos = payload.get("repositories")
    procedures = payload.get("procedures")
    cases = payload.get("cases")
    if not isinstance(repos, dict) or len(repos) < 3:
        raise WorkspaceBenchmarkError("manifest requires at least three repositories")
    if len({repo.get("stack") for repo in repos.values()}) < 2:
        raise WorkspaceBenchmarkError("manifest requires at least two technology stacks")
    for repo_id, repo in repos.items():
        remote = str(repo.get("remote") or "")
        if not remote.startswith("https://github.com/"):
            raise WorkspaceBenchmarkError(f"{repo_id}: repository must be a GitHub primary source")
        if len(str(repo.get("commit") or "")) != 40:
            raise WorkspaceBenchmarkError(f"{repo_id}: pinned commit is required")
        if not repo.get("license"):
            raise WorkspaceBenchmarkError(f"{repo_id}: license is required")
    if not isinstance(procedures, list) or len(procedures) < 60:
        raise WorkspaceBenchmarkError("manifest requires at least 60 procedures")
    if not isinstance(cases, list):
        raise WorkspaceBenchmarkError("manifest cases must be a list")
    procedure_ids = set()
    source_keys = set()
    for procedure in procedures:
        procedure_id = str(procedure.get("id") or "")
        if not procedure_id or procedure_id in procedure_ids:
            raise WorkspaceBenchmarkError("procedure ids must be unique")
        procedure_ids.add(procedure_id)
        repo_id = str(procedure.get("repo") or "")
        if repo_id not in repos:
            raise WorkspaceBenchmarkError(f"{procedure_id}: unknown repo")
        source_path = str(procedure.get("source_path") or "")
        source_key = (repo_id, source_path)
        if source_key in source_keys:
            raise WorkspaceBenchmarkError(f"{procedure_id}: duplicate source path")
        source_keys.add(source_key)
        if not procedure.get("source_url", "").startswith("https://github.com/"):
            raise WorkspaceBenchmarkError(f"{procedure_id}: primary source URL required")
        if len(str(procedure.get("source_sha256") or "")) != 64:
            raise WorkspaceBenchmarkError(f"{procedure_id}: source sha256 required")
        if not procedure.get("expected_outcome"):
            raise WorkspaceBenchmarkError(f"{procedure_id}: expected outcome required")
    counts = {
        "positive": 0,
        "controls": 0,
        "dev": 0,
        "heldout": 0,
    }
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if not case_id:
            raise WorkspaceBenchmarkError("case_id is required")
        split = str(case.get("split") or "")
        if split not in {"dev", "heldout"}:
            raise WorkspaceBenchmarkError(f"{case_id}: split must be dev or heldout")
        counts[split] += 1
        procedure_id = str(case.get("procedure_id") or "")
        if procedure_id not in procedure_ids:
            raise WorkspaceBenchmarkError(f"{case_id}: unknown procedure id")
        query = str(case.get("query") or "")
        if procedure_id in query:
            raise WorkspaceBenchmarkError(f"{case_id}: procedure id leaks into query")
        if case.get("kind") == "positive":
            counts["positive"] += 1
        else:
            counts["controls"] += 1
        if case.get("expected_behavior") not in {"execute_verified_outcome", "abstain"}:
            raise WorkspaceBenchmarkError(f"{case_id}: invalid expected behavior")
    if counts["positive"] < 60:
        raise WorkspaceBenchmarkError("manifest requires at least 60 positive cases")
    if counts["controls"] < 20:
        raise WorkspaceBenchmarkError("manifest requires at least 20 controls")
    if not counts["dev"] or not counts["heldout"]:
        raise WorkspaceBenchmarkError("manifest requires dev and heldout splits")
    if require_checkout:
        selected_cache = Path(cache_root or tempfile.mkdtemp(prefix="wm-workspace-src-"))
        repo_roots = _ensure_checkouts(payload, selected_cache)
        for procedure in procedures:
            repo_root = repo_roots[str(procedure["repo"])]
            path = repo_root / str(procedure["source_path"])
            if not path.is_file():
                raise WorkspaceBenchmarkError(f"{procedure['id']}: source file missing")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != procedure["source_sha256"]:
                raise WorkspaceBenchmarkError(f"{procedure['id']}: source checksum mismatch")
            before = _execute_outcome(repo_root, procedure["wrong_outcome"])
            after = _execute_outcome(repo_root, procedure["expected_outcome"])
            if before["passed"]:
                raise WorkspaceBenchmarkError(f"{procedure['id']}: before outcome should fail")
            if not after["passed"]:
                raise WorkspaceBenchmarkError(f"{procedure['id']}: expected outcome should pass")
    return counts


def run_benchmark(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    split: str = "dev",
    cache_root: str | Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    if split not in {"dev", "heldout", "all"}:
        raise WorkspaceBenchmarkError("split must be dev, heldout, or all")
    selected_cache = Path(cache_root or tempfile.mkdtemp(prefix="wm-workspace-src-"))
    validate_manifest(manifest, require_checkout=True, cache_root=selected_cache)
    source_roots = _ensure_checkouts(manifest, selected_cache)
    workspace_tmp = tempfile.TemporaryDirectory(
        prefix="wm-workspace-run-",
        dir=str(selected_cache.parent),
    )
    repo_roots: dict[str, Path] = {}
    procedure_by_id = {item["id"]: item for item in manifest["procedures"]}
    cases = [
        case for case in manifest["cases"] if split == "all" or case["split"] == split
    ]
    started = time.perf_counter()
    run_token = hashlib.sha1(
        f"{manifest['sha256']}:{split}:{started}".encode("utf-8")
    ).hexdigest()[:10]
    managers: dict[str, WorkspaceExperienceManager] = {}
    raw_traces: dict[str, list[dict[str, Any]]] = {repo_id: [] for repo_id in manifest["repositories"]}
    citation_to_procedure: dict[str, dict[str, Any]] = {}
    capture_expected = 0
    capture_actual = 0
    try:
        repo_roots = _create_run_worktrees(
            manifest,
            source_roots=source_roots,
            run_root=Path(workspace_tmp.name),
        )
        for repo_id, repo in manifest["repositories"].items():
            config = initialize_workspace(
                repo_roots[repo_id],
                workspace_id=f"{repo_id}-workspace-benchmark-{run_token}",
                tenant_id="benchmark",
                user_id="local",
                force=True,
            )
            managers[repo_id] = WorkspaceExperienceManager(config)
        for procedure in manifest["procedures"]:
            manager = managers[str(procedure["repo"])]
            trained = _train_procedure(manager, procedure, manifest)
            raw_traces[str(procedure["repo"])].append(_raw_trace(procedure, trained))
            citation_to_procedure[trained["citation"]] = procedure
            capture_expected += trained["mandatory_events_expected"]
            capture_actual += trained["mandatory_events_captured"]
        _train_control_records(managers, manifest)
        rows = []
        latencies = {
            "no_experience": [],
            "static_raw_trace_retrieval": [],
            "wavemind_verified_workspace_experience": [],
        }
        for case in cases:
            procedure = procedure_by_id[str(case["procedure_id"])]
            repo_root = repo_roots[str(case["repo"])]
            expected = _expected_citation_for_procedure(procedure, citation_to_procedure)
            no_result = _no_experience(case)
            static_result = _static_raw_trace(case, raw_traces[str(case["repo"])], repo_root)
            wave_result = _wavemind_verified(
                case,
                managers[str(case["repo"])],
                repo_root,
                citation_to_procedure,
            )
            for name, result in (
                ("no_experience", no_result),
                ("static_raw_trace_retrieval", static_result),
                ("wavemind_verified_workspace_experience", wave_result),
            ):
                latencies[name].append(float(result["latency_ms"]))
            rows.append(
                {
                    "case": case,
                    "expected_citation": expected,
                    "no_experience": no_result,
                    "static_raw_trace_retrieval": static_result,
                    "wavemind_verified_workspace_experience": wave_result,
                }
            )
        parity = _cross_client_parity(managers, repo_roots, cases, citation_to_procedure)
        onboarding_seconds = _measure_onboarding(repo_roots[next(iter(repo_roots))])
        metrics = _compute_metrics(
            rows,
            latencies,
            capture_expected=capture_expected,
            capture_actual=capture_actual,
            cross_client_parity=parity,
            onboarding_seconds=onboarding_seconds,
        )
        payload = {
            "schema": RESULT_SCHEMA,
            "status": "passed" if _passes(metrics, manifest["thresholds"]) else "failed",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_sha": _git_sha(ROOT),
            "split": split,
            "duration_seconds": time.perf_counter() - started,
            "manifest": {
                "revision": manifest["revision"],
                "sha256": manifest["sha256"],
                "procedure_count": len(manifest["procedures"]),
                "case_count": len(manifest["cases"]),
            },
            "protocol": {
                "llm_used": False,
                "gpu_used": False,
                "task_success_definition": (
                    "positive cases require selected procedure plus successful executable outcome; "
                    "control cases require abstention"
                ),
                "claim_boundary": manifest["claim_boundary"],
            },
            "metrics": metrics,
            "rows": rows,
        }
        validate_benchmark_results(payload, manifest)
        return payload
    finally:
        for manager in managers.values():
            manager.close()
        _remove_run_worktrees(source_roots, repo_roots)
        workspace_tmp.cleanup()


def validate_benchmark_results(payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    if payload.get("schema") != RESULT_SCHEMA:
        raise WorkspaceBenchmarkError("result schema mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise WorkspaceBenchmarkError("result rows required")
    for row in rows:
        case = row["case"]
        for mode in ("no_experience", "static_raw_trace_retrieval", "wavemind_verified_workspace_experience"):
            result = row[mode]
            if case["expected_behavior"] == "execute_verified_outcome":
                if result.get("task_success") and not result.get("command", {}).get("passed"):
                    raise WorkspaceBenchmarkError("citation-only success is forbidden")
            if case["expected_behavior"] == "abstain" and result.get("task_success"):
                if result.get("selected_citations"):
                    raise WorkspaceBenchmarkError("control success cannot include a citation")
    recomputed = _compute_metrics(
        rows,
        {
            mode: [float(row[mode]["latency_ms"]) for row in rows]
            for mode in ("no_experience", "static_raw_trace_retrieval", "wavemind_verified_workspace_experience")
        },
        capture_expected=int(payload["metrics"]["admission"]["capture_expected"]),
        capture_actual=int(payload["metrics"]["admission"]["capture_actual"]),
        cross_client_parity=float(payload["metrics"]["admission"]["cross_client_citation_state_parity"]),
        onboarding_seconds=float(payload["metrics"]["admission"]["clean_onboarding_seconds"]),
    )
    if _rounded(recomputed["admission"]) != _rounded(payload["metrics"]["admission"]):
        raise WorkspaceBenchmarkError("admission metrics do not match row data")
    if payload["manifest"]["sha256"] != manifest["sha256"]:
        raise WorkspaceBenchmarkError("result manifest checksum mismatch")


def write_artifacts(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    split: str = "dev",
    output: str | Path = "benchmarks/workspace_experience_benchmark_results.json",
    markdown_output: str | Path = "benchmarks/WORKSPACE_EXPERIENCE_BENCHMARK.md",
    cache_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = run_benchmark(manifest_path=manifest_path, split=split, cache_root=cache_root)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(markdown_output).write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _ensure_checkouts(manifest: dict[str, Any], cache_root: Path) -> dict[str, Path]:
    cache_root.mkdir(parents=True, exist_ok=True)
    roots = {}
    for repo_id, repo in manifest["repositories"].items():
        root = cache_root / repo_id
        if not (root / ".git").exists():
            subprocess.run(
                ["git", "clone", "--filter=blob:none", str(repo["remote"]), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["git", "-C", str(root), "fetch", "origin", str(repo["commit"])],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "checkout", "--detach", str(repo["commit"])],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual != repo["commit"]:
            raise WorkspaceBenchmarkError(f"{repo_id}: checkout commit mismatch")
        roots[repo_id] = root
    return roots


def _create_run_worktrees(
    manifest: dict[str, Any],
    *,
    source_roots: dict[str, Path],
    run_root: Path,
) -> dict[str, Path]:
    run_root.mkdir(parents=True, exist_ok=True)
    roots: dict[str, Path] = {}
    for repo_id, repo in manifest["repositories"].items():
        source_root = source_roots[repo_id]
        subprocess.run(
            ["git", "-C", str(source_root), "worktree", "prune"],
            check=True,
            capture_output=True,
            text=True,
        )
        root = run_root / repo_id
        subprocess.run(
            [
                "git",
                "-C",
                str(source_root),
                "worktree",
                "add",
                "--detach",
                str(root),
                str(repo["commit"]),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual != repo["commit"]:
            raise WorkspaceBenchmarkError(f"{repo_id}: run worktree commit mismatch")
        roots[repo_id] = root
    return roots


def _remove_run_worktrees(source_roots: dict[str, Path], repo_roots: dict[str, Path]) -> None:
    for repo_id, root in repo_roots.items():
        source_root = source_roots[repo_id]
        if root.exists():
            subprocess.run(
                ["git", "-C", str(source_root), "worktree", "remove", "--force", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["git", "-C", str(source_root), "worktree", "prune"],
            check=False,
            capture_output=True,
            text=True,
        )


def _train_procedure(
    manager: WorkspaceExperienceManager,
    procedure: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    repo = manifest["repositories"][str(procedure["repo"])]
    prefix = _sha256(manager.identity.namespace)[:10]
    run_id = f"workspace-bench-{prefix}-{procedure['id']}"
    started = manager.start_run(
        query=str(procedure["query"]),
        objective=f"verify {procedure['source_path']} before workspace edit",
        domain=str(repo["stack"]),
        task_type=str(procedure["task_type"]),
        run_id=run_id,
        tools=tuple(str(item) for item in procedure["tools"]),
        metadata={
            "procedure_id": procedure["id"],
            "source_url": procedure["source_url"],
            "source_sha256": procedure["source_sha256"],
        },
    )
    generic_tool = str(procedure["tools"][0])
    source_tool = f"{generic_tool}:{procedure['source_path']}"
    call = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-call",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_CALL,
            sequence=started["next_sequence"],
            tool_name=generic_tool,
            payload={"input": {"source_path": procedure["source_path"]}},
        )
    )
    source_call = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-source-call",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_CALL,
            sequence=started["next_sequence"] + 1,
            parent_event_id=call["event"]["id"],
            tool_name=source_tool,
            payload={"input": {"outcome": procedure["expected_outcome"]}},
        )
    )
    result = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-result",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_RESULT,
            sequence=started["next_sequence"] + 2,
            parent_event_id=source_call["event"]["id"],
            tool_name=source_tool,
            payload={
                "success": True,
                "output": {
                    "outcome": procedure["expected_outcome"],
                    "source_url": procedure["source_url"],
                },
            },
        )
    )
    verified = manager.verify_run(
        run_id=run_id,
        evidence_id=f"{procedure['id']}-source-check",
        source=VerificationSource.TOOL,
        verifier="workspace-source-check",
        success=True,
        score=1.0,
        reference=str(procedure["source_url"]),
        metadata={"procedure_id": procedure["id"]},
    )
    candidate_id = verified["candidate_ids"][0]
    edited = manager.edit_and_approve(
        candidate_id,
        evidence_id=f"{procedure['id']}-operator-freeze",
        title=f"Verify {procedure['source_path']} before editing",
        content=(
            f"Primary source: {procedure['source_url']}\n"
            f"Repo: {repo['name']} at {repo['commit']}\n"
            f"Task type: {procedure['task_type']}\n"
            f"Source path: {procedure['source_path']}\n"
            f"Run outcome `{procedure['expected_outcome']['kind']}` for "
            f"`{procedure['expected_outcome']['path']}` with SHA-256 "
            f"{procedure['expected_outcome']['sha256']} before editing."
        ),
        reason="freeze real-work benchmark procedure",
        metadata={
            "procedure_id": procedure["id"],
            "expected_outcome": procedure["expected_outcome"],
            "source_url": procedure["source_url"],
        },
    )
    events = manager.runtime.events(namespace=manager.identity.namespace, run_id=run_id)
    mandatory_ids = {call["event"]["id"], source_call["event"]["id"], result["event"]["id"]}
    captured_ids = {event.id for event in events}
    return {
        "citation": f"experience:{edited['experience_id']}@v{edited['experience']['version']}",
        "procedure_id": procedure["id"],
        "call_inserted": bool(call["inserted"]),
        "source_call_inserted": bool(source_call["inserted"]),
        "result_inserted": bool(result["inserted"]),
        "mandatory_events_expected": len(mandatory_ids),
        "mandatory_events_captured": len(mandatory_ids & captured_ids),
    }


def _train_control_records(managers: dict[str, WorkspaceExperienceManager], manifest: dict[str, Any]) -> None:
    for repo_id, manager in managers.items():
        prefix = _sha256(manager.identity.namespace)[:10]
        started = manager.start_run(
            query="unverified workspace rumor",
            objective="capture unverified control",
            domain=str(manifest["repositories"][repo_id]["stack"]),
            task_type="control:unverified",
            run_id=f"control-unverified-{prefix}-{repo_id}",
            tools=("control",),
        )
        manager.capture_event(
            WorkspaceEvent(
                id=f"control-unverified-{prefix}-{repo_id}-call",
                run_id=started["run_id"],
                session_id=started["session_id"],
                task_id=started["task_id"],
                kind=AgentEventKind.TOOL_CALL,
                sequence=started["next_sequence"],
                tool_name="control",
                payload={"input": "agent-generated claim without independent evidence"},
            )
        )


def _raw_trace(procedure: dict[str, Any], trained: dict[str, Any]) -> dict[str, Any]:
    return {
        "procedure_id": procedure["id"],
        "citation": trained["citation"],
        "outcome": procedure["expected_outcome"],
        "context": (
            f"RAW_TRACE procedure={procedure['id']} source={procedure['source_path']} "
            f"url={procedure['source_url']} stdout stderr retries noisy history "
            f"SUCCESS_OUTCOME={json.dumps(procedure['expected_outcome'], sort_keys=True)}"
        ),
    }


def _no_experience(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    abstain = True
    return {
        "selected_citations": [],
        "abstain": abstain,
        "context_chars": 0,
        "latency_ms": (time.perf_counter() - started) * 1000.0,
        "command": {"passed": False, "returncode": None},
        "task_success": case["expected_behavior"] == "abstain",
    }


def _static_raw_trace(
    case: dict[str, Any],
    traces: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    ranked = sorted(traces, key=lambda item: _overlap(case["query"], item["context"]), reverse=True)
    selected = ranked[0] if ranked and _overlap(case["query"], ranked[0]["context"]) > 0 else None
    selection_latency_ms = (time.perf_counter() - started) * 1000.0
    outcome_started = time.perf_counter()
    command = _execute_outcome(repo_root, selected["outcome"]) if selected else {"passed": False, "returncode": None}
    outcome_latency_ms = (time.perf_counter() - outcome_started) * 1000.0
    citations = [selected["citation"]] if selected else []
    selected_matches = (
        selected is not None and selected["procedure_id"] == case["procedure_id"]
    )
    task_success = (
        command["passed"] and selected_matches
        if case["expected_behavior"] == "execute_verified_outcome"
        else not citations
    )
    return {
        "selected_citations": citations,
        "abstain": not citations,
        "context_chars": sum(len(item["context"]) for item in ranked[:3]),
        "latency_ms": selection_latency_ms,
        "outcome_latency_ms": outcome_latency_ms,
        "command": command,
        "task_success": bool(task_success),
    }


def _wavemind_verified(
    case: dict[str, Any],
    manager: WorkspaceExperienceManager,
    repo_root: Path,
    citation_to_procedure: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    packet = manager.packet(
        str(case["query"]),
        domain=_stack_for_repo(case["repo"], citation_to_procedure),
        task_type=str(case["task_type"]),
        tools=tuple(str(item) for item in case["tools"]),
        token_budget=180,
        top_k=1,
    )
    selection_latency_ms = (time.perf_counter() - started) * 1000.0
    citations = list(packet["selected_citations"])
    selected = citation_to_procedure.get(citations[0]) if citations else None
    outcome_started = time.perf_counter()
    command = _execute_outcome(repo_root, selected["expected_outcome"]) if selected else {"passed": False, "returncode": None}
    outcome_latency_ms = (time.perf_counter() - outcome_started) * 1000.0
    selected_matches = selected is not None and selected["id"] == case["procedure_id"]
    task_success = (
        command["passed"] and selected_matches
        if case["expected_behavior"] == "execute_verified_outcome"
        else not citations
    )
    return {
        "selected_citations": citations,
        "abstain": packet["abstain"],
        "context_chars": _packet_context_chars(packet),
        "latency_ms": selection_latency_ms,
        "outcome_latency_ms": outcome_latency_ms,
        "command": command,
        "task_success": bool(task_success),
        "excluded": packet["excluded"],
    }


def _packet_context_chars(packet: dict[str, Any]) -> int:
    if packet.get("abstain"):
        return len(f"ABSTAIN: {packet.get('reason') or 'no applicable workspace experience'}")
    payload = packet.get("packet") or {}
    items = list(payload.get("items") or [])
    lines = []
    for item in items[:1]:
        lines.append(
            " ".join(
                str(part)
                for part in (
                    item.get("citation"),
                    item.get("title"),
                    item.get("excerpt"),
                )
                if part
            )
        )
    return len("\n".join(lines))


def _cross_client_parity(
    managers: dict[str, WorkspaceExperienceManager],
    repo_roots: dict[str, Path],
    cases: list[dict[str, Any]],
    citation_to_procedure: dict[str, dict[str, Any]],
) -> float:
    checked = 0
    matched = 0
    for case in cases:
        if case["expected_behavior"] != "execute_verified_outcome":
            continue
        before = _wavemind_verified(
            case,
            managers[str(case["repo"])],
            repo_roots[str(case["repo"])],
            citation_to_procedure,
        )
        reopened = WorkspaceExperienceManager.open(repo_roots[str(case["repo"])])
        try:
            after = _wavemind_verified(case, reopened, repo_roots[str(case["repo"])], citation_to_procedure)
        finally:
            reopened.close()
        checked += 1
        if before["selected_citations"] == after["selected_citations"]:
            matched += 1
    return matched / max(1, checked)


def _measure_onboarding(repo_root: Path) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind.cli",
            "workspace",
            "--root",
            str(repo_root),
            "demo",
            "--workspace-id",
            "benchmark-onboarding",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise WorkspaceBenchmarkError(f"onboarding failed: {completed.stderr[-500:]}")
    payload = json.loads(completed.stdout)
    if not payload["packet"]["selected_citations"]:
        raise WorkspaceBenchmarkError("onboarding did not produce a cited packet")
    return time.perf_counter() - started


def _execute_outcome(repo_root: Path, outcome: dict[str, Any]) -> dict[str, Any]:
    if outcome.get("kind") != "source_sha256_check":
        raise WorkspaceBenchmarkError("unsupported outcome kind")
    code = (
        "import hashlib,pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);"
        "expected=sys.argv[2];"
        "actual=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else '';"
        "sys.exit(0 if actual==expected else 7)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(outcome["path"]), str(outcome["sha256"])],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "kind": outcome["kind"],
        "path": outcome["path"],
    }


def _compute_metrics(
    rows: list[dict[str, Any]],
    latencies: dict[str, list[float]],
    *,
    capture_expected: int,
    capture_actual: int,
    cross_client_parity: float,
    onboarding_seconds: float,
) -> dict[str, Any]:
    by_mode = {
        mode: _mode_metrics(rows, mode)
        for mode in ("no_experience", "static_raw_trace_retrieval", "wavemind_verified_workspace_experience")
    }
    static = by_mode["static_raw_trace_retrieval"]
    wave = by_mode["wavemind_verified_workspace_experience"]
    admission = {
        "task_success_lift_pp": (wave["task_success_rate"] - static["task_success_rate"]) * 100.0,
        "repeated_known_error_reduction": _safe_reduction(static["known_error_rate"], wave["known_error_rate"]),
        "context_reduction": _safe_reduction(static["avg_context_chars"], wave["avg_context_chars"]),
        "false_procedure_injection": wave["false_procedure_injection_rate"],
        "unverified_injection": wave["unverified_injection"],
        "workspace_namespace_leakage": wave["workspace_namespace_leakage"],
        "mandatory_event_capture": capture_actual / max(1, capture_expected),
        "capture_actual": capture_actual,
        "capture_expected": capture_expected,
        "cross_client_citation_state_parity": cross_client_parity,
        "packet_selection_p95_ms": _percentile(latencies["wavemind_verified_workspace_experience"], 95),
        "packet_selection_p99_ms": _percentile(latencies["wavemind_verified_workspace_experience"], 99),
        "clean_onboarding_seconds": onboarding_seconds,
    }
    return {"modes": by_mode, "admission": admission}


def _mode_metrics(rows: list[dict[str, Any]], mode: str) -> dict[str, float]:
    successes = sum(1 for row in rows if row[mode]["task_success"])
    controls = [row for row in rows if row["case"]["expected_behavior"] == "abstain"]
    positives = [row for row in rows if row["case"]["expected_behavior"] == "execute_verified_outcome"]
    false_injections = sum(1 for row in controls if row[mode]["selected_citations"])
    unverified_injections = sum(
        1
        for row in controls
        if row["case"]["kind"] == "unverified" and row[mode]["selected_citations"]
    )
    workspace_leaks = sum(
        1
        for row in controls
        if row["case"]["kind"] == "wrong_workspace" and row[mode]["selected_citations"]
    )
    context_values = [float(row[mode]["context_chars"]) for row in rows]
    return {
        "task_success_rate": successes / max(1, len(rows)),
        "positive_success_rate": sum(1 for row in positives if row[mode]["task_success"]) / max(1, len(positives)),
        "control_success_rate": sum(1 for row in controls if row[mode]["task_success"]) / max(1, len(controls)),
        "known_error_rate": 1.0 - (successes / max(1, len(rows))),
        "false_procedure_injection_rate": false_injections / max(1, len(controls)),
        "unverified_injection": unverified_injections,
        "workspace_namespace_leakage": workspace_leaks,
        "avg_context_chars": statistics.fmean(context_values) if context_values else 0.0,
    }


def _passes(metrics: dict[str, Any], thresholds: dict[str, Any]) -> bool:
    admission = metrics["admission"]
    return (
        admission["task_success_lift_pp"] >= thresholds["task_success_lift_pp_min"]
        and admission["repeated_known_error_reduction"] >= thresholds["repeated_known_error_reduction_min"]
        and admission["context_reduction"] >= thresholds["context_reduction_min"]
        and admission["false_procedure_injection"] <= thresholds["false_procedure_injection_max"]
        and admission["unverified_injection"] == thresholds["unverified_injection"]
        and admission["workspace_namespace_leakage"] == thresholds["workspace_namespace_leakage"]
        and admission["mandatory_event_capture"] >= thresholds["mandatory_event_capture_min"]
        and admission["cross_client_citation_state_parity"] == thresholds["cross_client_citation_state_parity"]
        and admission["packet_selection_p95_ms"] <= thresholds["packet_selection_p95_ms_max"]
        and admission["packet_selection_p99_ms"] <= thresholds["packet_selection_p99_ms_max"]
        and admission["clean_onboarding_seconds"] <= thresholds["clean_onboarding_seconds_max"]
    )


def _expected_citation_for_procedure(
    procedure: dict[str, Any],
    citation_to_procedure: dict[str, dict[str, Any]],
) -> str | None:
    for citation, selected in citation_to_procedure.items():
        if selected["id"] == procedure["id"]:
            return citation
    return None


def _stack_for_repo(repo_id: str, citation_to_procedure: dict[str, dict[str, Any]]) -> str:
    for procedure in citation_to_procedure.values():
        if procedure["repo"] == repo_id:
            return str(procedure["stack"])
    return "workspace"


def _overlap(query: str, context: str) -> int:
    return len(_tokens(query) & _tokens(context))


def _tokens(text: str) -> set[str]:
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(token) > 2}


def _safe_reduction(before: float, after: float) -> float:
    if before <= 0:
        return 1.0 if after <= 0 else 0.0
    return (before - after) / before


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100.0) * (len(ordered) - 1)))
    return float(ordered[index])


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _git_sha(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _rounded(value: dict[str, Any]) -> dict[str, Any]:
    rounded = {}
    for key, item in value.items():
        rounded[key] = round(float(item), 6) if isinstance(item, float) else item
    return rounded


def _render_markdown(payload: dict[str, Any]) -> str:
    admission = payload["metrics"]["admission"]
    lines = [
        "# Workspace Experience Real-Work Benchmark",
        "",
        f"- Status: `{payload['status']}`",
        f"- Split: `{payload['split']}`",
        f"- Manifest: `{payload['manifest']['revision']}`",
        f"- Manifest SHA-256: `{payload['manifest']['sha256']}`",
        f"- Claim boundary: {payload['protocol']['claim_boundary']}",
        "",
        "| Metric | Value | Gate |",
        "|---|---:|---:|",
        f"| Task success lift | {admission['task_success_lift_pp']:.2f} pp | >= 15 pp |",
        f"| Known-error reduction | {admission['repeated_known_error_reduction']:.3f} | >= 0.50 |",
        f"| Context reduction | {admission['context_reduction']:.3f} | >= 0.30 |",
        f"| False procedure injection | {admission['false_procedure_injection']:.3f} | <= 0.01 |",
        f"| Mandatory event capture | {admission['mandatory_event_capture']:.3f} | >= 0.99 |",
        f"| Cross-client parity | {admission['cross_client_citation_state_parity']:.3f} | 1.00 |",
        f"| Packet p95 | {admission['packet_selection_p95_ms']:.2f} ms | <= 100 ms |",
        f"| Packet p99 | {admission['packet_selection_p99_ms']:.2f} ms | <= 250 ms |",
        f"| Clean onboarding | {admission['clean_onboarding_seconds']:.2f} s | <= 300 s |",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", default="benchmarks/workspace_experience_benchmark_results.json")
    parser.add_argument("--markdown-output", default="benchmarks/WORKSPACE_EXPERIENCE_BENCHMARK.md")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    if args.validate_only:
        counts = validate_manifest(
            manifest,
            require_checkout=True,
            cache_root=args.cache_root,
        )
        print(json.dumps({"status": "valid", "counts": counts}, indent=2))
        return 0
    payload = write_artifacts(
        manifest_path=args.manifest,
        split=args.split,
        output=args.output,
        markdown_output=args.markdown_output,
        cache_root=args.cache_root,
    )
    print(json.dumps({"status": payload["status"], "metrics": payload["metrics"]["admission"]}, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
