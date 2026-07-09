#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")
REGION_ZONES = {
    "region-a": "zone-a",
    "region-b": "zone-b",
    "region-c": "zone-c",
}


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


def build_region_resources(*, namespace: str, image: str) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for region_id, zone in REGION_ZONES.items():
        labels = {
            "app.kubernetes.io/name": "wavemind",
            "app.kubernetes.io/component": "active-active-region",
            "app.kubernetes.io/instance": region_id,
        }
        resources.append(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": region_id, "namespace": namespace, "labels": labels},
                "spec": {
                    "clusterIP": "None",
                    "ports": [{"name": "http", "port": 8000, "targetPort": "http"}],
                    "selector": labels,
                },
            }
        )
        replica_nodes = [f"{region_id}-replica-{index}" for index in range(3)]
        args = [
            "--score-threshold",
            "0.05",
            "--width",
            "16",
            "--height",
            "16",
            "--layers",
            "1",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--replicated-root",
            "/data/replicas",
            "--replication-factor",
            "3",
            "--read-quorum",
            "1",
        ]
        for node_id in replica_nodes:
            args.extend(("--replica-node", node_id))
        resources.append(
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {"name": region_id, "namespace": namespace, "labels": labels},
                "spec": {
                    "serviceName": region_id,
                    "replicas": 1,
                    "selector": {"matchLabels": labels},
                    "template": {
                        "metadata": {"labels": labels},
                        "spec": {
                            "nodeSelector": {"topology.kubernetes.io/zone": zone},
                            "terminationGracePeriodSeconds": 30,
                            "containers": [
                                {
                                    "name": "wavemind",
                                    "image": image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": ["wavemind"],
                                    "args": args,
                                    "env": [
                                        {
                                            "name": "WAVEMIND_API_SERIALIZE_OPERATIONS",
                                            "value": "1",
                                        }
                                    ],
                                    "ports": [
                                        {"name": "http", "containerPort": 8000}
                                    ],
                                    "readinessProbe": {
                                        "tcpSocket": {"port": "http"},
                                        "initialDelaySeconds": 3,
                                        "periodSeconds": 3,
                                    },
                                    "livenessProbe": {
                                        "tcpSocket": {"port": "http"},
                                        "initialDelaySeconds": 10,
                                        "periodSeconds": 10,
                                    },
                                    "volumeMounts": [
                                        {"name": "state", "mountPath": "/data"}
                                    ],
                                }
                            ],
                        },
                    },
                    "updateStrategy": {"type": "RollingUpdate"},
                    "volumeClaimTemplates": [
                        {
                            "metadata": {"name": "state"},
                            "spec": {
                                "accessModes": ["ReadWriteOnce"],
                                "resources": {"requests": {"storage": "1Gi"}},
                            },
                        }
                    ],
                },
            }
        )
    return resources


