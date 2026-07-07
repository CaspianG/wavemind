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
    return json.loads(path.read_text(encoding="utf-8"))


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
        str(scenario.get("evidence_source") or "").lower() not in {"", "fixture", "sample"},
        "evidence_source is required and cannot be fixture/sample",
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
            "next_action_count": len(next_actions),
        },
        "strict_production_evidence": strict,
        "production_evidence_preflight": preflight,
        "production_readiness": readiness,
        "artifact_audit": audit,
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
