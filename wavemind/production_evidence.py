from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path.cwd()


@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    title: str
    status: str
    evidence: str
    artifact: str
    command: str
    claim_unlocked: str
    issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = list(self.issues)
        return payload


@dataclass(frozen=True)
class EvidencePreflightCheck:
    id: str
    title: str
    status: str
    ready: bool
    evidence: str
    required_env: tuple[str, ...]
    missing_env: tuple[str, ...]
    command: str
    output_artifact: str
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_env"] = list(self.required_env)
        payload["missing_env"] = list(self.missing_env)
        payload["issues"] = list(self.issues)
        payload["warnings"] = list(self.warnings)
        return payload


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _size_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for size_result in payload.get("results", []):
        for result in size_result.get("results", []):
            if isinstance(result, dict):
                row = dict(result)
                row.setdefault("vectors", size_result.get("vectors"))
                rows.append(row)
    return rows


def _plan_command(root: Path, path: str) -> str:
    payload = _load_optional_json(root / path)
    for row in payload.get("plans", []):
        command = row.get("command")
        if command:
            return str(command).replace("\\", "/")
    return ""


def _status_from_issues(*, missing: bool, issues: list[str]) -> str:
    if missing:
        return "action_required"
    return "fail" if issues else "pass"


def _preflight_status(issues: list[str]) -> str:
    return "ready" if not issues else "action_required"


def _env_value(env: dict[str, str], name: str) -> str:
    return str(env.get(name) or "").strip()


def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]+", value or "") if item.strip()]


def _is_sample_url(value: str) -> bool:
    lowered = value.lower()
    return (
        "example.com" in lowered
        or "example.test" in lowered
        or lowered.startswith("http://localhost")
        or lowered.startswith("https://localhost")
        or lowered.startswith("http://127.0.0.1")
        or lowered.startswith("https://127.0.0.1")
    )


def _extract_url_from_spec(spec: str) -> str:
    return spec.split("=", 1)[-1].strip().rstrip("/")


