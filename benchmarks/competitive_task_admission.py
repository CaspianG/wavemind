from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.competitive_task_benchmark import (
    BOOTSTRAP_SAMPLES,
    ENGINE_SPECS,
    SCHEMA as BENCHMARK_SCHEMA,
)
from wavemind.evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    file_sha256,
    repository_commit,
    validate_source_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "wavemind.competitive_task_admission.v1"
MANDATORY_ENGINES = tuple(str(spec["engine"]) for spec in ENGINE_SPECS)
MIN_TASKS = 150
MIN_REPEATS = 5
MAX_CONTEXT_RATIO = 2.5
MAX_CANDIDATE_P95_MS = 75.0
SOURCE_FILES = (
    "benchmarks/competitive_task_benchmark.py",
    "benchmarks/competitive_task_admission.py",
    "benchmarks/verified_experience_benchmark.py",
    "benchmarks/public_memory_competitors.py",
    "benchmarks/long_memory_evidence_benchmark.py",
    "wavemind/experience_runtime.py",
    "wavemind/experience_compiler.py",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(
    check_id: str,
    passed: bool,
    *,
    target: str,
    actual: Any,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "blocked",
        "target": target,
        "actual": actual,
        "evidence": dict(evidence or {}),
    }


def evaluate_competitive_task_admission(
    benchmark: Mapping[str, Any],
    *,
    expected_source_sha: str,
    benchmark_path: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    expected_source_sha = str(expected_source_sha).strip().lower()
    observed_source_sha = str(benchmark.get("source_sha") or "").lower()
    candidate = dict(benchmark.get("candidate") or {})
    competitors = {
        str(row.get("engine")): dict(row)
        for row in benchmark.get("competitors") or []
        if isinstance(row, Mapping)
    }
    skipped = {
        str(row.get("engine")): dict(row)
        for row in benchmark.get("skipped") or []
        if isinstance(row, Mapping)
    }
    protocol = dict(benchmark.get("protocol") or {})
    strongest_summary = dict(benchmark.get("strongest_competitor") or {})
    strongest_engine = str(strongest_summary.get("engine") or "")
    strongest = competitors.get(strongest_engine, {})
    paired = dict(benchmark.get("paired_task_success_lift") or {})
    strongest_lift = dict(paired.get(strongest_engine) or {})

    candidate_success = float(
        dict(candidate.get("task_success") or {}).get("mean", 0.0)
    )
    strongest_success = float(
        dict(strongest.get("task_success") or {}).get("mean", 0.0)
    )
    candidate_context = float(
        dict(candidate.get("context_tokens") or {}).get("mean", 0.0)
    )
    strongest_context = float(
        dict(strongest.get("context_tokens") or {}).get("mean", 0.0)
    )
    context_ratio = candidate_context / max(strongest_context, 1.0)
    candidate_failures = float(candidate.get("failed_task_attempts", MIN_TASKS))
    strongest_failures = float(strongest.get("failed_task_attempts", 0.0))
    candidate_latency = float(candidate.get("p95_latency_ms", float("inf")))
    safety = dict(candidate.get("safety") or {})

    repository_sha = repository_commit(project_root)
    exact_sha_passed = bool(
        re.fullmatch(r"[0-9a-f]{40}", expected_source_sha)
        and observed_source_sha == expected_source_sha
        and repository_sha == expected_source_sha
    )
    complete_engines = [
        engine
        for engine in MANDATORY_ENGINES
        if engine in competitors
        and competitors[engine].get("status") == "pass"
        and engine not in skipped
    ]
    version_rows = {
        engine: str(competitors.get(engine, {}).get("system_version") or "")
        for engine in MANDATORY_ENGINES
    }
    protocol_flags = (
        "same_tasks",
        "same_procedure_corpus",
        "same_executable_state_verifier",
        "same_top_k",
        "same_namespace_routing",
        "same_shared_embedding_where_supported",
        "split_frozen_before_evaluation",
    )
    task_native_rows = {
        engine: {
            "execution_mode": competitors.get(engine, {}).get("execution_mode"),
            "case_count": len(competitors.get(engine, {}).get("case_success") or {}),
        }
        for engine in MANDATORY_ENGINES
    }
    lifecycle_noninferior = all(
        float(dict(candidate.get("repeated_error_rate") or {}).get("mean", 1.0))
        <= float(dict(row.get("repeated_error_rate") or {}).get("mean", 1.0))
        and float(
            dict(candidate.get("unnecessary_intervention_rate") or {}).get("mean", 1.0)
        )
        <= float(dict(row.get("unnecessary_intervention_rate") or {}).get("mean", 1.0))
        for row in competitors.values()
    )
    provenance_rows = {
        engine: {
            "provenance_mode": competitors.get(engine, {}).get("provenance_mode"),
            "embedding_profile": competitors.get(engine, {}).get("embedding_profile"),
        }
        for engine in MANDATORY_ENGINES
    }
    quality_win = candidate_success > strongest_success
    cost_win = (
        candidate_failures < strongest_failures
        and float(candidate.get("paid_api_cost_usd", -1.0)) == 0.0
        and float(strongest.get("paid_api_cost_usd", -1.0)) == 0.0
    )
    checks = [
        _check(
            "exact-source-sha",
            exact_sha_passed,
            target="benchmark, checkout, and expected SHA are identical",
            actual={
                "benchmark": observed_source_sha,
                "checkout": repository_sha,
                "expected": expected_source_sha,
            },
        ),
        _check(
            "benchmark-complete",
            benchmark.get("schema") == BENCHMARK_SCHEMA
            and benchmark.get("status") == "complete",
            target=f"{BENCHMARK_SCHEMA} with status complete",
            actual={
                "schema": benchmark.get("schema"),
                "status": benchmark.get("status"),
            },
        ),
        _check(
            "mandatory-real-engines",
            tuple(complete_engines) == MANDATORY_ENGINES,
            target=f"{len(MANDATORY_ENGINES)}/{len(MANDATORY_ENGINES)} real engines; no imitation or skip",
            actual={"completed": complete_engines, "skipped": sorted(skipped)},
        ),
        _check(
            "exact-system-versions",
            all(value and value != "unknown" for value in version_rows.values()),
            target="every mandatory competitor reports an installed package version",
            actual=version_rows,
        ),
        _check(
            "frozen-shared-protocol",
            int(protocol.get("held_out_tasks", 0)) >= MIN_TASKS
            and int(protocol.get("repeats", 0)) >= MIN_REPEATS
            and int(protocol.get("top_k", 0)) == 1
            and int(protocol.get("bootstrap_samples", 0)) >= BOOTSTRAP_SAMPLES
            and all(protocol.get(flag) is True for flag in protocol_flags),
            target=(
                f">={MIN_TASKS} tasks, >={MIN_REPEATS} repeats, top-k 1, "
                "10k bootstrap samples, frozen shared inputs/verifier"
            ),
            actual={
                key: protocol.get(key)
                for key in (
                    "held_out_tasks",
                    "repeats",
                    "top_k",
                    "bootstrap_samples",
                    *protocol_flags,
                )
            },
        ),
        _check(
            "task-native-execution",
            all(
                row["execution_mode"] == "task_native_retrieved_procedure"
                and row["case_count"] >= MIN_TASKS
                for row in task_native_rows.values()
            ),
            target="every competitor executes retrieved procedures on every held-out task",
            actual=task_native_rows,
        ),
        _check(
            "provenance-and-namespace-contract",
            protocol.get("same_namespace_routing") is True
            and all(
                row["provenance_mode"] and row["embedding_profile"]
                for row in provenance_rows.values()
            )
            and provenance_rows.get("Mem0 OSS", {})
            .get("embedding_profile", "")
            .startswith("fastembed:"),
            target="namespace parity, explicit provenance, shared embeddings except declared Mem0 native path",
            actual=provenance_rows,
        ),
        _check(
            "verified-lifecycle-safety",
            safety.get("unverified_auto_promotions") == 0
            and safety.get("namespace_leakage") == 0
            and float(safety.get("rollback_provenance_parity", 0.0)) == 1.0,
            target="zero unverified promotion/leakage and rollback provenance parity 1.0",
            actual=safety,
        ),
        _check(
            "paired-task-lift",
            int(strongest_lift.get("observations", 0)) >= MIN_TASKS
            and float(strongest_lift.get("lower", 0.0)) > 0.0,
            target="lower 95% paired bootstrap bound > 0 against strongest competitor",
            actual={"engine": strongest_engine, **strongest_lift},
        ),
        _check(
            "lifecycle-noninferiority",
            lifecycle_noninferior,
            target="no worse repeated-error or unnecessary-intervention rate than every competitor",
            actual={
                engine: {
                    "repeated_error_rate": dict(
                        row.get("repeated_error_rate") or {}
                    ).get("mean"),
                    "unnecessary_intervention_rate": dict(
                        row.get("unnecessary_intervention_rate") or {}
                    ).get("mean"),
                }
                for engine, row in {
                    candidate["engine"]: candidate,
                    **competitors,
                }.items()
            },
        ),
        _check(
            "operational-cost-win",
            cost_win,
            target="fewer failed task attempts than the strongest competitor with zero paid API cost",
            actual={
                "candidate_failed_attempts": candidate_failures,
                "competitor_failed_attempts": strongest_failures,
                "candidate_paid_api_cost_usd": candidate.get("paid_api_cost_usd"),
                "competitor_paid_api_cost_usd": strongest.get("paid_api_cost_usd"),
            },
        ),
        _check(
            "context-budget",
            context_ratio <= MAX_CONTEXT_RATIO,
            target=f"candidate context <= {MAX_CONTEXT_RATIO:.1f}x strongest competitor",
            actual={
                "candidate_tokens": candidate_context,
                "competitor_tokens": strongest_context,
                "ratio": context_ratio,
            },
        ),
        _check(
            "latency-budget",
            candidate_latency <= MAX_CANDIDATE_P95_MS,
            target=f"candidate p95 <= {MAX_CANDIDATE_P95_MS:.0f} ms",
            actual=candidate_latency,
        ),
        _check(
            "pareto-quality-cost",
            quality_win
            and cost_win
            and context_ratio <= MAX_CONTEXT_RATIO
            and candidate_latency <= MAX_CANDIDATE_P95_MS,
            target="strict quality and operational-cost wins inside context and latency budgets",
            actual={
                "quality_gain": candidate_success - strongest_success,
                "failed_attempt_reduction": strongest_failures - candidate_failures,
                "context_ratio": context_ratio,
                "candidate_p95_ms": candidate_latency,
            },
        ),
    ]
    blockers = [row["id"] for row in checks if row["status"] != "pass"]
    source_manifest = build_source_manifest(project_root, SOURCE_FILES)
    source_manifest_errors = validate_source_manifest(
        project_root,
        source_manifest,
        require_current_files=True,
    )
    checks.append(
        _check(
            "source-manifest-integrity",
            not source_manifest_errors,
            target="all admission-critical source hashes validate",
            actual=source_manifest_errors,
            evidence={"source_manifest": source_manifest},
        )
    )
    blockers = [row["id"] for row in checks if row["status"] != "pass"]
    benchmark_sha256 = file_sha256(benchmark_path) if benchmark_path else None
    payload = {
        "schema": SCHEMA,
        "status": "admitted" if not blockers else "blocked",
        "admitted": not blockers,
        "generated_at": _utc_now(),
        "source_sha": observed_source_sha,
        "expected_source_sha": expected_source_sha,
        "benchmark": {
            "schema": benchmark.get("schema"),
            "path": benchmark_path.as_posix() if benchmark_path else None,
            "sha256": benchmark_sha256,
            "protocol_hash": protocol.get("hash"),
            "task_fingerprint_sha256": protocol.get("task_fingerprint_sha256"),
            "corpus_fingerprint_sha256": protocol.get("corpus_fingerprint_sha256"),
        },
        "environment_manifest": {
            "hardware": protocol.get("hardware"),
            "versions": {
                candidate.get("engine", "candidate"): candidate.get("system_version"),
                **version_rows,
            },
            "embedding_profiles": {
                candidate.get("engine", "candidate"): candidate.get(
                    "embedding_profile"
                ),
                **{
                    engine: competitors.get(engine, {}).get("embedding_profile")
                    for engine in MANDATORY_ENGINES
                },
            },
        },
        "decision": {
            "candidate": candidate.get("engine"),
            "strongest_competitor": strongest_engine,
            "candidate_task_success": candidate_success,
            "competitor_task_success": strongest_success,
            "paired_lift_ci95": strongest_lift,
            "candidate_failed_attempts": candidate_failures,
            "competitor_failed_attempts": strongest_failures,
            "candidate_context_tokens": candidate_context,
            "competitor_context_tokens": strongest_context,
            "context_ratio": context_ratio,
            "candidate_p95_latency_ms": candidate_latency,
        },
        "summary": {
            "checks_passed": len(checks) - len(blockers),
            "checks_total": len(checks),
            "blocker_ids": blockers,
        },
        "checks": checks,
        "source_manifest": source_manifest,
        "claim_boundary": benchmark.get("claim_boundary"),
    }
    return attach_artifact_integrity(payload)


def render_markdown(payload: Mapping[str, Any]) -> str:
    decision = dict(payload.get("decision") or {})
    summary = dict(payload.get("summary") or {})
    lines = [
        "# WaveMind Competitive Task Admission",
        "",
        f"Status: **{payload.get('status', 'blocked')}**",
        "",
        f"Source SHA: `{payload.get('source_sha', 'unknown')}`",
        "",
        (
            f"Checks: **{summary.get('checks_passed', 0)}/"
            f"{summary.get('checks_total', 0)}**"
        ),
        "",
        "| Metric | WaveMind Verified Experience | Strongest competitor |",
        "|---|---:|---:|",
        f"| Task success | {decision.get('candidate_task_success', 0):.3f} | {decision.get('competitor_task_success', 0):.3f} |",
        f"| Failed task attempts | {decision.get('candidate_failed_attempts', 0):.1f} | {decision.get('competitor_failed_attempts', 0):.1f} |",
        f"| Context tokens | {decision.get('candidate_context_tokens', 0):.0f} | {decision.get('competitor_context_tokens', 0):.0f} |",
        f"| Candidate p95 latency | {decision.get('candidate_p95_latency_ms', 0):.3f} ms | — |",
        "",
        f"Strongest competitor: **{decision.get('strongest_competitor') or 'missing'}**.",
        "",
        "## Checks",
        "",
        "| Check | Status | Target |",
        "|---|---|---|",
    ]
    for row in payload.get("checks") or []:
        lines.append(f"| `{row['id']}` | `{row['status']}` | {row['target']} |")
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            str(payload.get("claim_boundary") or "No broad claim is allowed."),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/competitive_task_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/COMPETITIVE_TASK_ADMISSION.md"),
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args(argv)
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    payload = evaluate_competitive_task_admission(
        benchmark,
        expected_source_sha=args.expected_source_sha,
        benchmark_path=args.benchmark,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.fail_on_blocked and not payload["admitted"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