def evaluate_kubernetes_active_active_region_smoke(
    observed: dict[str, Any],
) -> dict[str, Any]:
    addresses = [str(value) for value in observed.get("region_addresses") or []]
    seed = dict(observed.get("seed") or {})
    outage = dict(observed.get("outage") or {})
    recovered = dict(observed.get("recovered") or {})
    seed_verification = dict(seed.get("verification") or {})
    outage_verification = dict(outage.get("verification") or {})
    recovery_verification = dict(recovered.get("verification") or {})
    recovery_sync = dict(recovered.get("sync") or {})
    checks = [
        {
            "id": "three_regions",
            "passed": len(addresses) == 3,
            "observed": len(addresses),
            "required": 3,
        },
        {
            "id": "non_loopback_region_services",
            "passed": len(addresses) == 3
            and all(".svc.cluster.local" in value for value in addresses)
            and all("127.0.0.1" not in value and "localhost" not in value for value in addresses),
            "observed": addresses,
            "required": "three Kubernetes service DNS endpoints",
        },
        {
            "id": "three_zone_placement",
            "passed": int(observed.get("zone_count") or 0) == 3,
            "observed": observed.get("zone_count"),
            "required": 3,
        },
        {
            "id": "persistent_region_volumes",
            "passed": bool(observed.get("all_regions_use_pvc")),
            "observed": observed.get("all_regions_use_pvc"),
            "required": True,
        },
        {
            "id": "initial_convergence",
            "passed": seed.get("status") == "pass"
            and float(seed_verification.get("convergence_rate") or 0.0) >= 1.0,
            "observed": seed_verification.get("convergence_rate"),
            "required": 1.0,
        },
        {
            "id": "physical_region_worker_pause",
            "passed": observed.get("failure_method") == "docker-pause-kind-worker"
            and bool(observed.get("target_worker")),
            "observed": {
                "method": observed.get("failure_method"),
                "worker": observed.get("target_worker"),
            },
            "required": "physical worker pause",
        },
        {
            "id": "runner_survives_other_zone",
            "passed": observed.get("runner_worker") != observed.get("target_worker")
            and observed.get("runner_zone") != observed.get("target_zone"),
            "observed": {
                "runner_worker": observed.get("runner_worker"),
                "target_worker": observed.get("target_worker"),
                "runner_zone": observed.get("runner_zone"),
                "target_zone": observed.get("target_zone"),
            },
            "required": "runner survives in another zone",
        },
        {
            "id": "failed_region_detected",
            "passed": outage.get("unavailable_regions") == [observed.get("target_region")],
            "observed": outage.get("unavailable_regions"),
            "required": [observed.get("target_region")],
        },
        {
            "id": "writes_continue_during_outage",
            "passed": outage.get("status") == "pass" and int(outage.get("writes") or 0) > 0,
            "observed": outage.get("writes"),
            "required": "> 0",
        },
        {
            "id": "survivor_convergence",
            "passed": float(outage_verification.get("convergence_rate") or 0.0) >= 1.0,
            "observed": outage_verification.get("convergence_rate"),
            "required": 1.0,
        },
        {
            "id": "survivor_delete_suppression",
            "passed": float(outage_verification.get("delete_suppression_rate") or 0.0) >= 1.0,
            "observed": outage_verification.get("delete_suppression_rate"),
            "required": 1.0,
        },
        {
            "id": "worker_unpaused",
            "passed": bool(observed.get("worker_unpaused")),
            "observed": observed.get("worker_unpaused"),
            "required": True,
        },
        {
            "id": "region_api_recovers",
            "passed": bool(observed.get("target_region_ready_after_recovery")),
            "observed": observed.get("target_region_ready_after_recovery"),
            "required": True,
        },
        {
            "id": "region_pod_preserved",
            "passed": bool(observed.get("target_region_pod_uid_preserved")),
            "observed": observed.get("target_region_pod_uid_preserved"),
            "required": True,
        },
        {
            "id": "full_region_convergence",
            "passed": recovered.get("status") == "pass"
            and float(recovery_verification.get("convergence_rate") or 0.0) >= 1.0,
            "observed": recovery_verification.get("convergence_rate"),
            "required": 1.0,
        },
        {
            "id": "recovered_delete_suppression",
            "passed": float(recovery_verification.get("delete_suppression_rate") or 0.0) >= 1.0,
            "observed": recovery_verification.get("delete_suppression_rate"),
            "required": 1.0,
        },
        {
            "id": "final_sync_idempotent",
            "passed": int(recovery_sync.get("final_noop_records_imported") or 0) == 0
            and int(recovery_sync.get("final_noop_tombstones_imported") or 0) == 0
            and int(recovery_sync.get("final_noop_failed_pairs") or 0) == 0,
            "observed": {
                "records": recovery_sync.get("final_noop_records_imported"),
                "tombstones": recovery_sync.get("final_noop_tombstones_imported"),
                "failed_pairs": recovery_sync.get("final_noop_failed_pairs"),
            },
            "required": {"records": 0, "tombstones": 0, "failed_pairs": 0},
        },
    ]
    passed = sum(bool(check["passed"]) for check in checks)
    return _source_provenance(
        {
            "schema": "wavemind.kubernetes_active_active_region_smoke.v1",
            "generated_at": _utc_now(),
            "environment": "kind-multizone-active-active-ci",
            "evidence_source": "github-actions-kind-physical-region-worker-pause",
            "claim_boundary": (
                "Ephemeral non-loopback Kubernetes three-zone active-active region "
                "failure evidence; not remote multi-region production admission."
            ),
            "status": "pass" if passed == len(checks) else "fail",
            "summary": {
                "check_count": len(checks),
                "passed_checks": passed,
                "failed_checks": len(checks) - passed,
            },
            "checks": checks,
            "observed": observed,
        }
    )


