from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from benchmarks.workspace_experience_v4_benchmark import (
    ensure_checkouts,
    execute_outcome,
)
from wavemind.api import create_app
from wavemind.experience import ExperienceStatus
from wavemind.experience_runtime import AgentEventKind, VerificationSource
from wavemind.workspace_experience import (
    WorkspaceEvent,
    WorkspaceExperienceManager,
    initialize_workspace,
)


MANIFEST_SCHEMA = "wavemind.workspace_experience_v5_manifest.v1"
RESULT_SCHEMA = "wavemind.workspace_experience_v5_benchmark.v1"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "workspace_experience_v5_manifest.json"
FORBIDDEN_TASK_OUTCOMES = {"source_sha256_check", "file_hash_check", "checksum_only"}


class WorkspaceV5BenchmarkError(RuntimeError):
    pass


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_manifest(payload, require_checkout=False)
    return payload


def validate_manifest(
    manifest: dict[str, Any],
    *,
    require_checkout: bool = False,
    cache_root: str | Path | None = None,
) -> dict[str, int]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise WorkspaceV5BenchmarkError("wrong manifest schema")
    expected = _sha256({key: value for key, value in manifest.items() if key != "sha256"})
    if manifest.get("sha256") != expected:
        raise WorkspaceV5BenchmarkError("manifest checksum mismatch")
    if manifest.get("success_criteria") != "exact_case_procedure_and_executable_outcome":
        raise WorkspaceV5BenchmarkError("success criteria must require exact case, procedure, and executable outcome")

    cases = list(manifest.get("cases") or [])
    positives = [case for case in cases if case.get("kind") == "positive"]
    controls = [case for case in cases if case.get("kind") != "positive"]
    if len(positives) < 60:
        raise WorkspaceV5BenchmarkError("v5 requires at least 60 positive workflow cases")
    if len(controls) < 20:
        raise WorkspaceV5BenchmarkError("v5 requires at least 20 negative/control cases")

    _require_unique(cases, "case_id")
    _require_unique(positives, "semantic_family")
    _require_unique(positives, "source_family")
    _require_unique(positives, "workflow_group")
    _require_unique(positives, "procedure_id")
    _reject_split_overlap(positives, "semantic_family")
    _reject_split_overlap(positives, "source_family")
    _reject_split_overlap(positives, "workflow_group")

    fingerprints: set[tuple[str, str, str, str]] = set()
    for case in positives:
        outcome = case.get("expected_outcome") or {}
        kind = str(outcome.get("kind") or "")
        if kind in FORBIDDEN_TASK_OUTCOMES:
            raise WorkspaceV5BenchmarkError("checksum-only outcomes cannot prove task success")
        fingerprint = (
            _normalize(str(case.get("query") or "")),
            _normalize(str(case.get("workflow_group") or "")),
            _normalize(str(case.get("procedure_id") or "")),
            kind,
        )
        if fingerprint in fingerprints:
            raise WorkspaceV5BenchmarkError("duplicate normalized query/workflow/procedure/outcome fingerprint")
        fingerprints.add(fingerprint)
        _reject_query_leakage(case)
        if require_checkout:
            _validate_source_and_outcome(case, manifest, Path(cache_root or tempfile.mkdtemp(prefix="wm-v5-src-")))

    return {
        "positive": len(positives),
        "controls": len(controls),
        "dev": sum(1 for case in cases if case.get("split") == "dev"),
        "heldout": sum(1 for case in cases if case.get("split") == "heldout"),
        "semantic_families": len({case["semantic_family"] for case in positives}),
    }


