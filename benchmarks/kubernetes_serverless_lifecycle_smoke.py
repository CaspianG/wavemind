#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from wavemind.serverless import SecretEnvRef, WaveMindServerlessSpec


T = TypeVar("T")
API_KEY = "wavemind-kind-serverless-ci"
WORKLOAD_SCRIPT = r'''
import concurrent.futures
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

cfg = json.loads(sys.argv[1])
headers = {
    "Authorization": "Bearer " + cfg["api_key"],
    "Content-Type": "application/json",
}

def request(base, path, payload=None, method="POST", timeout=10.0):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    elapsed = (time.perf_counter() - started) * 1000.0
    return (json.loads(raw.decode("utf-8")) if raw else {}), elapsed

def query(base, text, top_k=1, min_score=None, tags=None):
    payload = {"text": text, "namespace": cfg["namespace"], "top_k": top_k}
    if min_score is not None:
        payload["min_score"] = min_score
    if tags is not None:
        payload["tags"] = tags
    payload, elapsed = request(
        base,
        "/query",
        payload,
    )
    return payload.get("results") or [], elapsed

mode = cfg["mode"]
if mode == "probe":
    payload, elapsed = request(cfg["bases"][0], "/stats", None, method="GET", timeout=3.0)
    print(json.dumps({"ready": True, "elapsed_ms": elapsed, "stats": payload}))
elif mode == "seed":
    ids = []
    latencies = []
    for index in range(cfg["count"]):
        token = "sls-%04d" % index
        payload, elapsed = request(
            cfg["bases"][0],
            "/remember",
            {
                "text": "serverless durable memory %04d token %s" % (index, token),
                "namespace": cfg["namespace"],
                "tags": ["serverless", "durable"],
                "metadata": {"ordinal": index, "token": token},
            },
        )
        ids.append(int(payload["id"]))
        latencies.append(elapsed)
    print(json.dumps({"ids": ids, "latencies_ms": latencies}))
elif mode == "verify":
    successes = 0
    latencies = []
    for index in range(cfg["count"]):
        token = "sls-%04d" % index
        results, elapsed = query(cfg["bases"][index % len(cfg["bases"])], token)
        latencies.append(elapsed)
        if results and token in results[0].get("text", ""):
            successes += 1
    print(json.dumps({"successes": successes, "count": cfg["count"], "latencies_ms": latencies}))
elif mode == "cross-replica":
    marker = "cross-replica-%d" % int(time.time() * 1000)
    created, write_ms = request(
        cfg["service_base"],
        "/remember",
        {
            "text": "serverless shared mutation " + marker,
            "namespace": cfg["namespace"],
            "tags": ["serverless", "coherence"],
        },
    )
    visible = 0
    read_ms = []
    write_counts = []
    for index, base in enumerate(cfg["bases"]):
        results, elapsed = query(
            base,
            marker,
            top_k=10,
            min_score=(index + 1) * 0.000001,
            tags=["coherence"],
        )
        read_ms.append(elapsed)
        stats, _ = request(
            base,
            "/stats?namespace=" + urllib.parse.quote(cfg["namespace"]),
            None,
            method="GET",
        )
        write_counts.append(int(stats.get("active_memories", -1)))
        if any(marker in result.get("text", "") for result in results):
            visible += 1
    deleted, delete_ms = request(
        cfg["service_base"],
        "/forget",
        {"id": int(created["id"]), "namespace": cfg["namespace"]},
        method="DELETE",
    )
    suppressed = 0
    delete_counts = []
    for index, base in enumerate(cfg["bases"]):
        results, _ = query(
            base,
            marker,
            top_k=10,
            min_score=0.0001 + ((index + 1) * 0.000001),
            tags=["coherence"],
        )
        stats, _ = request(
            base,
            "/stats?namespace=" + urllib.parse.quote(cfg["namespace"]),
            None,
            method="GET",
        )
        delete_counts.append(int(stats.get("active_memories", -1)))
        if not any(marker in result.get("text", "") for result in results):
            suppressed += 1
    print(json.dumps({
        "memory_id": int(created["id"]),
        "replicas": len(cfg["bases"]),
        "visible_replicas": visible,
        "suppressed_replicas": suppressed,
        "write_active_counts": write_counts,
        "delete_active_counts": delete_counts,
        "seed_count": cfg["count"],
        "deleted": int(deleted.get("deleted", 0)),
        "write_ms": write_ms,
        "read_ms": read_ms,
        "delete_ms": delete_ms,
    }))
elif mode == "burst":
    requests = cfg["requests"]
    workers = cfg["workers"]
    started = time.perf_counter()
    def one(index):
        token = "sls-%04d" % (index % cfg["count"])
        try:
            results, elapsed = query(cfg["bases"][index % len(cfg["bases"])], token)
            return bool(results and token in results[0].get("text", "")), elapsed, None
        except Exception as exc:
            return False, 0.0, type(exc).__name__ + ": " + str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, range(requests)))
    wall = time.perf_counter() - started
    latencies = [row[1] for row in rows if row[2] is None]
    errors = [row[2] for row in rows if row[2] is not None]
    latencies_sorted = sorted(latencies)
    def percentile(value):
        if not latencies_sorted:
            return float("inf")
        pos = max(0, min(len(latencies_sorted) - 1, math.ceil(value * len(latencies_sorted)) - 1))
        return latencies_sorted[pos]
    print(json.dumps({
        "requests": requests,
        "successes": sum(1 for ok, _, error in rows if ok and error is None),
        "errors": len(errors),
        "error_sample": errors[:5],
        "wall_seconds": wall,
        "requests_per_second": requests / wall if wall > 0 else 0.0,
        "avg_ms": statistics.fmean(latencies) if latencies else float("inf"),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
    }))
else:
    raise SystemExit("unknown mode: " + mode)
'''


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(*command: str, timeout: float = 120.0, input_text: str | None = None) -> str:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        input=input_text,
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
        payload["workflow_run_url"] = f"{server_url}/{repository}/actions/runs/{workflow_run_id}"
    return payload