def _drill_command(
    *,
    kubectl: str,
    namespace: str,
    runner_pod: str,
    mode: str,
    regions: dict[str, str],
    failed_region: str | None,
    namespace_prefix: str,
    namespace_count: int,
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
        "active-active-drill",
        "--mode",
        mode,
        "--namespace-prefix",
        namespace_prefix,
        "--namespace-count",
        str(namespace_count),
        "--timeout",
        str(request_timeout),
        "--min-convergence-rate",
        "1.0",
        "--json",
    ]
    if failed_region:
        command.extend(("--failed-region", failed_region))
    for region_id, address in sorted(regions.items()):
        command.extend(("--region", f"{region_id}={address}"))
    return json.loads(_run(*command, timeout=360.0))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        _run(args.kubectl, "create", "namespace", args.namespace)
    except RuntimeError as exc:
        if "AlreadyExists" not in str(exc):
            raise
    resources = {
        "apiVersion": "v1",
        "kind": "List",
        "items": build_region_resources(namespace=args.namespace, image=args.image),
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(resources, handle)
        manifest_path = Path(handle.name)
    try:
        _run(args.kubectl, "apply", "-f", str(manifest_path))
    finally:
        manifest_path.unlink(missing_ok=True)

    selector = "app.kubernetes.io/component=active-active-region"

    def _ready_region_pods() -> list[dict[str, Any]] | None:
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
        return pods if len(pods) == 3 else None

    pods = _wait_for(
        "three ready active-active region pods",
        _ready_region_pods,
        timeout_seconds=args.timeout_seconds,
    )
    nodes = {
        str((item.get("metadata") or {}).get("name") or ""): item
        for item in (_json(args.kubectl, "get", "nodes").get("items") or [])
    }
    placement: dict[str, dict[str, str]] = {}
    for pod in pods:
        pod_name = str((pod.get("metadata") or {}).get("name") or "")
        region_id = pod_name.rsplit("-", 1)[0]
        worker = str((pod.get("spec") or {}).get("nodeName") or "")
        zone = str(
            (((nodes.get(worker) or {}).get("metadata") or {}).get("labels") or {}).get(
                "topology.kubernetes.io/zone"
            )
            or ""
        )
        volumes = (pod.get("spec") or {}).get("volumes") or []
        uses_pvc = any(volume.get("persistentVolumeClaim") for volume in volumes)
        placement[region_id] = {
            "pod": pod_name,
            "uid": str((pod.get("metadata") or {}).get("uid") or ""),
            "worker": worker,
            "zone": zone,
            "uses_pvc": str(bool(uses_pvc)).lower(),
        }
    if set(placement) != set(REGION_ZONES):
        raise RuntimeError(f"unexpected region placement: {placement}")
    if any(placement[region]["zone"] != zone for region, zone in REGION_ZONES.items()):
        raise RuntimeError(f"regions were not placed in requested zones: {placement}")

    regions = {
        region_id: (
            f"http://{region_id}.{args.namespace}.svc.cluster.local:8000"
        )
        for region_id in REGION_ZONES
    }
    runner_region = "region-a"
    target_region = "region-b"
    runner = placement[runner_region]
    target = placement[target_region]
    if runner["worker"] == target["worker"]:
        raise RuntimeError("runner and target region share a worker")

    seed = _drill_command(
        kubectl=args.kubectl,
        namespace=args.namespace,
        runner_pod=runner["pod"],
        mode="seed",
        regions=regions,
        failed_region=None,
        namespace_prefix=args.namespace_prefix,
        namespace_count=args.namespace_count,
        request_timeout=args.request_timeout,
    )
    if seed.get("status") != "pass":
        raise RuntimeError(f"active-active seed failed: {seed}")

    worker_unpaused = False
    pause_started = time.perf_counter()
    _run("docker", "pause", target["worker"], timeout=30.0)
    try:
        time.sleep(args.failure_settle_seconds)
        outage = _drill_command(
            kubectl=args.kubectl,
            namespace=args.namespace,
            runner_pod=runner["pod"],
            mode="outage",
            regions=regions,
            failed_region=target_region,
            namespace_prefix=args.namespace_prefix,
            namespace_count=args.namespace_count,
            request_timeout=args.request_timeout,
        )
    finally:
        _run("docker", "unpause", target["worker"], timeout=30.0)
        worker_unpaused = True
    outage_duration_ms = round((time.perf_counter() - pause_started) * 1000.0, 3)

    def _recover() -> dict[str, Any] | None:
        payload = _drill_command(
            kubectl=args.kubectl,
            namespace=args.namespace,
            runner_pod=runner["pod"],
            mode="recover",
            regions=regions,
            failed_region=target_region,
            namespace_prefix=args.namespace_prefix,
            namespace_count=args.namespace_count,
            request_timeout=args.request_timeout,
        )
        return payload if payload.get("status") == "pass" else None

    recovered = _wait_for(
        "failed active-active region to recover and converge",
        _recover,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=2.0,
    )
    target_node = _json(args.kubectl, "get", "node", target["worker"])
    target_region_ready = _ready(target_node)
    after_target_pod = _json(
        args.kubectl,
        "get",
        "pod",
        target["pod"],
        "-n",
        args.namespace,
    )
    target_uid_preserved = (
        str((after_target_pod.get("metadata") or {}).get("uid") or "") == target["uid"]
    )

    return evaluate_kubernetes_active_active_region_smoke(
        {
            "region_addresses": list(regions.values()),
            "region_placement": placement,
            "zone_count": len({value["zone"] for value in placement.values()}),
            "all_regions_use_pvc": all(
                value["uses_pvc"] == "true" for value in placement.values()
            ),
            "runner_region": runner_region,
            "runner_worker": runner["worker"],
            "runner_zone": runner["zone"],
            "target_region": target_region,
            "target_worker": target["worker"],
            "target_zone": target["zone"],
            "failure_method": "docker-pause-kind-worker",
            "failure_settle_seconds": args.failure_settle_seconds,
            "outage_duration_ms": outage_duration_ms,
            "worker_unpaused": worker_unpaused,
            "target_region_ready_after_recovery": target_region_ready,
            "target_region_pod_uid_preserved": target_uid_preserved,
            "seed": seed,
            "outage": outage,
            "recovered": recovered,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a three-zone Kubernetes active-active region outage and recovery drill"
    )
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--namespace", default="wavemind-regions")
    parser.add_argument("--image", default="wavemind:ci-upgrade")
    parser.add_argument("--namespace-prefix", default="kind-region-drill")
    parser.add_argument("--namespace-count", type=int, default=16)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    parser.add_argument("--failure-settle-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/kubernetes_active_active_region_smoke_results.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = _source_provenance(
            {
                "schema": "wavemind.kubernetes_active_active_region_smoke.v1",
                "generated_at": _utc_now(),
                "environment": "kind-multizone-active-active-ci",
                "evidence_source": "github-actions-kind-physical-region-worker-pause",
                "claim_boundary": (
                    "Ephemeral non-loopback Kubernetes three-zone active-active "
                    "region failure evidence; not remote multi-region production admission."
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