def _validate_url_specs(
    specs: list[str],
    *,
    min_count: int,
    label: str,
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    urls = [_extract_url_from_spec(spec) for spec in specs]
    if len(urls) < min_count:
        issues.append(f"{label} requires at least {min_count} URLs")
    for url in urls:
        if not url.startswith(("http://", "https://")):
            issues.append(f"{label} URL must start with http:// or https://: {url}")
        if _is_sample_url(url):
            issues.append(f"{label} URL must be remote/staging/production, not sample/local: {url}")
    if len(set(urls)) != len(urls):
        issues.append(f"{label} URLs must be unique")
    return urls, issues


def _manifest_specs(
    manifest_json: str,
    *,
    kind: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    if not manifest_json.strip():
        return [], [], {}
    try:
        payload = json.loads(manifest_json)
    except json.JSONDecodeError as exc:
        return [], [f"{kind} manifest JSON is invalid: {exc.msg}"], {}
    key = "nodes" if kind == "cluster" else "regions"
    entries = payload.get(key)
    if not isinstance(entries, list):
        return [], [f"{kind} manifest must contain a {key} array"], payload
    specs: list[str] = []
    issues: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            issues.append(f"{kind} manifest {key}[{index}] must be an object")
            continue
        item_id = str(entry.get("id") or entry.get("name") or f"{kind}-{index:03d}").strip()
        url = str(entry.get("url") or entry.get("address") or "").strip()
        if not url:
            issues.append(f"{kind} manifest {key}[{index}] requires url/address")
            continue
        specs.append(f"{item_id}={url}")
    environment = str(payload.get("environment") or "").lower()
    source = str(payload.get("source") or "").lower()
    if environment in {"", "local", "local-loopback", "loopback"}:
        issues.append(f"{kind} manifest environment must be remote/staging/production")
    if source in {"", "fixture", "sample", "loopback-api-processes", "loopback-api-regions"}:
        issues.append(f"{kind} manifest source must identify a real deployment")
    if not payload.get("deployment_id"):
        issues.append(f"{kind} manifest deployment_id is required")
    return specs, issues, payload


def _first_plan(root: Path, plan_artifact: str) -> dict[str, Any]:
    payload = _load_optional_json(root / plan_artifact)
    plans = payload.get("plans") if isinstance(payload, dict) else None
    if isinstance(plans, list) and plans:
        first = plans[0]
        if isinstance(first, dict):
            return first
    return {}


def _production_scale_run_contract(root: Path) -> dict[str, Any]:
    artifact = "benchmarks/production_scale_run_plan.json"
    payload = _load_optional_json(root / artifact)
    expected_profiles = {
        "qdrant-10m",
        "qdrant-sharded-10m",
        "pgvector-10m",
        "faiss-ivfpq-50m",
        "qdrant-sharded-100m",
    }
    issues: list[str] = []
    if not payload:
        issues.append(f"missing {artifact}")
        return {
            "status": "action_required",
            "artifact": artifact,
            "profile_count": 0,
            "ready_count": 0,
            "action_required_count": 0,
            "target_memories_total": 0,
            "profiles": [],
            "issues": issues,
        }

    if payload.get("schema") != "wavemind.production_scale_run_plan.v1":
        issues.append("schema must be wavemind.production_scale_run_plan.v1")
    rows = payload.get("profiles")
    if not isinstance(rows, list):
        issues.append("profiles must be a list")
        rows = []
    names = {str(row.get("profile")) for row in rows if isinstance(row, dict)}
    missing_profiles = sorted(expected_profiles - names)
    if missing_profiles:
        issues.append("missing profiles: " + ", ".join(missing_profiles))

    target_total = 0
    ready_count = 0
    action_required_count = 0
    profiles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            issues.append("profile rows must be objects")
            continue
        profile = str(row.get("profile") or "unknown")
        status = str(row.get("status") or "missing")
        target_memories = int(row.get("target_memories") or 0)
        target_total += target_memories
        if status == "ready":
            ready_count += 1
        elif status == "action_required":
            action_required_count += 1
        else:
            issues.append(f"{profile} has unknown status {status}")
        for key in ("command", "output_artifact", "checkpoint_path", "claim_boundary"):
            if not row.get(key):
                issues.append(f"{profile} missing {key}")
        if not str(row.get("claim_boundary") or "").startswith("plan_only"):
            issues.append(f"{profile} claim_boundary must mark this as plan_only")
        profiles.append(
            {
                "profile": profile,
                "status": status,
                "engine": row.get("engine"),
                "target_memories": target_memories,
                "output_artifact": row.get("output_artifact"),
                "required_env": list(row.get("required_env") or []),
                "missing_env": list(row.get("missing_env") or []),
                "blockers": list(row.get("blockers") or []),
            }
        )

    if target_total < 180_000_000:
        issues.append("target_memories_total must cover at least 180000000 memories")

    return {
        "status": "available" if not issues else "action_required",
        "artifact": artifact,
        "schema": payload.get("schema"),
        "profile_count": len(profiles),
        "ready_count": ready_count,
        "action_required_count": action_required_count,
        "target_memories_total": target_total,
        "profiles": profiles,
        "issues": list(dict.fromkeys(issues)),
    }


def _disk_free_gb_for_path(path_value: str) -> float | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    parent = path if path.is_dir() else path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists():
        return None
    usage = shutil.disk_usage(parent)
    return usage.free / (1024**3)


def _disk_free_override_gb(env: dict[str, str], env_name: str) -> float | None:
    candidates = [
        f"{env_name}_FREE_GB",
        env_name.replace("_PATH", "_FREE_GB"),
    ]
    for candidate in dict.fromkeys(candidates):
        raw = _env_value(env, candidate)
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            return None
        if value >= 0:
            return value
    return None


def _validate_external_cluster_payload(
    payload: dict[str, Any] | None,
    *,
    min_nodes: int = 4,
    min_namespaces: int = 32,
    min_memories_per_namespace: int = 8,
    min_batch_query_size: int = 12,
    min_success_rate: float = 1.0,
    min_failover_hit_rate: float = 0.95,
    p99_slo_ms: float = 1000.0,
) -> dict[str, Any]:
    if not payload:
        return {
            "status": "action_required",
            "evidence": "no checked-in external HTTP cluster load result",
            "next_step": (
                "Run external-http-cluster-load against real API nodes and "
                "upload or commit the resulting artifact."
            ),
            "issues": ["missing artifact"],
        }

    scenario = payload.get("scenario", {})
    results = [
        result
        for result in payload.get("results", [])
        if result.get("engine") == "WaveMind external HTTP cluster load"
    ]
    result = results[0] if results else {}
    issues: list[str] = []

    def require(condition: bool, issue: str) -> None:
        if not condition:
            issues.append(issue)

    require(scenario.get("name") == "http_cluster_load", "scenario name must be http_cluster_load")
    require(int(scenario.get("node_count", 0)) >= min_nodes, f"node_count must be >= {min_nodes}")
    require(bool(scenario.get("deployment_id")), "deployment_id is required")
    require(bool(scenario.get("environment")), "environment is required")
    require(
        str(scenario.get("source") or "").lower() not in {"fixture", "sample"},
        "source cannot be fixture/sample",
    )
    require(int(scenario.get("namespace_count", 0)) >= min_namespaces, f"namespace_count must be >= {min_namespaces}")
    require(
        int(scenario.get("memories_per_namespace", 0)) >= min_memories_per_namespace,
        f"memories_per_namespace must be >= {min_memories_per_namespace}",
    )
    require(int(scenario.get("replication_factor", 0)) >= 3, "replication_factor must be >= 3")
    require(bool(result), "WaveMind external HTTP cluster load result is required")
    if result:
        require(float(result.get("success_rate", 0.0)) >= min_success_rate, "success_rate below SLO")
        require(float(result.get("write_success_rate", 0.0)) >= min_success_rate, "write_success_rate below SLO")
        require(float(result.get("query_hit_rate", 0.0)) >= min_success_rate, "query_hit_rate below SLO")
        require(
            float(result.get("failover_hit_rate", 0.0)) >= min_failover_hit_rate,
            "failover_hit_rate below SLO",
        )
        require(
            float(result.get("delete_suppression_rate", 0.0)) >= min_success_rate,
            "delete_suppression_rate below SLO",
        )
        require(bool(result.get("repair_ok")), "repair_ok must be true")
        require(int(result.get("repair_repaired_total", 0)) >= 1, "repair_repaired_total must be >= 1")
        require(bool(result.get("slo_pass")), "slo_pass must be true")
        require(float(result.get("p99_operation_ms", float("inf"))) <= p99_slo_ms, "p99_operation_ms above SLO")
        batch_query = result.get("batch_query")
        require(isinstance(batch_query, dict), "batch_query result is required")
        if isinstance(batch_query, dict):
            require(bool(batch_query.get("success")), "batch_query success must be true")
            require(bool(batch_query.get("individual_success")), "batch_query individual_success must be true")
            require(bool(batch_query.get("batch_success")), "batch_query batch_success must be true")
            require(
                int(batch_query.get("batch_size", 0)) >= min_batch_query_size,
                f"batch_query batch_size must be >= {min_batch_query_size}",
            )
            require(int(batch_query.get("batch_http_requests", 0)) == 1, "batch_query batch_http_requests must be 1")
            require(
                float(batch_query.get("request_reduction_ratio", 0.0)) >= 0.9,
                "batch_query request_reduction_ratio below 0.9",
            )
            require(float(batch_query.get("batch_p99_ms", float("inf"))) <= p99_slo_ms, "batch_query p99 above SLO")

    batch_query = result.get("batch_query") if result else {}
    evidence = (
        f"nodes {scenario.get('node_count')}, "
        f"deployment {scenario.get('deployment_id')}, "
        f"environment {scenario.get('environment')}, "
        f"source {scenario.get('source')}, "
        f"namespaces {scenario.get('namespace_count')}, "
        f"success {result.get('success_rate')}, "
        f"failover {result.get('failover_hit_rate')}, "
        f"p99 {result.get('p99_operation_ms')} ms, "
        f"batch query {batch_query.get('success') if isinstance(batch_query, dict) else None}, "
        f"batch HTTP {batch_query.get('individual_http_requests') if isinstance(batch_query, dict) else None} -> "
        f"{batch_query.get('batch_http_requests') if isinstance(batch_query, dict) else None}, "
        f"batch p99 {batch_query.get('batch_p99_ms') if isinstance(batch_query, dict) else None} ms"
        if result
        else "invalid external HTTP cluster load artifact"
    )
    return {
        "status": "pass" if not issues else "fail",
        "evidence": evidence if not issues else f"{evidence}; issues: {', '.join(issues)}",
        "issues": issues,
    }


def _validate_external_active_active_payload(
    payload: dict[str, Any] | None,
    *,
    min_regions: int = 3,
    min_namespaces: int = 16,
    min_success_rate: float = 1.0,
    min_convergence_rate: float = 1.0,
    min_delete_suppression_rate: float = 1.0,
    p99_slo_ms: float = 1500.0,
) -> dict[str, Any]:
    if not payload:
        return {
            "status": "action_required",
            "evidence": "no checked-in external HTTP active-active region result",
            "next_step": (
                "Run external-http-active-active against real API regions and "
                "upload or commit the resulting artifact."
            ),
            "issues": ["missing artifact"],
        }

    scenario = payload.get("scenario", {})
    results = [
        result
        for result in payload.get("results", [])
        if result.get("engine") == "WaveMind real HTTP active-active service-region sync"
    ]
    result = results[0] if results else {}
    issues: list[str] = []

    def require(condition: bool, issue: str) -> None:
        if not condition:
            issues.append(issue)

    require(
        scenario.get("name") == "local_http_active_active_smoke",
        "scenario name must be local_http_active_active_smoke",
    )
    require(scenario.get("source") == "external-regions", "source must be external-regions")
    require(int(scenario.get("region_count", 0)) >= min_regions, f"region_count must be >= {min_regions}")
    require(bool(scenario.get("deployment_id")), "deployment_id is required")
    require(bool(scenario.get("environment")), "environment is required")
    require(
        str(scenario.get("environment") or "").lower() not in {"", "local", "local-loopback", "loopback"},
        "environment must be a real remote/staging/production deployment",
    )
    require(
        str(scenario.get("evidence_source") or "").lower()
        not in {"", "fixture", "sample", "loopback-api-regions"},
        "evidence_source is required and cannot be fixture/sample/loopback",
    )
    require(int(scenario.get("namespace_count", 0)) >= min_namespaces, f"namespace_count must be >= {min_namespaces}")
    require(bool(result), "WaveMind real HTTP active-active service-region sync result is required")
    if result:
        require(float(result.get("convergence_rate", 0.0)) >= min_convergence_rate, "convergence_rate below SLO")
        require(
            float(result.get("delete_suppression_rate", 0.0)) >= min_delete_suppression_rate,
            "delete_suppression_rate below SLO",
        )
        require(float(result.get("success_rate", 0.0)) >= min_success_rate, "success_rate below SLO")
        require(int(result.get("failed_pairs", 1)) == 0, "failed_pairs must be 0")
        require(int(result.get("final_noop_records_imported", 1)) == 0, "final_noop_records_imported must be 0")
        require(int(result.get("final_noop_failed_pairs", 1)) == 0, "final_noop_failed_pairs must be 0")
        require(bool(result.get("slo_pass")), "slo_pass must be true")
        require(float(result.get("p99_operation_ms", float("inf"))) <= p99_slo_ms, "p99_operation_ms above SLO")

    evidence = (
        f"regions {scenario.get('region_count')}, "
        f"deployment {scenario.get('deployment_id')}, "
        f"environment {scenario.get('environment')}, "
        f"source {scenario.get('evidence_source')}, "
        f"namespaces {scenario.get('namespace_count')}, "
        f"convergence {result.get('convergence_rate')}, "
        f"delete suppression {result.get('delete_suppression_rate')}, "
        f"success {result.get('success_rate')}, "
        f"final noop {result.get('final_noop_records_imported')}, "
        f"p99 {result.get('p99_operation_ms')} ms"
        if result
        else "invalid external HTTP active-active region artifact"
    )
    return {
        "status": "pass" if not issues else "fail",
        "evidence": evidence if not issues else f"{evidence}; issues: {', '.join(issues)}",
        "issues": issues,
    }


def _external_cluster_requirement(root: Path) -> EvidenceRequirement:
    artifact = "benchmarks/http_cluster_load_results.json"
    payload = _load_optional_json(root / artifact)
    validation = _validate_external_cluster_payload(payload or None)
    scenario = payload.get("scenario", {}) if payload else {}
    validation_issues = list(validation.get("issues", []))
    issues = list(validation_issues)
    environment = str(scenario.get("environment") or "").lower()
    source = str(scenario.get("source") or "").lower()
    local_only = False
    if payload and environment in {"", "local", "local-loopback", "loopback"}:
        local_only = True
        issues.append("environment must be a real remote/staging/production deployment")
    if payload and source in {"", "fixture", "sample", "loopback-api-processes"}:
        local_only = True
        issues.append("source must identify a real remote run, not a sample or loopback")
    missing = not payload
    status = _status_from_issues(missing=missing, issues=validation_issues)
    if local_only and status == "pass":
        status = "action_required"
    return EvidenceRequirement(
        id="external_http_cluster",
        title="External HTTP service-node load",
        status=status,
        evidence=str(validation.get("evidence") or "missing external cluster artifact"),
        artifact=artifact,
        command=(
            "gh workflow run external-http-cluster-load.yml "
            "-f nodes=\"node-a=https://wm-a.example.com,node-b=https://wm-b.example.com,"
            "node-c=https://wm-c.example.com,node-d=https://wm-d.example.com\" "
            "-f replication_factor=3 -f read_quorum=1 -f read_fanout=1 "
            "-f batch_query_size=24 "
            "-f fail_on_slo=true -f commit_results=true"
        ),
        claim_unlocked="Remote service-node cluster load SLO.",
        issues=tuple(dict.fromkeys(issues)),
    )


def _external_active_active_requirement(root: Path) -> EvidenceRequirement:
    artifact = "benchmarks/external_http_active_active_results.json"
    payload = _load_optional_json(root / artifact)
    validation = _validate_external_active_active_payload(payload or None)
    issues = list(validation.get("issues", []))
    missing = not payload
    return EvidenceRequirement(
        id="external_http_active_active",
        title="External HTTP active-active regions",
        status=_status_from_issues(missing=missing, issues=issues),
        evidence=str(validation.get("evidence") or "missing external active-active artifact"),
        artifact=artifact,
        command=(
            "gh workflow run external-http-active-active.yml "
            "-f regions=\"us-east=https://wm-us.example.com,eu-west=https://wm-eu.example.com,"
            "ap-south=https://wm-ap.example.com\" "
            "-f namespace_count=16 -f p99_slo_ms=1500 "
            "-f fail_on_slo=true -f commit_results=true"
        ),
        claim_unlocked="Remote multi-region active-active memory convergence.",
        issues=tuple(dict.fromkeys(issues)),
    )


def _serverless_requirement(root: Path) -> EvidenceRequirement:
    artifact = "deploy/serverless/observed-telemetry.remote.json"
    payload = _load_optional_json(root / artifact)
    issues: list[str] = []
    if not payload:
        issues.append("missing artifact")
    else:
        if payload.get("node_mode") != "external":
            issues.append("node_mode must be external")
        if not payload.get("observed_slo_pass"):
            issues.append("observed_slo_pass must be true")
        if float(payload.get("p99_request_ms", float("inf"))) > float(
            payload.get("target_p99_ms", 500.0)
        ):
            issues.append("p99_request_ms above target")
        if float(payload.get("error_rate", 1.0)) > float(
            payload.get("max_error_rate", 0.01)
        ):
            issues.append("error_rate above target")
        source = str(payload.get("source") or "").lower()
        if source in {"", "fixture", "sample", "loopback-api-capacity-estimate"}:
            issues.append("source must identify a real remote/serverless run")
    return EvidenceRequirement(
        id="serverless_remote_telemetry",
        title="Managed/serverless remote telemetry",
        status=_status_from_issues(missing=not payload, issues=issues),
        evidence=(
            f"node_mode {payload.get('node_mode')}, source {payload.get('source')}, "
            f"rps {payload.get('requests_per_second')}, p99 {payload.get('p99_request_ms')} ms, "
            f"errors {payload.get('error_rate')}, slo {payload.get('observed_slo_pass')}"
            if payload
            else "no checked-in remote serverless telemetry"
        ),
        artifact=artifact,
        command=(
            "gh workflow run serverless-observed-telemetry.yml "
            "-f nodes=\"https://wm-a.example.com,https://wm-b.example.com\" "
            "-f seed_mode=first -f commit_results=true"
        ),
        claim_unlocked="Hosted/serverless p99, cold-start, error-rate, and scale-out SLO.",
        issues=tuple(dict.fromkeys(issues)),
    )


def _large_service_requirement(
    root: Path,
    *,
    requirement_id: str,
    title: str,
    artifact: str,
    plan_artifact: str,
    engine: str,
    min_vectors: int,
    claim_unlocked: str,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
) -> EvidenceRequirement:
    payload = _load_optional_json(root / artifact)
    rows = [
        row
        for row in _size_results(payload)
        if row.get("engine") == engine and not row.get("skipped")
    ]
    row = max(rows, key=lambda item: int(item.get("vectors", 0) or 0), default={})
    issues: list[str] = []
    if not row:
        issues.append("missing artifact")
    else:
        if int(row.get("vectors", 0) or 0) < min_vectors:
            issues.append(f"vectors must be >= {min_vectors}")
        if float(row.get("recall_at_k", row.get("target_recall_at_k", 0.0))) < target_recall:
            issues.append(f"recall_at_k must be >= {target_recall}")
        if float(row.get("p99_latency_ms", float("inf"))) > target_p99_ms:
            issues.append(f"p99_latency_ms must be <= {target_p99_ms}")
        if row.get("cost_status") != "valid_slo":
            issues.append("cost_status must be valid_slo")
    return EvidenceRequirement(
        id=requirement_id,
        title=title,
        status=_status_from_issues(missing=not row, issues=issues),
        evidence=(
            f"{row.get('engine')}: vectors {row.get('vectors')}, "
            f"recall {row.get('recall_at_k', row.get('target_recall_at_k'))}, "
            f"p99 {row.get('p99_latency_ms')} ms, cost {row.get('cost_status')}"
            if row
            else f"no checked-in {min_vectors:,}-vector result for {engine}"
        ),
        artifact=artifact,
        command=_plan_command(root, plan_artifact),
        claim_unlocked=claim_unlocked,
        issues=tuple(dict.fromkeys(issues)),
    )


def _hundred_million_requirement(root: Path) -> EvidenceRequirement:
    artifact = "benchmarks/production_streaming_load_qdrant_sharded_100m_results.json"
    plan_artifact = "benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json"
    payload = _load_optional_json(root / artifact)
    rows = [
        row
        for row in _size_results(payload)
        if not row.get("skipped") and int(row.get("vectors", 0) or 0) >= 100_000_000
    ]
    row = rows[0] if rows else {}
    issues: list[str] = []
    if not row:
        issues.append("missing artifact")
    else:
        if float(row.get("recall_at_k", row.get("target_recall_at_k", 0.0))) < 0.95:
            issues.append("recall_at_k must be >= 0.95")
        if float(row.get("p99_latency_ms", float("inf"))) > 100.0:
            issues.append("p99_latency_ms must be <= 100")
        if row.get("cost_status") != "valid_slo":
            issues.append("cost_status must be valid_slo")
    return EvidenceRequirement(
        id="hundred_million_remote_load",
        title="100M remote load result",
        status=_status_from_issues(missing=not row, issues=issues),
        evidence=(
            f"{row.get('engine')}: vectors {row.get('vectors')}, "
            f"recall {row.get('recall_at_k', row.get('target_recall_at_k'))}, "
            f"p99 {row.get('p99_latency_ms')} ms, cost {row.get('cost_status')}"
            if row
            else "no checked-in 100M remote service-backed latency result"
        ),
        artifact=artifact,
        command=_plan_command(root, plan_artifact)
        or (
            "python benchmarks/production_streaming_load_benchmark.py "
            "--sizes 100000000 --engines qdrant-sharded-service "
            "--queries 100 --batch-size 2000 "
            "--output benchmarks/production_streaming_load_qdrant_sharded_100m_results.json"
        ),
        claim_unlocked="100M+ memories with measured recall, p99, and cost SLO.",
        issues=tuple(dict.fromkeys(issues)),
    )


def _endpoint_preflight(
    *,
    check_id: str,
    title: str,
    list_env: str,
    manifest_env: str | None,
    min_count: int,
    label: str,
    command: str,
    output_artifact: str,
    env: dict[str, str],
    manifest_kind: str,
) -> EvidencePreflightCheck:
    required_env = (list_env,) if not manifest_env else (list_env, manifest_env)
    specs: list[str] = []
    issues: list[str] = []
    warnings: list[str] = []
    manifest_payload: dict[str, Any] = {}
    manifest_value = _env_value(env, manifest_env) if manifest_env else ""
    if manifest_value:
        specs, manifest_issues, manifest_payload = _manifest_specs(
            manifest_value,
            kind=manifest_kind,
        )
        issues.extend(manifest_issues)
    else:
        specs = _split_env_list(_env_value(env, list_env))
    urls, url_issues = _validate_url_specs(specs, min_count=min_count, label=label)
    issues.extend(url_issues)
    if not manifest_value and not _env_value(env, list_env):
        issues.append(f"set {list_env} or {manifest_env}" if manifest_env else f"set {list_env}")
    if "WAVEMIND_API_KEY" not in env:
        warnings.append("WAVEMIND_API_KEY is not set; only use this if the target endpoints are intentionally unauthenticated")
    deployment_id = manifest_payload.get("deployment_id") if manifest_payload else None
    evidence = (
        f"{len(urls)} URLs configured"
        + (f", deployment {deployment_id}" if deployment_id else "")
    )
    missing_env = () if (manifest_value or _env_value(env, list_env)) else required_env
    return EvidencePreflightCheck(
        id=check_id,
        title=title,
        status=_preflight_status(issues),
        ready=not issues,
        evidence=evidence,
        required_env=required_env,
        missing_env=missing_env,
        command=command,
        output_artifact=output_artifact,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _serverless_preflight(env: dict[str, str]) -> EvidencePreflightCheck:
    command = (
        "gh workflow run serverless-observed-telemetry.yml "
        "-f nodes=\"$WAVEMIND_SERVERLESS_NODES\" -f seed_mode=first "
        "-f commit_results=true"
    )
    node_specs = _split_env_list(_env_value(env, "WAVEMIND_SERVERLESS_NODES"))
    urls, issues = _validate_url_specs(
        node_specs,
        min_count=1,
        label="serverless node",
    )
    if not _env_value(env, "WAVEMIND_SERVERLESS_NODES"):
        issues.append("set WAVEMIND_SERVERLESS_NODES")
    warnings: list[str] = []
    if "WAVEMIND_API_KEY" not in env:
        warnings.append("WAVEMIND_API_KEY is not set; only use this if the target endpoints are intentionally unauthenticated")
    return EvidencePreflightCheck(
        id="serverless_remote_telemetry",
        title="Managed/serverless remote telemetry preflight",
        status=_preflight_status(issues),
        ready=not issues,
        evidence=f"{len(urls)} node URLs configured",
        required_env=("WAVEMIND_SERVERLESS_NODES",),
        missing_env=("WAVEMIND_SERVERLESS_NODES",)
        if not _env_value(env, "WAVEMIND_SERVERLESS_NODES")
        else (),
        command=command,
        output_artifact="deploy/serverless/observed-telemetry.remote.json",
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _large_run_preflight(
    root: Path,
    *,
    check_id: str,
    title: str,
    plan_artifact: str,
    output_artifact: str,
    env: dict[str, str],
) -> EvidencePreflightCheck:
    plan = _first_plan(root, plan_artifact)
    issues: list[str] = []
    warnings: list[str] = []
    if not plan:
        issues.append(f"missing plan artifact {plan_artifact}")
    required_env = tuple(str(item) for item in plan.get("required_env", []) if item) if plan else ()
    missing_env = tuple(name for name in required_env if not _env_value(env, name))
    for name in missing_env:
        issues.append(f"set {name}")

    if "WAVEMIND_QDRANT_URL" in required_env and _env_value(env, "WAVEMIND_QDRANT_URL"):
        url = _env_value(env, "WAVEMIND_QDRANT_URL")
        if url == ":memory:":
            issues.append("WAVEMIND_QDRANT_URL must point at a real Qdrant service, not :memory:")
        elif not url.startswith(("http://", "https://")):
            issues.append("WAVEMIND_QDRANT_URL must start with http:// or https://")
    if "WAVEMIND_QDRANT_URLS" in required_env and _env_value(env, "WAVEMIND_QDRANT_URLS"):
        _, url_issues = _validate_url_specs(
            _split_env_list(_env_value(env, "WAVEMIND_QDRANT_URLS")),
            min_count=2,
            label="Qdrant shard",
        )
        issues.extend(url_issues)
    if "WAVEMIND_PGVECTOR_DSN" in required_env and _env_value(env, "WAVEMIND_PGVECTOR_DSN"):
        dsn = _env_value(env, "WAVEMIND_PGVECTOR_DSN")
        if not dsn.startswith(("postgresql://", "postgres://")):
            issues.append("WAVEMIND_PGVECTOR_DSN must start with postgresql:// or postgres://")
    for name in ("WAVEMIND_FAISS_PATH", "WAVEMIND_FAISS_IVFPQ_PATH"):
        if name in required_env and _env_value(env, name):
            required_free = float(plan.get("required_local_free_gb", 0.0) or 0.0)
            free = _disk_free_override_gb(env, name)
            if free is None:
                free = _disk_free_gb_for_path(_env_value(env, name))
            if free is None:
                issues.append(f"{name} parent path does not exist on this machine")
            elif required_free and free < required_free:
                issues.append(f"{name} free disk {free:.2f} GB is below required {required_free:.2f} GB")
            elif required_free and free < required_free * 1.5:
                warnings.append(f"{name} free disk {free:.2f} GB is close to required {required_free:.2f} GB")

    command = str(plan.get("command") or "")
    if not command:
        issues.append(f"{plan_artifact} does not contain a reproduction command")
    if output_artifact not in command.replace("\\", "/"):
        issues.append(f"reproduction command must write {output_artifact}")

    evidence = (
        f"plan {plan_artifact}, vectors {plan.get('vectors')}, "
        f"required env {len(required_env)}, missing env {len(missing_env)}, "
        f"required local free {plan.get('required_local_free_gb')} GB"
        if plan
        else f"missing plan {plan_artifact}"
    )
    return EvidencePreflightCheck(
        id=check_id,
        title=title,
        status=_preflight_status(issues),
        ready=not issues,
        evidence=evidence,
        required_env=required_env,
        missing_env=missing_env,
        command=command,
        output_artifact=output_artifact,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def evaluate_production_evidence_preflight(
    root: Path = PROJECT_ROOT,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    checks = [
        _endpoint_preflight(
            check_id="external_http_cluster",
            title="External HTTP service-node load preflight",
            list_env="WAVEMIND_CLUSTER_NODES",
            manifest_env="WAVEMIND_CLUSTER_NODES_MANIFEST_JSON",
            min_count=4,
            label="cluster node",
            command=(
                "gh workflow run external-http-cluster-load.yml "
                "-f nodes=\"$WAVEMIND_CLUSTER_NODES\" "
                "-f batch_query_size=24 -f commit_results=true"
            ),
            output_artifact="benchmarks/http_cluster_load_results.json",
            env=environment,
            manifest_kind="cluster",
        ),
        _endpoint_preflight(
            check_id="external_http_active_active",
            title="External HTTP active-active regions preflight",
            list_env="WAVEMIND_ACTIVE_ACTIVE_REGIONS",
            manifest_env="WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON",
            min_count=3,
            label="active-active region",
            command=(
                "gh workflow run external-http-active-active.yml "
                "-f regions=\"$WAVEMIND_ACTIVE_ACTIVE_REGIONS\" -f commit_results=true"
            ),
            output_artifact="benchmarks/external_http_active_active_results.json",
            env=environment,
            manifest_kind="active-active",
        ),
        _serverless_preflight(environment),
        _large_run_preflight(
            root,
            check_id="qdrant_10m_service",
            title="10M Qdrant service load preflight",
            plan_artifact="benchmarks/production_streaming_load_qdrant_10m_plan.json",
            output_artifact="benchmarks/production_streaming_load_qdrant_10m_results.json",
            env=environment,
        ),
        _large_run_preflight(
            root,
            check_id="qdrant_sharded_10m_service",
            title="10M sharded Qdrant service load preflight",
            plan_artifact="benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json",
            output_artifact="benchmarks/production_streaming_load_qdrant_sharded_10m_results.json",
            env=environment,
        ),
        _large_run_preflight(
            root,
            check_id="pgvector_10m_service",
            title="10M pgvector service load preflight",
            plan_artifact="benchmarks/production_streaming_load_pgvector_10m_plan.json",
            output_artifact="benchmarks/production_streaming_load_pgvector_10m_results.json",
            env=environment,
        ),
        _large_run_preflight(
            root,
            check_id="faiss_ivfpq_50m",
            title="50M FAISS IVF-PQ streaming load preflight",
            plan_artifact="benchmarks/production_streaming_load_50m_plan.json",
            output_artifact="benchmarks/production_streaming_load_ivfpq_50m_results.json",
            env=environment,
        ),
        _large_run_preflight(
            root,
            check_id="hundred_million_remote_load",
            title="100M sharded Qdrant service load preflight",
            plan_artifact="benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json",
            output_artifact="benchmarks/production_streaming_load_qdrant_sharded_100m_results.json",
            env=environment,
        ),
    ]
    ready_count = sum(1 for item in checks if item.ready)
    action_required_count = len(checks) - ready_count
    overall_status = "ready" if action_required_count == 0 else "action_required"
    return {
        "schema": "wavemind.production_evidence_preflight.v1",
        "generated_at": _utc_now(),
        "overall_status": overall_status,
        "summary": {
            "overall_status": overall_status,
            "ready_count": ready_count,
            "action_required_count": action_required_count,
            "total_checks": len(checks),
        },
        "checks": [item.as_dict() for item in checks],
    }


def evaluate_production_evidence(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    requirements = [
        _external_cluster_requirement(root),
        _external_active_active_requirement(root),
        _serverless_requirement(root),
        _large_service_requirement(
            root,
            requirement_id="qdrant_10m_service",
            title="10M Qdrant service load",
            artifact="benchmarks/production_streaming_load_qdrant_10m_results.json",
            plan_artifact="benchmarks/production_streaming_load_qdrant_10m_plan.json",
            engine="Qdrant service streaming",
            min_vectors=10_000_000,
            claim_unlocked="10M Qdrant service-backed candidate index SLO.",
        ),
        _large_service_requirement(
            root,
            requirement_id="qdrant_sharded_10m_service",
            title="10M sharded Qdrant service load",
            artifact="benchmarks/production_streaming_load_qdrant_sharded_10m_results.json",
            plan_artifact="benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json",
            engine="Qdrant sharded service streaming",
            min_vectors=10_000_000,
            claim_unlocked="Horizontally sharded Qdrant service recall/latency SLO.",
        ),
        _large_service_requirement(
            root,
            requirement_id="pgvector_10m_service",
            title="10M pgvector service load",
            artifact="benchmarks/production_streaming_load_pgvector_10m_results.json",
            plan_artifact="benchmarks/production_streaming_load_pgvector_10m_plan.json",
            engine="WaveMind pgvector streaming",
            min_vectors=10_000_000,
            claim_unlocked="10M PostgreSQL/pgvector service candidate-index SLO.",
        ),
        _large_service_requirement(
            root,
            requirement_id="faiss_ivfpq_50m",
            title="50M FAISS IVF-PQ streaming load",
            artifact="benchmarks/production_streaming_load_ivfpq_50m_results.json",
            plan_artifact="benchmarks/production_streaming_load_50m_plan.json",
            engine="WaveMind faiss-ivfpq-persisted streaming",
            min_vectors=50_000_000,
            claim_unlocked="50M compressed local/persistent FAISS profile.",
        ),
        _hundred_million_requirement(root),
    ]
    pass_count = sum(1 for item in requirements if item.status == "pass")
    action_required_count = sum(
        1 for item in requirements if item.status == "action_required"
    )
    fail_count = sum(1 for item in requirements if item.status == "fail")
    overall_status = (
        "fail"
        if fail_count
        else "action_required"
        if action_required_count
        else "pass"
    )
    return {
        "schema": "wavemind.production_evidence.v1",
        "generated_at": _utc_now(),
        "overall_status": overall_status,
        "summary": {
            "overall_status": overall_status,
            "pass_count": pass_count,
            "action_required_count": action_required_count,
            "fail_count": fail_count,
            "total_requirements": len(requirements),
        },
        "requirements": [item.as_dict() for item in requirements],
    }


def _gh_workflow_command(workflow: str, inputs: dict[str, Any]) -> str:
    parts = ["gh", "workflow", "run", workflow]
    for key, value in inputs.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value_text = "true" if value else "false"
        else:
            value_text = str(value)
        escaped = value_text.replace('"', '\\"')
        parts.extend(["-f", f'{key}="{escaped}"'])
    return " ".join(parts)


def _dispatch_input_bindings(inputs: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in inputs.items()
        if isinstance(value, str) and value.startswith("$")
    }


def _dispatch_job_status(strict_status: str, preflight_status: str) -> str:
    if strict_status == "pass":
        return "complete"
    if preflight_status == "ready":
        return "ready_to_dispatch"
    return "blocked_by_preflight"


def _streaming_dispatch_inputs(
    root: Path,
    *,
    plan_artifact: str,
    engine: str,
    size: int,
    credential_input: str,
    credential_placeholder: str,
    runner_label: str,
    commit_results: bool,
) -> dict[str, Any]:
    payload = _load_optional_json(root / plan_artifact)
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), dict) else {}
    row = _first_plan(root, plan_artifact)
    inputs: dict[str, Any] = {
        "engine": engine,
        "size": str(size),
        "dim": str(scenario.get("vector_dim") or row.get("vector_dim") or 128),
        "queries": str(scenario.get("queries_per_size") or row.get("queries") or 2000),
        "top_k": str(scenario.get("top_k") or row.get("top_k") or 10),
        "batch_size": str(scenario.get("batch_size") or row.get("batch_size") or 5000),
        "target_recall": str(scenario.get("target_recall_at_k") or 0.95),
        "target_p99_ms": str(scenario.get("target_p99_ms") or 100.0),
        "target_qps": str(scenario.get("target_qps") or 100.0),
        "replicas": str(scenario.get("replicas") or 3),
        "autoscaling_max_replicas": str(scenario.get("autoscaling_max_replicas") or 24),
        "capacity_headroom": str(scenario.get("capacity_headroom") or 0.7),
        "runner_label": runner_label,
        "runner_storage_root": str(
            row.get("runner_storage_root")
            or scenario.get("runner_storage_root")
            or "state"
        ),
        "commit_results": commit_results,
    }
    inputs[credential_input] = credential_placeholder
    return inputs


def _dispatch_config(
    root: Path,
    requirement_id: str,
    *,
    runner_label: str,
    commit_results: bool,
) -> dict[str, Any]:
    if requirement_id == "external_http_cluster":
        inputs = {
            "nodes": "$WAVEMIND_CLUSTER_NODES",
            "nodes_manifest_json": "$WAVEMIND_CLUSTER_NODES_MANIFEST_JSON",
            "namespace_count": "32",
            "memories_per_namespace": "8",
            "workers": "8",
            "batch_query_size": "24",
            "replication_factor": "3",
            "read_quorum": "1",
            "read_fanout": "1",
            "p99_slo_ms": "1000",
            "commit_results": commit_results,
        }
        return {
            "workflow": "external-http-cluster-load.yml",
            "wave": "remote-service",
            "inputs": inputs,
            "required_secrets": ["WAVEMIND_API_KEY"],
        }
    if requirement_id == "external_http_active_active":
        inputs = {
            "regions": "$WAVEMIND_ACTIVE_ACTIVE_REGIONS",
            "regions_manifest_json": "$WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON",
            "namespace_count": "16",
            "p99_slo_ms": "1500",
            "commit_results": commit_results,
        }
        return {
            "workflow": "external-http-active-active.yml",
            "wave": "remote-service",
            "inputs": inputs,
            "required_secrets": ["WAVEMIND_API_KEY"],
        }
    if requirement_id == "serverless_remote_telemetry":
        inputs = {
            "nodes": "$WAVEMIND_SERVERLESS_NODES",
            "requests": "240",
            "workers": "4",
            "seed_memories": "24",
            "seed_mode": "first",
            "max_scale": "256",
            "target_rps": "3200",
            "target_p99_ms": "500",
            "external_cold_start_ms": "900",
            "estimated_scale_out_seconds": "18",
            "commit_results": commit_results,
        }
        return {
            "workflow": "serverless-observed-telemetry.yml",
            "wave": "remote-service",
            "inputs": inputs,
            "required_secrets": ["WAVEMIND_API_KEY"],
        }
    if requirement_id == "qdrant_10m_service":
        return {
            "workflow": "production-streaming-load.yml",
            "wave": "service-scale-10m",
            "inputs": _streaming_dispatch_inputs(
                root,
                plan_artifact="benchmarks/production_streaming_load_qdrant_10m_plan.json",
                engine="qdrant-service",
                size=10_000_000,
                credential_input="qdrant_url",
                credential_placeholder="$WAVEMIND_QDRANT_URL",
                runner_label=runner_label,
                commit_results=commit_results,
            ),
            "required_secrets": ["WAVEMIND_QDRANT_API_KEY"],
        }
    if requirement_id == "qdrant_sharded_10m_service":
        return {
            "workflow": "production-streaming-load.yml",
            "wave": "service-scale-10m",
            "inputs": _streaming_dispatch_inputs(
                root,
                plan_artifact="benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json",
                engine="qdrant-sharded-service",
                size=10_000_000,
                credential_input="qdrant_urls",
                credential_placeholder="$WAVEMIND_QDRANT_URLS",
                runner_label=runner_label,
                commit_results=commit_results,
            ),
            "required_secrets": ["WAVEMIND_QDRANT_API_KEYS"],
        }
    if requirement_id == "pgvector_10m_service":
        return {
            "workflow": "production-streaming-load.yml",
            "wave": "service-scale-10m",
            "inputs": _streaming_dispatch_inputs(
                root,
                plan_artifact="benchmarks/production_streaming_load_pgvector_10m_plan.json",
                engine="pgvector-service",
                size=10_000_000,
                credential_input="pgvector_dsn",
                credential_placeholder="$WAVEMIND_PGVECTOR_DSN",
                runner_label=runner_label,
                commit_results=commit_results,
            ),
            "required_secrets": [],
        }
    if requirement_id == "faiss_ivfpq_50m":
        return {
            "workflow": "production-streaming-load.yml",
            "wave": "large-local-index",
            "inputs": _streaming_dispatch_inputs(
                root,
                plan_artifact="benchmarks/production_streaming_load_50m_plan.json",
                engine="faiss-ivfpq-persisted",
                size=50_000_000,
                credential_input="faiss_ivfpq_path",
                credential_placeholder="$WAVEMIND_FAISS_IVFPQ_PATH",
                runner_label=runner_label,
                commit_results=commit_results,
            ),
            "required_secrets": [],
        }
    if requirement_id == "hundred_million_remote_load":
        return {
            "workflow": "production-streaming-load.yml",
            "wave": "hundred-million-service",
            "inputs": _streaming_dispatch_inputs(
                root,
                plan_artifact="benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json",
                engine="qdrant-sharded-service",
                size=100_000_000,
                credential_input="qdrant_urls",
                credential_placeholder="$WAVEMIND_QDRANT_URLS",
                runner_label=runner_label,
                commit_results=commit_results,
            ),
            "required_secrets": ["WAVEMIND_QDRANT_API_KEYS"],
        }
    return {
        "workflow": "",
        "wave": "unknown",
        "inputs": {"commit_results": commit_results},
        "required_secrets": [],
    }


def build_production_evidence_dispatch_plan(
    root: Path = PROJECT_ROOT,
    *,
    env: dict[str, str] | None = None,
    runner_label: str = "self-hosted-large",
    commit_results: bool = False,
) -> dict[str, Any]:
    """Build a launch plan for strict production-evidence GitHub workflows.

    The plan does not unlock claims by itself. It joins the strict evidence gate,
    preflight, workflow names, workflow inputs, secret requirements, and artifact
    promotion commands so operators can launch real remote/large-N runs without
    manually reconstructing each workflow_dispatch payload.
    """

    root = Path(root)
    strict = evaluate_production_evidence(root)
    preflight = evaluate_production_evidence_preflight(root, env=env)
    strict_by_id = {
        str(row.get("id")): row
        for row in strict.get("requirements", [])
        if isinstance(row, dict)
    }
    preflight_by_id = {
        str(row.get("id")): row
        for row in preflight.get("checks", [])
        if isinstance(row, dict)
    }

    jobs: list[dict[str, Any]] = []
    for requirement in strict.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        requirement_id = str(requirement.get("id") or "unknown")
        check = preflight_by_id.get(requirement_id, {})
        strict_status = str(requirement.get("status") or "missing")
        preflight_status = str(check.get("status") or "missing")
        config = _dispatch_config(
            root,
            requirement_id,
            runner_label=runner_label,
            commit_results=commit_results,
        )
        workflow = str(config.get("workflow") or "")
        inputs = dict(config.get("inputs") or {})
        status = _dispatch_job_status(strict_status, preflight_status)
        launch_command = _gh_workflow_command(workflow, inputs) if workflow else ""
        publish_inputs = dict(inputs)
        publish_inputs["commit_results"] = True
        publish_command = _gh_workflow_command(workflow, publish_inputs) if workflow else ""
        artifact = str(requirement.get("artifact") or check.get("output_artifact") or "")
        jobs.append(
            {
                "id": requirement_id,
                "title": requirement.get("title") or check.get("title") or requirement_id,
                "status": status,
                "dispatch_required": status != "complete",
                "ready": status == "ready_to_dispatch",
                "strict_status": strict_status,
                "preflight_status": preflight_status,
                "wave": config.get("wave"),
                "workflow": workflow,
                "artifact": artifact,
                "claim_unlocked": requirement.get("claim_unlocked"),
                "inputs": inputs,
                "input_bindings": _dispatch_input_bindings(inputs),
                "required_env": list(check.get("required_env") or []),
                "missing_env": list(check.get("missing_env") or []),
                "required_secrets": list(config.get("required_secrets") or []),
                "issues": list(check.get("issues") or requirement.get("issues") or []),
                "warnings": list(check.get("warnings") or []),
                "safe_launch_command": launch_command,
                "publish_launch_command": publish_command,
                "download_command": (
                    "gh run download <run-id> --repo CaspianG/wavemind "
                    "--dir state/production-evidence-downloads"
                ),
                "ingest_command": (
                    "wavemind ingest-production-evidence "
                    "--artifact-dir state/production-evidence-downloads --refresh"
                ),
            }
        )

    status_counts: dict[str, int] = {}
    wave_counts: dict[str, int] = {}
    for job in jobs:
        status_counts[str(job["status"])] = status_counts.get(str(job["status"]), 0) + 1
        wave = str(job.get("wave") or "unknown")
        wave_counts[wave] = wave_counts.get(wave, 0) + 1
    blocked_count = status_counts.get("blocked_by_preflight", 0)
    ready_count = status_counts.get("ready_to_dispatch", 0)
    complete_count = status_counts.get("complete", 0)
    if complete_count == len(jobs):
        overall_status = "complete"
    elif blocked_count:
        overall_status = "action_required"
    else:
        overall_status = "ready_to_dispatch"

    return {
        "schema": "wavemind.production_evidence_dispatch.v1",
        "generated_at": _utc_now(),
        "overall_status": overall_status,
        "summary": {
            "overall_status": overall_status,
            "total_jobs": len(jobs),
            "ready_to_dispatch_count": ready_count,
            "blocked_by_preflight_count": blocked_count,
            "complete_count": complete_count,
            "commit_results_default": bool(commit_results),
            "runner_label": runner_label,
            "wave_counts": dict(sorted(wave_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "launch_policy": {
            "safe_default": (
                "safe_launch_command uses commit_results=false by default; download "
                "the workflow artifact and promote it through ingest-production-evidence."
            ),
            "publish_mode": (
                "publish_launch_command sets commit_results=true for maintainer-controlled "
                "runs that may commit refreshed strict evidence artifacts directly."
            ),
            "secret_policy": (
                "The dispatch plan contains environment-variable placeholders and secret "
                "names only. It must not contain credential values."
            ),
        },
        "jobs": jobs,
        "promotion": {
            "download_command": (
                "gh run download <run-id> --repo CaspianG/wavemind "
                "--dir state/production-evidence-downloads"
            ),
            "ingest_command": (
                "wavemind ingest-production-evidence "
                "--artifact-dir state/production-evidence-downloads --refresh"
            ),
            "claim_boundary": (
                "Only artifacts that pass ingest-production-evidence and the strict "
                "production-evidence gate may unlock remote, 50M, or 100M claims."
            ),
        },
        "source_artifacts": {
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "preflight": "benchmarks/production_evidence_preflight_results.json",
            "scale_run_plan": "benchmarks/production_scale_run_plan.json",
        },
    }


def evaluate_production_evidence_bundle(
    root: Path = PROJECT_ROOT,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(root)
    strict = evaluate_production_evidence(root)
    preflight = evaluate_production_evidence_preflight(root, env=env)
    readiness = _load_optional_json(root / "benchmarks" / "production_readiness_results.json")
    audit = _load_optional_json(root / "benchmarks" / "benchmark_artifact_audit.json")
    matrix = _load_optional_json(root / "benchmarks" / "benchmark_matrix_results.json")
    scale_run_contract = _production_scale_run_contract(root)

    strict_by_id = {
        str(row.get("id")): row
        for row in strict.get("requirements", [])
        if isinstance(row, dict)
    }
    preflight_by_id = {
        str(row.get("id")): row
        for row in preflight.get("checks", [])
        if isinstance(row, dict)
    }
    next_actions = []
    for requirement_id, requirement in strict_by_id.items():
        if requirement.get("status") == "pass":
            continue
        check = preflight_by_id.get(requirement_id, {})
        command = str(check.get("command") or requirement.get("command") or "")
        next_actions.append(
            {
                "id": requirement_id,
                "title": requirement.get("title"),
                "strict_status": requirement.get("status"),
                "preflight_status": check.get("status", "missing"),
                "artifact": requirement.get("artifact"),
                "output_artifact": check.get("output_artifact", requirement.get("artifact")),
                "issues": list(requirement.get("issues") or ()),
                "missing_env": list(check.get("missing_env") or ()),
                "warnings": list(check.get("warnings") or ()),
                "command": command.replace("\\", "/"),
                "claim_unlocked": requirement.get("claim_unlocked"),
            }
        )

    audit_status = str(audit.get("status", "missing"))
    readiness_status = str(readiness.get("overall_status", "missing"))
    strict_status = str(strict.get("overall_status", "missing"))
    preflight_status = str(preflight.get("overall_status", "missing"))
    if strict_status == "pass":
        claim_status = "claims_unlocked"
    elif strict_status == "fail" or audit_status != "pass" or readiness_status != "pass":
        claim_status = "claims_blocked"
    else:
        claim_status = "claims_limited"

    implemented_count = 0
    if isinstance(matrix.get("benchmarks"), list):
        implemented_count = sum(
            1
            for item in matrix["benchmarks"]
            if isinstance(item, dict) and item.get("status") == "implemented"
        )

    return {
        "schema": "wavemind.production_evidence_bundle.v1",
        "generated_at": _utc_now(),
        "claim_status": claim_status,
        "summary": {
            "claim_status": claim_status,
            "strict_overall_status": strict_status,
            "strict_pass_count": strict.get("summary", {}).get("pass_count", 0),
            "strict_total_requirements": strict.get("summary", {}).get("total_requirements", 0),
            "preflight_overall_status": preflight_status,
            "preflight_ready_count": preflight.get("summary", {}).get("ready_count", 0),
            "preflight_total_checks": preflight.get("summary", {}).get("total_checks", 0),
            "production_readiness_status": readiness_status,
            "production_readiness_score": readiness.get("readiness_score"),
            "artifact_audit_status": audit_status,
            "implemented_benchmarks": implemented_count,
            "production_scale_run_contract_status": scale_run_contract.get("status"),
            "production_scale_run_profile_count": scale_run_contract.get("profile_count"),
            "production_scale_run_target_memories_total": scale_run_contract.get("target_memories_total"),
            "next_action_count": len(next_actions),
        },
        "strict_production_evidence": strict,
        "production_evidence_preflight": preflight,
        "production_readiness": readiness,
        "artifact_audit": audit,
        "production_scale_run_contract": scale_run_contract,
        "next_actions": next_actions,
        "claim_boundaries": [
            {
                "claim": "Core library/API readiness",
                "status": "unlocked" if readiness_status == "pass" and audit_status == "pass" else "blocked",
                "evidence": "production_readiness_results.json and benchmark_artifact_audit.json",
            },
            {
                "claim": "Remote service-node cluster SLO",
                "status": "unlocked" if strict_by_id.get("external_http_cluster", {}).get("status") == "pass" else "locked",
                "evidence": "benchmarks/http_cluster_load_results.json",
            },
            {
                "claim": "Remote multi-region active-active convergence",
                "status": "unlocked" if strict_by_id.get("external_http_active_active", {}).get("status") == "pass" else "locked",
                "evidence": "benchmarks/external_http_active_active_results.json",
            },
            {
                "claim": "Large-N production run contracts",
                "status": "available"
                if scale_run_contract.get("status") == "available"
                else "locked",
                "evidence": "benchmarks/production_scale_run_plan.json",
            },
            {
                "claim": "10M-100M service-backed production scale",
                "status": "unlocked"
                if all(
                    strict_by_id.get(item, {}).get("status") == "pass"
                    for item in (
                        "qdrant_10m_service",
                        "qdrant_sharded_10m_service",
                        "pgvector_10m_service",
                        "faiss_ivfpq_50m",
                        "hundred_million_remote_load",
                    )
                )
                else "locked",
                "evidence": "large-N production_streaming_load result artifacts",
            },
        ],
    }


def build_release_claims_manifest(
    root: Path = PROJECT_ROOT,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the compact release-facing claim contract.

    The production evidence bundle is intentionally verbose because operators
    need every command, missing environment variable, and evidence artifact.
    Release automation needs a smaller contract: whether the package can be
    released, which claims are safe to repeat, and which claims remain locked.
    """

    bundle = evaluate_production_evidence_bundle(root, env=env)
    summary = bundle.get("summary", {})
    claim_status = str(bundle.get("claim_status") or summary.get("claim_status") or "missing")
    readiness_status = str(summary.get("production_readiness_status") or "missing")
    artifact_audit_status = str(summary.get("artifact_audit_status") or "missing")
    strict_status = str(summary.get("strict_overall_status") or "missing")

    if claim_status == "claims_unlocked":
        release_status = "full_production_claims_ready"
    elif (
        claim_status == "claims_limited"
        and readiness_status == "pass"
        and artifact_audit_status == "pass"
    ):
        release_status = "core_release_ready"
    else:
        release_status = "release_blocked"

    allowed_claims: list[dict[str, Any]] = []
    locked_claims: list[dict[str, Any]] = []
    for row in bundle.get("claim_boundaries", []):
        if not isinstance(row, dict):
            continue
        normalized = {
            "claim": row.get("claim"),
            "status": row.get("status"),
            "evidence": row.get("evidence"),
        }
        if row.get("status") in {"unlocked", "available"}:
            allowed_claims.append(normalized)
        else:
            locked_claims.append(normalized)

    next_actions: list[dict[str, Any]] = []
    for row in bundle.get("next_actions", []):
        if not isinstance(row, dict):
            continue
        next_actions.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "strict_status": row.get("strict_status"),
                "preflight_status": row.get("preflight_status"),
                "artifact": row.get("artifact"),
                "missing_env": list(row.get("missing_env") or []),
                "command": row.get("command"),
                "claim_unlocked": row.get("claim_unlocked"),
            }
        )

    return {
        "schema": "wavemind.release_claims.v1",
        "generated_at": _utc_now(),
        "release_status": release_status,
        "claim_status": claim_status,
        "summary": {
            "release_status": release_status,
            "claim_status": claim_status,
            "strict_overall_status": strict_status,
            "production_readiness_status": readiness_status,
            "artifact_audit_status": artifact_audit_status,
            "allowed_claim_count": len(allowed_claims),
            "locked_claim_count": len(locked_claims),
            "next_action_count": len(next_actions),
        },
        "allowed_claims": allowed_claims,
        "locked_claims": locked_claims,
        "next_actions": next_actions,
        "source_artifacts": {
            "bundle": "benchmarks/production_evidence_bundle_results.json",
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "preflight": "benchmarks/production_evidence_preflight_results.json",
            "readiness": "benchmarks/production_readiness_results.json",
            "artifact_audit": "benchmarks/benchmark_artifact_audit.json",
        },
    }


_SCALE_GAP_REQUIREMENTS = {
    "qdrant-10m": "qdrant_10m_service",
    "qdrant-sharded-10m": "qdrant_sharded_10m_service",
    "pgvector-10m": "pgvector_10m_service",
    "faiss-ivfpq-50m": "faiss_ivfpq_50m",
    "qdrant-sharded-100m": "hundred_million_remote_load",
}


_SCALE_GAP_BASELINES = {
    "qdrant-10m": (
        ("benchmarks/production_streaming_load_qdrant_1m_tuned_results.json", "qdrant"),
        ("benchmarks/production_streaming_load_qdrant_1m_results.json", "qdrant"),
        ("benchmarks/production_streaming_load_qdrant_smoke_results.json", "qdrant"),
    ),
    "qdrant-sharded-10m": (
        ("benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json", "qdrant"),
        ("benchmarks/production_streaming_load_qdrant_1m_tuned_results.json", "qdrant"),
    ),
    "pgvector-10m": (
        ("benchmarks/production_pgvector_tuning_results.json", "pgvector-iterative"),
        ("benchmarks/production_streaming_load_pgvector_smoke_results.json", "pgvector"),
    ),
    "faiss-ivfpq-50m": (
        ("benchmarks/production_streaming_load_ivfpq_10m_results.json", "ivfpq"),
        ("benchmarks/production_streaming_load_ivfpq_1m_results.json", "ivfpq"),
        ("benchmarks/production_streaming_load_ivfpq_100k_results.json", "ivfpq"),
    ),
    "qdrant-sharded-100m": (
        ("benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json", "qdrant"),
        ("benchmarks/production_streaming_load_qdrant_1m_tuned_results.json", "qdrant"),
    ),
}


_ADMISSION_MIN_STRICT_MEMORIES = 10_000_000
_ADMISSION_PROFILE_TITLES = {
    "qdrant-10m": "10M Qdrant service admission",
    "qdrant-sharded-10m": "10M sharded Qdrant admission",
    "pgvector-10m": "10M pgvector service admission",
    "faiss-ivfpq-50m": "50M FAISS IVF-PQ admission",
    "qdrant-sharded-100m": "100M sharded Qdrant admission",
}


def _artifact_exists(root: Path, artifact: str) -> bool:
    return bool(artifact) and (root / artifact).exists()


def _result_metric(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_scale_baseline(
    root: Path,
    candidates: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    best: dict[str, Any] = {}
    for artifact, engine_hint in candidates:
        payload = _load_optional_json(root / artifact)
        if not payload:
            continue
        hint = engine_hint.lower()
        for result in _size_results(payload):
            engine = str(result.get("engine") or "").lower()
            if hint and hint not in engine:
                continue
            vectors = int(result.get("vectors") or 0)
            if vectors <= int(best.get("vectors") or 0):
                continue
            best = {
                "artifact": artifact,
                "engine": result.get("engine"),
                "vectors": vectors,
                "recall_at_k": _result_metric(result, "recall_at_k"),
                "target_recall_at_k": _result_metric(result, "target_recall_at_k"),
                "p99_latency_ms": _result_metric(result, "p99_latency_ms"),
                "avg_latency_ms": _result_metric(result, "avg_latency_ms"),
                "slo_status": result.get("slo_status") or result.get("status"),
                "cost_status": result.get("cost_status"),
            }
    return best


def _scale_gap_status(
    *,
    strict_status: str,
    plan_status: str,
    preflight_status: str,
    missing_env: list[str],
    blockers: list[str],
) -> str:
    if strict_status == "pass":
        return "complete"
    if plan_status in {"", "missing"}:
        return "missing_plan"
    if preflight_status == "ready":
        return "ready_to_run"
    if missing_env:
        return "blocked_by_env"
    if blockers:
        return "blocked_by_preflight"
    return "planned"


def build_scale_gap_manifest(
    root: Path = PROJECT_ROOT,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the large-scale benchmark gap matrix.

    The production scale run plan says which 10M/50M/100M jobs should be run.
    Strict production evidence says which results are already claim-worthy.
    This manifest joins the two so the public dashboard can show exactly which
    scale claims are proven, plan-only, or blocked by missing environment.
    """

    root = Path(root)
    bundle = evaluate_production_evidence_bundle(root, env=env)
    strict_requirements = {
        str(row.get("id")): row
        for row in bundle.get("strict_production_evidence", {}).get("requirements", [])
        if isinstance(row, dict)
    }
    preflight_checks = {
        str(row.get("id")): row
        for row in bundle.get("production_evidence_preflight", {}).get("checks", [])
        if isinstance(row, dict)
    }
    scale_contract = bundle.get("production_scale_run_contract") or {}
    plans = {
        str(row.get("profile")): row
        for row in scale_contract.get("profiles", [])
        if isinstance(row, dict)
    }
    full_scale_plan = _load_optional_json(
        root / "benchmarks" / "production_scale_run_plan.json"
    )
    for row in full_scale_plan.get("profiles", []) if isinstance(full_scale_plan, dict) else []:
        if not isinstance(row, dict):
            continue
        profile = str(row.get("profile") or "")
        if not profile:
            continue
        compact = plans.get(profile, {})
        plans[profile] = {**compact, **row}

    profile_gaps: list[dict[str, Any]] = []
    for profile, requirement_id in _SCALE_GAP_REQUIREMENTS.items():
        plan = plans.get(profile, {})
        requirement = strict_requirements.get(requirement_id, {})
        preflight = preflight_checks.get(requirement_id, {})
        target_memories = int(plan.get("target_memories") or 0)
        output_artifact = str(
            plan.get("output_artifact")
            or requirement.get("artifact")
            or ""
        )
        strict_status = str(requirement.get("status") or "missing")
        plan_status = str(plan.get("status") or "missing")
        preflight_status = str(preflight.get("status") or "missing")
        missing_env = list(preflight.get("missing_env") or plan.get("missing_env") or [])
        blockers = list(plan.get("blockers") or [])
        baseline = _best_scale_baseline(root, _SCALE_GAP_BASELINES.get(profile, ()))
        baseline_vectors = int(baseline.get("vectors") or 0)
        progress_ratio = (
            round(baseline_vectors / target_memories, 6)
            if target_memories > 0 and baseline_vectors > 0
            else 0.0
        )
        gap_multiplier = (
            round(target_memories / baseline_vectors, 3)
            if baseline_vectors > 0 and target_memories > 0
            else None
        )
        profile_gaps.append(
            {
                "profile": profile,
                "requirement_id": requirement_id,
                "status": _scale_gap_status(
                    strict_status=strict_status,
                    plan_status=plan_status,
                    preflight_status=preflight_status,
                    missing_env=missing_env,
                    blockers=blockers,
                ),
                "strict_status": strict_status,
                "plan_status": plan_status,
                "preflight_status": preflight_status,
                "engine": plan.get("engine"),
                "target_memories": target_memories,
                "target_recall_at_k": plan.get("target_recall_at_k"),
                "target_p99_ms": plan.get("target_p99_ms"),
                "target_qps": plan.get("target_qps"),
                "output_artifact": output_artifact,
                "output_artifact_exists": _artifact_exists(root, output_artifact),
                "checkpoint_path": plan.get("checkpoint_path"),
                "missing_env": missing_env,
                "blockers": blockers,
                "command": plan.get("command") or preflight.get("command") or requirement.get("command"),
                "claim_unlocked": requirement.get("claim_unlocked"),
                "nearest_baseline": baseline,
                "baseline_progress_ratio": progress_ratio,
                "target_gap_multiplier": gap_multiplier,
                "next_action": (
                    "Strict result artifact already passes."
                    if strict_status == "pass"
                    else "Provision the listed environment, run the command, then promote the result artifact through the ingest gate."
                ),
            }
        )

    status_counts: dict[str, int] = {}
    for row in profile_gaps:
        status = str(row["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    proven_target_memories = sum(
        int(row["target_memories"])
        for row in profile_gaps
        if row["status"] == "complete"
    )
    planned_target_memories = sum(int(row["target_memories"]) for row in profile_gaps)
    baseline_max_memories = max(
        (int((row.get("nearest_baseline") or {}).get("vectors") or 0) for row in profile_gaps),
        default=0,
    )

    return {
        "schema": "wavemind.scale_gap.v1",
        "generated_at": _utc_now(),
        "overall_status": "complete" if proven_target_memories == planned_target_memories else "action_required",
        "summary": {
            "total_profiles": len(profile_gaps),
            "complete_count": status_counts.get("complete", 0),
            "ready_to_run_count": status_counts.get("ready_to_run", 0),
            "blocked_by_env_count": status_counts.get("blocked_by_env", 0),
            "blocked_by_preflight_count": status_counts.get("blocked_by_preflight", 0),
            "missing_plan_count": status_counts.get("missing_plan", 0),
            "planned_target_memories": planned_target_memories,
            "proven_target_memories": proven_target_memories,
            "nearest_baseline_max_memories": baseline_max_memories,
            "claim_status": bundle.get("claim_status"),
        },
        "profile_gaps": profile_gaps,
        "source_artifacts": {
            "production_scale_run_plan": "benchmarks/production_scale_run_plan.json",
            "production_evidence_bundle": "benchmarks/production_evidence_bundle_results.json",
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "preflight": "benchmarks/production_evidence_preflight_results.json",
        },
    }


def _normalize_admission_engine(engine: str | None) -> str | None:
    normalized = str(engine or "").strip().lower().replace("_", "-")
    if not normalized:
        return None
    aliases = {
        "qdrant": "qdrant-service",
        "qdrant-service": "qdrant-service",
        "qdrant-local": "qdrant-service",
        "qdrant-sharded": "qdrant-sharded-service",
        "sharded-qdrant": "qdrant-sharded-service",
        "qdrant-sharded-service": "qdrant-sharded-service",
        "pgvector": "pgvector-service",
        "postgres": "pgvector-service",
        "postgresql": "pgvector-service",
        "pgvector-service": "pgvector-service",
        "faiss": "faiss-ivfpq-persisted",
        "faiss-ivfpq": "faiss-ivfpq-persisted",
        "faiss-ivfpq-persisted": "faiss-ivfpq-persisted",
    }
    return aliases.get(normalized, normalized)


def _admission_profiles_for_target(
    *,
    target_memories: int,
    engine: str | None,
) -> tuple[str, ...]:
    normalized_engine = _normalize_admission_engine(engine)
    target = int(target_memories)
    if target < _ADMISSION_MIN_STRICT_MEMORIES:
        return ()
    if target >= 100_000_000:
        if normalized_engine in {None, "qdrant-sharded-service"}:
            return ("qdrant-sharded-100m",)
        return ()
    if target >= 50_000_000:
        if normalized_engine in {None, "faiss-ivfpq-persisted"}:
            return ("faiss-ivfpq-50m",)
        if normalized_engine == "qdrant-sharded-service":
            return ("qdrant-sharded-100m",)
        return ()
    if normalized_engine is None:
        return ("qdrant-10m", "qdrant-sharded-10m", "pgvector-10m")
    if normalized_engine == "qdrant-service":
        return ("qdrant-10m",)
    if normalized_engine == "qdrant-sharded-service":
        return ("qdrant-sharded-10m",)
    if normalized_engine == "pgvector-service":
        return ("pgvector-10m",)
    if normalized_engine == "faiss-ivfpq-persisted":
        return ("faiss-ivfpq-50m",)
    return ()


def evaluate_production_admission(
    root: Path = PROJECT_ROOT,
    *,
    target_memories: int,
    engine: str | None = None,
    deployment: str = "production",
    allow_plan_only: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Decide whether a requested production scale is currently admissible.

    This is stricter than the roadmap and stricter than scale planning. It only
    admits large-N deployments when matching strict evidence artifacts already
    pass. Plan-only contracts are reported as useful next steps, never as
    production admission.
    """

    root = Path(root)
    target = max(0, int(target_memories))
    normalized_engine = _normalize_admission_engine(engine)
    strict = evaluate_production_evidence(root)
    strict_requirements = {
        str(row.get("id")): row
        for row in strict.get("requirements", [])
        if isinstance(row, dict)
    }
    gap = build_scale_gap_manifest(root, env=env)
    gaps = {
        str(row.get("profile")): row
        for row in gap.get("profile_gaps", [])
        if isinstance(row, dict)
    }
    selected_profiles = _admission_profiles_for_target(
        target_memories=target,
        engine=normalized_engine,
    )
    issues: list[str] = []
    warnings: list[str] = []
    required_evidence: list[dict[str, Any]] = []

    if target >= _ADMISSION_MIN_STRICT_MEMORIES and not selected_profiles:
        issues.append(
            "No strict production-evidence profile covers this target/engine combination."
        )
        warnings.append(
            "Use `wavemind production-scale-plan --profile all --json` to choose a supported 10M/50M/100M profile."
        )

    if target < _ADMISSION_MIN_STRICT_MEMORIES:
        warnings.append(
            "Strict large-N admission is not required below 10M memories; still run scale-plan and production-readiness gates."
        )

    for profile in selected_profiles:
        gap_row = gaps.get(profile, {})
        requirement_id = str(
            gap_row.get("requirement_id") or _SCALE_GAP_REQUIREMENTS.get(profile) or ""
        )
        requirement = strict_requirements.get(requirement_id, {})
        status = str(requirement.get("status") or gap_row.get("strict_status") or "missing")
        profile_status = str(gap_row.get("status") or "missing")
        row = {
            "profile": profile,
            "title": _ADMISSION_PROFILE_TITLES.get(profile, profile),
            "requirement_id": requirement_id,
            "strict_status": status,
            "scale_gap_status": profile_status,
            "admitted": status == "pass",
            "artifact": requirement.get("artifact") or gap_row.get("output_artifact"),
            "artifact_exists": bool(gap_row.get("output_artifact_exists")),
            "target_memories": gap_row.get("target_memories") or target,
            "target_recall_at_k": gap_row.get("target_recall_at_k"),
            "target_p99_ms": gap_row.get("target_p99_ms"),
            "target_qps": gap_row.get("target_qps"),
            "nearest_baseline": gap_row.get("nearest_baseline") or {},
            "baseline_progress_ratio": gap_row.get("baseline_progress_ratio"),
            "target_gap_multiplier": gap_row.get("target_gap_multiplier"),
            "missing_env": list(gap_row.get("missing_env") or []),
            "blockers": list(gap_row.get("blockers") or []),
            "issues": list(requirement.get("issues") or []),
            "command": requirement.get("command") or gap_row.get("command"),
            "next_action": gap_row.get("next_action")
            or "Run the strict evidence command and ingest the resulting artifact.",
        }
        required_evidence.append(row)
        if status != "pass":
            issues.append(
                f"{profile} is not admitted: strict_status={status}, scale_gap_status={profile_status}"
            )
        if profile_status in {"ready_to_run", "planned"} and status != "pass":
            warnings.append(f"{profile} has a run contract, but no passing strict artifact yet.")

    admitted = bool(required_evidence) and any(row["admitted"] for row in required_evidence)
    if not required_evidence and target < _ADMISSION_MIN_STRICT_MEMORIES:
        admitted = True

    if admitted:
        status = "admitted"
    elif allow_plan_only and required_evidence and any(
        row["scale_gap_status"] in {"ready_to_run", "planned", "blocked_by_env", "blocked_by_preflight"}
        for row in required_evidence
    ):
        status = "plan_only"
    else:
        status = "blocked"

    next_actions: list[str] = []
    if status == "admitted":
        next_actions.append("Proceed with deployment, keeping production-readiness and runtime health gates enabled.")
    elif status == "plan_only":
        next_actions.append("Do not admit production traffic yet; run the listed strict-evidence job first.")
    elif target >= _ADMISSION_MIN_STRICT_MEMORIES:
        next_actions.append("Keep the production claim locked until a matching strict evidence artifact passes.")
    else:
        next_actions.append("Run `wavemind scale-plan --fail-on action_required` for the concrete deployment.")
    for row in required_evidence:
        command = str(row.get("command") or "")
        if command and command not in next_actions:
            next_actions.append(command)

    return {
        "schema": "wavemind.production_admission.v1",
        "generated_at": _utc_now(),
        "status": status,
        "admitted": admitted,
        "deployment": str(deployment),
        "target_memories": target,
        "engine": normalized_engine,
        "allow_plan_only": bool(allow_plan_only),
        "claim_boundary": (
            "strict_evidence_required"
            if target >= _ADMISSION_MIN_STRICT_MEMORIES
            else "scale_plan_required"
        ),
        "summary": {
            "status": status,
            "admitted": admitted,
            "required_profiles": list(selected_profiles),
            "required_evidence_count": len(required_evidence),
            "blocking_issue_count": len(dict.fromkeys(issues)),
            "warning_count": len(dict.fromkeys(warnings)),
            "strict_overall_status": strict.get("overall_status"),
            "scale_gap_status": gap.get("overall_status"),
        },
        "required_evidence": required_evidence,
        "issues": list(dict.fromkeys(issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "next_actions": list(dict.fromkeys(next_actions)),
        "source_artifacts": {
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "scale_gap": "benchmarks/scale_gap_results.json",
            "production_scale_run_plan": "benchmarks/production_scale_run_plan.json",
        },
    }


def evaluate_active_active_admission(
    root: Path = PROJECT_ROOT,
    *,
    deployment: str = "production",
    min_regions: int = 3,
    namespace_count: int = 16,
    p99_slo_ms: float = 1500.0,
    allow_plan_only: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Gate multi-region active-active production rollout.

    This is the deployment-facing counterpart to the strict production evidence
    requirement named ``external_http_active_active``. It never treats local
    loopback profiles as production evidence. A production rollout is admitted
    only after a real external HTTP active-active artifact passes.
    """

    root = Path(root)
    strict = evaluate_production_evidence(root)
    strict_requirements = {
        str(row.get("id")): row
        for row in strict.get("requirements", [])
        if isinstance(row, dict)
    }
    requirement = strict_requirements.get("external_http_active_active", {})
    preflight = evaluate_production_evidence_preflight(root, env=env)
    preflight_checks = {
        str(row.get("id")): row
        for row in preflight.get("checks", [])
        if isinstance(row, dict)
    }
    preflight_check = preflight_checks.get("external_http_active_active", {})

    strict_status = str(requirement.get("status") or "missing")
    preflight_status = str(preflight_check.get("status") or "missing")
    admitted = strict_status == "pass"
    if admitted:
        status = "admitted"
    elif allow_plan_only:
        status = "plan_only"
    else:
        status = "blocked"

    issues: list[str] = []
    warnings: list[str] = []
    if strict_status != "pass":
        issues.append(
            "external_http_active_active is not admitted: "
            f"strict_status={strict_status}"
        )
    if preflight_status != "ready":
        warnings.append(
            "active-active remote preflight is not ready; provide real region URLs "
            "or a regions manifest before dispatching the workflow."
        )
    if int(min_regions) < 3:
        issues.append("min_regions must be at least 3 for production active-active.")
    if int(namespace_count) < 1:
        issues.append("namespace_count must be positive.")
    if float(p99_slo_ms) <= 0:
        issues.append("p99_slo_ms must be positive.")

    command = str(requirement.get("command") or preflight_check.get("command") or "")
    next_actions: list[str] = []
    if admitted:
        next_actions.append(
            "Proceed with multi-region rollout while keeping convergence, tombstone, and p99 SLO monitors enabled."
        )
    elif status == "plan_only":
        next_actions.append(
            "Do not admit multi-region production traffic yet; run the external active-active workflow against real regions first."
        )
    else:
        next_actions.append(
            "Keep the active-active production claim locked until the strict external artifact passes."
        )
    if command:
        next_actions.append(command)

    requirement_issues = list(requirement.get("issues") or [])
    preflight_issues = list(preflight_check.get("issues") or [])
    missing_env = list(preflight_check.get("missing_env") or [])
    required_env = list(preflight_check.get("required_env") or [])

    return {
        "schema": "wavemind.active_active_admission.v1",
        "generated_at": _utc_now(),
        "status": status,
        "admitted": admitted,
        "deployment": str(deployment),
        "min_regions": int(min_regions),
        "namespace_count": int(namespace_count),
        "p99_slo_ms": float(p99_slo_ms),
        "allow_plan_only": bool(allow_plan_only),
        "claim_boundary": "external_active_active_evidence_required",
        "summary": {
            "status": status,
            "admitted": admitted,
            "strict_status": strict_status,
            "preflight_status": preflight_status,
            "required_artifact": requirement.get("artifact")
            or "benchmarks/external_http_active_active_results.json",
            "missing_env": missing_env,
            "blocking_issue_count": len(dict.fromkeys(issues + requirement_issues)),
            "warning_count": len(dict.fromkeys(warnings + preflight_issues)),
        },
        "required_evidence": {
            "id": "external_http_active_active",
            "title": requirement.get("title") or "External HTTP active-active regions",
            "status": strict_status,
            "artifact": requirement.get("artifact")
            or "benchmarks/external_http_active_active_results.json",
            "evidence": requirement.get("evidence")
            or "missing external active-active artifact",
            "issues": requirement_issues,
            "command": command,
            "claim_unlocked": requirement.get("claim_unlocked")
            or "Remote multi-region active-active memory convergence.",
        },
        "preflight": {
            "status": preflight_status,
            "ready": bool(preflight_check.get("ready")),
            "evidence": preflight_check.get("evidence") or "",
            "required_env": required_env,
            "missing_env": missing_env,
            "issues": preflight_issues,
            "warnings": list(preflight_check.get("warnings") or []),
            "output_artifact": preflight_check.get("output_artifact")
            or "benchmarks/external_http_active_active_results.json",
        },
        "issues": list(dict.fromkeys(issues + requirement_issues)),
        "warnings": list(dict.fromkeys(warnings + preflight_issues)),
        "next_actions": list(dict.fromkeys(next_actions)),
        "source_artifacts": {
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "preflight": "benchmarks/production_evidence_preflight_results.json",
            "required_result": "benchmarks/external_http_active_active_results.json",
        },
    }


def render_active_active_admission_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    required = payload["required_evidence"]
    preflight = payload["preflight"]
    lines = [
        "# WaveMind Active-Active Admission",
        "",
        "This is the deployment-facing gate for remote multi-region active-active",
        "rollouts. It admits production traffic only when real external HTTP",
        "regions have passed convergence, tombstone, final-noop, and p99 SLO",
        "evidence. Local loopback profiles stay useful for development, but do",
        "not unlock this gate.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| admitted | `{payload['admitted']}` |",
        f"| deployment | `{payload['deployment']}` |",
        f"| min regions | `{payload['min_regions']}` |",
        f"| namespace count | `{payload['namespace_count']}` |",
        f"| p99 SLO ms | `{payload['p99_slo_ms']}` |",
        f"| strict evidence | `{summary['strict_status']}` |",
        f"| preflight | `{summary['preflight_status']}` |",
        f"| required artifact | `{summary['required_artifact']}` |",
        "",
        "## Required Evidence",
        "",
        "| requirement | status | artifact | evidence |",
        "|---|---|---|---|",
        "| {title} | `{status}` | `{artifact}` | {evidence} |".format(
            title=required["title"],
            status=required["status"],
            artifact=required["artifact"],
            evidence=str(required.get("evidence") or "").replace("|", "\\|"),
        ),
        "",
        "## Preflight",
        "",
        "| status | required env | missing env | evidence |",
        "|---|---|---|---|",
        "| `{status}` | `{required_env}` | `{missing_env}` | {evidence} |".format(
            status=preflight["status"],
            required_env=", ".join(preflight.get("required_env") or []),
            missing_env=", ".join(preflight.get("missing_env") or []),
            evidence=str(preflight.get("evidence") or "").replace("|", "\\|"),
        ),
        "",
        "## Issues",
        "",
    ]
    issues = payload.get("issues") or []
    lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- none")
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions", []):
        lines.append(
            f"- `{action}`"
            if action.startswith(("python ", "gh ", "wavemind "))
            else f"- {action}"
        )
    lines.append("")
    return "\n".join(lines)


def render_production_admission_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Admission",
        "",
        "This is the deployment-facing admission gate. It answers whether a",
        "requested production scale is backed by passing strict evidence, or still",
        "limited to a plan-only run contract.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| admitted | `{payload['admitted']}` |",
        f"| deployment | `{payload['deployment']}` |",
        f"| engine | `{payload.get('engine')}` |",
        f"| target memories | `{payload['target_memories']}` |",
        f"| required profiles | `{', '.join(summary.get('required_profiles') or [])}` |",
        f"| blocking issues | `{summary['blocking_issue_count']}` |",
        f"| strict evidence | `{summary['strict_overall_status']}` |",
        f"| scale gap | `{summary['scale_gap_status']}` |",
        "",
        "## Required Evidence",
        "",
        "| profile | strict | scale gap | artifact | nearest baseline | missing env |",
        "|---|---|---|---|---:|---|",
    ]
    for row in payload.get("required_evidence", []):
        baseline = row.get("nearest_baseline") or {}
        missing_env = ", ".join(row.get("missing_env") or ())
        lines.append(
            f"| {row['profile']} | `{row['strict_status']}` | `{row['scale_gap_status']}` | "
            f"`{row.get('artifact')}` | {baseline.get('vectors') or 0} | `{missing_env}` |"
        )
    lines.extend(["", "## Issues", ""])
    issues = payload.get("issues") or []
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- none")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" if action.startswith(("python ", "gh ", "wavemind ")) else f"- {action}" for action in payload.get("next_actions", []))
    lines.append("")
    return "\n".join(lines)


def render_scale_gap_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Scale Gap Matrix",
        "",
        "This report joins the large-N production run contracts with the strict",
        "production evidence gate. It shows which 10M, 50M, and 100M scale claims",
        "are proven, which are plan-only, and what must run next.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{payload['overall_status']}` |",
        f"| complete profiles | `{summary['complete_count']}/{summary['total_profiles']}` |",
        f"| ready to run | `{summary['ready_to_run_count']}` |",
        f"| blocked by env | `{summary['blocked_by_env_count']}` |",
        f"| planned target memories | `{summary['planned_target_memories']}` |",
        f"| proven target memories | `{summary['proven_target_memories']}` |",
        f"| nearest baseline max memories | `{summary['nearest_baseline_max_memories']}` |",
        f"| claim status | `{summary['claim_status']}` |",
        "",
        "| profile | status | target | nearest baseline | gap | artifact | missing env |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in payload.get("profile_gaps", []):
        baseline = row.get("nearest_baseline") or {}
        missing_env = ", ".join(row.get("missing_env") or ())
        baseline_vectors = baseline.get("vectors") or 0
        gap = row.get("target_gap_multiplier")
        lines.append(
            f"| {row['profile']} | `{row['status']}` | {row['target_memories']} | "
            f"{baseline_vectors} | {gap if gap is not None else ''} | "
            f"`{row['output_artifact']}` | `{missing_env}` |"
        )
    lines.extend(["", "## Commands", ""])
    for row in payload.get("profile_gaps", []):
        command = str(row.get("command") or "").replace("|", "\\|")
        lines.append(f"- `{row['profile']}`: `{command}`")
    lines.append("")
    return "\n".join(lines)


def render_dispatch_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Evidence Dispatch Plan",
        "",
        "This report turns strict production-evidence gaps into concrete GitHub",
        "Actions dispatch payloads. It does not unlock production claims by itself;",
        "claims unlock only after the resulting artifacts pass the ingest gate and",
        "strict production-evidence validation.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{payload['overall_status']}` |",
        f"| ready to dispatch | `{summary['ready_to_dispatch_count']}` |",
        f"| blocked by preflight | `{summary['blocked_by_preflight_count']}` |",
        f"| complete | `{summary['complete_count']}` |",
        f"| total jobs | `{summary['total_jobs']}` |",
        f"| runner label | `{summary['runner_label']}` |",
        f"| commit results default | `{summary['commit_results_default']}` |",
        "",
        "## Jobs",
        "",
        "| job | status | wave | workflow | artifact | missing env |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload.get("jobs", []):
        missing_env = ", ".join(row.get("missing_env") or ())
        lines.append(
            f"| {row['title']} | `{row['status']}` | `{row['wave']}` | "
            f"`{row['workflow']}` | `{row['artifact']}` | `{missing_env}` |"
        )

    lines.extend(["", "## Safe Launch Commands", ""])
    for row in payload.get("jobs", []):
        command = str(row.get("safe_launch_command") or "").replace("|", "\\|")
        lines.append(f"- `{row['id']}`: `{command}`")

    lines.extend(["", "## Promotion", ""])
    promotion = payload.get("promotion", {})
    lines.append(f"- Download: `{promotion.get('download_command', '')}`")
    lines.append(f"- Ingest: `{promotion.get('ingest_command', '')}`")
    lines.append(f"- Boundary: {promotion.get('claim_boundary', '')}")
    lines.append("")
    return "\n".join(lines)


def render_release_claims_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Release Claims",
        "",
        "This is the compact release-facing claim contract. It separates what a",
        "release may safely claim from production-scale claims that remain locked",
        "until strict external evidence artifacts pass.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| release status | `{summary['release_status']}` |",
        f"| claim status | `{summary['claim_status']}` |",
        f"| strict evidence | `{summary['strict_overall_status']}` |",
        f"| production readiness | `{summary['production_readiness_status']}` |",
        f"| artifact audit | `{summary['artifact_audit_status']}` |",
        f"| allowed claims | `{summary['allowed_claim_count']}` |",
        f"| locked claims | `{summary['locked_claim_count']}` |",
        f"| next actions | `{summary['next_action_count']}` |",
        "",
        "## Allowed Claims",
        "",
        "| claim | status | evidence |",
        "|---|---|---|",
    ]
    for row in payload.get("allowed_claims", []):
        lines.append(
            f"| {row['claim']} | `{row['status']}` | `{row['evidence']}` |"
        )
    lines.extend(
        [
            "",
            "## Locked Claims",
            "",
            "| claim | status | evidence |",
            "|---|---|---|",
        ]
    )
    for row in payload.get("locked_claims", []):
        lines.append(
            f"| {row['claim']} | `{row['status']}` | `{row['evidence']}` |"
        )
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "| item | strict | preflight | artifact | missing env | command |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in payload.get("next_actions", []):
        missing_env = ", ".join(row.get("missing_env") or ())
        command = str(row.get("command") or "").replace("|", "\\|")
        lines.append(
            f"| {row['title']} | `{row['strict_status']}` | `{row['preflight_status']}` | "
            f"`{row['artifact']}` | `{missing_env}` | `{command}` |"
        )
    lines.append("")
    return "\n".join(lines)


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Strict Production Evidence Gate",
        "",
        "This report is the hard boundary for large-scale production claims.",
        "Core readiness can pass without these artifacts; claiming remote",
        "multi-region, managed-serverless, 50M, or 100M production scale cannot.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{summary['overall_status']}` |",
        f"| passed requirements | `{summary['pass_count']}` |",
        f"| action required | `{summary['action_required_count']}` |",
        f"| failed requirements | `{summary['fail_count']}` |",
        f"| total requirements | `{summary['total_requirements']}` |",
        "",
        "| requirement | status | evidence | artifact | command | unlocks |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["requirements"]:
        command = str(row["command"]).replace("|", "\\|")
        evidence = str(row["evidence"]).replace("|", "\\|")
        issues = ", ".join(row.get("issues") or ())
        if issues:
            evidence = f"{evidence}; issues: {issues}"
        lines.append(
            f"| {row['title']} | `{row['status']}` | {evidence} | "
            f"`{row['artifact']}` | `{command}` | {row['claim_unlocked']} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_bundle_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Evidence Bundle",
        "",
        "This bundle is the operator-facing status page for large-scale production claims.",
        "It combines strict evidence, environment preflight, readiness, benchmark audit,",
        "claim boundaries, and the exact next actions required to unlock blocked claims.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| claim status | `{summary['claim_status']}` |",
        f"| strict evidence | `{summary['strict_pass_count']}/{summary['strict_total_requirements']}` |",
        f"| preflight ready | `{summary['preflight_ready_count']}/{summary['preflight_total_checks']}` |",
        f"| production readiness | `{summary['production_readiness_status']}` |",
        f"| readiness score | `{summary['production_readiness_score']}` |",
        f"| artifact audit | `{summary['artifact_audit_status']}` |",
        f"| implemented benchmarks | `{summary['implemented_benchmarks']}` |",
        f"| production scale run contract | `{summary.get('production_scale_run_contract_status', 'missing')}` |",
        f"| production scale profiles | `{summary.get('production_scale_run_profile_count', 0)}` |",
        f"| production scale target memories | `{summary.get('production_scale_run_target_memories_total', 0)}` |",
        f"| next actions | `{summary['next_action_count']}` |",
        "",
        "## Claim Boundaries",
        "",
        "| claim | status | evidence |",
        "|---|---|---|",
    ]
    for row in payload.get("claim_boundaries", []):
        lines.append(
            f"| {row['claim']} | `{row['status']}` | `{row['evidence']}` |"
        )
    contract = payload.get("production_scale_run_contract") or {}
    if contract:
        lines.extend(
            [
                "",
                "## Production Scale Run Contract",
                "",
                "| profile | status | engine | target memories | output artifact | missing env |",
                "|---|---|---|---:|---|---|",
            ]
        )
        for row in contract.get("profiles", []):
            missing_env = ", ".join(row.get("missing_env") or ())
            lines.append(
                f"| {row.get('profile')} | `{row.get('status')}` | `{row.get('engine')}` | "
                f"{row.get('target_memories')} | `{row.get('output_artifact')}` | `{missing_env}` |"
            )
        issues = ", ".join(contract.get("issues") or ())
        if issues:
            lines.extend(["", f"Contract issues: {issues}"])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "| item | strict | preflight | artifact | missing env | command |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in payload.get("next_actions", []):
        missing_env = ", ".join(row.get("missing_env") or ())
        issues = ", ".join(row.get("issues") or ())
        if issues:
            missing_env = f"{missing_env}; issues: {issues}".strip("; ")
        command = str(row.get("command") or "").replace("|", "\\|")
        lines.append(
            f"| {row['title']} | `{row['strict_status']}` | `{row['preflight_status']}` | "
            f"`{row['artifact']}` | `{missing_env}` | `{command}` |"
        )
    lines.append("")
    return "\n".join(lines)


def render_preflight_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Evidence Preflight",
        "",
        "This report checks whether the environment is ready to run the strict",
        "remote and large-N production evidence jobs. It is not a substitute for",
        "the strict production evidence gate; it only verifies prerequisites.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{summary['overall_status']}` |",
        f"| ready checks | `{summary['ready_count']}` |",
        f"| action required | `{summary['action_required_count']}` |",
        f"| total checks | `{summary['total_checks']}` |",
        "",
        "| check | status | evidence | missing env | output | command |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["checks"]:
        evidence = str(row["evidence"]).replace("|", "\\|")
        issues = ", ".join(row.get("issues") or ())
        warnings = ", ".join(row.get("warnings") or ())
        if issues:
            evidence = f"{evidence}; issues: {issues}"
        if warnings:
            evidence = f"{evidence}; warnings: {warnings}"
        missing_env = ", ".join(row.get("missing_env") or ())
        command = str(row["command"]).replace("|", "\\|")
        lines.append(
            f"| {row['title']} | `{row['status']}` | {evidence} | "
            f"`{missing_env}` | `{row['output_artifact']}` | `{command}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=default_root or PROJECT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_evidence_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_EVIDENCE.md"),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless every external production-evidence requirement passes.",
    )
    args = parser.parse_args(argv)
    payload = evaluate_production_evidence(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"{payload['overall_status']} "
        f"({payload['summary']['pass_count']}/{payload['summary']['total_requirements']} pass)"
    )
    if args.strict and payload["overall_status"] != "pass":
        return 2
    return 0 if payload["overall_status"] in {"pass", "action_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
