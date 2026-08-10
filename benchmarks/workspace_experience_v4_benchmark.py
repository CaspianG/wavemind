from __future__ import annotations

import argparse
import os
import hashlib
import json
import shutil
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

from wavemind.experience import ExperienceKind, ExperienceStatus
from wavemind.experience_runtime import AgentEventKind, VerificationSource
from wavemind.workspace_experience import (
    WorkspaceEvent,
    WorkspaceExperienceManager,
    initialize_workspace,
)

MANIFEST_SCHEMA = "wavemind.workspace_experience_v4_manifest.v1"
RESULT_SCHEMA = "wavemind.workspace_experience_v4_benchmark.v1"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "workspace_experience_v4_manifest.json"
PROTOCOL_STATUS = "historical_invalid_not_admission_evidence"
PROTOCOL_INVALID_REASONS = [
    "clean_onboarding_seconds was hardcoded instead of measured from a clean subprocess flow",
    "static baseline can collapse to zero positive success and is not the strongest static comparator",
    "positive task success accepts outcome-kind matches without exact case/procedure validation",
    "cross-client parity reopens the same Python manager instead of cross-surface client A to restart to client B replay",
]
FORBIDDEN_TASK_OUTCOMES = {"source_sha256_check", "file_hash_check", "checksum_only"}
SUPPORTED_OUTCOMES = {
    "python_py_compile",
    "python_ast_parse",
    "python_import_module",
    "python_toml_parse",
    "python_configparser_parse",
    "yaml_parse",
    "json_parse",
    "xml_parse",
    "node_syntax_check",
}


class WorkspaceV4BenchmarkError(ValueError):
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
) -> dict[str, int]:
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise WorkspaceV4BenchmarkError("manifest schema mismatch")
    expected_hash = _sha256({key: value for key, value in payload.items() if key != "sha256"})
    if payload.get("sha256") != expected_hash:
        raise WorkspaceV4BenchmarkError("manifest checksum mismatch")

    repos = payload.get("repositories")
    cases = payload.get("cases")
    if not isinstance(repos, dict) or len(repos) < 3:
        raise WorkspaceV4BenchmarkError("manifest requires at least three repositories")
    if len({repo.get("stack") for repo in repos.values()}) < 2:
        raise WorkspaceV4BenchmarkError("manifest requires at least two technology stacks")
    for repo_id, repo in repos.items():
        remote = str(repo.get("remote") or "")
        if not remote.startswith("https://github.com/"):
            raise WorkspaceV4BenchmarkError(f"{repo_id}: repository must be a GitHub primary source")
        if len(str(repo.get("commit") or "")) != 40:
            raise WorkspaceV4BenchmarkError(f"{repo_id}: pinned commit is required")
        if not repo.get("license"):
            raise WorkspaceV4BenchmarkError(f"{repo_id}: license is required")

    if not isinstance(cases, list):
        raise WorkspaceV4BenchmarkError("manifest cases must be a list")
    case_ids: set[str] = set()
    source_keys: set[tuple[str, str]] = set()
    semantic_keys: set[str] = set()
    semantic_families: set[str] = set()
    fingerprints: set[tuple[str, str, str]] = set()
    source_family_splits: dict[str, set[str]] = {}
    counts = {"positive": 0, "controls": 0, "dev": 0, "heldout": 0}
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in case_ids:
            raise WorkspaceV4BenchmarkError("case ids must be unique")
        case_ids.add(case_id)
        split = str(case.get("split") or "")
        if split not in {"dev", "heldout"}:
            raise WorkspaceV4BenchmarkError(f"{case_id}: split must be dev or heldout")
        counts[split] += 1
        repo_id = str(case.get("repo") or "")
        if repo_id not in repos:
            raise WorkspaceV4BenchmarkError(f"{case_id}: unknown repo")
        kind = str(case.get("kind") or "")
        if kind == "positive":
            counts["positive"] += 1
            _validate_positive_case(
                case_id,
                case,
                repo_id,
                source_keys,
                semantic_keys,
                semantic_families,
                fingerprints,
                source_family_splits,
                split,
            )
        else:
            counts["controls"] += 1
            _validate_control_case(case_id, case)

    if counts["positive"] < 60:
        raise WorkspaceV4BenchmarkError("manifest requires at least 60 positive real-work cases")
    if counts["controls"] < 20:
        raise WorkspaceV4BenchmarkError("manifest requires at least 20 controls")
    if not counts["dev"] or not counts["heldout"]:
        raise WorkspaceV4BenchmarkError("manifest requires dev and heldout splits")
    overlapping_families = {
        family for family, splits in source_family_splits.items() if len(splits) > 1
    }
    if overlapping_families:
        raise WorkspaceV4BenchmarkError(
            "semantic source families cannot overlap dev and heldout: "
            + ", ".join(sorted(overlapping_families)[:5])
        )

    if require_checkout:
        selected_cache = Path(cache_root or tempfile.mkdtemp(prefix="wm-workspace-v4-src-"))
        repo_roots = ensure_checkouts(payload, selected_cache)
        for case in (case for case in cases if case.get("kind") == "positive"):
            repo_root = repo_roots[str(case["repo"])]
            source_path = str(case["source_path"])
            source_file = repo_root / source_path
            if not source_file.is_file():
                raise WorkspaceV4BenchmarkError(f"{case['case_id']}: source file missing")
            actual = hashlib.sha256(source_file.read_bytes()).hexdigest()
            if actual != case["source_sha256"]:
                raise WorkspaceV4BenchmarkError(f"{case['case_id']}: source checksum mismatch")
            result = execute_outcome(repo_root, case["expected_outcome"])
            if not result["passed"]:
                raise WorkspaceV4BenchmarkError(f"{case['case_id']}: expected outcome failed")
            mutated = execute_outcome(repo_root, case["expected_outcome"], mutate=True)
            if mutated["passed"]:
                raise WorkspaceV4BenchmarkError(
                    f"{case['case_id']}: mutation control did not fail"
                )
    return counts


