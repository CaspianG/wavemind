#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK_ARTIFACT = "benchmarks/kubernetes_cluster_network_smoke_results.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run(
    command: list[str],
    *,
    timeout: float = 120.0,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=input_text,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _pod_ready(pod: dict[str, Any]) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in (pod.get("status") or {}).get("conditions") or []
    )


def current_cluster_pods(
    *,
    kubectl: str,
    namespace: str,
    cluster_name: str,
) -> list[dict[str, Any]]:
    selector = (
        f"app.kubernetes.io/instance={cluster_name},"
        "app.kubernetes.io/component=api"
    )
    payload = json.loads(
        _run(
            [
                kubectl,
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                selector,
                "-o",
                "json",
            ]
        )
    )
    return [
        {
            "id": str((pod.get("metadata") or {}).get("name") or ""),
            "uid": str((pod.get("metadata") or {}).get("uid") or ""),
            "worker": str((pod.get("spec") or {}).get("nodeName") or ""),
            "ready": _pod_ready(pod),
        }
        for pod in payload.get("items") or []
    ]


def evaluate_kubernetes_external_http_cluster_evidence(
    load_payload: dict[str, Any],
    network_payload: dict[str, Any],
    *,
    current_pods: list[dict[str, Any]] | None = None,
    network_artifact: str = DEFAULT_NETWORK_ARTIFACT,
) -> dict[str, Any]:
    payload = copy.deepcopy(load_payload)
    payload["schema"] = "wavemind.external_http_cluster.v2"
    scenario = payload.setdefault("scenario", {})
    result = next(
        (
            row
            for row in payload.get("results") or []
            if row.get("engine") == "WaveMind external HTTP cluster load"
        ),
        {},
    )
    observed = dict(network_payload.get("observed") or {})
    network_addresses = [str(item) for item in observed.get("service_addresses") or []]
    load_addresses = [str(item) for item in scenario.get("node_addresses") or []]
    placement = [dict(item) for item in observed.get("pod_placement") or []]
    placement_by_id = {str(item.get("id") or ""): item for item in placement}
    current_by_id = {
        str(item.get("id") or ""): dict(item)
        for item in (current_pods or placement)
    }
    target_pods = {
        str(item) for item in observed.get("target_data_pods") or []
    }
    outage = dict(observed.get("outage") or {})
    recovered = dict(observed.get("recovered") or {})
    failed_during_outage = {
        str(item) for item in outage.get("failed_nodes_seen") or []
    }
    network_checks = list(network_payload.get("checks") or [])
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, observed_value: Any, required: Any) -> None:
        checks.append(
            {
                "id": check_id,
                "passed": bool(passed),
                "observed": observed_value,
                "required": required,
            }
        )

    check(
        "load_slo",
        bool(result.get("slo_pass")),
        {
            "slo_pass": result.get("slo_pass"),
            "success_rate": result.get("success_rate"),
            "p99_operation_ms": result.get("p99_operation_ms"),
        },
        "mixed workload SLO pass",
    )
    check(
        "network_evidence_pass",
        network_payload.get("schema") == "wavemind.kubernetes_cluster_network_smoke.v1"
        and network_payload.get("status") == "pass"
        and bool(network_checks)
        and all(bool(item.get("passed")) for item in network_checks),
        {
            "schema": network_payload.get("schema"),
            "status": network_payload.get("status"),
            "passed_checks": sum(bool(item.get("passed")) for item in network_checks),
            "check_count": len(network_checks),
        },
        "passing Kubernetes physical-network evidence",
    )
    check(
        "same_service_nodes",
        len(load_addresses) >= 4
        and set(load_addresses) == set(network_addresses)
        and set(str(item) for item in scenario.get("node_ids") or [])
        == set(placement_by_id),
        {
            "load_addresses": load_addresses,
            "network_addresses": network_addresses,
        },
        "load and failure drill use the same four or more pods",
    )
    check(
        "non_loopback_pod_dns",
        bool(load_addresses)
        and all(".svc.cluster.local" in value for value in load_addresses)
        and all("localhost" not in value and "127.0.0.1" not in value for value in load_addresses),
        load_addresses,
        "Kubernetes pod DNS only",
    )
    check(
        "three_failure_domains",
        int(observed.get("zone_count") or 0) >= 3,
        observed.get("zone_count"),
        3,
    )
    check(
        "physical_worker_failure",
        observed.get("failure_method") == "docker-pause-kind-worker"
        and bool(observed.get("target_worker"))
        and bool(target_pods)
        and bool(failed_during_outage & target_pods),
        {
            "method": observed.get("failure_method"),
            "target_worker": observed.get("target_worker"),
            "target_pods": sorted(target_pods),
            "failed_nodes_seen": sorted(failed_during_outage),
        },
        "physical worker pause makes at least one hosted pod unreachable",
    )
    check(
        "quorum_availability_during_outage",
        outage.get("status") == "pass"
        and float(outage.get("hit_rate") or 0.0) >= 1.0,
        {"status": outage.get("status"), "hit_rate": outage.get("hit_rate")},
        "100% recall during physical worker outage",
    )
    check(
        "full_recovery",
        recovered.get("status") == "pass"
        and float(recovered.get("hit_rate") or 0.0) >= 1.0
        and not recovered.get("failed_nodes_seen")
        and bool(observed.get("worker_unpaused"))
        and bool(observed.get("node_ready_after_recovery")),
        {
            "status": recovered.get("status"),
            "hit_rate": recovered.get("hit_rate"),
            "failed_nodes_seen": recovered.get("failed_nodes_seen"),
            "worker_unpaused": observed.get("worker_unpaused"),
            "node_ready": observed.get("node_ready_after_recovery"),
        },
        "worker and all service nodes recover",
    )
    identities_preserved = bool(placement_by_id) and all(
        bool(current_by_id.get(pod_id, {}).get("ready", True))
        and str(current_by_id.get(pod_id, {}).get("uid") or "")
        == str(item.get("uid") or "")
        and str(current_by_id.get(pod_id, {}).get("worker") or "")
        == str(item.get("worker") or "")
        for pod_id, item in placement_by_id.items()
    )
    check(
        "pod_identity_preserved",
        bool(observed.get("pod_uids_preserved")) and identities_preserved,
        {
            "drill_reported": observed.get("pod_uids_preserved"),
            "current_pods": current_by_id,
        },
        "same pod UIDs and worker placement after recovery",
    )
    check(
        "github_workflow_provenance",
        bool(network_payload.get("source_ref"))
        and bool(network_payload.get("workflow_run_id"))
        and bool(network_payload.get("workflow_run_url")),
        {
            "source_ref": network_payload.get("source_ref"),
            "workflow_run_id": network_payload.get("workflow_run_id"),
            "workflow_run_url": network_payload.get("workflow_run_url"),
        },
        "traceable GitHub Actions source SHA and workflow run",
    )

    passed_checks = sum(bool(item["passed"]) for item in checks)
    attestation = {
        "schema": "wavemind.kubernetes_external_http_cluster_attestation.v1",
        "generated_at": _utc_now(),
        "status": "pass" if passed_checks == len(checks) else "fail",
        "evidence_source": "github-actions-kind-physical-node-pause",
        "network_evidence_artifact": network_artifact.replace("\\", "/"),
        "network_evidence_sha256": canonical_payload_sha256(network_payload),
        "source_ref": network_payload.get("source_ref"),
        "workflow_run_id": network_payload.get("workflow_run_id"),
        "workflow_run_url": network_payload.get("workflow_run_url"),
        "service_addresses": network_addresses,
        "failure_domains": sorted(
            {str(item.get("zone") or "") for item in placement if item.get("zone")}
        ),
        "physical_failure": {
            "method": observed.get("failure_method"),
            "target_worker": observed.get("target_worker"),
            "target_pods": sorted(target_pods),
            "outage_duration_ms": observed.get("outage_duration_ms"),
        },
        "summary": {
            "check_count": len(checks),
            "passed_checks": passed_checks,
            "failed_checks": len(checks) - passed_checks,
        },
        "checks": checks,
    }
    scenario.update(
        {
            "environment": "kubernetes-kind-non-loopback-ci",
            "source": "kubernetes-pod-dns-physical-node-drill",
            "source_ref": network_payload.get("source_ref"),
            "workflow_run_id": network_payload.get("workflow_run_id"),
            "workflow_run_url": network_payload.get("workflow_run_url"),
            "kubernetes_attestation": attestation,
            "claim_boundary": (
                "Ephemeral non-loopback Kubernetes service-network capability evidence; "
                "not managed multi-region production evidence."
            ),
        }
    )
    if result:
        result["physical_failure_slo_pass"] = attestation["status"] == "pass"
    return payload


