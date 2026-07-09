from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(
    kubectl: str,
    *args: str,
    timeout: float = 60.0,
) -> str:
    completed = subprocess.run(
        [kubectl, *args],
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )
    return completed.stdout.strip()


def _json(kubectl: str, *args: str, timeout: float = 60.0) -> dict[str, Any]:
    raw = _run(kubectl, *args, "-o", "json", timeout=timeout)
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"kubectl returned non-object JSON for {' '.join(args)}")
    return payload


def _ready(pod: dict[str, Any]) -> bool:
    status = dict(pod.get("status") or {})
    if status.get("phase") != "Running":
        return False
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions") or []
        if isinstance(condition, dict)
    )


def _wait_for(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout_seconds: float,
    interval_seconds: float = 2.0,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(interval_seconds)
    suffix = f": {last_error}" if last_error else ""
    raise TimeoutError(f"timed out waiting for {description}{suffix}")


def _lease_state(payload: dict[str, Any]) -> tuple[str, int, str | None]:
    spec = dict(payload.get("spec") or {})
    metadata = dict(payload.get("metadata") or {})
    return (
        str(spec.get("holderIdentity") or ""),
        int(spec.get("leaseTransitions") or 0),
        str(metadata.get("resourceVersion") or "") or None,
    )


def evaluate_kubernetes_operator_smoke(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "id": "multi_node_cluster",
            "passed": int(metrics.get("node_count", 0)) >= 3,
            "value": metrics.get("node_count", 0),
            "target": 3,
        },
        {
            "id": "redundant_operator_pods",
            "passed": int(metrics.get("operator_pod_count", 0)) >= 2,
            "value": metrics.get("operator_pod_count", 0),
            "target": 2,
        },
        {
            "id": "operator_cross_node_placement",
            "passed": int(metrics.get("operator_node_count", 0)) >= 2,
            "value": metrics.get("operator_node_count", 0),
            "target": 2,
        },
        {
            "id": "data_plane_topology_spread",
            "passed": int(metrics.get("topology_spread_constraint_count", 0)) >= 2,
            "value": metrics.get("topology_spread_constraint_count", 0),
            "target": 2,
        },
        {
            "id": "pod_disruption_budget",
            "passed": int(metrics.get("pdb_min_available", 0))
            >= max(1, int(metrics.get("desired_replicas_after_scale", 0)) - 1)
            and int(metrics.get("pdb_disruptions_allowed", 0)) >= 1,
            "value": {
                "minAvailable": metrics.get("pdb_min_available", 0),
                "disruptionsAllowed": metrics.get("pdb_disruptions_allowed", 0),
            },
            "target": "minAvailable >= replicas - 1 and disruptionsAllowed >= 1",
        },
        {
            "id": "leader_failover",
            "passed": bool(metrics.get("initial_holder"))
            and bool(metrics.get("next_holder"))
            and metrics.get("initial_holder") != metrics.get("next_holder"),
            "value": f"{metrics.get('initial_holder')} -> {metrics.get('next_holder')}",
            "target": "holder changes",
        },
        {
            "id": "lease_transition_recorded",
            "passed": int(metrics.get("lease_transitions_after", 0))
            > int(metrics.get("lease_transitions_before", 0)),
            "value": metrics.get("lease_transitions_after", 0),
            "target": int(metrics.get("lease_transitions_before", 0)) + 1,
        },
        {
            "id": "leader_reconcile_after_failover",
            "passed": int(metrics.get("ready_replicas_after_scale", 0))
            == int(metrics.get("desired_replicas_after_scale", -1)),
            "value": metrics.get("ready_replicas_after_scale", 0),
            "target": metrics.get("desired_replicas_after_scale", 0),
        },
        {
            "id": "operator_status_tracks_leader",
            "passed": bool(metrics.get("next_holder"))
            and metrics.get("cluster_status_holder") == metrics.get("next_holder"),
            "value": metrics.get("cluster_status_holder"),
            "target": metrics.get("next_holder"),
        },
        {
            "id": "data_pod_recovered",
            "passed": bool(metrics.get("data_pod_uid_changed")),
            "value": metrics.get("data_pod_uid_changed"),
            "target": True,
        },
        {
            "id": "api_healthy_after_recovery",
            "passed": bool(metrics.get("api_healthy_after_recovery")),
            "value": metrics.get("api_healthy_after_recovery"),
            "target": True,
        },
        {
            "id": "rolling_upgrade_revision_changed",
            "passed": bool(metrics.get("rolling_upgrade_revision_changed")),
            "value": metrics.get("rolling_upgrade_revision_changed"),
            "target": True,
        },
        {
            "id": "rolling_upgrade_replaced_all_pods",
            "passed": int(metrics.get("rolling_upgrade_replaced_pods", 0))
            >= int(metrics.get("desired_replicas_after_scale", -1)),
            "value": metrics.get("rolling_upgrade_replaced_pods", 0),
            "target": metrics.get("desired_replicas_after_scale", 0),
        },
        {
            "id": "api_healthy_after_rolling_upgrade",
            "passed": bool(metrics.get("api_healthy_after_upgrade")),
            "value": metrics.get("api_healthy_after_upgrade"),
            "target": True,
        },
    ]
    passed = sum(1 for check in checks if check["passed"])
    payload = {
        "schema": "wavemind.kubernetes_operator_smoke.v1",
        "generated_at": _utc_now(),
        "environment": "kind-multinode-ci",
        "evidence_source": "github-actions-kind",
        "claim_boundary": (
            "Ephemeral multi-node Kubernetes CI evidence. It proves real Kubernetes "
            "API reconciliation, Lease/etcd-backed operator failover, StatefulSet "
            "reconciliation, and pod recovery. It does not unlock remote production, "
            "multi-region, managed-serverless, or 100M admission claims."
        ),
        "status": "pass" if passed == len(checks) else "fail",
        "summary": {
            "passed_checks": passed,
            "check_count": len(checks),
            **metrics,
        },
        "checks": checks,
    }
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


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    namespace = args.namespace
    label = "app.kubernetes.io/name=wavemind-operator"
    _run(
        args.kubectl,
        "rollout",
        "status",
        f"deployment/{args.operator_deployment}",
        "-n",
        namespace,
        f"--timeout={int(args.timeout_seconds)}s",
        timeout=args.timeout_seconds + 10,
    )

    nodes = _json(args.kubectl, "get", "nodes")

    def _ready_operators() -> list[dict[str, Any]] | None:
        payload = _json(args.kubectl, "get", "pods", "-n", namespace, "-l", label)
        pods = [pod for pod in payload.get("items") or [] if _ready(pod)]
        pod_nodes = {
            str((pod.get("spec") or {}).get("nodeName") or "")
            for pod in pods
            if (pod.get("spec") or {}).get("nodeName")
        }
        return pods if len(pods) >= 2 and len(pod_nodes) >= 2 else None

    ready_operator_pods = _wait_for(
        "two ready operator replicas on separate nodes",
        _ready_operators,
        timeout_seconds=args.timeout_seconds,
    )
    operator_nodes = {
        str((pod.get("spec") or {}).get("nodeName") or "")
        for pod in ready_operator_pods
        if (pod.get("spec") or {}).get("nodeName")
    }
    lease = _wait_for(
        "operator Lease",
        lambda: _json(
            args.kubectl,
            "get",
            "lease",
            args.lease_name,
            "-n",
            namespace,
        ),
        timeout_seconds=args.timeout_seconds,
    )
    initial_holder, transitions_before, _ = _lease_state(lease)
    if not initial_holder:
        raise RuntimeError("operator Lease has no holderIdentity")
    _run(
        args.kubectl,
        "delete",
        "pod",
        initial_holder,
        "-n",
        namespace,
        "--wait=false",
    )

    def _new_leader() -> tuple[str, int, str | None] | None:
        state = _lease_state(
            _json(
                args.kubectl,
                "get",
                "lease",
                args.lease_name,
                "-n",
                namespace,
            )
        )
        if state[0] and state[0] != initial_holder and state[1] > transitions_before:
            return state
        return None

    next_holder, transitions_after, resource_version = _wait_for(
        "operator Lease takeover",
        _new_leader,
        timeout_seconds=args.timeout_seconds,
    )
    _run(
        args.kubectl,
        "rollout",
        "status",
        f"deployment/{args.operator_deployment}",
        "-n",
        namespace,
        f"--timeout={int(args.timeout_seconds)}s",
        timeout=args.timeout_seconds + 10,
    )

    statefulset = _wait_for(
        "initial WaveMind StatefulSet",
        lambda: _json(
            args.kubectl,
            "get",
            "statefulset",
            args.cluster_name,
            "-n",
            namespace,
        ),
        timeout_seconds=args.timeout_seconds,
    )
    original_replicas = int((statefulset.get("spec") or {}).get("replicas") or 0)
    desired_replicas = original_replicas + 1
    _run(
        args.kubectl,
        "patch",
        "wavemindcluster",
        args.cluster_name,
        "-n",
        namespace,
        "--type=merge",
        "-p",
        json.dumps({"spec": {"replicas": desired_replicas}}),
    )

    def _scaled_statefulset() -> dict[str, Any] | None:
        current = _json(
            args.kubectl,
            "get",
            "statefulset",
            args.cluster_name,
            "-n",
            namespace,
        )
        spec_replicas = int((current.get("spec") or {}).get("replicas") or 0)
        ready_replicas = int((current.get("status") or {}).get("readyReplicas") or 0)
        return current if spec_replicas == desired_replicas and ready_replicas == desired_replicas else None

    scaled = _wait_for(
        "StatefulSet scale reconciliation",
        _scaled_statefulset,
        timeout_seconds=args.timeout_seconds,
    )
    ready_replicas = int((scaled.get("status") or {}).get("readyReplicas") or 0)

    def _cluster_status_holder() -> str | None:
        cluster = _json(
            args.kubectl,
            "get",
            "wavemindcluster",
            args.cluster_name,
            "-n",
            namespace,
        )
        holder = str(
            ((cluster.get("status") or {}).get("operatorLeader") or {}).get(
                "holderIdentity"
            )
            or ""
        )
        return holder if holder == next_holder else None

    cluster_status_holder = _wait_for(
        "WaveMindCluster status to record the new operator leader",
        _cluster_status_holder,
        timeout_seconds=args.timeout_seconds,
    )

    data_pod_name = f"{args.cluster_name}-0"
    data_pod = _json(args.kubectl, "get", "pod", data_pod_name, "-n", namespace)
    original_uid = str((data_pod.get("metadata") or {}).get("uid") or "")
    _run(
        args.kubectl,
        "delete",
        "pod",
        data_pod_name,
        "-n",
        namespace,
        "--wait=false",
    )

    def _recovered_data_pod() -> dict[str, Any] | None:
        pod = _json(args.kubectl, "get", "pod", data_pod_name, "-n", namespace)
        uid = str((pod.get("metadata") or {}).get("uid") or "")
        return pod if uid and uid != original_uid and _ready(pod) else None

    recovered = _wait_for(
        "StatefulSet pod recovery",
        _recovered_data_pod,
        timeout_seconds=args.timeout_seconds,
    )
    recovered_uid = str((recovered.get("metadata") or {}).get("uid") or "")
    health_raw = _run(
        args.kubectl,
        "exec",
        data_pod_name,
        "-n",
        namespace,
        "--",
        "python",
        "-c",
        (
            "import json,urllib.request; "
            "print(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/stats', "
            "timeout=5).read()))"
        ),
    )

    def _ready_pdb() -> dict[str, Any] | None:
        payload = _json(
            args.kubectl,
            "get",
            "poddisruptionbudget",
            args.cluster_name,
            "-n",
            namespace,
        )
        min_available = int((payload.get("spec") or {}).get("minAvailable") or 0)
        disruptions_allowed = int((payload.get("status") or {}).get("disruptionsAllowed") or 0)
        return (
            payload
            if min_available >= max(1, desired_replicas - 1) and disruptions_allowed >= 1
            else None
        )

    pdb = _wait_for(
        "PodDisruptionBudget to protect the scaled data plane",
        _ready_pdb,
        timeout_seconds=args.timeout_seconds,
    )
    pdb_min_available = int((pdb.get("spec") or {}).get("minAvailable") or 0)
    pdb_disruptions_allowed = int((pdb.get("status") or {}).get("disruptionsAllowed") or 0)
    topology_spread_count = len(
        ((scaled.get("spec") or {}).get("template") or {}).get("spec", {}).get(
            "topologySpreadConstraints"
        )
        or []
    )

    selector_labels = dict((scaled.get("spec") or {}).get("selector", {}).get("matchLabels") or {})
    selector = ",".join(f"{key}={value}" for key, value in sorted(selector_labels.items()))
    before_upgrade_pods = _json(
        args.kubectl,
        "get",
        "pods",
        "-n",
        namespace,
        "-l",
        selector,
    )
    before_upgrade_uids = {
        str((pod.get("metadata") or {}).get("uid") or "")
        for pod in before_upgrade_pods.get("items") or []
        if (pod.get("metadata") or {}).get("uid")
    }
    revision_before_upgrade = str(
        (scaled.get("status") or {}).get("updateRevision")
        or (scaled.get("status") or {}).get("currentRevision")
        or ""
    )
    _run(
        args.kubectl,
        "patch",
        "wavemindcluster",
        args.cluster_name,
        "-n",
        namespace,
        "--type=merge",
        "-p",
        json.dumps({"spec": {"image": args.upgrade_image}}),
    )

    def _upgrade_started() -> dict[str, Any] | None:
        current = _json(
            args.kubectl,
            "get",
            "statefulset",
            args.cluster_name,
            "-n",
            namespace,
        )
        containers = (
            ((current.get("spec") or {}).get("template") or {}).get("spec", {}).get(
                "containers"
            )
            or []
        )
        return current if containers and containers[0].get("image") == args.upgrade_image else None

    _wait_for(
        "operator to start the CR-driven rolling upgrade",
        _upgrade_started,
        timeout_seconds=args.timeout_seconds,
    )
    _run(
        args.kubectl,
        "rollout",
        "status",
        f"statefulset/{args.cluster_name}",
        "-n",
        namespace,
        f"--timeout={int(args.timeout_seconds)}s",
        timeout=args.timeout_seconds + 10,
    )

    def _upgraded_data_plane() -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        current = _json(
            args.kubectl,
            "get",
            "statefulset",
            args.cluster_name,
            "-n",
            namespace,
        )
        pods_payload = _json(
            args.kubectl,
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            selector,
        )
        pods = list(pods_payload.get("items") or [])
        images = {
            str(container.get("image") or "")
            for pod in pods
            for container in ((pod.get("spec") or {}).get("containers") or [])
        }
        status = dict(current.get("status") or {})
        revision_changed = bool(status.get("updateRevision")) and (
            str(status.get("updateRevision")) != revision_before_upgrade
        )
        ready = (
            len(pods) == desired_replicas
            and all(_ready(pod) for pod in pods)
            and images == {args.upgrade_image}
            and int(status.get("readyReplicas") or 0) == desired_replicas
            and status.get("currentRevision") == status.get("updateRevision")
            and revision_changed
        )
        return (current, pods) if ready else None

    upgraded_statefulset, upgraded_pods = _wait_for(
        "all data pods to complete the rolling upgrade",
        _upgraded_data_plane,
        timeout_seconds=args.timeout_seconds,
    )
    after_upgrade_uids = {
        str((pod.get("metadata") or {}).get("uid") or "")
        for pod in upgraded_pods
        if (pod.get("metadata") or {}).get("uid")
    }
    replaced_pods = len(after_upgrade_uids - before_upgrade_uids)
    upgraded_status = dict(upgraded_statefulset.get("status") or {})
    rolling_revision_changed = bool(upgraded_status.get("updateRevision")) and (
        str(upgraded_status.get("updateRevision")) != revision_before_upgrade
    )
    upgraded_health = []
    for pod in sorted(
        str((item.get("metadata") or {}).get("name") or "") for item in upgraded_pods
    ):
        upgraded_health.append(
            bool(
                _run(
                    args.kubectl,
                    "exec",
                    pod,
                    "-n",
                    namespace,
                    "--",
                    "python",
                    "-c",
                    (
                        "import json,urllib.request; "
                        "print(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/stats', "
                        "timeout=5).read()))"
                    ),
                )
            )
        )

    return evaluate_kubernetes_operator_smoke(
        {
            "node_count": len(nodes.get("items") or []),
            "operator_pod_count": len(ready_operator_pods),
            "operator_node_count": len(operator_nodes),
            "initial_holder": initial_holder,
            "next_holder": next_holder,
            "lease_transitions_before": transitions_before,
            "lease_transitions_after": transitions_after,
            "lease_resource_version_after": resource_version,
            "original_replicas": original_replicas,
            "desired_replicas_after_scale": desired_replicas,
            "ready_replicas_after_scale": ready_replicas,
            "cluster_status_holder": cluster_status_holder,
            "data_pod_uid_changed": bool(original_uid and recovered_uid != original_uid),
            "api_healthy_after_recovery": bool(health_raw),
            "topology_spread_constraint_count": topology_spread_count,
            "pdb_min_available": pdb_min_available,
            "pdb_disruptions_allowed": pdb_disruptions_allowed,
            "rolling_upgrade_image": args.upgrade_image,
            "rolling_upgrade_revision_changed": rolling_revision_changed,
            "rolling_upgrade_replaced_pods": replaced_pods,
            "api_healthy_after_upgrade": bool(upgraded_health) and all(upgraded_health),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a real multi-node Kubernetes operator failover smoke")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--namespace", default="wavemind-system")
    parser.add_argument("--operator-deployment", default="wavemind-operator")
    parser.add_argument("--lease-name", default="wavemind-operator")
    parser.add_argument("--cluster-name", default="wavemind-ci")
    parser.add_argument("--upgrade-image", default="wavemind:ci-upgrade")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/kubernetes_operator_smoke_results.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = {
            "schema": "wavemind.kubernetes_operator_smoke.v1",
            "generated_at": _utc_now(),
            "environment": "kind-multinode-ci",
            "evidence_source": "github-actions-kind",
            "claim_boundary": "Ephemeral CI evidence only; not remote production admission.",
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(main())
