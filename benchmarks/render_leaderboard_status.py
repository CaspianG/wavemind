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
    production_evidence_env = _load_json(
        root / "benchmarks" / "production_evidence_env_contract.json",
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
    strict_evidence_readiness = _load_json(
        root / "benchmarks" / "strict_evidence_readiness_results.json",
        load_errors,
        required=False,
    )
    cluster_admission = _load_json(
        root / "benchmarks" / "cluster_admission_results.json",
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
    multimodal_admission = _load_json(
        root / "benchmarks" / "multimodal_admission_results.json",
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
    memory_os_evolution = _load_json(
        root / "benchmarks" / "memory_os_policy_evolution_results.json",
        load_errors,
        required=False,
    )
    memory_os_policy_bundle = _load_json(
        root / "benchmarks" / "memory_os_policy_bundle_results.json",
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
    agent_impact = _load_json(
        root / "benchmarks" / "agent_impact_results.json",
        load_errors,
        required=False,
    )
    structured_memory = _load_json(
        root / "benchmarks" / "structured_memory_results.json",
        load_errors,
        required=False,
    )
    memory_os_intelligence = _load_json(
        root / "benchmarks" / "memory_os_intelligence_results.json",
        load_errors,
        required=False,
    )
    cluster_autoscale = _load_json(
        root / "benchmarks" / "cluster_autoscale_results.json",
        load_errors,
        required=False,
    )
    kubernetes_operator_failover = _load_json(
        root / "benchmarks" / "kubernetes_operator_smoke_results.json",
        load_errors,
        required=False,
    )
    kubernetes_cluster_network_failure = _load_json(
        root / "benchmarks" / "kubernetes_cluster_network_smoke_results.json",
        load_errors,
        required=False,
    )
    kubernetes_active_active_region_failure = _load_json(
        root / "benchmarks" / "kubernetes_active_active_region_smoke_results.json",
        load_errors,
        required=False,
    )
    kubernetes_serverless_lifecycle = _load_json(
        root / "benchmarks" / "kubernetes_serverless_lifecycle_smoke_results.json",
        load_errors,
        required=False,
    )
    kubernetes_postgres_qdrant_dr = _load_json(
        root / "benchmarks" / "kubernetes_postgres_qdrant_dr_smoke_results.json",
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
        "benchmarks/production_evidence_env_contract.json": production_evidence_env,
        "benchmarks/production_evidence_bundle_results.json": evidence_bundle,
        "benchmarks/release_claims_results.json": release_claims,
        "benchmarks/scale_gap_results.json": scale_gap,
        "benchmarks/strict_evidence_readiness_results.json": strict_evidence_readiness,
        "benchmarks/cluster_admission_results.json": cluster_admission,
        "benchmarks/active_active_admission_results.json": active_active_admission,
        "benchmarks/serverless_admission_results.json": serverless_admission,
        "benchmarks/multimodal_admission_results.json": multimodal_admission,
        "benchmarks/memory_os_admission_results.json": memory_os_admission,
        "benchmarks/memory_os_canary_results.json": memory_os_canary,
        "benchmarks/memory_os_policy_evolution_results.json": memory_os_evolution,
        "benchmarks/memory_os_policy_bundle_results.json": memory_os_policy_bundle,
        "benchmarks/production_evidence_dispatch_results.json": dispatch,
        "benchmarks/production_scale_run_plan.json": scale_run_plan,
        "benchmarks/agent_coherence_results.json": agent_coherence,
        "benchmarks/agent_impact_results.json": agent_impact,
        "benchmarks/structured_memory_results.json": structured_memory,
        "benchmarks/memory_os_intelligence_results.json": memory_os_intelligence,
        "benchmarks/cluster_autoscale_results.json": cluster_autoscale,
        "benchmarks/kubernetes_operator_smoke_results.json": kubernetes_operator_failover,
        "benchmarks/kubernetes_cluster_network_smoke_results.json": (
            kubernetes_cluster_network_failure
        ),
        "benchmarks/kubernetes_active_active_region_smoke_results.json": (
            kubernetes_active_active_region_failure
        ),
        "benchmarks/kubernetes_serverless_lifecycle_smoke_results.json": (
            kubernetes_serverless_lifecycle
        ),
        "benchmarks/kubernetes_postgres_qdrant_dr_smoke_results.json": (
            kubernetes_postgres_qdrant_dr
        ),
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
        "agent_impact": _agent_impact_status(agent_impact),
        "structured_memory": _structured_memory_status(structured_memory),
        "multimodal_admission": {
            "schema": multimodal_admission.get("schema"),
            "status": multimodal_admission.get("status", "missing"),
            "admitted": multimodal_admission.get("admitted", False),
            "claim_boundary": multimodal_admission.get("claim_boundary", ""),
            "summary": multimodal_admission.get("summary", {}),
            "structured_contract": multimodal_admission.get("structured_contract", {}),
            "required_evidence": multimodal_admission.get("required_evidence", {}),
            "requested_evidence": multimodal_admission.get("requested_evidence", {}),
        },
        "memory_os_intelligence": _memory_os_intelligence_status(memory_os_intelligence),
        "cluster_autoscale": _cluster_autoscale_status(cluster_autoscale),
        "kubernetes_operator_failover": _kubernetes_operator_failover_status(
            kubernetes_operator_failover
        ),
        "kubernetes_cluster_network_failure": _kubernetes_cluster_network_failure_status(
            kubernetes_cluster_network_failure
        ),
        "kubernetes_active_active_region_failure": (
            _kubernetes_active_active_region_failure_status(
                kubernetes_active_active_region_failure
            )
        ),
        "kubernetes_serverless_lifecycle": _kubernetes_serverless_lifecycle_status(
            kubernetes_serverless_lifecycle
        ),
        "kubernetes_postgres_qdrant_dr": _kubernetes_postgres_qdrant_dr_status(
            kubernetes_postgres_qdrant_dr
        ),
        "memory_os_policy": _memory_os_policy_status(scale_readiness),
        "memory_os_policy_evolution": _memory_os_policy_evolution_status(
            memory_os_evolution
        ),
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
        "production_evidence_env": {
            "schema": production_evidence_env.get("schema"),
            "overall_status": production_evidence_env.get("overall_status", "missing"),
            "summary": production_evidence_env.get("summary", {}),
            "github_secret_count": len(
                (production_evidence_env.get("github_actions") or {}).get(
                    "secret_names", []
                )
            ),
            "check_count": len(production_evidence_env.get("checks", []))
            if isinstance(production_evidence_env.get("checks"), list)
            else 0,
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
        "strict_evidence_readiness": {
            "schema": strict_evidence_readiness.get("schema"),
            "status": strict_evidence_readiness.get("status", "missing"),
            "readiness_status": strict_evidence_readiness.get(
                "readiness_status", "missing"
            ),
            "claim_status": strict_evidence_readiness.get("claim_status", "missing"),
            "summary": strict_evidence_readiness.get("summary", {}),
            "checks": strict_evidence_readiness.get("checks", []),
            "requirements": strict_evidence_readiness.get("requirements", []),
            "claim_boundary": strict_evidence_readiness.get("claim_boundary", ""),
        },
        "cluster_admission": {
            "schema": cluster_admission.get("schema"),
            "status": cluster_admission.get("status", "missing"),
            "admitted": cluster_admission.get("admitted", False),
            "claim_boundary": cluster_admission.get("claim_boundary", ""),
            "summary": cluster_admission.get("summary", {}),
            "required_evidence": cluster_admission.get("required_evidence", {}),
            "requested_evidence": cluster_admission.get("requested_evidence", {}),
            "preflight": cluster_admission.get("preflight", {}),
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
        "memory_os_policy_bundle": {
            "schema": memory_os_policy_bundle.get("schema"),
            "status": memory_os_policy_bundle.get("status", "missing"),
            "ok": memory_os_policy_bundle.get("ok", False),
            "claim_boundary": memory_os_policy_bundle.get("claim_boundary", ""),
            "summary": memory_os_policy_bundle.get("summary", {}),
            "checks": memory_os_policy_bundle.get("checks", []),
            "runtime_policy": memory_os_policy_bundle.get("runtime_policy", {}),
            "kubernetes_patch": memory_os_policy_bundle.get("kubernetes_patch", {}),
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


def _agent_impact_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    status = "missing"
    if summary:
        wins = int(summary.get("wavemind_primary_wins", 0) or 0)
        benchmark_count = int(summary.get("benchmark_count", 0) or 0)
        average_lift = float(summary.get("average_primary_lift", 0.0) or 0.0)
        status = "pass" if benchmark_count > 0 and wins == benchmark_count and average_lift > 0 else "watch"
    return {
        "schema": payload.get("schema"),
        "status": status,
        "benchmark_count": summary.get("benchmark_count", 0),
        "wavemind_row_count": summary.get("wavemind_row_count", 0),
        "baseline_row_count": summary.get("baseline_row_count", 0),
        "wavemind_primary_wins": summary.get("wavemind_primary_wins", 0),
        "average_primary_lift": summary.get("average_primary_lift"),
        "average_context_saved": summary.get("average_context_saved"),
        "average_stale_safety_score": summary.get("average_stale_safety_score"),
        "best_impact_profile": summary.get("best_impact_profile"),
        "source_files": summary.get("source_files", []),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/agent_impact_results.json",
    }


def _structured_memory_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    passed_checks = sum(
        1 for check in checks if isinstance(check, dict) and bool(check.get("pass"))
    )
    total_checks = len(checks)
    return {
        "schema": payload.get("schema"),
        "status": summary.get("status", "missing"),
        "modality_count": summary.get("modality_count", 0),
        "modalities": summary.get("modalities", []),
        "check_count": total_checks,
        "passed_check_count": passed_checks,
        "precision_at_1": summary.get("precision_at_1"),
        "cross_modal_precision_at_1": summary.get("cross_modal_precision_at_1"),
        "cross_modal_vectors_persisted_rate": summary.get("cross_modal_vectors_persisted_rate"),
        "cross_modal_provenance_rate": summary.get("cross_modal_provenance_rate"),
        "precomputed_vector_precision_at_1": summary.get("precomputed_vector_precision_at_1"),
        "precomputed_vector_persisted_rate": summary.get("precomputed_vector_persisted_rate"),
        "encoder_contract_ok": summary.get("encoder_contract_ok"),
        "encoder_contract_margin": summary.get("encoder_contract_margin"),
        "encoder_contract_min_required_margin": summary.get(
            "encoder_contract_min_required_margin"
        ),
        "encoder_health_ok": summary.get("encoder_health_ok"),
        "encoder_health_global_precision_at_1": summary.get(
            "encoder_health_global_precision_at_1"
        ),
        "encoder_health_target_modality_routing_rate": summary.get(
            "encoder_health_target_modality_routing_rate"
        ),
        "encoder_health_dimension_match_rate": summary.get(
            "encoder_health_dimension_match_rate"
        ),
        "encoder_health_payload_encode_p95_ms": summary.get(
            "encoder_health_payload_encode_p95_ms"
        ),
        "encoder_health_query_encode_p95_ms": summary.get(
            "encoder_health_query_encode_p95_ms"
        ),
        "encoder_health_margin": summary.get("encoder_health_margin"),
        "encoder_health_min_required_margin": summary.get(
            "encoder_health_min_required_margin"
        ),
        "temporal_event_precision_at_1": summary.get("temporal_event_precision_at_1"),
        "temporal_event_persistence_rate": summary.get("temporal_event_persistence_rate"),
        "temporal_event_provenance_rate": summary.get("temporal_event_provenance_rate"),
        "knowledge_graph_precision_at_1": summary.get("knowledge_graph_precision_at_1"),
        "knowledge_graph_path_precision_at_1": summary.get(
            "knowledge_graph_path_precision_at_1"
        ),
        "knowledge_graph_persistence_rate": summary.get("knowledge_graph_persistence_rate"),
        "knowledge_graph_provenance_rate": summary.get("knowledge_graph_provenance_rate"),
        "cross_modal_avg_latency_ms": summary.get("cross_modal_avg_latency_ms"),
        "temporal_event_avg_latency_ms": summary.get("temporal_event_avg_latency_ms"),
        "knowledge_graph_avg_latency_ms": summary.get("knowledge_graph_avg_latency_ms"),
        "asset_manifest_verified": summary.get("asset_manifest_verified"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/structured_memory_results.json",
    }


def _memory_os_intelligence_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    passed_checks = sum(
        1 for check in checks if isinstance(check, dict) and bool(check.get("pass"))
    )
    total_checks = len(checks)
    return {
        "schema": payload.get("schema"),
        "status": summary.get("status", "missing"),
        "check_count": total_checks,
        "passed_check_count": passed_checks,
        "worker_ok": summary.get("worker_ok"),
        "hot_queries": summary.get("hot_queries"),
        "prewarm_warmed": summary.get("prewarm_warmed"),
        "predictive_prefetch_warmed": summary.get("predictive_prefetch_warmed"),
        "transition_prefetch_hit": summary.get("transition_prefetch_hit"),
        "concepts_created": summary.get("concepts_created"),
        "concept_recall": summary.get("concept_recall"),
        "user_feedback_events": summary.get("user_feedback_events"),
        "positive_feedback_priority_delta": summary.get("positive_feedback_priority_delta"),
        "negative_feedback_priority_delta": summary.get("negative_feedback_priority_delta"),
        "priority_predictions": summary.get("priority_predictions"),
        "priority_boost_total": summary.get("priority_boost_total"),
        "forgetting_demotions": summary.get("forgetting_demotions"),
        "forgetting_decay_total": summary.get("forgetting_decay_total"),
        "policy_status": summary.get("policy_status"),
        "policy_decision_count": summary.get("policy_decision_count"),
        "policy_decision_ids": summary.get("policy_decision_ids", []),
        "execution_safe_to_run": summary.get("execution_safe_to_run"),
        "execution_requires_shared_cache": summary.get("execution_requires_shared_cache"),
        "execution_requires_distributed_lock": summary.get(
            "execution_requires_distributed_lock"
        ),
        "redis_memory_os_cross_worker_hit": summary.get("redis_memory_os_cross_worker_hit"),
        "redis_memory_os_busy_lock_skipped": summary.get("redis_memory_os_busy_lock_skipped"),
        "agent_task_success_rate": summary.get("agent_task_success_rate"),
        "agent_stale_error_rate": summary.get("agent_stale_error_rate"),
        "agent_context_budget_saved": summary.get("agent_context_budget_saved"),
        "agent_memory_os_cache_hit_rate": summary.get("agent_memory_os_cache_hit_rate"),
        "canary_status": summary.get("canary_status"),
        "canary_admitted": summary.get("canary_admitted"),
        "admission_status": summary.get("admission_status"),
        "admission_blocker_count": summary.get("admission_blocker_count"),
        "admission_blocker_ids": summary.get("admission_blocker_ids", []),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source_files": payload.get("source_files", []),
        "source": "benchmarks/memory_os_intelligence_results.json",
    }


def _cluster_autoscale_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    passed_checks = sum(
        1 for check in checks if isinstance(check, dict) and bool(check.get("pass"))
    )
    total_checks = len(checks)
    return {
        "schema": payload.get("schema"),
        "status": summary.get("status", "missing"),
        "check_count": total_checks,
        "passed_check_count": passed_checks,
        "simulated_memories": summary.get("simulated_memories"),
        "namespace_count": summary.get("namespace_count"),
        "planner_node_count": summary.get("planner_node_count"),
        "planner_replication_factor": summary.get("planner_replication_factor"),
        "planner_node_loss_min_availability": summary.get(
            "planner_node_loss_min_availability"
        ),
        "planner_zone_loss_min_availability": summary.get(
            "planner_zone_loss_min_availability"
        ),
        "autoscaler_status": summary.get("autoscaler_status"),
        "autoscaler_target_memories": summary.get("autoscaler_target_memories"),
        "autoscaler_required_nodes": summary.get("autoscaler_required_nodes"),
        "autoscaler_additional_nodes": summary.get("autoscaler_additional_nodes"),
        "autoscaler_target_within_headroom": summary.get(
            "autoscaler_target_within_headroom"
        ),
        "autoscaler_rebalance_batches": summary.get("autoscaler_rebalance_batches"),
        "operator_status_phase": summary.get("operator_status_phase"),
        "operator_status_ready": summary.get("operator_status_ready"),
        "operator_replicas": summary.get("operator_replicas"),
        "operator_controller_replicas": summary.get("operator_controller_replicas"),
        "operator_leader_election": summary.get("operator_leader_election"),
        "operator_lease_backend": summary.get("operator_lease_backend"),
        "operator_pdb_rbac": summary.get("operator_pdb_rbac"),
        "operator_has_pod_disruption_budget": summary.get(
            "operator_has_pod_disruption_budget"
        ),
        "operator_pdb_min_available": summary.get("operator_pdb_min_available"),
        "operator_statefulset_rolling_update": summary.get(
            "operator_statefulset_rolling_update"
        ),
        "operator_statefulset_topology_spread_keys": summary.get(
            "operator_statefulset_topology_spread_keys", []
        ),
        "operator_rebalance_move_count": summary.get("operator_rebalance_move_count"),
        "operator_memory_os_ready": summary.get("operator_memory_os_ready"),
        "control_plane_ok": summary.get("control_plane_ok"),
        "distributed_http_recalled_after_primary_loss": summary.get(
            "distributed_http_recalled_after_primary_loss"
        ),
        "distributed_http_concurrent_query_hit_rate": summary.get(
            "distributed_http_concurrent_query_hit_rate"
        ),
        "active_active_convergence_rate": summary.get("active_active_convergence_rate"),
        "http_active_active_success_rate": summary.get("http_active_active_success_rate"),
        "field_crdt_commutative_convergence": summary.get(
            "field_crdt_commutative_convergence"
        ),
        "capacity_target_memories": summary.get("capacity_target_memories"),
        "capacity_node_count": summary.get("capacity_node_count"),
        "capacity_zones": summary.get("capacity_zones"),
        "capacity_replication_factor": summary.get("capacity_replication_factor"),
        "capacity_valid_plan": summary.get("capacity_valid_plan"),
        "capacity_distinct_replica_rate": summary.get("capacity_distinct_replica_rate"),
        "capacity_zone_spread_rate": summary.get("capacity_zone_spread_rate"),
        "capacity_recommended_autoscaling_max_replicas": summary.get(
            "capacity_recommended_autoscaling_max_replicas"
        ),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/cluster_autoscale_results.json",
    }


def _kubernetes_operator_failover_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status", "missing"),
        "environment": payload.get("environment"),
        "evidence_source": payload.get("evidence_source"),
        "source_ref": payload.get("source_ref"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_run_url": payload.get("workflow_run_url"),
        "passed_checks": summary.get("passed_checks"),
        "check_count": summary.get("check_count"),
        "node_count": summary.get("node_count"),
        "operator_pod_count": summary.get("operator_pod_count"),
        "operator_node_count": summary.get("operator_node_count"),
        "lease_transitions_after": summary.get("lease_transitions_after"),
        "ready_replicas_after_scale": summary.get("ready_replicas_after_scale"),
        "cluster_status_holder": summary.get("cluster_status_holder"),
        "next_holder": summary.get("next_holder"),
        "data_pod_uid_changed": summary.get("data_pod_uid_changed"),
        "api_healthy_after_recovery": summary.get("api_healthy_after_recovery"),
        "topology_spread_constraint_count": summary.get(
            "topology_spread_constraint_count"
        ),
        "pdb_min_available": summary.get("pdb_min_available"),
        "pdb_disruptions_allowed": summary.get("pdb_disruptions_allowed"),
        "rolling_upgrade_revision_changed": summary.get(
            "rolling_upgrade_revision_changed"
        ),
        "rolling_upgrade_replaced_pods": summary.get("rolling_upgrade_replaced_pods"),
        "api_healthy_after_upgrade": summary.get("api_healthy_after_upgrade"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/kubernetes_operator_smoke_results.json",
    }


def _kubernetes_cluster_network_failure_status(
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    outage = observed.get("outage") if isinstance(observed.get("outage"), dict) else {}
    recovered = (
        observed.get("recovered")
        if isinstance(observed.get("recovered"), dict)
        else {}
    )
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status", "missing"),
        "environment": payload.get("environment"),
        "evidence_source": payload.get("evidence_source"),
        "source_ref": payload.get("source_ref"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_run_url": payload.get("workflow_run_url"),
        "passed_checks": summary.get("passed_checks"),
        "check_count": summary.get("check_count"),
        "service_node_count": len(observed.get("service_addresses") or []),
        "zone_count": observed.get("zone_count"),
        "failure_method": observed.get("failure_method"),
        "target_worker": observed.get("target_worker"),
        "target_zone": observed.get("target_zone"),
        "outage_duration_ms": observed.get("outage_duration_ms"),
        "outage_hit_rate": outage.get("hit_rate"),
        "failed_nodes_during_outage": outage.get("failed_nodes_seen"),
        "recovery_hit_rate": recovered.get("hit_rate"),
        "failed_nodes_after_recovery": recovered.get("failed_nodes_seen"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/kubernetes_cluster_network_smoke_results.json",
    }


def _kubernetes_active_active_region_failure_status(
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    seed = observed.get("seed") if isinstance(observed.get("seed"), dict) else {}
    outage = observed.get("outage") if isinstance(observed.get("outage"), dict) else {}
    recovered = (
        observed.get("recovered")
        if isinstance(observed.get("recovered"), dict)
        else {}
    )
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status", "missing"),
        "environment": payload.get("environment"),
        "evidence_source": payload.get("evidence_source"),
        "source_ref": payload.get("source_ref"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_run_url": payload.get("workflow_run_url"),
        "passed_checks": summary.get("passed_checks"),
        "check_count": summary.get("check_count"),
        "region_count": len(observed.get("region_addresses") or []),
        "zone_count": observed.get("zone_count"),
        "all_regions_use_pvc": observed.get("all_regions_use_pvc"),
        "failure_method": observed.get("failure_method"),
        "target_region": observed.get("target_region"),
        "outage_duration_ms": observed.get("outage_duration_ms"),
        "seed_writes": seed.get("writes"),
        "outage_unavailable_regions": outage.get("unavailable_regions"),
        "outage_writes": outage.get("writes"),
        "outage_convergence_rate": (outage.get("verification") or {}).get(
            "convergence_rate"
        ),
        "outage_delete_suppression_rate": (outage.get("verification") or {}).get(
            "delete_suppression_rate"
        ),
        "recovery_convergence_rate": (recovered.get("verification") or {}).get(
            "convergence_rate"
        ),
        "recovery_delete_suppression_rate": (
            recovered.get("verification") or {}
        ).get("delete_suppression_rate"),
        "final_noop_records_imported": (recovered.get("sync") or {}).get(
            "final_noop_records_imported"
        ),
        "final_noop_tombstones_imported": (recovered.get("sync") or {}).get(
            "final_noop_tombstones_imported"
        ),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/kubernetes_active_active_region_smoke_results.json",
    }


def _kubernetes_serverless_lifecycle_status(
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    cross = observed.get("cross_replica") if isinstance(observed.get("cross_replica"), dict) else {}
    burst = observed.get("burst") if isinstance(observed.get("burst"), dict) else {}
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status", "missing"),
        "environment": payload.get("environment"),
        "evidence_source": payload.get("evidence_source"),
        "source_ref": payload.get("source_ref"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_run_url": payload.get("workflow_run_url"),
        "passed_checks": summary.get("passed_checks"),
        "check_count": summary.get("check_count"),
        "persistent_volume_claims": observed.get("persistent_volume_claims"),
        "cold_start_ms": observed.get("cold_start_ms"),
        "restored_after_zero_rate": (observed.get("restored_after_zero") or {}).get("rate"),
        "ready_replicas": observed.get("ready_replicas"),
        "zone_count": observed.get("zone_count"),
        "visible_replicas": cross.get("visible_replicas"),
        "suppressed_replicas": cross.get("suppressed_replicas"),
        "write_propagation_ms": cross.get("write_propagation_ms"),
        "delete_propagation_ms": cross.get("delete_propagation_ms"),
        "burst_requests_per_second": burst.get("requests_per_second"),
        "burst_p99_ms": burst.get("p99_ms"),
        "final_restore_rate": (observed.get("final_restore") or {}).get("rate"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/kubernetes_serverless_lifecycle_smoke_results.json",
    }


def _kubernetes_postgres_qdrant_dr_status(
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    stats = observed.get("recovery_stats") if isinstance(observed.get("recovery_stats"), dict) else {}
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status", "missing"),
        "environment": payload.get("environment"),
        "evidence_source": payload.get("evidence_source"),
        "source_ref": payload.get("source_ref"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_run_url": payload.get("workflow_run_url"),
        "passed_checks": summary.get("passed_checks"),
        "check_count": summary.get("check_count"),
        "backup_format": observed.get("backup_format"),
        "backup_bytes": observed.get("backup_bytes"),
        "source_state_stopped": observed.get("source_state_stopped"),
        "recovery_pvcs": observed.get("recovery_pvcs"),
        "restored_rate": (observed.get("restored") or {}).get("rate"),
        "index_healthy": stats.get("index_healthy"),
        "index_expected_records": stats.get("index_expected_records"),
        "index_vector_records": stats.get("index_vector_records"),
        "restored_after_api_replacement_rate": (
            observed.get("restored_after_api_replacement") or {}
        ).get("rate"),
        "restore_elapsed_ms": observed.get("restore_elapsed_ms"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/kubernetes_postgres_qdrant_dr_smoke_results.json",
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


def _memory_os_policy_evolution_status(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    passed_checks = sum(
        1 for check in checks if isinstance(check, dict) and bool(check.get("pass"))
    )
    total_checks = len(checks)
    return {
        "schema": payload.get("schema") or "wavemind.memory_os_policy_evolution.v1",
        "status": payload.get("status") or summary.get("status", "missing"),
        "ok": bool(payload.get("ok", False)),
        "deployment": payload.get("deployment"),
        "cycles": payload.get("cycles") or summary.get("cycles", 0),
        "target_memories": payload.get("target_memories"),
        "namespace_count": payload.get("namespace_count"),
        "node_count": payload.get("node_count"),
        "replayed_query_count": payload.get("replayed_query_count"),
        "check_count": total_checks,
        "passed_check_count": passed_checks,
        "decision_coverage_rate": summary.get("decision_coverage_rate"),
        "repeated_required_cycle_count": summary.get("repeated_required_cycle_count"),
        "history_suggestion_count": summary.get("history_suggestion_count"),
        "escalation_action_count": summary.get("escalation_action_count"),
        "scheduler_policy_escalation_ids": summary.get(
            "scheduler_policy_escalation_ids", []
        ),
        "scheduler_history_trend": summary.get("scheduler_history_trend"),
        "scheduler_history_previous_runs": summary.get(
            "scheduler_history_previous_runs"
        ),
        "stable_ok_ids": summary.get("stable_ok_ids", []),
        "prewarm_warmed": summary.get("prewarm_warmed"),
        "predictive_prefetch_warmed": summary.get("predictive_prefetch_warmed"),
        "priority_predictions": summary.get("priority_predictions"),
        "forgetting_demotions": summary.get("forgetting_demotions"),
        "concepts_created": summary.get("concepts_created"),
        "claim_boundary": payload.get("claim_boundary", ""),
        "source": "benchmarks/memory_os_policy_evolution_results.json",
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