def _labels(component: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": "wavemind",
        "app.kubernetes.io/component": component,
        "app.kubernetes.io/part-of": "wavemind-serverless-smoke",
    }


def _service(name: str, namespace: str, component: str, port: int) -> dict[str, Any]:
    labels = _labels(component)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "selector": labels,
            "ports": [{"name": "tcp", "port": port, "targetPort": port}],
        },
    }


def _stateful_service(
    *,
    name: str,
    namespace: str,
    component: str,
    image: str,
    port: int,
    env: list[dict[str, Any]] | None = None,
    args: list[str] | None = None,
    mount_path: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    labels = _labels(component)
    container: dict[str, Any] = {
        "name": name,
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "ports": [{"name": "tcp", "containerPort": port}],
        "env": env or [],
        "volumeMounts": [{"name": "data", "mountPath": mount_path}],
        "readinessProbe": {**readiness, "initialDelaySeconds": 2, "periodSeconds": 2},
        "resources": {
            "requests": {"cpu": "50m", "memory": "96Mi"},
            "limits": {"cpu": "1", "memory": "768Mi"},
        },
    }
    if args:
        container["args"] = args
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "serviceName": name,
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {"metadata": {"labels": labels}, "spec": {"containers": [container]}},
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": "1Gi"}},
                    },
                }
            ],
        },
    }