def ensure_checkouts(manifest: dict[str, Any], cache_root: Path) -> dict[str, Path]:
    cache_root.mkdir(parents=True, exist_ok=True)
    roots: dict[str, Path] = {}
    for repo_id, repo in manifest["repositories"].items():
        root = cache_root / repo_id
        if not (root / ".git").exists():
            subprocess.run(
                ["git", "clone", "--filter=blob:none", str(repo["remote"]), str(root)],
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
            raise WorkspaceV4BenchmarkError(f"{repo_id}: checkout commit mismatch")
        roots[repo_id] = root
    return roots


def run_benchmark(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    split: str = "dev",
    cache_root: str | Path | None = None,
    allow_heldout: bool = False,
    allow_invalid_protocol: bool = False,
) -> dict[str, Any]:
    if split not in {"dev", "heldout"}:
        raise WorkspaceV4BenchmarkError("split must be dev or heldout")
    if not allow_invalid_protocol:
        raise WorkspaceV4BenchmarkError(
            "v4 protocol is historical_invalid_not_admission_evidence; "
            "use v5 for admission or pass allow_invalid_protocol for diagnostics"
        )
    if split == "heldout" and not allow_heldout:
        raise WorkspaceV4BenchmarkError(
            "v4 held-out requires explicit allow_heldout after committed protocol freeze"
        )
    manifest = load_manifest(manifest_path)
    selected_cache = Path(cache_root or tempfile.mkdtemp(prefix="wm-workspace-v4-src-"))
    validate_manifest(manifest, require_checkout=True, cache_root=selected_cache)
    repo_roots = ensure_checkouts(manifest, selected_cache)
    started = time.perf_counter()
    run_token = hashlib.sha1(
        f"{manifest['sha256']}:{split}:{started}".encode("utf-8")
    ).hexdigest()[:10]
    workspace_tmp = tempfile.TemporaryDirectory(
        prefix="wm-workspace-v4-run-",
        dir=str(selected_cache.parent),
    )
    managers: dict[str, WorkspaceExperienceManager] = {}
    raw_traces: dict[str, list[dict[str, Any]]] = {
        repo_id: [] for repo_id in manifest["repositories"]
    }
    citation_to_case: dict[str, dict[str, Any]] = {}
    capture_expected = 0
    capture_actual = 0
    try:
        for repo_id, repo in manifest["repositories"].items():
            workspace_root = Path(workspace_tmp.name) / repo_id
            _create_minimal_workspace(workspace_root, repo)
            config = initialize_workspace(
                workspace_root,
                workspace_id=f"{repo_id}-workspace-v4-{run_token}",
                tenant_id="benchmark",
                user_id="local",
                force=True,
            )
            managers[repo_id] = WorkspaceExperienceManager(config)
        eval_cases = [
            case for case in manifest["cases"] if case["split"] == split
        ]
        for case in eval_cases:
            manager = managers[str(case["repo"])]
            trained = (
                _train_case(manager, case, manifest)
                if case["kind"] == "positive"
                else _capture_control_case(manager, case, manifest)
            )
            raw_traces[str(case["repo"])].append(_raw_trace(case, trained))
            if case["kind"] == "positive":
                citation_to_case[trained["citation"]] = case
            capture_expected += trained["mandatory_events_expected"]
            capture_actual += trained["mandatory_events_captured"]
        rows: list[dict[str, Any]] = []
        latencies = {
            "no_experience": [],
            "static_raw_trace_retrieval": [],
            "wavemind_verified_workspace_experience": [],
        }
        for case in eval_cases:
            repo_root = repo_roots[str(case["repo"])]
            no_result = _no_experience(case)
            static_result = _static_raw_trace(case, raw_traces[str(case["repo"])], repo_root)
            wave_result = _wavemind_verified(
                case,
                managers[str(case["repo"])],
                repo_root,
                citation_to_case,
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
                    "no_experience": no_result,
                    "static_raw_trace_retrieval": static_result,
                    "wavemind_verified_workspace_experience": wave_result,
                }
            )
        parity = _cross_client_parity(managers, repo_roots, eval_cases, citation_to_case)
        metrics = _compute_metrics(
            rows,
            latencies,
            capture_expected=capture_expected,
            capture_actual=capture_actual,
            cross_client_parity=parity,
            onboarding_seconds=0.0,
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
                "case_count": len(manifest["cases"]),
            },
            "protocol": {
                "status": PROTOCOL_STATUS,
                "invalid_reasons": PROTOCOL_INVALID_REASONS,
                "llm_used": False,
                "gpu_used": False,
                "task_success_definition": (
                    "positive cases require a selected verified procedure whose real "
                    "outcome kind matches the case, plus a passing command on the "
                    "case source path; controls require abstention"
                ),
                "claim_boundary": manifest["claim_boundary"],
            },
            "metrics": metrics,
            "rows": rows,
        }
        validate_benchmark_results(payload, manifest, allow_heldout=allow_heldout)
        return payload
    finally:
        for manager in managers.values():
            manager.close()
        workspace_tmp.cleanup()


