#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(*command: str, timeout: float = 120.0) -> str:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _json(kubectl: str, *args: str) -> dict[str, Any]:
    return json.loads(_run(kubectl, *args, "-o", "json"))


def _ready(resource: dict[str, Any]) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in (resource.get("status") or {}).get("conditions") or []
    )


def _wait_for(
    description: str,
    probe: Callable[[], T | None],
    *,
    timeout_seconds: float,
    interval_seconds: float = 1.0,
) -> T:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result is not None:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(interval_seconds)
    suffix = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {description}{suffix}")


def _source_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(os.getenv("GITHUB_SHA") or "").strip()
    workflow_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    repository = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    server_url = str(os.getenv("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    if source_ref:
        payload["source_ref"] = source_ref
    if workflow_run_id:
        payload["workflow_run_id"] = workflow_run_id
    if workflow_run_id and repository:
        payload["workflow_run_url"] = (
            f"{server_url}/{repository}/actions/runs/{workflow_run_id}"
        )
    return payload


def evaluate_kubernetes_cluster_network_smoke(observed: dict[str, Any]) -> dict[str, Any]:
    service_addresses = [str(value) for value in observed.get("service_addresses") or []]
    target_pods = set(str(value) for value in observed.get("target_data_pods") or [])
    outage = dict(observed.get("outage") or {})
    recovered = dict(observed.get("recovered") or {})
    seed = dict(observed.get("seed") or {})
    failed_during_outage = set(str(value) for value in outage.get("failed_nodes_seen") or [])
    checks = [
        {
            "id": "four_service_nodes",
            "passed": len(service_addresses) >= 4,
            "observed": len(service_addresses),
            "required": 4,
        },
        {
            "id": "non_loopback_pod_dns",
            "passed": bool(service_addresses)
            and all(".svc.cluster.local" in value for value in service_addresses)
            and all("127.0.0.1" not in value and "localhost" not in value for value in service_addresses),
            "observed": service_addresses,
            "required": "Kubernetes pod DNS only",
        },
        {
            "id": "three_failure_domains",
            "passed": int(observed.get("zone_count") or 0) >= 3,
            "observed": int(observed.get("zone_count") or 0),
            "required": 3,
        },
        {
            "id": "seed_quorum_writes",
            "passed": seed.get("status") == "pass"
            and int(seed.get("written_memories") or 0) == int(seed.get("expected_memories") or -1),
            "observed": {
                "status": seed.get("status"),
                "written": seed.get("written_memories"),
                "expected": seed.get("expected_memories"),
            },
            "required": "all deterministic memories written through quorum",
        },
        {
            "id": "physical_worker_pause",
            "passed": observed.get("failure_method") == "docker-pause-kind-worker"
            and bool(observed.get("target_worker"))
            and bool(target_pods),
            "observed": {
                "method": observed.get("failure_method"),
                "worker": observed.get("target_worker"),
                "pods": sorted(target_pods),
            },
            "required": "physical kind worker container paused",
        },
        {
            "id": "runner_survived_other_node",
            "passed": bool(observed.get("runner_worker"))
            and observed.get("runner_worker") != observed.get("target_worker"),
            "observed": {
                "runner": observed.get("runner_worker"),
                "target": observed.get("target_worker"),
            },
            "required": "workload runner on a surviving worker",
        },
        {
            "id": "zone_failure_isolated",
            "passed": bool(observed.get("runner_zone"))
            and bool(observed.get("target_zone"))
            and observed.get("runner_zone") != observed.get("target_zone"),
            "observed": {
                "runner": observed.get("runner_zone"),
                "target": observed.get("target_zone"),
            },
            "required": "runner and failed worker in distinct zones",
        },
        {
            "id": "network_failure_observed",
            "passed": bool(failed_during_outage) and bool(failed_during_outage & target_pods),
            "observed": sorted(failed_during_outage),
            "required": "at least one pod on paused worker reported unreachable",
        },
        {
            "id": "quorum_reads_during_outage",
            "passed": outage.get("status") == "pass" and float(outage.get("hit_rate") or 0.0) >= 1.0,
            "observed": {
                "status": outage.get("status"),
                "hit_rate": outage.get("hit_rate"),
            },
            "required": "100% deterministic recall while worker is paused",
        },
        {
            "id": "worker_unpaused",
            "passed": bool(observed.get("worker_unpaused")),
            "observed": observed.get("worker_unpaused"),
            "required": True,
        },
        {
            "id": "node_ready_after_recovery",
            "passed": bool(observed.get("node_ready_after_recovery")),
            "observed": observed.get("node_ready_after_recovery"),
            "required": True,
        },
        {
            "id": "pods_preserved_across_pause",
            "passed": bool(observed.get("pod_uids_preserved")),
            "observed": observed.get("pod_uids_preserved"),
            "required": True,
        },
        {
            "id": "full_recovery",
            "passed": recovered.get("status") == "pass"
            and float(recovered.get("hit_rate") or 0.0) >= 1.0
            and not recovered.get("failed_nodes_seen"),
            "observed": {
                "status": recovered.get("status"),
                "hit_rate": recovered.get("hit_rate"),
                "failed_nodes": recovered.get("failed_nodes_seen"),
            },
            "required": "100% recall with no unreachable nodes after recovery",
        },
    ]
    passed_checks = sum(bool(check["passed"]) for check in checks)
    payload = {
        "schema": "wavemind.kubernetes_cluster_network_smoke.v1",
        "generated_at": _utc_now(),
        "environment": "kind-multinode-network-ci",
        "evidence_source": "github-actions-kind-physical-node-pause",
        "claim_boundary": (
            "Ephemeral non-loopback Kubernetes service-network and physical kind-worker "
            "failure evidence; not remote multi-region production admission."
        ),
        "status": "pass" if passed_checks == len(checks) else "fail",
        "summary": {
            "check_count": len(checks),
            "passed_checks": passed_checks,
            "failed_checks": len(checks) - passed_checks,
        },
        "checks": checks,
        "observed": observed,
    }
    return _source_provenance(payload)


def _cluster_drill_command(
    *,
    kubectl: str,
    namespace: str,
    runner_pod: str,
    mode: str,
    nodes: list[dict[str, str]],
    namespace_prefix: str,
    namespace_count: int,
    memories_per_namespace: int,
    request_timeout: float,
) -> dict[str, Any]:
    command = [
        kubectl,
        "exec",
        runner_pod,
        "-n",
        namespace,
        "--",
        "wavemind",
        "cluster-drill",
        "--mode",
        mode,
        "--replication-factor",
        "3",
        "--write-quorum",
        "2",
        "--read-quorum",
        "1",
        "--read-fanout",
        "3",
        "--namespace-prefix",
        namespace_prefix,
        "--namespace-count",
        str(namespace_count),
        "--memories-per-namespace",
        str(memories_per_namespace),
        "--min-hit-rate",
        "1.0",
        "--timeout",
        str(request_timeout),
        "--json",
    ]
    for node in nodes:
        command.extend(("--node", f"{node['id']}={node['address']}"))
        command.extend(("--zone", f"{node['id']}={node['zone']}"))
    return json.loads(_run(*command, timeout=360.0))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    selector = (
        f"app.kubernetes.io/instance={args.cluster_name},"
        "app.kubernetes.io/component=api"
    )

    def _ready_data_pods() -> list[dict[str, Any]] | None:
        payload = _json(
            args.kubectl,
            "get",
            "pods",
            "-n",
            args.namespace,
            "-l",
            selector,
        )
        pods = [pod for pod in payload.get("items") or [] if _ready(pod)]
        return pods if len(pods) >= 4 else None

    pods = _wait_for(
        "four ready WaveMind data pods",
        _ready_data_pods,
        timeout_seconds=args.timeout_seconds,
    )
    kubernetes_nodes = {
        str((item.get("metadata") or {}).get("name") or ""): item
        for item in (_json(args.kubectl, "get", "nodes").get("items") or [])
    }
    pod_records: list[dict[str, str]] = []
    for pod in pods:
        pod_name = str((pod.get("metadata") or {}).get("name") or "")
        worker = str((pod.get("spec") or {}).get("nodeName") or "")
        labels = (kubernetes_nodes.get(worker, {}).get("metadata") or {}).get("labels") or {}
        zone = str(labels.get("topology.kubernetes.io/zone") or "")
        if not pod_name or not worker or not zone:
            raise RuntimeError(f"pod {pod_name or '<unknown>'} is missing worker or zone metadata")
        pod_records.append(
            {
                "id": pod_name,
                "worker": worker,
                "zone": zone,
                "address": (
                    f"http://{pod_name}.{args.cluster_name}-headless."
                    f"{args.namespace}.svc.cluster.local:8000"
                ),
                "uid": str((pod.get("metadata") or {}).get("uid") or ""),
            }
        )
    pod_records.sort(key=lambda item: item["id"])

    workers = sorted({record["worker"] for record in pod_records})
    if len(workers) < 3:
        raise RuntimeError("data plane is not spread across three workers")
    worker_pod_counts = {
        worker: sum(record["worker"] == worker for record in pod_records)
        for worker in workers
    }
    target_worker = min(workers, key=lambda worker: (worker_pod_counts[worker], worker))
    runner_record = next(record for record in pod_records if record["worker"] != target_worker)
    target_records = [record for record in pod_records if record["worker"] == target_worker]
    runner_pod = runner_record["id"]

    drill_nodes = [
        {"id": item["id"], "address": item["address"], "zone": item["zone"]}
        for item in pod_records
    ]
    seed = _cluster_drill_command(
        kubectl=args.kubectl,
        namespace=args.namespace,
        runner_pod=runner_pod,
        mode="seed",
        nodes=drill_nodes,
        namespace_prefix=args.namespace_prefix,
        namespace_count=args.namespace_count,
        memories_per_namespace=args.memories_per_namespace,
        request_timeout=max(30.0, args.request_timeout),
    )
    if seed.get("status") != "pass":
        raise RuntimeError(f"cluster seed failed: {seed}")

    outage: dict[str, Any] = {}
    worker_unpaused = False
    pause_started = time.perf_counter()
    _run("docker", "pause", target_worker, timeout=30.0)
    try:
        time.sleep(args.failure_settle_seconds)
        outage = _cluster_drill_command(
            kubectl=args.kubectl,
            namespace=args.namespace,
            runner_pod=runner_pod,
            mode="verify",
            nodes=drill_nodes,
            namespace_prefix=args.namespace_prefix,
            namespace_count=args.namespace_count,
            memories_per_namespace=args.memories_per_namespace,
            request_timeout=args.request_timeout,
        )
    finally:
        _run("docker", "unpause", target_worker, timeout=30.0)
        worker_unpaused = True
    outage_duration_ms = round((time.perf_counter() - pause_started) * 1000.0, 3)

    def _node_ready() -> bool | None:
        node = _json(args.kubectl, "get", "node", target_worker)
        return True if _ready(node) else None

    node_ready_after_recovery = _wait_for(
        "paused worker to become Ready",
        _node_ready,
        timeout_seconds=args.timeout_seconds,
    )

    def _recovered_payload() -> dict[str, Any] | None:
        payload = _cluster_drill_command(
            kubectl=args.kubectl,
            namespace=args.namespace,
            runner_pod=runner_pod,
            mode="verify",
            nodes=drill_nodes,
            namespace_prefix=args.namespace_prefix,
            namespace_count=args.namespace_count,
            memories_per_namespace=args.memories_per_namespace,
            request_timeout=args.request_timeout,
        )
        return (
            payload
            if payload.get("status") == "pass" and not payload.get("failed_nodes_seen")
            else None
        )

    recovered = _wait_for(
        "all cluster service nodes to recover",
        _recovered_payload,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=2.0,
    )
    after_pods = {
        str((item.get("metadata") or {}).get("name") or ""): str(
            (item.get("metadata") or {}).get("uid") or ""
        )
        for item in (
            _json(
                args.kubectl,
                "get",
                "pods",
                "-n",
                args.namespace,
                "-l",
                selector,
            ).get("items")
            or []
        )
    }
    pod_uids_preserved = all(
        after_pods.get(record["id"]) == record["uid"] for record in target_records
    )

    return evaluate_kubernetes_cluster_network_smoke(
        {
            "service_addresses": [item["address"] for item in pod_records],
            "zone_count": len({item["zone"] for item in pod_records}),
            "pod_placement": pod_records,
            "runner_pod": runner_pod,
            "runner_worker": runner_record["worker"],
            "runner_zone": runner_record["zone"],
            "target_worker": target_worker,
            "target_zone": target_records[0]["zone"],
            "target_data_pods": [item["id"] for item in target_records],
            "failure_method": "docker-pause-kind-worker",
            "failure_settle_seconds": args.failure_settle_seconds,
            "outage_duration_ms": outage_duration_ms,
            "worker_unpaused": worker_unpaused,
            "node_ready_after_recovery": node_ready_after_recovery,
            "pod_uids_preserved": pod_uids_preserved,
            "seed": seed,
            "outage": outage,
            "recovered": recovered,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a non-loopback Kubernetes quorum workload through a physical kind worker outage"
    )
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--namespace", default="wavemind-system")
    parser.add_argument("--cluster-name", default="wavemind-ci")
    parser.add_argument("--namespace-prefix", default="kind-network-drill")
    parser.add_argument("--namespace-count", type=int, default=32)
    parser.add_argument("--memories-per-namespace", type=int, default=8)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    parser.add_argument("--failure-settle-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/kubernetes_cluster_network_smoke_results.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = _source_provenance(
            {
                "schema": "wavemind.kubernetes_cluster_network_smoke.v1",
                "generated_at": _utc_now(),
                "environment": "kind-multinode-network-ci",
                "evidence_source": "github-actions-kind-physical-node-pause",
                "claim_boundary": (
                    "Ephemeral non-loopback Kubernetes service-network and physical "
                    "kind-worker failure evidence; not remote multi-region production admission."
                ),
                "status": "fail",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(main())