def build_serverless_resources(
    *,
    namespace: str,
    image: str,
    postgres_image: str,
    qdrant_image: str,
    redis_image: str,
) -> list[dict[str, Any]]:
    postgres_dsn = f"postgresql://wavemind:wavemind@postgres.{namespace}.svc.cluster.local:5432/wavemind"
    qdrant_url = f"http://qdrant.{namespace}.svc.cluster.local:6333"
    redis_url = f"redis://redis.{namespace}.svc.cluster.local:6379/0"
    resources: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "wavemind-postgres", "namespace": namespace},
            "stringData": {"dsn": postgres_dsn},
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "wavemind-qdrant", "namespace": namespace},
            "stringData": {"url": qdrant_url},
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "wavemind-redis", "namespace": namespace},
            "stringData": {"url": redis_url},
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "wavemind-auth", "namespace": namespace},
            "stringData": {"api-keys": API_KEY},
        },
        _service("postgres", namespace, "serverless-postgres", 5432),
        _stateful_service(
            name="postgres",
            namespace=namespace,
            component="serverless-postgres",
            image=postgres_image,
            port=5432,
            env=[
                {"name": "POSTGRES_USER", "value": "wavemind"},
                {"name": "POSTGRES_PASSWORD", "value": "wavemind"},
                {"name": "POSTGRES_DB", "value": "wavemind"},
                {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
            ],
            mount_path="/var/lib/postgresql/data",
            readiness={"exec": {"command": ["pg_isready", "-U", "wavemind", "-d", "wavemind"]}},
        ),
        _service("qdrant", namespace, "serverless-qdrant", 6333),
        _stateful_service(
            name="qdrant",
            namespace=namespace,
            component="serverless-qdrant",
            image=qdrant_image,
            port=6333,
            mount_path="/qdrant/storage",
            readiness={"tcpSocket": {"port": 6333}},
        ),
        _service("redis", namespace, "serverless-redis", 6379),
        _stateful_service(
            name="redis",
            namespace=namespace,
            component="serverless-redis",
            image=redis_image,
            port=6379,
            args=["redis-server", "--appendonly", "yes"],
            mount_path="/data",
            readiness={"exec": {"command": ["redis-cli", "ping"]}},
        ),
    ]
    spec = WaveMindServerlessSpec(
        name="wavemind-serverless",
        namespace=namespace,
        image=image,
        min_scale=0,
        max_scale=3,
        target_concurrency=16,
        postgres_dsn=SecretEnvRef("wavemind-postgres", "dsn"),
        qdrant_url=SecretEnvRef("wavemind-qdrant", "url"),
        redis_url=SecretEnvRef("wavemind-redis", "url"),
        api_keys=SecretEnvRef("wavemind-auth", "api-keys"),
        resources={
            "requests": {"cpu": "100m", "memory": "192Mi"},
            "limits": {"cpu": "2", "memory": "1Gi"},
        },
    )
    deployment = spec.keda_deployment()
    deployment["spec"]["replicas"] = 0
    pod_spec = deployment["spec"]["template"]["spec"]
    pod_spec["topologySpreadConstraints"] = [
        {
            "maxSkew": 1,
            "topologyKey": "topology.kubernetes.io/zone",
            "whenUnsatisfiable": "DoNotSchedule",
            "labelSelector": {"matchLabels": deployment["spec"]["selector"]["matchLabels"]},
        }
    ]
    container = pod_spec["containers"][0]
    container["imagePullPolicy"] = "IfNotPresent"
    container["readinessProbe"].update({"initialDelaySeconds": 1, "periodSeconds": 2})
    container["env"].extend(
        [
            {"name": "WAVEMIND_QDRANT_COLLECTION", "value": "kind_serverless_lifecycle"},
            {"name": "WAVEMIND_API_SERIALIZE_OPERATIONS", "value": "1"},
            {"name": "WAVEMIND_CACHE_TTL_SECONDS", "value": "30"},
        ]
    )
    resources.extend([deployment, spec.keda_service()])
    resources.append(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "serverless-runner", "namespace": namespace, "labels": _labels("serverless-runner")},
            "spec": {
                "restartPolicy": "Never",
                "containers": [
                    {
                        "name": "runner",
                        "image": image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["sleep", "1800"],
                        "resources": {
                            "requests": {"cpu": "50m", "memory": "64Mi"},
                            "limits": {"cpu": "1", "memory": "512Mi"},
                        },
                    }
                ],
            },
        }
    )
    return resources


def _workload(
    *,
    kubectl: str,
    namespace: str,
    config: dict[str, Any],
    timeout: float = 180.0,
) -> dict[str, Any]:
    output = _run(
        kubectl,
        "exec",
        "-i",
        "serverless-runner",
        "-n",
        namespace,
        "--",
        "python",
        "-",
        json.dumps(config, separators=(",", ":")),
        timeout=timeout,
        input_text=WORKLOAD_SCRIPT,
    )
    return json.loads(output.splitlines()[-1])


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return float("inf")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return float(ordered[index])