def write_artifacts(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    split: str = "dev",
    output: str | Path = "benchmarks/workspace_experience_v4_dev_results.json",
    cache_root: str | Path | None = None,
    allow_heldout: bool = False,
    allow_invalid_protocol: bool = False,
) -> dict[str, Any]:
    payload = run_benchmark(
        manifest_path=manifest_path,
        split=split,
        cache_root=cache_root,
        allow_heldout=allow_heldout,
        allow_invalid_protocol=allow_invalid_protocol,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def execute_outcome(
    repo_root: Path,
    outcome: dict[str, Any],
    *,
    mutate: bool = False,
) -> dict[str, Any]:
    kind = str(outcome.get("kind") or "")
    if kind in FORBIDDEN_TASK_OUTCOMES:
        raise WorkspaceV4BenchmarkError(f"{kind} cannot be task-success evidence")
    if kind not in SUPPORTED_OUTCOMES:
        raise WorkspaceV4BenchmarkError(f"unsupported outcome kind: {kind}")
    relative = Path(str(outcome.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise WorkspaceV4BenchmarkError("outcome path must stay inside repository")
    target = repo_root / relative
    if not target.is_file():
        raise WorkspaceV4BenchmarkError(f"outcome path missing: {relative}")
    run_root = repo_root
    cleanup: tempfile.TemporaryDirectory[str] | None = None
    try:
        if mutate:
            cleanup = tempfile.TemporaryDirectory(prefix="wm-v4-mutated-")
            run_root = Path(cleanup.name) / "repo"
            shutil.copytree(
                repo_root,
                run_root,
                ignore=shutil.ignore_patterns(".git", ".wavemind", "__pycache__"),
            )
            _mutate_file(run_root / relative, kind)
        command = _outcome_command(kind, relative, outcome)
        env = _outcome_env(kind, outcome, run_root)
        completed = subprocess.run(
            command,
            cwd=str(run_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=int(outcome.get("timeout_seconds") or 30),
        )
        return {
            "passed": completed.returncode == int(outcome.get("expected_exit_code", 0)),
            "returncode": completed.returncode,
            "kind": kind,
            "path": str(relative),
            "mutated": mutate,
            "stdout_tail": completed.stdout[-500:],
            "stderr_tail": completed.stderr[-500:],
        }
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def _validate_positive_case(
    case_id: str,
    case: dict[str, Any],
    repo_id: str,
    source_keys: set[tuple[str, str]],
    semantic_keys: set[str],
    semantic_families: set[str],
    fingerprints: set[tuple[str, str, str]],
    source_family_splits: dict[str, set[str]],
    split: str,
) -> None:
    source_path = str(case.get("source_path") or "")
    source_key = (repo_id, source_path)
    if source_key in source_keys:
        raise WorkspaceV4BenchmarkError(f"{case_id}: duplicate source path")
    source_keys.add(source_key)
    semantic_key = str(case.get("semantic_key") or "")
    if not semantic_key or semantic_key in semantic_keys:
        raise WorkspaceV4BenchmarkError(f"{case_id}: duplicate semantic case")
    semantic_keys.add(semantic_key)
    semantic_family = str(case.get("semantic_family") or "")
    if not semantic_family or semantic_family in semantic_families:
        raise WorkspaceV4BenchmarkError(f"{case_id}: duplicate semantic family")
    semantic_families.add(semantic_family)
    source_family = str(case.get("source_family") or "")
    if not source_family:
        raise WorkspaceV4BenchmarkError(f"{case_id}: source family required")
    source_family_splits.setdefault(source_family, set()).add(split)
    workflow_group = str(case.get("workflow_group") or "")
    if not workflow_group:
        raise WorkspaceV4BenchmarkError(f"{case_id}: workflow group required")
    if not str(case.get("source_url") or "").startswith("https://github.com/"):
        raise WorkspaceV4BenchmarkError(f"{case_id}: primary source URL required")
    if len(str(case.get("source_sha256") or "")) != 64:
        raise WorkspaceV4BenchmarkError(f"{case_id}: source sha256 required")
    outcome = case.get("expected_outcome") or {}
    if outcome.get("kind") in FORBIDDEN_TASK_OUTCOMES:
        raise WorkspaceV4BenchmarkError(f"{case_id}: checksum-only outcome forbidden")
    if outcome.get("kind") not in SUPPORTED_OUTCOMES:
        raise WorkspaceV4BenchmarkError(f"{case_id}: unsupported real outcome")
    fingerprint = (
        _normalize_text(str(case.get("query") or "")),
        _normalize_text(workflow_group),
        str(outcome.get("kind") or ""),
    )
    if fingerprint in fingerprints:
        raise WorkspaceV4BenchmarkError(
            f"{case_id}: duplicate normalized query/workflow/outcome fingerprint"
        )
    fingerprints.add(fingerprint)
    if _normalize_text(source_path).replace("/", "-") == _normalize_text(workflow_group):
        raise WorkspaceV4BenchmarkError(f"{case_id}: workflow cannot be the source path")
    if not case.get("license"):
        raise WorkspaceV4BenchmarkError(f"{case_id}: license required")
    _reject_query_leakage(case_id, str(case.get("query") or ""), source_path)


def _validate_control_case(case_id: str, case: dict[str, Any]) -> None:
    if case.get("expected_behavior") != "abstain":
        raise WorkspaceV4BenchmarkError(f"{case_id}: control must require abstain")
    if case.get("source_path"):
        _reject_query_leakage(case_id, str(case.get("query") or ""), str(case["source_path"]))


def _create_minimal_workspace(root: Path, repo: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "benchmark@example.com"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "WaveMind Benchmark"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "README.md").write_text(
        f"# {repo['name']}\n\nPinned source: {repo['commit']}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "README.md"], cwd=str(root), check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "workspace seed"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(repo["remote"])],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )


def _train_case(
    manager: WorkspaceExperienceManager,
    case: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    repo = manifest["repositories"][str(case["repo"])]
    outcome_kind = str(case["expected_outcome"]["kind"])
    run_id = f"workspace-v4-{_sha256(manager.identity.namespace)[:10]}-{case['case_id']}"
    started = manager.start_run(
        query=str(case["query"]),
        objective=f"verify {case['workflow_group']} before accepting workspace change",
        domain=str(repo["stack"]),
        task_type=str(case["workflow_group"]),
        tools=(outcome_kind, "workspace-verification"),
        run_id=run_id,
        metadata={
            "case_id": case["case_id"],
            "semantic_key": case["semantic_key"],
            "workflow_group": case["workflow_group"],
            "source_url": case["source_url"],
        },
    )
    call = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-call",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_CALL,
            sequence=started["next_sequence"],
            tool_name=outcome_kind,
            payload={"input": {"path": case["source_path"]}},
        )
    )
    result = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-result",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_RESULT,
            sequence=started["next_sequence"] + 1,
            parent_event_id=call["event"]["id"],
            tool_name=outcome_kind,
            payload={
                "success": True,
                "output": {
                    "outcome_kind": outcome_kind,
                    "source_url": case["source_url"],
                },
            },
        )
    )
    verified = manager.verify_run(
        run_id=run_id,
        evidence_id=f"{case['case_id']}-real-command",
        source=VerificationSource.TOOL,
        verifier=outcome_kind,
        success=True,
        score=1.0,
        reference=str(case["source_url"]),
        metadata={"case_id": case["case_id"], "outcome_kind": outcome_kind},
    )
    candidate = _current_procedure(manager, case, tuple(verified["candidate_ids"]))
    if candidate.status in {ExperienceStatus.SHADOW, ExperienceStatus.CANARY}:
        edited = manager.edit_and_approve(
            candidate.id,
            evidence_id=f"{case['case_id']}-operator-freeze",
            title=f"Run {outcome_kind} for {case['workflow_group']}",
            content=(
                f"For {case['workflow_group']} in {repo['name']}, run `{outcome_kind}` "
                "against the touched file before accepting the change. "
                f"Primary source: {case['source_url']}."
            ),
            reason="freeze v4 real-outcome workspace procedure",
            metadata={
                "case_id": case["case_id"],
                "semantic_key": case["semantic_key"],
                "workflow_group": case["workflow_group"],
                "outcome_kind": outcome_kind,
            },
        )
        citation = f"experience:{edited['experience_id']}@v{edited['experience']['version']}"
    else:
        citation = f"experience:{candidate.id}@v{candidate.version}"
    events = manager.runtime.events(namespace=manager.identity.namespace, run_id=run_id)
    mandatory_ids = {call["event"]["id"], result["event"]["id"]}
    captured_ids = {event.id for event in events}
    return {
        "citation": citation,
        "outcome_kind": outcome_kind,
        "workflow_group": case["workflow_group"],
        "context": (
            f"RAW_TRACE workflow={case['workflow_group']} outcome={outcome_kind} "
            f"source={case['source_url']} noisy stdout stderr previous attempts"
        ),
        "mandatory_events_expected": len(mandatory_ids),
        "mandatory_events_captured": len(mandatory_ids & captured_ids),
    }


def _current_procedure(
    manager: WorkspaceExperienceManager,
    case: dict[str, Any],
    candidate_ids: tuple[str, ...],
):
    outcome_kind = str(case["expected_outcome"]["kind"])
    workflow_group = str(case["workflow_group"])
    records = [
        record
        for record in manager.store.list(
            namespace=manager.identity.namespace,
            kind=ExperienceKind.PROCEDURE,
            include_expired=True,
            limit=10_000,
        )
        if record.status
        in {
            ExperienceStatus.SHADOW,
            ExperienceStatus.CANARY,
            ExperienceStatus.ACTIVE,
        }
        and workflow_group in record.applicability.task_types
        and outcome_kind in record.applicability.tools
    ]
    candidate_set = set(candidate_ids)
    records.sort(
        key=lambda record: (
            0 if record.id in candidate_set else 1,
            0 if record.status is ExperienceStatus.ACTIVE else 1,
            -int(record.version),
            -float(record.updated_at),
        )
    )
    if not records:
        raise WorkspaceV4BenchmarkError(
            f"{case['case_id']}: no current reviewable procedure for {workflow_group}"
        )
    return records[0]


def _raw_trace(case: dict[str, Any], trained: dict[str, Any]) -> dict[str, Any]:
    return {
        "citation": trained["citation"],
        "outcome_kind": trained["outcome_kind"],
        "workflow_group": trained["workflow_group"],
        "context": trained["context"],
    }


def _no_experience(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_citations": [],
        "abstain": True,
        "context_chars": 0,
        "latency_ms": 0.0,
        "command": {"passed": False, "returncode": None},
        "task_success": case["expected_behavior"] == "abstain",
    }


def _static_raw_trace(case: dict[str, Any], traces: list[dict[str, Any]], repo_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    ranked = sorted(traces, key=lambda item: _overlap(case["query"], item["context"]), reverse=True)
    selected = ranked[0] if ranked and _overlap(case["query"], ranked[0]["context"]) > 0 else None
    selection_latency_ms = (time.perf_counter() - started) * 1000.0
    citations = [selected["citation"]] if selected else []
    if case["expected_behavior"] == "execute_verified_outcome":
        kind_matches = selected is not None and selected["outcome_kind"] == case["expected_outcome"]["kind"]
        command = execute_outcome(repo_root, case["expected_outcome"]) if kind_matches else {"passed": False, "returncode": None}
        task_success = bool(command["passed"] and kind_matches)
    else:
        command = {"passed": False, "returncode": None}
        task_success = not citations
    return {
        "selected_citations": citations,
        "abstain": not citations,
        "context_chars": sum(len(item["context"]) for item in ranked[:3]),
        "latency_ms": selection_latency_ms,
        "command": command,
        "task_success": task_success,
    }


def _capture_control_case(
    manager: WorkspaceExperienceManager,
    case: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    repo = manifest["repositories"][str(case["repo"])]
    control_kind = str(case["kind"])
    run_id = f"workspace-v4-{_sha256(manager.identity.namespace)[:10]}-{case['case_id']}"
    started = manager.start_run(
        query=str(case["query"]),
        objective=f"inspect {control_kind} workspace evidence without promotion",
        domain=str(repo["stack"]),
        task_type=control_kind,
        tools=(f"{control_kind}_raw_trace",),
        run_id=run_id,
        metadata={
            "case_id": case["case_id"],
            "control_kind": control_kind,
            "verification_required": True,
        },
    )
    call = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-call",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_CALL,
            sequence=started["next_sequence"],
            tool_name=f"{control_kind}_raw_trace",
            payload={"input": {"query": case["query"]}},
        )
    )
    result = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-result",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_RESULT,
            sequence=started["next_sequence"] + 1,
            parent_event_id=call["event"]["id"],
            tool_name=f"{control_kind}_raw_trace",
            payload={
                "success": True,
                "output": {
                    "control_kind": control_kind,
                    "independently_verified": False,
                },
            },
        )
    )
    events = manager.runtime.events(namespace=manager.identity.namespace, run_id=run_id)
    mandatory_ids = {call["event"]["id"], result["event"]["id"]}
    captured_ids = {event.id for event in events}
    return {
        "citation": f"raw-trace:{case['case_id']}",
        "outcome_kind": f"{control_kind}_raw_trace",
        "workflow_group": control_kind,
        "context": (
            f"RAW_TRACE {control_kind} workspace request evidence without independent "
            f"verification. This trace is {control_kind} and should not be promoted: "
            f"{case['query']}"
        ),
        "mandatory_events_expected": len(mandatory_ids),
        "mandatory_events_captured": len(mandatory_ids & captured_ids),
    }