def _write_source_to_pod(
    *,
    kubectl: str,
    namespace: str,
    pod: str,
    destination: str,
    source: Path,
) -> None:
    parent = str(Path(destination).parent).replace("\\", "/")
    command = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"cat > {shlex.quote(destination)}"
    )
    _run(
        [kubectl, "exec", "-i", pod, "-n", namespace, "--", "sh", "-c", command],
        input_text=source.read_text(encoding="utf-8"),
    )


def run_kubernetes_external_http_cluster_evidence(
    args: argparse.Namespace,
) -> dict[str, Any]:
    network_payload = json.loads(args.network_evidence.read_text(encoding="utf-8"))
    observed = dict(network_payload.get("observed") or {})
    placement = [dict(item) for item in observed.get("pod_placement") or []]
    if network_payload.get("status") != "pass" or len(placement) < 4:
        raise RuntimeError("physical Kubernetes network evidence is not passing")
    runner_pod = str(observed.get("runner_pod") or "")
    if not runner_pod or runner_pod not in {str(item.get("id")) for item in placement}:
        raise RuntimeError("network evidence does not identify a valid surviving runner pod")

    current_pods = current_cluster_pods(
        kubectl=args.kubectl,
        namespace=args.namespace,
        cluster_name=args.cluster_name,
    )
    remote_root = args.remote_root.rstrip("/")
    _write_source_to_pod(
        kubectl=args.kubectl,
        namespace=args.namespace,
        pod=runner_pod,
        destination=f"{remote_root}/benchmarks/scale_readiness_benchmark.py",
        source=PROJECT_ROOT / "benchmarks" / "scale_readiness_benchmark.py",
    )
    _write_source_to_pod(
        kubectl=args.kubectl,
        namespace=args.namespace,
        pod=runner_pod,
        destination=f"{remote_root}/benchmarks/http_cluster_load_benchmark.py",
        source=PROJECT_ROOT / "benchmarks" / "http_cluster_load_benchmark.py",
    )

    workflow_run_id = str(network_payload.get("workflow_run_id") or "manual")
    deployment_id = (
        f"github-actions-{workflow_run_id}-{args.cluster_name}-{args.namespace}"
    )
    remote_output = f"{remote_root}/http_cluster_load_results.json"
    command = [
        args.kubectl,
        "exec",
        runner_pod,
        "-n",
        args.namespace,
        "--",
        "python",
        f"{remote_root}/benchmarks/http_cluster_load_benchmark.py",
        "--namespace-prefix",
        f"kind-external:{workflow_run_id}",
        "--deployment-id",
        deployment_id,
        "--environment",
        "kubernetes-kind-non-loopback-ci",
        "--source",
        "kubernetes-pod-dns-physical-node-drill",
        "--namespace-count",
        str(args.namespace_count),
        "--memories-per-namespace",
        str(args.memories_per_namespace),
        "--workers",
        str(args.workers),
        "--batch-query-size",
        str(args.batch_query_size),
        "--replication-factor",
        "3",
        "--write-quorum",
        "2",
        "--read-quorum",
        "1",
        "--read-fanout",
        "1",
        "--timeout",
        str(args.request_timeout),
        "--p99-slo-ms",
        str(args.p99_slo_ms),
        "--output",
        remote_output,
        "--fail-on-slo",
    ]
    for item in placement:
        command.extend(("--node", f"{item['id']}={item['address']}"))
        command.extend(("--zone", f"{item['id']}={item['zone']}"))
    _run(command, timeout=args.timeout_seconds)
    load_payload = json.loads(
        _run(
            [
                args.kubectl,
                "exec",
                runner_pod,
                "-n",
                args.namespace,
                "--",
                "cat",
                remote_output,
            ]
        )
    )
    return evaluate_kubernetes_external_http_cluster_evidence(
        load_payload,
        network_payload,
        current_pods=current_pods,
        network_artifact=args.network_artifact,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the sustained HTTP cluster workload from a Kubernetes pod and "
            "bind it to a physical worker-failure attestation."
        )
    )
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--namespace", default="wavemind-system")
    parser.add_argument("--cluster-name", default="wavemind-ci")
    parser.add_argument(
        "--network-evidence",
        type=Path,
        default=Path(DEFAULT_NETWORK_ARTIFACT),
    )
    parser.add_argument("--network-artifact", default=DEFAULT_NETWORK_ARTIFACT)
    parser.add_argument("--namespace-count", type=int, default=32)
    parser.add_argument("--memories-per-namespace", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-query-size", type=int, default=24)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--p99-slo-ms", type=float, default=1000.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--remote-root", default="/tmp/wavemind-external-evidence")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/http_cluster_load_results.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = run_kubernetes_external_http_cluster_evidence(args)
    except Exception as exc:
        payload = {
            "schema": "wavemind.external_http_cluster.v2",
            "generated_at": _utc_now(),
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    attestation = dict((payload.get("scenario") or {}).get("kubernetes_attestation") or {})
    return 0 if attestation.get("status") == "pass" else 5


if __name__ == "__main__":
    raise SystemExit(main())
