from __future__ import annotations

import argparse
import json
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


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _validate_external_cluster_payload(
    payload: dict[str, Any] | None,
    *,
    min_nodes: int = 4,
    min_namespaces: int = 32,
    min_memories_per_namespace: int = 8,
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

    evidence = (
        f"nodes {scenario.get('node_count')}, "
        f"deployment {scenario.get('deployment_id')}, "
        f"environment {scenario.get('environment')}, "
        f"source {scenario.get('source')}, "
        f"namespaces {scenario.get('namespace_count')}, "
        f"success {result.get('success_rate')}, "
        f"failover {result.get('failover_hit_rate')}, "
        f"p99 {result.get('p99_operation_ms')} ms"
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
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
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