def _wavemind_verified(
    case: dict[str, Any],
    manager: WorkspaceExperienceManager,
    repo_root: Path,
    citation_to_case: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    packet = manager.packet(
        str(case["query"]),
        domain=_repo_stack(str(case["repo"]), citation_to_case),
        task_type=str(case.get("workflow_group") or "control"),
        tools=(str(case.get("expected_outcome", {}).get("kind") or "control"),),
        token_budget=180,
        top_k=1,
    )
    selection_latency_ms = (time.perf_counter() - started) * 1000.0
    citations = list(packet["selected_citations"])
    selected = citation_to_case.get(citations[0]) if citations else None
    if case["expected_behavior"] == "execute_verified_outcome":
        kind_matches = selected is not None and selected["expected_outcome"]["kind"] == case["expected_outcome"]["kind"]
        command = execute_outcome(repo_root, case["expected_outcome"]) if kind_matches else {"passed": False, "returncode": None}
        task_success = bool(command["passed"] and kind_matches)
    else:
        command = {"passed": False, "returncode": None}
        task_success = not citations
    return {
        "selected_citations": citations,
        "abstain": packet["abstain"],
        "context_chars": _packet_context_chars(packet),
        "latency_ms": selection_latency_ms,
        "command": command,
        "task_success": task_success,
    }


def _cross_client_parity(
    managers: dict[str, WorkspaceExperienceManager],
    repo_roots: dict[str, Path],
    cases: list[dict[str, Any]],
    citation_to_case: dict[str, dict[str, Any]],
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
            citation_to_case,
        )
        reopened = WorkspaceExperienceManager.open(managers[str(case["repo"])].config.config_path)
        try:
            after = _wavemind_verified(case, reopened, repo_roots[str(case["repo"])], citation_to_case)
        finally:
            reopened.close()
        checked += 1
        if before["selected_citations"] == after["selected_citations"]:
            matched += 1
    return matched / max(1, checked)


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
                for part in (item.get("citation"), item.get("title"), item.get("excerpt"))
                if part
            )
        )
    return len("\n".join(lines))


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
        1 for row in controls if row["case"]["kind"] == "unverified" and row[mode]["selected_citations"]
    )
    workspace_leaks = sum(
        1 for row in controls if row["case"]["kind"] == "wrong_workspace" and row[mode]["selected_citations"]
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


def validate_benchmark_results(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    *,
    allow_heldout: bool = False,
) -> None:
    if payload.get("schema") != RESULT_SCHEMA:
        raise WorkspaceV4BenchmarkError("result schema mismatch")
    if payload.get("split") == "heldout" and not allow_heldout:
        raise WorkspaceV4BenchmarkError("heldout results require explicit allowance")
    if payload.get("split") not in {"dev", "heldout"}:
        raise WorkspaceV4BenchmarkError("result split must be dev or heldout")
    if payload.get("manifest", {}).get("sha256") != manifest["sha256"]:
        raise WorkspaceV4BenchmarkError("result manifest checksum mismatch")
    for row in payload.get("rows") or []:
        case = row["case"]
        for mode in ("static_raw_trace_retrieval", "wavemind_verified_workspace_experience"):
            result = row[mode]
            if case["expected_behavior"] == "execute_verified_outcome":
                if result.get("task_success") and not result.get("command", {}).get("passed"):
                    raise WorkspaceV4BenchmarkError("citation-only success is forbidden")
            if case["expected_behavior"] == "abstain" and result.get("task_success"):
                if result.get("selected_citations"):
                    raise WorkspaceV4BenchmarkError("control success cannot include a citation")


def _repo_stack(repo_id: str, citation_to_case: dict[str, dict[str, Any]]) -> str:
    for case in citation_to_case.values():
        if case["repo"] == repo_id:
            return "javascript" if repo_id == "vite" else "python"
    return "workspace"


def _overlap(query: str, context: str) -> int:
    return len(_tokens(query) & _tokens(context))


def _tokens(text: str) -> set[str]:
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(token) > 2}


