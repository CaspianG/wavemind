from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def render_leaderboard_status(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    load_errors: list[str] = []

    matrix = _load_json(root / "benchmarks" / "benchmark_matrix_results.json", load_errors)
    audit = _load_json(root / "benchmarks" / "benchmark_artifact_audit.json", load_errors)
    readiness = _load_json(root / "benchmarks" / "production_readiness_results.json", load_errors)
    evidence = _load_json(root / "benchmarks" / "production_evidence_results.json", load_errors)
    evidence_bundle = _load_json(
        root / "benchmarks" / "production_evidence_bundle_results.json",
        load_errors,
        required=False,
    )
    scale_run_plan = _load_json(
        root / "benchmarks" / "production_scale_run_plan.json",
        load_errors,
        required=False,
    )
    preflight = _load_json(
        root / "benchmarks" / "production_evidence_preflight_results.json",
        load_errors,
        required=False,
    )
    release_claims = _load_json(
        root / "benchmarks" / "release_claims_results.json",
        load_errors,
        required=False,
    )
    scale_gap = _load_json(
        root / "benchmarks" / "scale_gap_results.json",
        load_errors,
        required=False,
    )
    active_active_admission = _load_json(
        root / "benchmarks" / "active_active_admission_results.json",
        load_errors,
        required=False,
    )
    serverless_admission = _load_json(
        root / "benchmarks" / "serverless_admission_results.json",
        load_errors,
        required=False,
    )
    memory_os_admission = _load_json(
        root / "benchmarks" / "memory_os_admission_results.json",
        load_errors,
        required=False,
    )
    memory_os_canary = _load_json(
        root / "benchmarks" / "memory_os_canary_results.json",
        load_errors,
        required=False,
    )
    dispatch = _load_json(
        root / "benchmarks" / "production_evidence_dispatch_results.json",
        load_errors,
        required=False,
    )
    agent_coherence = _load_json(
        root / "benchmarks" / "agent_coherence_results.json",
        load_errors,
        required=False,
    )
    scale_readiness = _load_json(
        root / "benchmarks" / "scale_readiness_results.json",
        load_errors,
        required=False,
    )
    cost_efficiency = _load_json(
        root / "benchmarks" / "cost_efficiency_results.json",
        load_errors,
        required=False,
    )

    benchmarks = matrix.get("benchmarks") if isinstance(matrix.get("benchmarks"), list) else []
    status_counts = Counter(
        str(entry.get("status", "unknown"))
        for entry in benchmarks
        if isinstance(entry, dict)
    )
    category_counts = Counter(
        str(entry.get("category", "unknown"))
        for entry in benchmarks
        if isinstance(entry, dict)
    )

    audit_status = str(audit.get("status", "missing"))
    readiness_status = str(readiness.get("overall_status", "missing"))
    evidence_status = str(evidence.get("overall_status", "missing"))
    preflight_status = str(preflight.get("overall_status", "missing"))
    source_payloads = {
        "benchmarks/benchmark_matrix_results.json": matrix,
        "benchmarks/benchmark_artifact_audit.json": audit,
        "benchmarks/production_readiness_results.json": readiness,
        "benchmarks/production_evidence_results.json": evidence,
        "benchmarks/production_evidence_preflight_results.json": preflight,
        "benchmarks/production_evidence_bundle_results.json": evidence_bundle,
        "benchmarks/release_claims_results.json": release_claims,
        "benchmarks/scale_gap_results.json": scale_gap,
        "benchmarks/active_active_admission_results.json": active_active_admission,
        "benchmarks/serverless_admission_results.json": serverless_admission,
        "benchmarks/memory_os_admission_results.json": memory_os_admission,
        "benchmarks/memory_os_canary_results.json": memory_os_canary,
        "benchmarks/production_evidence_dispatch_results.json": dispatch,
        "benchmarks/production_scale_run_plan.json": scale_run_plan,
        "benchmarks/agent_coherence_results.json": agent_coherence,
        "benchmarks/scale_readiness_results.json": scale_readiness,
        "benchmarks/cost_efficiency_results.json": cost_efficiency,
    }
    publishing_status = _publishing_status(
        audit_status=audit_status,
        readiness_status=readiness_status,
        evidence_status=evidence_status,
        load_errors=load_errors,
    )

    action_required = [
        {
            "id": str(requirement.get("id", "unknown")),
            "title": str(requirement.get("title", "unknown")),
            "artifact": str(requirement.get("artifact", "")),
            "claim_unlocked": str(requirement.get("claim_unlocked", "")),
            "issues": requirement.get("issues", []),
        }
        for requirement in evidence.get("requirements", [])
        if isinstance(requirement, dict)
        and str(requirement.get("status", "")) == "action_required"
    ]

    return {
        "schema": "wavemind.leaderboard_status.v1",
        "generated_at": _status_timestamp(matrix, audit, readiness, evidence),
        "source_ref": matrix.get("source_ref"),
        "workflow_run_id": matrix.get("workflow_run_id"),
        "refresh_profile": matrix.get("refresh_profile"),
        "public_url": "https://caspiang.github.io/wavemind/",
        "publishing_status": publishing_status,
        "publication_contract": _publication_contract(
            root,
            publishing_status=publishing_status,
            source_ref=matrix.get("source_ref"),
            workflow_run_id=matrix.get("workflow_run_id"),
            refresh_profile=matrix.get("refresh_profile"),
        ),
        "freshness_gate": _freshness_gate(
            source_payloads,
            checked_at=str(audit.get("checked_at") or ""),
            max_age_days=audit.get("max_age_days"),
            load_errors=load_errors,
        ),
        "benchmark_matrix": {
            "schema": matrix.get("schema"),
            "generated_at": matrix.get("generated_at"),
            "implemented_count": status_counts.get("implemented", 0),
            "runner_ready_count": status_counts.get("runner-ready", 0),
            "planned_count": status_counts.get("planned", 0),
            "total_count": sum(status_counts.values()),
            "status_counts": dict(sorted(status_counts.items())),
            "category_counts": dict(sorted(category_counts.items())),
        },
        "artifact_audit": {
            "schema": audit.get("schema"),
            "status": audit_status,
            "checked_at": audit.get("checked_at"),
            "age_days": audit.get("age_days"),
            "max_age_days": audit.get("max_age_days"),
            "errors": audit.get("errors", []),
        },
        "production_readiness": {
            "schema": readiness.get("schema"),
            "overall_status": readiness_status,
            "readiness_score": readiness.get("readiness_score"),
            "summary": readiness.get("summary", {}),
        },
        "agent_quality": _agent_quality_status(agent_coherence),
        "memory_os_policy": _memory_os_policy_status(scale_readiness),
        "strict_production_evidence": {
            "schema": evidence.get("schema"),
            "overall_status": evidence_status,
            "summary": evidence.get("summary", {}),
            "action_required": action_required,
        },
        "production_evidence_bundle": {
            "schema": evidence_bundle.get("schema"),
            "claim_status": evidence_bundle.get("claim_status", "missing"),
            "summary": evidence_bundle.get("summary", {}),
            "next_action_count": len(evidence_bundle.get("next_actions", []))
            if isinstance(evidence_bundle.get("next_actions"), list)
            else 0,
            "production_scale_run_contract": evidence_bundle.get(
                "production_scale_run_contract", {}
            ),
        },
        "production_scale_run_plan": {
            "schema": scale_run_plan.get("schema"),
            "overall_status": (scale_run_plan.get("summary") or {}).get("overall_status", "missing"),
            "ready_count": (scale_run_plan.get("summary") or {}).get("ready_count", 0),
            "action_required_count": (scale_run_plan.get("summary") or {}).get("action_required_count", 0),
            "total_profiles": (scale_run_plan.get("summary") or {}).get("total_profiles", 0),
            "target_memories_total": (scale_run_plan.get("summary") or {}).get(
                "target_memories_total", 0
            ),
            "estimated_monthly_total_cost_at_target_qps_usd": (
                scale_run_plan.get("summary") or {}
            ).get("estimated_monthly_total_cost_at_target_qps_usd"),
            "monthly_budget_usd_total": (scale_run_plan.get("summary") or {}).get(
                "monthly_budget_usd_total"
            ),
            "cost_status_counts": (scale_run_plan.get("summary") or {}).get(
                "cost_status_counts", {}
            ),
            "pareto_frontier_profiles": (scale_run_plan.get("summary") or {}).get(
                "pareto_frontier_profiles", []
            ),
            "best_by_target_class": (scale_run_plan.get("summary") or {}).get(
                "best_by_target_class", {}
            ),
            "profiles": (scale_run_plan.get("summary") or {}).get("profiles", []),
        },
        "cost_efficiency": {
            "schema": cost_efficiency.get("schema"),
            "measured_row_count": (cost_efficiency.get("summary") or {}).get(
                "measured_row_count", 0
            ),
            "planned_row_count": (cost_efficiency.get("summary") or {}).get(
                "planned_row_count", 0
            ),
            "measured_slo_pass_count": (cost_efficiency.get("summary") or {}).get(
                "measured_slo_pass_count", 0
            ),
            "measured_valid_cost_count": (cost_efficiency.get("summary") or {}).get(
                "measured_valid_cost_count", 0
            ),
            "planned_valid_cost_count": (cost_efficiency.get("summary") or {}).get(
                "planned_valid_cost_count", 0
            ),
            "measured_frontier_profiles": (cost_efficiency.get("summary") or {}).get(
                "measured_frontier_profiles", []
            ),
            "planned_frontier_profiles": (cost_efficiency.get("summary") or {}).get(
                "planned_frontier_profiles", []
            ),
            "best_measured_by_target_class": (cost_efficiency.get("summary") or {}).get(
                "best_measured_by_target_class", {}
            ),
            "best_planned_by_target_class": (cost_efficiency.get("summary") or {}).get(
                "best_planned_by_target_class", {}
            ),
            "claim_boundary": cost_efficiency.get("claim_boundary", ""),
        },
        "production_evidence_preflight": {
            "schema": preflight.get("schema"),
            "overall_status": preflight_status,
            "summary": preflight.get("summary", {}),
        },
        "production_evidence_dispatch": {
            "schema": dispatch.get("schema"),
            "overall_status": dispatch.get("overall_status", "missing"),
            "summary": dispatch.get("summary", {}),
            "jobs": dispatch.get("jobs", []),
        },
        "release_claims": {
            "schema": release_claims.get("schema"),
            "release_status": release_claims.get("release_status", "missing"),
            "claim_status": release_claims.get("claim_status", "missing"),
            "summary": release_claims.get("summary", {}),
            "allowed_claims": release_claims.get("allowed_claims", []),
            "locked_claims": release_claims.get("locked_claims", []),
        },
        "scale_gap": {
            "schema": scale_gap.get("schema"),
            "overall_status": scale_gap.get("overall_status", "missing"),
            "summary": scale_gap.get("summary", {}),
            "profile_gaps": scale_gap.get("profile_gaps", []),
        },
        "active_active_admission": {
            "schema": active_active_admission.get("schema"),
            "status": active_active_admission.get("status", "missing"),
            "admitted": active_active_admission.get("admitted", False),
            "claim_boundary": active_active_admission.get("claim_boundary", ""),
            "summary": active_active_admission.get("summary", {}),
            "required_evidence": active_active_admission.get("required_evidence", {}),
            "preflight": active_active_admission.get("preflight", {}),
        },
        "serverless_admission": {
            "schema": serverless_admission.get("schema"),
            "status": serverless_admission.get("status", "missing"),
            "admitted": serverless_admission.get("admitted", False),
            "claim_boundary": serverless_admission.get("claim_boundary", ""),
            "summary": serverless_admission.get("summary", {}),
            "required_evidence": serverless_admission.get("required_evidence", {}),
            "preflight": serverless_admission.get("preflight", {}),
        },
        "memory_os_admission": {
            "schema": memory_os_admission.get("schema"),
            "status": memory_os_admission.get("status", "missing"),
            "admitted": memory_os_admission.get("admitted", False),
            "summary": memory_os_admission.get("summary", {}),
            "requirements": memory_os_admission.get("requirements", []),
        },
        "memory_os_canary": {
            "schema": memory_os_canary.get("schema"),
            "status": memory_os_canary.get("status", "missing"),
            "ok": memory_os_canary.get("ok", False),
            "claim_boundary": memory_os_canary.get("claim_boundary", ""),
            "summary": memory_os_canary.get("summary", {}),
            "checks": memory_os_canary.get("checks", []),
        },
        "source_files": list(source_payloads),
        "load_errors": load_errors,
    }


def _publication_contract(
    root: Path,
    *,
    publishing_status: str,
    source_ref: Any,
    workflow_run_id: Any,
    refresh_profile: Any,
) -> dict[str, Any]:
    workflow_path = root / ".github" / "workflows" / "benchmark-leaderboard.yml"
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        workflow = ""

    weekly_cron = 'cron: "17 4 * * 1"' in workflow or "cron: '17 4 * * 1'" in workflow
    manual_dispatch = "workflow_dispatch:" in workflow
    pages_upload = "actions/upload-pages-artifact@v3" in workflow
    pages_deploy = "actions/deploy-pages@v4" in workflow
    review_artifact = "name: benchmark-leaderboard" in workflow
    no_bot_commit_to_main = "git push" not in workflow and "git commit -m" not in workflow
    strict_freshness = "--max-age-days 8" in workflow
    status_json_copied = "docs/data/leaderboard-status.json" in workflow

    checks = {
        "weekly_schedule": weekly_cron,
        "manual_dispatch": manual_dispatch,
        "github_pages_upload": pages_upload,
        "github_pages_deploy": pages_deploy,
        "review_artifact_uploaded": review_artifact,
        "no_scheduled_bot_commit_to_main": no_bot_commit_to_main,
        "strict_freshness_gate": strict_freshness,
        "machine_status_published": status_json_copied,
    }
    return {
        "schema": "wavemind.leaderboard_publication.v1",
        "status": "pass" if all(checks.values()) else "action_required",
        "workflow": ".github/workflows/benchmark-leaderboard.yml",
        "schedule_cron": "17 4 * * 1",
        "timezone": "UTC",
        "public_url": "https://caspiang.github.io/wavemind/",
        "publishing_status": publishing_status,
        "source_ref": source_ref,
        "workflow_run_id": workflow_run_id,
        "refresh_profile": refresh_profile,
        "expected_scheduled_refresh_profile": "weekly-fast",
        "github_pages": {
            "artifact_action": "actions/upload-pages-artifact@v3",
            "deploy_action": "actions/deploy-pages@v4",
            "status_json": "data/leaderboard-status.json",
        },
        "review_policy": (
            "Scheduled runs publish GitHub Pages and upload the benchmark-leaderboard "
            "artifact for maintainer review; they do not commit generated benchmark "
            "artifacts back to main."
        ),
        "claim_policy": (
            "Dashboard rows may publish checked-in benchmark evidence; remote, "
            "managed-serverless, 50M, and 100M production claims stay locked until "
            "strict evidence artifacts pass."
        ),
        "checks": checks,
    }


def _load_json(path: Path, errors: list[str], *, required: bool = True) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            errors.append(f"missing {path.as_posix()}")
        return {}
    except Exception as exc:
        errors.append(f"cannot read {path.as_posix()}: {exc}")
        return {}


def _publishing_status(
    *,
    audit_status: str,
    readiness_status: str,
    evidence_status: str,
    load_errors: list[str],
) -> str:
    if load_errors:
        return "blocked"
    if audit_status != "pass":
        return "blocked"
    if readiness_status != "pass":
        return "blocked"
    if evidence_status == "fail":
        return "blocked"
    if evidence_status == "action_required":
        return "publishable_with_claim_limits"
    if evidence_status == "pass":
        return "publishable"
    return "publishable_with_unknown_evidence"


def _agent_quality_status(payload: dict[str, Any]) -> dict[str, Any]:
    results = _engine_results(payload)
    wavemind = results.get("WaveMind", {})
    memory_os = results.get("WaveMind + Memory OS", {})
    baselines = [
        result
        for engine, result in results.items()
        if not engine.startswith("WaveMind") and isinstance(result, dict)
    ]
    best_baseline = max(
        (float(result.get("task_success_rate", 0.0) or 0.0) for result in baselines),
        default=0.0,
    )
    wavemind_success = float(wavemind.get("task_success_rate", 0.0) or 0.0)
    wavemind_stale = float(wavemind.get("stale_error_rate", 1.0) or 0.0)
    wavemind_context_saved = float(wavemind.get("context_budget_saved", 0.0) or 0.0)
    memory_os_payload = (
        dict(memory_os.get("memory_os") or {})
        if isinstance(memory_os.get("memory_os"), dict)
        else {}
    )
    status = "missing"
    if wavemind:
        status = "pass" if wavemind_success > best_baseline and wavemind_stale <= 0.05 else "watch"
    return {
        "schema": payload.get("schema"),
        "status": status,
        "scenario": payload.get("scenario", {}),
        "wavemind_task_success_rate": wavemind_success,
        "best_baseline_task_success_rate": best_baseline,
        "task_success_lift": wavemind_success - best_baseline,
        "wavemind_stale_error_rate": wavemind_stale,
        "wavemind_context_budget_saved": wavemind_context_saved,
        "wavemind_coherent_turns": int(wavemind.get("coherent_turns", 0) or 0),
        "wavemind_avg_latency_ms": float(wavemind.get("avg_latency_ms", 0.0) or 0.0),
        "memory_os_task_success_rate": float(memory_os.get("task_success_rate", 0.0) or 0.0),
        "memory_os_avg_latency_ms": float(memory_os.get("avg_latency_ms", 0.0) or 0.0),
        "memory_os_worker_ok": bool(memory_os_payload.get("worker_ok", False)),
        "memory_os_hot_queries": int(memory_os_payload.get("hot_queries", 0) or 0),
        "memory_os_prewarm_warmed": int(memory_os_payload.get("prewarm_warmed", 0) or 0),
        "memory_os_predictive_prefetch_warmed": int(
            memory_os_payload.get("predictive_prefetch_warmed", 0) or 0
        ),
        "memory_os_priority_predictions": int(memory_os_payload.get("priority_predictions", 0) or 0),
        "memory_os_cache_hit_rate": float(memory_os_payload.get("cache_hit_rate", 0.0) or 0.0),
        "memory_os_policy_status": memory_os_payload.get("policy_status", "missing"),
        "baseline_engines": sorted(
            engine for engine in results if not engine.startswith("WaveMind")
        ),
        "wavemind_variant_engines": sorted(
            engine for engine in results if engine.startswith("WaveMind")
        ),
        "source": "benchmarks/agent_coherence_results.json",
    }


def _memory_os_policy_status(payload: dict[str, Any]) -> dict[str, Any]:
    results = _engine_results(payload)
    row = results.get("WaveMind Memory OS", {})
    decision_ids = list(row.get("policy_decision_ids", []) or [])
    strategies = dict(row.get("policy_decision_strategies", {}) or {})
    status = str(row.get("policy_status") or "missing")
    required = {
        "prefetch-policy",
        "priority-policy",
        "forgetting-policy",
        "consolidation-policy",
        "scale-policy",
        "coordination-policy",
    }
    contract_status = "missing"
    if row:
        contract_status = "pass" if required.issubset(set(decision_ids)) else "action_required"
    return {
        "schema": payload.get("schema") or "wavemind.scale_readiness_benchmark.v1",
        "status": contract_status,
        "policy_status": status,
        "decision_count": int(row.get("policy_decision_count", 0) or 0),
        "decision_ids": decision_ids,
        "decision_statuses": list(row.get("policy_decision_statuses", []) or []),
        "decision_strategies": strategies,
        "scale_strategy": strategies.get("scale-policy"),
        "coordination_strategy": strategies.get("coordination-policy"),
        "history_trend": row.get("policy_history_trend", "missing"),
        "history_previous_runs": int(row.get("policy_history_previous_runs", 0) or 0),
        "repeated_required_ids": list(row.get("policy_repeated_required_ids", []) or []),
        "history_escalations": int(row.get("policy_history_escalations", 0) or 0),
        "required_decisions_present": required.issubset(set(decision_ids)),
        "source": "benchmarks/scale_readiness_results.json",
    }


def _engine_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        return {}
    return {
        str(row.get("engine")): row
        for row in results
        if isinstance(row, dict) and row.get("engine") is not None
    }


def _freshness_gate(
    source_payloads: dict[str, dict[str, Any]],
    *,
    checked_at: str,
    max_age_days: Any,
    load_errors: list[str],
) -> dict[str, Any]:
    reference_time = _parse_iso_timestamp(checked_at)
    max_age = _safe_float(max_age_days)
    sources: list[dict[str, Any]] = []

    for path, payload in source_payloads.items():
        timestamp_key, timestamp = _payload_timestamp(payload)
        parsed = _parse_iso_timestamp(timestamp)
        age_days = None
        status = "pass"
        if not payload:
            status = "missing"
        elif parsed is None:
            status = "no_timestamp"
        elif reference_time is not None:
            age_days = max(0.0, (reference_time - parsed).total_seconds() / 86400.0)
            if max_age is not None and age_days > max_age:
                status = "stale"

        sources.append(
            {
                "path": path,
                "schema": payload.get("schema"),
                "timestamp_key": timestamp_key,
                "timestamp": timestamp,
                "age_days": age_days,
                "status": status,
            }
        )

    stale = [row["path"] for row in sources if row["status"] == "stale"]
    missing = [row["path"] for row in sources if row["status"] == "missing"]
    no_timestamp = [row["path"] for row in sources if row["status"] == "no_timestamp"]
    status = "pass"
    if load_errors or stale or missing or no_timestamp:
        status = "action_required"

    return {
        "schema": "wavemind.leaderboard_freshness.v1",
        "status": status,
        "checked_at": checked_at or None,
        "max_age_days": max_age,
        "source_count": len(sources),
        "fresh_count": sum(1 for row in sources if row["status"] == "pass"),
        "stale_count": len(stale),
        "missing_count": len(missing),
        "no_timestamp_count": len(no_timestamp),
        "load_error_count": len(load_errors),
        "stale_sources": stale,
        "missing_sources": missing,
        "no_timestamp_sources": no_timestamp,
        "sources": sources,
    }


def _payload_timestamp(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in ("checked_at", "generated_at", "created_at", "updated_at"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return key, value
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ("checked_at", "generated_at", "created_at", "updated_at"):
            value = summary.get(key)
            if isinstance(value, str) and value:
                return f"summary.{key}", value
    return None, None


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_timestamp(*payloads: dict[str, Any]) -> str | None:
    for key in ("checked_at", "generated_at"):
        values = [
            str(payload.get(key))
            for payload in payloads
            if isinstance(payload.get(key), str) and payload.get(key)
        ]
        if values:
            return max(values)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/data/leaderboard-status.json"))
    args = parser.parse_args()

    payload = render_leaderboard_status()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