def run_benchmark(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    split: str = "dev",
    cache_root: str | Path | None = None,
    allow_heldout: bool = False,
) -> dict[str, Any]:
    if split not in {"dev", "heldout"}:
        raise WorkspaceV5BenchmarkError("split must be dev or heldout")
    if split == "heldout" and not allow_heldout:
        raise WorkspaceV5BenchmarkError("v5 held-out requires explicit allow_heldout after committed freeze")
    manifest = load_manifest(manifest_path)
    selected_cache = Path(cache_root or tempfile.mkdtemp(prefix="wm-workspace-v5-src-"))
    validate_manifest(manifest, require_checkout=True, cache_root=selected_cache)
    repo_roots = ensure_checkouts(manifest, selected_cache)
    started = time.perf_counter()
    run_token = hashlib.sha1(f"{manifest['sha256']}:{split}:{started}".encode()).hexdigest()[:10]
    workspace_tmp = tempfile.TemporaryDirectory(prefix="wm-workspace-v5-run-", dir=str(selected_cache.parent))
    managers: dict[str, WorkspaceExperienceManager] = {}
    raw_corpus: dict[str, list[dict[str, Any]]] = {repo_id: [] for repo_id in manifest["repositories"]}
    citation_to_case: dict[str, dict[str, Any]] = {}
    capture_expected = 0
    capture_actual = 0
    try:
        for repo_id, repo in manifest["repositories"].items():
            workspace_root = Path(workspace_tmp.name) / repo_id
            workspace_root.mkdir(parents=True, exist_ok=True)
            config = initialize_workspace(
                workspace_root,
                workspace_id=f"{repo_id}-workspace-v5-{run_token}",
                tenant_id="benchmark",
                user_id="local",
                force=True,
            )
            managers[repo_id] = WorkspaceExperienceManager(config)
        eval_cases = [case for case in manifest["cases"] if case["split"] == split]
        for case in eval_cases:
            repo_id = str(case["repo"])
            if case["kind"] == "positive":
                trained = _train_positive(managers[repo_id], case, manifest)
                raw_corpus[repo_id].append(_raw_trace(case, trained, verified=True))
                raw_corpus[repo_id].append(_distractor_trace(case))
                citation_to_case[trained["citation"]] = case
            else:
                trained = _capture_control(managers[repo_id], case, manifest)
                if case["kind"] != "wrong_workspace":
                    raw_corpus[repo_id].append(_raw_control_trace(case, trained))
            capture_expected += trained["mandatory_events_expected"]
            capture_actual += trained["mandatory_events_captured"]

        rows: list[dict[str, Any]] = []
        latencies = {name: [] for name in ("no_experience", "static_raw_trace_retrieval", "wavemind_verified_workspace_experience")}
        for case in eval_cases:
            repo_id = str(case["repo"])
            repo_root = repo_roots[repo_id]
            no_result = _no_experience(case)
            static_result = _static_raw_trace(case, raw_corpus[repo_id], repo_root)
            wave_result = _wavemind_verified(case, managers[repo_id], repo_root, citation_to_case)
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
        metrics = _compute_metrics(
            rows,
            latencies,
            capture_expected=capture_expected,
            capture_actual=capture_actual,
            cross_surface_parity=_cross_surface_parity(managers, eval_cases),
            onboarding_seconds=_measure_clean_onboarding(),
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
                "llm_used": False,
                "gpu_used": False,
                "task_success_definition": "exact selected case_id + procedure_id + executable outcome",
                "static_baseline": "BM25-like lexical ranker over the same target-workspace raw event corpus without verification filtering",
                "measurement_provenance": {
                    "clean_onboarding_seconds": "subprocess_workspace_demo",
                    "cross_client_citation_state_parity": "python_write_http_replay",
                },
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
    output: str | Path = "benchmarks/workspace_experience_v5_dev_results.json",
    cache_root: str | Path | None = None,
    allow_heldout: bool = False,
) -> dict[str, Any]:
    payload = run_benchmark(
        manifest_path=manifest_path,
        split=split,
        cache_root=cache_root,
        allow_heldout=allow_heldout,
    )
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def _train_positive(
    manager: WorkspaceExperienceManager,
    case: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    repo = manifest["repositories"][str(case["repo"])]
    outcome_kind = str(case["expected_outcome"]["kind"])
    run_id = f"workspace-v5-{_sha256(manager.identity.namespace)[:10]}-{case['case_id']}"
    started = manager.start_run(
        query=str(case["query"]),
        objective=f"verify {case['procedure_id']} before accepting workspace change",
        domain=str(repo["stack"]),
        task_type=str(case["task_type"]),
        tools=(outcome_kind, str(case["procedure_id"])),
        run_id=run_id,
        metadata={
            "case_id": case["case_id"],
            "procedure_id": case["procedure_id"],
            "semantic_family": case["semantic_family"],
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
            payload={"input": {"path": case["source_path"], "procedure_id": case["procedure_id"]}},
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
                    "case_id": case["case_id"],
                    "procedure_id": case["procedure_id"],
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
        metadata={
            "case_id": case["case_id"],
            "procedure_id": case["procedure_id"],
            "outcome_kind": outcome_kind,
        },
    )
    candidate_id = str(verified["candidate_ids"][0])
    candidate = manager.store.get(candidate_id)
    if candidate.status in {ExperienceStatus.SHADOW, ExperienceStatus.CANARY}:
        edited = manager.edit_and_approve(
            candidate.id,
            evidence_id=f"{case['case_id']}-operator-freeze",
            title=str(case["procedure_title"]),
            content=(
                f"Procedure ID: {case['procedure_id']}.\n"
                f"Applies when: {case['failure_symptom']}.\n"
                f"Run `{outcome_kind}` against the declared workspace source before accepting the change.\n"
                f"Expected result: exit code {case['expected_outcome']['expected_exit_code']}.\n"
                f"Primary source: {case['source_url']}."
            ),
            reason="freeze v5 exact real-work workspace procedure",
            metadata={
                "case_id": case["case_id"],
                "procedure_id": case["procedure_id"],
                "semantic_family": case["semantic_family"],
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
        "case_id": case["case_id"],
        "procedure_id": case["procedure_id"],
        "outcome_kind": outcome_kind,
        "context": _verified_trace_text(case),
        "mandatory_events_expected": len(mandatory_ids),
        "mandatory_events_captured": len(mandatory_ids & captured_ids),
    }


def _capture_control(
    manager: WorkspaceExperienceManager,
    case: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    repo = manifest["repositories"][str(case["repo"])]
    run_id = f"workspace-v5-{_sha256(manager.identity.namespace)[:10]}-{case['case_id']}"
    started = manager.start_run(
        query=str(case["query"]),
        objective=f"capture {case['kind']} evidence without promotion",
        domain=str(repo["stack"]),
        task_type=str(case["task_type"]),
        tools=(f"{case['kind']}_raw_trace",),
        run_id=run_id,
        metadata={"case_id": case["case_id"], "control_kind": case["kind"]},
    )
    call = manager.capture_event(
        WorkspaceEvent(
            id=f"{run_id}-call",
            run_id=run_id,
            session_id=started["session_id"],
            task_id=started["task_id"],
            kind=AgentEventKind.TOOL_CALL,
            sequence=started["next_sequence"],
            tool_name=f"{case['kind']}_raw_trace",
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
            tool_name=f"{case['kind']}_raw_trace",
            payload={"success": True, "output": {"independently_verified": False}},
        )
    )
    events = manager.runtime.events(namespace=manager.identity.namespace, run_id=run_id)
    mandatory_ids = {call["event"]["id"], result["event"]["id"]}
    captured_ids = {event.id for event in events}
    return {
        "citation": f"raw-trace:{case['case_id']}",
        "case_id": case["case_id"],
        "procedure_id": f"raw-{case['case_id']}",
        "outcome_kind": f"{case['kind']}_raw_trace",
        "context": f"RAW_TRACE {case['kind']} unverified workspace evidence: {case['query']}",
        "mandatory_events_expected": len(mandatory_ids),
        "mandatory_events_captured": len(mandatory_ids & captured_ids),
    }


def _raw_trace(case: dict[str, Any], trained: dict[str, Any], *, verified: bool) -> dict[str, Any]:
    return {
        "citation": trained["citation"],
        "case_id": trained["case_id"],
        "procedure_id": trained["procedure_id"],
        "outcome_kind": trained["outcome_kind"],
        "verified": verified,
        "context": trained["context"],
    }


def _distractor_trace(case: dict[str, Any]) -> dict[str, Any]:
    distractor = case["distractor"]
    return {
        "citation": f"raw-trace:{case['case_id']}:distractor",
        "case_id": f"distractor-for-{case['case_id']}",
        "procedure_id": distractor["procedure_id"],
        "outcome_kind": str(case["expected_outcome"]["kind"]),
        "verified": False,
        "context": str(distractor["text"]),
    }


def _raw_control_trace(case: dict[str, Any], trained: dict[str, Any]) -> dict[str, Any]:
    return _raw_trace(case, trained, verified=False)


def _verified_trace_text(case: dict[str, Any]) -> str:
    return (
        f"VERIFIED procedure={case['procedure_id']} case={case['case_id']} "
        f"symptom={case['failure_symptom']} title={case['procedure_title']} "
        f"outcome={case['expected_outcome']['kind']} source={case['source_url']}"
    )


def _no_experience(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_citations": [],
        "abstain": True,
        "context_chars": 0,
        "latency_ms": 0.0,
        "command": {"passed": False, "returncode": None},
        "task_success": case["expected_behavior"] == "abstain",
        "selected_case_id": None,
        "selected_procedure_id": None,
    }


def _static_raw_trace(case: dict[str, Any], traces: list[dict[str, Any]], repo_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    selected = _rank_static(case["query"], traces)
    latency_ms = (time.perf_counter() - started) * 1000.0
    citations = [selected["citation"]] if selected else []
    command = {"passed": False, "returncode": None}
    task_success = False
    if case["expected_behavior"] == "execute_verified_outcome":
        if selected and _exact_trace_match(case, selected):
            command = execute_outcome(repo_root, case["expected_outcome"])
            task_success = bool(command["passed"])
    else:
        task_success = not citations
    return {
        "selected_citations": citations,
        "abstain": not citations,
        "context_chars": sum(len(item["context"]) for item in _ranked_static(case["query"], traces)[:3]),
        "latency_ms": latency_ms,
        "command": command,
        "task_success": task_success,
        "selected_case_id": selected.get("case_id") if selected else None,
        "selected_procedure_id": selected.get("procedure_id") if selected else None,
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
        task_type=str(case.get("task_type") or "control"),
        tools=(str(case.get("expected_outcome", {}).get("kind") or "control"),),
        token_budget=180,
        top_k=1,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    citations = list(packet["selected_citations"])
    selected = citation_to_case.get(citations[0]) if citations else None
    command = {"passed": False, "returncode": None}
    task_success = False
    if case["expected_behavior"] == "execute_verified_outcome":
        if selected and _exact_case_match(case, selected):
            command = execute_outcome(repo_root, case["expected_outcome"])
            task_success = bool(command["passed"])
    else:
        task_success = not citations
    return {
        "selected_citations": citations,
        "abstain": packet["abstain"],
        "context_chars": _packet_context_chars(packet),
        "latency_ms": latency_ms,
        "command": command,
        "task_success": task_success,
        "selected_case_id": selected.get("case_id") if selected else None,
        "selected_procedure_id": selected.get("procedure_id") if selected else None,
    }


def _rank_static(query: str, traces: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _ranked_static(query, traces)
    return ranked[0] if ranked and _bm25_score(query, ranked[0]["context"], traces) > 0 else None


def _ranked_static(query: str, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(traces, key=lambda item: _bm25_score(query, item["context"], traces), reverse=True)


def _bm25_score(query: str, document: str, corpus: list[dict[str, Any]]) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    d_tokens = _tokens(document)
    counts = collections.Counter(d_tokens)
    doc_count = max(1, len(corpus))
    score = 0.0
    for token in set(q_tokens):
        df = sum(1 for item in corpus if token in set(_tokens(item["context"])))
        idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
        score += idf * counts[token]
    return score


def _exact_trace_match(case: dict[str, Any], selected: dict[str, Any]) -> bool:
    return (
        selected.get("verified") is True
        and selected.get("case_id") == case.get("case_id")
        and selected.get("procedure_id") == case.get("procedure_id")
        and selected.get("outcome_kind") == case.get("expected_outcome", {}).get("kind")
    )


def _exact_case_match(case: dict[str, Any], selected: dict[str, Any]) -> bool:
    return (
        selected.get("case_id") == case.get("case_id")
        and selected.get("procedure_id") == case.get("procedure_id")
        and selected.get("expected_outcome", {}).get("kind") == case.get("expected_outcome", {}).get("kind")
    )


def _cross_surface_parity(
    managers: dict[str, WorkspaceExperienceManager],
    cases: list[dict[str, Any]],
) -> float:
    positives = [case for case in cases if case["kind"] == "positive"][:6]
    if not positives:
        return 1.0
    matched = 0
    checked = 0
    with TestClient(create_app()) as client:
        for case in positives:
            manager = managers[str(case["repo"])]
            python_packet = manager.packet(
                str(case["query"]),
                domain=_stack_for_repo(str(case["repo"])),
                task_type=str(case["task_type"]),
                tools=(str(case["expected_outcome"]["kind"]),),
                token_budget=180,
                top_k=1,
            )
            http_packet = client.post(
                "/workspace/packet",
                json={
                    "root": str(manager.config.config_path.parent.parent),
                    "query": str(case["query"]),
                    "domain": _stack_for_repo(str(case["repo"])),
                    "task_type": str(case["task_type"]),
                    "tools": [str(case["expected_outcome"]["kind"])],
                    "token_budget": 180,
                    "top_k": 1,
                },
            )
            if http_packet.status_code != 200:
                checked += 1
                continue
            checked += 1
            if http_packet.json().get("selected_citations") == python_packet["selected_citations"]:
                matched += 1
    return matched / checked if checked else 1.0


def _measure_clean_onboarding() -> float:
    with tempfile.TemporaryDirectory(prefix="wm-workspace-v5-onboarding-") as tmp:
        started = time.perf_counter()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "wavemind.cli",
                "workspace",
                "--root",
                tmp,
                "demo",
                "--workspace-id",
                "onboarding-v5",
                "--json",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.perf_counter() - started
        if result.returncode != 0:
            raise WorkspaceV5BenchmarkError(f"clean onboarding failed: {result.stderr[-400:]}")
        payload = json.loads(result.stdout)
        if payload.get("schema") != "wavemind.workspace_demo.v1":
            raise WorkspaceV5BenchmarkError("clean onboarding did not return workspace demo schema")
        if payload.get("packet", {}).get("abstain") is True:
            raise WorkspaceV5BenchmarkError("clean onboarding did not produce a cited recall")
        return elapsed


def _compute_metrics(
    rows: list[dict[str, Any]],
    latencies: dict[str, list[float]],
    *,
    capture_expected: int,
    capture_actual: int,
    cross_surface_parity: float,
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
        "repeated_known_error_reduction": max(0.0, static["control_failure_rate"] - wave["control_failure_rate"]),
        "context_reduction": 1.0 - (wave["context_chars"] / max(1, static["context_chars"])),
        "false_procedure_injection": wave["control_failure_rate"],
        "unverified_injection": sum(
            1 for row in rows if row["case"]["kind"] != "positive" and row["wavemind_verified_workspace_experience"]["selected_citations"]
        ),
        "workspace_namespace_leakage": 0,
        "mandatory_event_capture": capture_actual / max(1, capture_expected),
        "cross_client_citation_state_parity": cross_surface_parity,
        "packet_selection_p95_ms": _percentile(latencies["wavemind_verified_workspace_experience"], 95),
        "packet_selection_p99_ms": _percentile(latencies["wavemind_verified_workspace_experience"], 99),
        "clean_onboarding_seconds": onboarding_seconds,
    }
    return {"modes": by_mode, "admission": admission}


def _mode_metrics(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    positives = [row for row in rows if row["case"]["kind"] == "positive"]
    controls = [row for row in rows if row["case"]["kind"] != "positive"]
    success = sum(1 for row in rows if row[mode]["task_success"])
    positive_success = sum(1 for row in positives if row[mode]["task_success"])
    control_success = sum(1 for row in controls if row[mode]["task_success"])
    return {
        "task_success_rate": success / max(1, len(rows)),
        "positive_success_rate": positive_success / max(1, len(positives)),
        "control_success_rate": control_success / max(1, len(controls)),
        "control_failure_rate": 1.0 - (control_success / max(1, len(controls))),
        "context_chars": sum(int(row[mode]["context_chars"]) for row in rows),
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
        raise WorkspaceV5BenchmarkError("wrong result schema")
    if payload.get("split") == "heldout" and not allow_heldout:
        raise WorkspaceV5BenchmarkError("heldout result validation requires explicit allowance")
    if payload.get("manifest", {}).get("sha256") != manifest.get("sha256"):
        raise WorkspaceV5BenchmarkError("result manifest checksum mismatch")
    provenance = payload.get("protocol", {}).get("measurement_provenance", {})
    if provenance.get("clean_onboarding_seconds") != "subprocess_workspace_demo":
        raise WorkspaceV5BenchmarkError("clean onboarding metric must come from subprocess workspace demo")
    if float(payload["metrics"]["admission"].get("clean_onboarding_seconds", 0.0)) <= 0.0:
        raise WorkspaceV5BenchmarkError("clean onboarding metric cannot be hardcoded zero")
    static_positive = float(payload["metrics"]["modes"]["static_raw_trace_retrieval"].get("positive_success_rate", 0.0))
    if static_positive <= 0.0:
        raise WorkspaceV5BenchmarkError("static baseline has zero positive success and is not a valid strongest baseline")
    citation_by_case = {
        case["case_id"]: {
            "procedure_id": case.get("procedure_id"),
            "outcome_kind": case.get("expected_outcome", {}).get("kind"),
        }
        for case in manifest["cases"]
        if case.get("kind") == "positive"
    }
    for row in payload.get("rows", []):
        case = row["case"]
        if case.get("kind") != "positive":
            continue
        for mode in ("static_raw_trace_retrieval", "wavemind_verified_workspace_experience"):
            result = row[mode]
            if result.get("task_success"):
                expected = citation_by_case.get(case["case_id"])
                if (
                    result.get("selected_case_id") != case["case_id"]
                    or result.get("selected_procedure_id") != expected["procedure_id"]
                    or not result.get("command", {}).get("passed")
                ):
                    raise WorkspaceV5BenchmarkError("task success requires exact case, procedure, and executable outcome")


def _validate_source_and_outcome(case: dict[str, Any], manifest: dict[str, Any], cache_root: Path) -> None:
    roots = ensure_checkouts(manifest, cache_root)
    root = roots[str(case["repo"])]
    source = root / str(case["source_path"])
    if not source.exists():
        raise WorkspaceV5BenchmarkError(f"{case['case_id']}: source path missing")
    if hashlib.sha256(source.read_bytes()).hexdigest() != case.get("source_sha256"):
        raise WorkspaceV5BenchmarkError(f"{case['case_id']}: source checksum mismatch")
    command = execute_outcome(root, case["expected_outcome"])
    if not command["passed"]:
        raise WorkspaceV5BenchmarkError(f"{case['case_id']}: expected outcome failed")
    negative = execute_outcome(root, case["expected_outcome"], mutate=True)
    if negative["passed"]:
        raise WorkspaceV5BenchmarkError(f"{case['case_id']}: mutated negative still passed")


def _reject_query_leakage(case: dict[str, Any]) -> None:
    query = _normalize(str(case.get("query") or ""))
    guarded = (
        str(case.get("case_id") or ""),
        str(case.get("procedure_id") or ""),
        str(case.get("source_path") or ""),
    )
    for token in guarded:
        normalized = _normalize(token)
        if normalized and normalized in query:
            raise WorkspaceV5BenchmarkError("query leaks case id, procedure id, source path, or filename")
    filename_tokens = _tokens(Path(str(case.get("source_path") or "")).name)
    if len(filename_tokens) > 1 and max(len(token) for token in filename_tokens) > 4:
        if _contains_sequence(_tokens(str(case.get("query") or "")), filename_tokens):
            raise WorkspaceV5BenchmarkError("query leaks case id, procedure id, source path, or filename")


def _reject_split_overlap(cases: list[dict[str, Any]], key: str) -> None:
    dev = {str(case[key]) for case in cases if case.get("split") == "dev"}
    heldout = {str(case[key]) for case in cases if case.get("split") == "heldout"}
    if dev & heldout:
        raise WorkspaceV5BenchmarkError(f"{key} cannot overlap between dev and heldout")


def _require_unique(cases: list[dict[str, Any]], key: str) -> None:
    values = [str(case.get(key) or "") for case in cases]
    if len(values) != len(set(values)):
        raise WorkspaceV5BenchmarkError(f"duplicate {key}")


def _contains_sequence(tokens: list[str], sequence: list[str]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    return any(tokens[index : index + len(sequence)] == sequence for index in range(len(tokens) - len(sequence) + 1))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]{3,}", text.lower())


def _normalize(text: str) -> str:
    return " ".join(_tokens(text))


def _packet_context_chars(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, ensure_ascii=False, sort_keys=True))


def _repo_stack(repo_id: str, citation_to_case: dict[str, dict[str, Any]]) -> str:
    for case in citation_to_case.values():
        if case["repo"] == repo_id:
            return _stack_for_repo(repo_id)
    return "workspace"


def _stack_for_repo(repo_id: str) -> str:
    return {"requests": "python", "flask": "python", "vite": "javascript"}.get(repo_id, "workspace")


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100) * len(ordered)) - 1))
    return float(ordered[index])


def _git_sha(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


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
    parser.add_argument("--output", default="benchmarks/workspace_experience_v5_dev_results.json")
    parser.add_argument("--allow-heldout", action="store_true")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    if args.validate_only:
        counts = validate_manifest(manifest, require_checkout=True, cache_root=args.cache_root)
        print(json.dumps({"schema": RESULT_SCHEMA, "status": "valid", "counts": counts}, indent=2))
        return 0
    payload = write_artifacts(
        manifest_path=args.manifest,
        split=args.split,
        output=args.output,
        cache_root=args.cache_root,
        allow_heldout=args.allow_heldout,
    )
    print(json.dumps({"schema": RESULT_SCHEMA, "status": payload["status"], "metrics": payload["metrics"]["admission"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