def _normalize_text(text: str) -> str:
    return " ".join(_tokens(text))


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


def _git_sha(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _reject_query_leakage(case_id: str, query: str, source_path: str) -> None:
    normalized_query = query.lower().replace("\\", "/")
    path = source_path.lower().replace("\\", "/")
    filename = Path(path).name
    stem = Path(filename).stem
    if path and path in normalized_query:
        raise WorkspaceV4BenchmarkError(f"{case_id}: source path leaks into query")
    if filename and filename in normalized_query:
        raise WorkspaceV4BenchmarkError(f"{case_id}: source filename leaks into query")
    query_tokens = _tokens(normalized_query)
    if any(token for token in _tokens(stem) if len(token) >= 6 and token in query_tokens):
        raise WorkspaceV4BenchmarkError(f"{case_id}: source filename stem leaks into query")


def _outcome_command(kind: str, relative: Path, outcome: dict[str, Any]) -> list[str]:
    path = str(relative)
    if kind == "python_py_compile":
        return [sys.executable, "-m", "py_compile", path]
    if kind == "python_ast_parse":
        code = "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text('utf-8'))"
        return [sys.executable, "-c", code, path]
    if kind == "python_import_module":
        module = str(outcome.get("module") or "")
        if not module:
            raise WorkspaceV4BenchmarkError("python_import_module requires module")
        code = "import importlib,sys; importlib.import_module(sys.argv[1])"
        return [sys.executable, "-c", code, module]
    if kind == "python_toml_parse":
        code = "import pathlib,sys,tomllib; tomllib.load(pathlib.Path(sys.argv[1]).open('rb'))"
        return [sys.executable, "-c", code, path]
    if kind == "python_configparser_parse":
        code = "import configparser,pathlib,sys; p=pathlib.Path(sys.argv[1]); c=configparser.ConfigParser(); c.read_file(p.open(encoding='utf-8'))"
        return [sys.executable, "-c", code, path]
    if kind == "yaml_parse":
        code = "import pathlib,sys,yaml; yaml.safe_load(pathlib.Path(sys.argv[1]).read_text('utf-8'))"
        return [sys.executable, "-c", code, path]
    if kind == "json_parse":
        return [sys.executable, "-m", "json.tool", path]
    if kind == "xml_parse":
        code = "import sys,xml.etree.ElementTree as ET; ET.parse(sys.argv[1])"
        return [sys.executable, "-c", code, path]
    if kind == "node_syntax_check":
        return ["node", "--check", path]
    raise WorkspaceV4BenchmarkError(f"unsupported outcome kind: {kind}")


def _outcome_env(kind: str, outcome: dict[str, Any], run_root: Path) -> dict[str, str] | None:
    if kind != "python_import_module":
        return None
    env = dict(os.environ)
    pythonpath = str(outcome.get("pythonpath") or "").strip()
    if pythonpath:
        path = run_root / pythonpath
        env["PYTHONPATH"] = str(path) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _mutate_file(path: Path, kind: str) -> None:
    if kind in {"python_py_compile", "python_ast_parse", "python_import_module"}:
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\nif =\n", encoding="utf-8")
    elif kind == "python_toml_parse":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n[broken\n", encoding="utf-8")
    elif kind == "python_configparser_parse":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n[\n", encoding="utf-8")
    elif kind == "yaml_parse":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n: : :\n", encoding="utf-8")
    elif kind == "json_parse":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n{", encoding="utf-8")
    elif kind == "xml_parse":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n<broken", encoding="utf-8")
    elif kind == "node_syntax_check":
        path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\nif (", encoding="utf-8")
    else:
        raise WorkspaceV4BenchmarkError(f"unsupported outcome kind: {kind}")


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", default="benchmarks/workspace_experience_v4_dev_results.json")
    parser.add_argument(
        "--allow-heldout",
        action="store_true",
        help="Run the frozen heldout split after protocol freeze.",
    )
    parser.add_argument(
        "--allow-invalid-protocol",
        action="store_true",
        help="Run v4 only as a historical diagnostic; v4 is not admission evidence.",
    )
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    if args.validate_only:
        counts = validate_manifest(
            manifest,
            require_checkout=True,
            cache_root=args.cache_root,
        )
        print(json.dumps({"schema": RESULT_SCHEMA, "status": "valid", "counts": counts}, indent=2))
        return 0
    payload = write_artifacts(
        manifest_path=args.manifest,
        split=args.split,
        output=args.output,
        cache_root=args.cache_root,
        allow_heldout=args.allow_heldout,
        allow_invalid_protocol=args.allow_invalid_protocol,
    )
    print(
        json.dumps(
            {
                "schema": RESULT_SCHEMA,
                "status": payload["status"],
                "metrics": payload["metrics"]["admission"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