def evaluate_kubernetes_serverless_lifecycle_smoke(observed: dict[str, Any]) -> dict[str, Any]:
    burst = observed.get("burst") or {}
    cross = observed.get("cross_replica") or {}
    seed_count = int(cross.get("seed_count") or 0)
    write_counts = [int(value) for value in cross.get("write_active_counts") or []]
    delete_counts = [int(value) for value in cross.get("delete_active_counts") or []]
    checks = [
        {
            "id": "non_loopback_service_dns",
            "passed": str(observed.get("service_address") or "").endswith(".svc.cluster.local:8000"),
            "observed": observed.get("service_address"),
            "required": "ClusterIP .svc.cluster.local endpoint",
        },
        {
            "id": "external_durable_state",
            "passed": observed.get("external_services") == ["postgres", "qdrant", "redis"]
            and int(observed.get("persistent_volume_claims") or 0) >= 3,
            "observed": {
                "services": observed.get("external_services"),
                "pvcs": observed.get("persistent_volume_claims"),
            },
            "required": {"services": ["postgres", "qdrant", "redis"], "pvcs": ">=3"},
        },
        {
            "id": "scale_to_zero",
            "passed": observed.get("zero_replicas") is True and observed.get("zero_endpoints") is True,
            "observed": {"replicas": observed.get("zero_replicas"), "endpoints": observed.get("zero_endpoints")},
            "required": True,
        },
        {
            "id": "cold_start_ready",
            "passed": float(observed.get("cold_start_ms") or float("inf")) <= float(observed.get("cold_start_budget_ms") or 120000),
            "observed": observed.get("cold_start_ms"),
            "required": f"<= {observed.get('cold_start_budget_ms', 120000)} ms",
        },
        {
            "id": "state_restored_after_zero",
            "passed": float((observed.get("restored_after_zero") or {}).get("rate") or 0.0) >= 1.0,
            "observed": (observed.get("restored_after_zero") or {}).get("rate"),
            "required": 1.0,
        },
        {
            "id": "scale_out_three_replicas",
            "passed": int(observed.get("ready_replicas") or 0) == 3
            and int(observed.get("endpoint_count") or 0) == 3,
            "observed": {"replicas": observed.get("ready_replicas"), "endpoints": observed.get("endpoint_count")},
            "required": 3,
        },
        {
            "id": "multi_zone_placement",
            "passed": int(observed.get("zone_count") or 0) >= 3,
            "observed": observed.get("zone_count"),
            "required": 3,
        },
        {
            "id": "cross_replica_write_visibility",
            "passed": int(cross.get("visible_replicas") or 0)
            == int(cross.get("replicas") or -1)
            == 3
            and write_counts == [seed_count + 1] * 3,
            "observed": {
                "visible": cross.get("visible_replicas"),
                "replicas": cross.get("replicas"),
                "active_counts": cross.get("write_active_counts"),
            },
            "required": {"visible": 3, "active_counts": "seed_count + 1"},
        },
        {
            "id": "cross_replica_delete_suppression",
            "passed": int(cross.get("suppressed_replicas") or 0) == int(cross.get("replicas") or -1) == 3
            and int(cross.get("deleted") or 0) == 1
            and delete_counts == [seed_count] * 3,
            "observed": {
                "suppressed": cross.get("suppressed_replicas"),
                "deleted": cross.get("deleted"),
                "active_counts": cross.get("delete_active_counts"),
            },
            "required": {"suppressed": 3, "deleted": 1, "active_counts": "seed_count"},
        },
        {
            "id": "burst_success",
            "passed": int(burst.get("successes") or 0) == int(burst.get("requests") or -1)
            and int(burst.get("errors") or 0) == 0,
            "observed": {"successes": burst.get("successes"), "requests": burst.get("requests"), "errors": burst.get("errors")},
            "required": "100% successful",
        },
        {
            "id": "burst_p99_budget",
            "passed": float(burst.get("p99_ms") or float("inf")) <= float(observed.get("burst_p99_budget_ms") or 2000),
            "observed": burst.get("p99_ms"),
            "required": f"<= {observed.get('burst_p99_budget_ms', 2000)} ms",
        },
        {
            "id": "second_zero_restore",
            "passed": float((observed.get("final_restore") or {}).get("rate") or 0.0) >= 1.0,
            "observed": (observed.get("final_restore") or {}).get("rate"),
            "required": 1.0,
        },
    ]
    passed = sum(bool(check["passed"]) for check in checks)
    return _source_provenance(
        {
            "schema": "wavemind.kubernetes_serverless_lifecycle_smoke.v1",
            "generated_at": _utc_now(),
            "environment": "kind-multizone-serverless-lifecycle-ci",
            "evidence_source": "github-actions-kind-external-state-manual-scale-lifecycle",
            "claim_boundary": (
                "Ephemeral non-loopback Kubernetes lifecycle evidence with external durable state. "
                "It proves scale-to-zero state safety and multi-replica behavior, but does not unlock "
                "remote managed Knative/KEDA production admission."
            ),
            "status": "pass" if passed == len(checks) else "fail",
            "summary": {"check_count": len(checks), "passed_checks": passed, "failed_checks": len(checks) - passed},
            "checks": checks,
            "observed": observed,
        }
    )


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
        "items": build_serverless_resources(
            namespace=args.namespace,
            image=args.image,
            postgres_image=args.postgres_image,
            qdrant_image=args.qdrant_image,
            redis_image=args.redis_image,
        ),
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(resources, handle)
        manifest_path = Path(handle.name)
    try:
        _run(args.kubectl, "apply", "-f", str(manifest_path), timeout=180.0)
    finally:
        manifest_path.unlink(missing_ok=True)

    for pod_name in ("postgres-0", "qdrant-0", "redis-0", "serverless-runner"):
        _wait_for(
            f"ready pod {pod_name}",
            lambda pod_name=pod_name: (
                pod if _ready(pod := _json(args.kubectl, "get", "pod", pod_name, "-n", args.namespace)) else None
            ),
            timeout_seconds=args.timeout_seconds,
            interval_seconds=2.0,
        )

    service_base = f"http://wavemind-serverless-keda.{args.namespace}.svc.cluster.local:8000"
    base_config = {"api_key": API_KEY, "namespace": args.memory_namespace}

    def scale(replicas: int) -> None:
        _run(
            args.kubectl,
            "scale",
            "deployment/wavemind-serverless-keda",
            "-n",
            args.namespace,
            f"--replicas={replicas}",
        )

    def ready_pods(expected: int) -> list[dict[str, Any]] | None:
        payload = _json(
            args.kubectl,
            "get",
            "pods",
            "-n",
            args.namespace,
            "-l",
            "app.kubernetes.io/component=serverless-api-keda",
        )
        pods = [pod for pod in payload.get("items") or [] if _ready(pod)]
        return pods if len(pods) == expected else None

    cold_started = time.perf_counter()
    scale(1)
    _wait_for("first serverless API replica", lambda: ready_pods(1), timeout_seconds=args.timeout_seconds)
    _wait_for(
        "serverless service HTTP readiness",
        lambda: _workload(
            kubectl=args.kubectl,
            namespace=args.namespace,
            config={**base_config, "mode": "probe", "bases": [service_base]},
            timeout=20.0,
        ),
        timeout_seconds=args.timeout_seconds,
    )
    first_cold_start_ms = round((time.perf_counter() - cold_started) * 1000.0, 3)
    seed = _workload(
        kubectl=args.kubectl,
        namespace=args.namespace,
        config={**base_config, "mode": "seed", "bases": [service_base], "count": args.memories},
        timeout=300.0,
    )

    scale(0)

    def zero_state() -> bool | None:
        deployment = _json(args.kubectl, "get", "deployment", "wavemind-serverless-keda", "-n", args.namespace)
        replicas = int((deployment.get("status") or {}).get("replicas") or 0)
        endpoints = _json(args.kubectl, "get", "endpoints", "wavemind-serverless-keda", "-n", args.namespace)
        subsets = endpoints.get("subsets") or []
        return True if replicas == 0 and not subsets else None

    _wait_for("zero API replicas and endpoints", zero_state, timeout_seconds=args.timeout_seconds)
    cold_started = time.perf_counter()
    scale(1)
    _wait_for("restored serverless API replica", lambda: ready_pods(1), timeout_seconds=args.timeout_seconds)
    _wait_for(
        "restored serverless service HTTP readiness",
        lambda: _workload(
            kubectl=args.kubectl,
            namespace=args.namespace,
            config={**base_config, "mode": "probe", "bases": [service_base]},
            timeout=20.0,
        ),
        timeout_seconds=args.timeout_seconds,
    )
    cold_start_ms = round((time.perf_counter() - cold_started) * 1000.0, 3)
    restored = _workload(
        kubectl=args.kubectl,
        namespace=args.namespace,
        config={**base_config, "mode": "verify", "bases": [service_base], "count": args.memories},
        timeout=300.0,
    )

    scale(3)
    pods = _wait_for("three ready serverless API replicas", lambda: ready_pods(3), timeout_seconds=args.timeout_seconds)
    nodes = {
        str((node.get("metadata") or {}).get("name") or ""): node
        for node in (_json(args.kubectl, "get", "nodes").get("items") or [])
    }
    pod_bases: list[str] = []
    zones: set[str] = set()
    placements: list[dict[str, str]] = []
    for pod in pods:
        metadata = pod.get("metadata") or {}
        status = pod.get("status") or {}
        spec = pod.get("spec") or {}
        worker = str(spec.get("nodeName") or "")
        zone = str((((nodes.get(worker) or {}).get("metadata") or {}).get("labels") or {}).get("topology.kubernetes.io/zone") or "")
        pod_ip = str(status.get("podIP") or "")
        if not pod_ip:
            raise RuntimeError(f"pod has no IP: {metadata.get('name')}")
        zones.add(zone)
        pod_bases.append(f"http://{pod_ip}:8000")
        placements.append({"pod": str(metadata.get("name") or ""), "worker": worker, "zone": zone, "pod_ip": pod_ip})
    endpoints = _json(args.kubectl, "get", "endpoints", "wavemind-serverless-keda", "-n", args.namespace)
    endpoint_count = sum(len(subset.get("addresses") or []) for subset in endpoints.get("subsets") or [])
    cross = _workload(
        kubectl=args.kubectl,
        namespace=args.namespace,
        config={
            **base_config,
            "mode": "cross-replica",
            "bases": pod_bases,
            "service_base": service_base,
            "count": args.memories,
        },
        timeout=180.0,
    )
    burst = _workload(
        kubectl=args.kubectl,
        namespace=args.namespace,
        config={
            **base_config,
            "mode": "burst",
            "bases": [service_base],
            "count": args.memories,
            "requests": args.burst_requests,
            "workers": args.burst_workers,
        },
        timeout=300.0,
    )

    scale(0)
    _wait_for("second zero API state", zero_state, timeout_seconds=args.timeout_seconds)
    scale(1)
    _wait_for("final restored serverless API replica", lambda: ready_pods(1), timeout_seconds=args.timeout_seconds)
    _wait_for(
        "final serverless service HTTP readiness",
        lambda: _workload(
            kubectl=args.kubectl,
            namespace=args.namespace,
            config={**base_config, "mode": "probe", "bases": [service_base]},
            timeout=20.0,
        ),
        timeout_seconds=args.timeout_seconds,
    )
    final_restore = _workload(
        kubectl=args.kubectl,
        namespace=args.namespace,
        config={**base_config, "mode": "verify", "bases": [service_base], "count": args.memories},
        timeout=300.0,
    )
    pvc_count = len((_json(args.kubectl, "get", "pvc", "-n", args.namespace).get("items") or []))

    for payload in (restored, final_restore):
        payload["rate"] = int(payload.get("successes") or 0) / max(1, int(payload.get("count") or 0))
        payload["p99_ms"] = _percentile([float(value) for value in payload.get("latencies_ms") or []], 0.99)

    return evaluate_kubernetes_serverless_lifecycle_smoke(
        {
            "service_address": service_base,
            "external_services": ["postgres", "qdrant", "redis"],
            "persistent_volume_claims": pvc_count,
            "zero_replicas": True,
            "zero_endpoints": True,
            "first_cold_start_ms": first_cold_start_ms,
            "cold_start_ms": cold_start_ms,
            "cold_start_budget_ms": args.cold_start_budget_ms,
            "seed": seed,
            "restored_after_zero": restored,
            "ready_replicas": len(pods),
            "endpoint_count": endpoint_count,
            "zone_count": len(zones),
            "placements": placements,
            "cross_replica": cross,
            "burst": burst,
            "burst_p99_budget_ms": args.burst_p99_budget_ms,
            "final_restore": final_restore,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Kubernetes serverless scale-to-zero and external-state lifecycle smoke")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--namespace", default="wavemind-serverless")
    parser.add_argument("--image", default="wavemind:ci-upgrade")
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--qdrant-image", default="qdrant/qdrant:v1.15.1")
    parser.add_argument("--redis-image", default="redis:7-alpine")
    parser.add_argument("--memory-namespace", default="kind-serverless-lifecycle")
    parser.add_argument("--memories", type=int, default=24)
    parser.add_argument("--burst-requests", type=int, default=120)
    parser.add_argument("--burst-workers", type=int, default=12)
    parser.add_argument("--cold-start-budget-ms", type=float, default=120000.0)
    parser.add_argument("--burst-p99-budget-ms", type=float, default=2000.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/kubernetes_serverless_lifecycle_smoke_results.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = _source_provenance(
            {
                "schema": "wavemind.kubernetes_serverless_lifecycle_smoke.v1",
                "generated_at": _utc_now(),
                "environment": "kind-multizone-serverless-lifecycle-ci",
                "evidence_source": "github-actions-kind-external-state-manual-scale-lifecycle",
                "claim_boundary": (
                    "Ephemeral non-loopback Kubernetes lifecycle evidence; not remote managed "
                    "Knative/KEDA production admission."
                ),
                "status": "fail",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(main())
