import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError

import pytest

from wavemind import (
    KubernetesApplyClient,
    KubernetesLeaderElectionReport,
    WaveMindClusterSpec,
    custom_resource_definition,
    kubernetes_resource_path,
    operator_bundle,
    operator_loop,
    operator_reconcile,
    operator_status,
)


def run_cli(*args):
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "wavemind", *args],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


class RecordingKubernetesClient:
    def __init__(self, clusters, *, leader=True):
        self.clusters = clusters
        self.applied = []
        self.status_patches = []
        self.leader = leader
        self.lease_calls = []

    def acquire_or_renew_operator_lease(
        self,
        *,
        namespace,
        lease_name,
        holder_identity,
        lease_duration_seconds,
    ):
        self.lease_calls.append(
            {
                "namespace": namespace,
                "lease_name": lease_name,
                "holder_identity": holder_identity,
                "lease_duration_seconds": lease_duration_seconds,
            }
        )
        return KubernetesLeaderElectionReport(
            namespace=namespace,
            lease_name=lease_name,
            holder_identity=holder_identity,
            current_holder=holder_identity if self.leader else "operator-other",
            acquired=self.leader,
            renewed=False,
            lease_duration_seconds=lease_duration_seconds,
            lease_transitions=0,
            resource_version="7",
            reason="acquired" if self.leader else "lease_held",
        )

    def list_wavemind_clusters(self, namespace):
        assert namespace == "wavemind-system"
        return self.clusters

    def apply(self, resource):
        self.applied.append(resource)
        return resource

    def patch_wavemind_cluster_status(self, *, namespace, name, status, field_manager="wavemind-operator"):
        self.status_patches.append(
            {
                "namespace": namespace,
                "name": name,
                "status": status,
                "field_manager": field_manager,
            }
        )
        return {"status": status}


class LeaseApiClient(KubernetesApplyClient):
    def __init__(self):
        super().__init__(host="https://kubernetes.example", token="test")
        self.lease = None
        self.requests = []

    def _request(self, method, path, *, payload=None, content_type="application/json"):
        self.requests.append((method, path, payload, content_type))
        if method == "GET":
            if self.lease is None:
                raise HTTPError(path, 404, "not found", None, None)
            return json.loads(json.dumps(self.lease))
        if method == "POST":
            if self.lease is not None:
                raise HTTPError(path, 409, "conflict", None, None)
            self.lease = json.loads(json.dumps(payload))
            self.lease["metadata"]["resourceVersion"] = "1"
            return json.loads(json.dumps(self.lease))
        if method == "PUT":
            expected = str((payload.get("metadata") or {}).get("resourceVersion") or "")
            current = str((self.lease.get("metadata") or {}).get("resourceVersion") or "")
            if expected != current:
                raise HTTPError(path, 409, "conflict", None, None)
            self.lease = json.loads(json.dumps(payload))
            self.lease["metadata"]["resourceVersion"] = str(int(current) + 1)
            return json.loads(json.dumps(self.lease))
        raise AssertionError(f"unexpected request: {method} {path}")


def test_custom_resource_definition_declares_namespaced_wavemindcluster():
    crd = custom_resource_definition()

    assert crd["kind"] == "CustomResourceDefinition"
    assert crd["metadata"]["name"] == "wavemindclusters.memory.wavemind.ai"
    assert crd["spec"]["scope"] == "Namespaced"
    assert crd["spec"]["names"]["kind"] == "WaveMindCluster"
    spec_props = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    assert "autoscaling" in spec_props
    assert "controlPlane" in spec_props
    assert "productionAdmission" in spec_props
    status_props = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["status"]
    assert crd["spec"]["versions"][0]["subresources"] == {"status": {}}
    assert status_props["x-kubernetes-preserve-unknown-fields"] is True
    consensus_props = spec_props["controlPlane"]["properties"]["consensus"]["properties"]
    memory_os_props = spec_props["memoryOs"]["properties"]
    assert "enabled" in consensus_props
    assert "leaseTtlSeconds" in consensus_props
    assert "configRevision" in consensus_props
    assert "enabled" in memory_os_props
    assert "schedule" in memory_os_props
    assert memory_os_props["cacheMode"]["enum"] == ["auto", "disabled", "local", "redis"]
    assert "lockRequired" in memory_os_props
    assert "runOnAllReplicas" in memory_os_props
    positive_number_schemas = [
        memory_os_props["targetQps"],
        memory_os_props["targetP99Ms"],
        memory_os_props["timeoutSeconds"],
        consensus_props["leaseTtlSeconds"],
        spec_props["autoscaling"]["properties"]["headroom"],
    ]
    assert all(schema["minimum"] == 0 for schema in positive_number_schemas)
    assert all(schema["exclusiveMinimum"] is True for schema in positive_number_schemas)
    production_admission_props = spec_props["productionAdmission"]["properties"]
    assert "enabled" in production_admission_props
    assert "targetMemories" in production_admission_props
    assert "engine" in production_admission_props
    assert "evidenceRoot" in production_admission_props
    assert "maxReplicas" in spec_props["autoscaling"]["properties"]
    assert "targetMemories" in spec_props["autoscaling"]["properties"]
    assert "maxMemoriesPerNode" in spec_props["autoscaling"]["properties"]
    assert "headroom" in spec_props["autoscaling"]["properties"]
    rebalance_props = spec_props["autoscaling"]["properties"]["rebalance"]["properties"]
    assert "batchSize" in rebalance_props
    assert "maxNodeMovesPerBatch" in rebalance_props
    assert "previewBatches" in rebalance_props


def test_operator_reconcile_renders_cluster_resources():
    spec = WaveMindClusterSpec(
        name="wm-prod",
        namespace="wavemind-system",
        image="ghcr.io/caspiang/wavemind:2.4.3",
        replicas=3,
        replication_factor=2,
        namespace_count=4,
        auth_secret="wavemind-auth",
    )

    payload = operator_reconcile(spec.custom_resource())
    resources = {resource["kind"]: resource for resource in payload["items"]}

    assert payload["kind"] == "List"
    assert resources["StatefulSet"]["spec"]["replicas"] == 3
    assert resources["StatefulSet"]["spec"]["serviceName"] == "wm-prod-headless"
    assert resources["StatefulSet"]["spec"]["updateStrategy"] == {"type": "RollingUpdate"}
    assert resources["StatefulSet"]["spec"]["minReadySeconds"] == 5
    pod_spec = resources["StatefulSet"]["spec"]["template"]["spec"]
    assert pod_spec["terminationGracePeriodSeconds"] == 30
    assert {
        constraint["topologyKey"] for constraint in pod_spec["topologySpreadConstraints"]
    } == {"kubernetes.io/hostname", "topology.kubernetes.io/zone"}
    assert pod_spec["affinity"]["podAntiAffinity"][
        "preferredDuringSchedulingIgnoredDuringExecution"
    ]
    assert resources["PodDisruptionBudget"]["apiVersion"] == "policy/v1"
    assert resources["PodDisruptionBudget"]["spec"]["minAvailable"] == 2
    container = resources["StatefulSet"]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/caspiang/wavemind:2.4.3"
    assert container["command"] == ["wavemind"]
    assert container["args"] == ["serve", "--host", "0.0.0.0", "--port", "8000"]
    assert {"name": "WAVEMIND_REPLICATION_FACTOR", "value": "2"} in container["env"]
    assert resources["CronJob"]["metadata"]["name"] == "wm-prod-cluster-repair"
    repair_args = resources["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert repair_args.count("--namespace") == 4
    assert "wm-prod-0=http://wm-prod-0.wm-prod-headless.wavemind-system.svc.cluster.local:8000" in repair_args
    assert payload["operatorStatus"]["controlPlane"]["ready"] is True
    assert payload["operatorStatus"]["controlPlane"]["profile"]["voters_initial"] == 3


def test_operator_reconcile_renders_horizontal_pod_autoscaler_when_enabled():
    spec = WaveMindClusterSpec(
        name="wm-scale",
        namespace="wavemind-system",
        replicas=4,
        replication_factor=2,
        namespace_count=8,
        autoscaling_enabled=True,
        autoscaling_min_replicas=4,
        autoscaling_max_replicas=24,
        autoscaling_target_cpu_utilization=65,
        autoscaling_target_memory_utilization=80,
    )

    payload = operator_reconcile(spec.custom_resource())
    resources = {resource["kind"]: resource for resource in payload["items"]}
    hpa = resources["HorizontalPodAutoscaler"]

    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["spec"]["scaleTargetRef"]["kind"] == "StatefulSet"
    assert hpa["spec"]["scaleTargetRef"]["name"] == "wm-scale"
    assert hpa["spec"]["minReplicas"] == 4
    assert hpa["spec"]["maxReplicas"] == 24
    metric_names = [metric["resource"]["name"] for metric in hpa["spec"]["metrics"]]
    assert metric_names == ["cpu", "memory"]


def test_operator_reconcile_renders_explicit_production_admission_guard():
    spec = WaveMindClusterSpec(
        name="wm-guarded",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=2,
        namespace_count=8,
        production_admission_enabled=True,
        production_admission_target_memories=100_000_000,
        production_admission_engine="qdrant-sharded-service",
        production_admission_root="/evidence",
    )

    resource = spec.custom_resource()
    assert resource["spec"]["productionAdmission"]["enabled"] is True
    assert resource["spec"]["productionAdmission"]["targetMemories"] == 100_000_000

    payload = operator_reconcile(resource)
    statefulset = {
        resource["kind"]: resource for resource in payload["items"]
    }["StatefulSet"]
    container = statefulset["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item.get("value") for item in container["env"]}

    assert container["command"] == ["wavemind"]
    assert container["args"] == ["serve", "--host", "0.0.0.0", "--port", "8000"]
    assert env["WAVEMIND_REQUIRE_PRODUCTION_ADMISSION"] == "1"
    assert env["WAVEMIND_PRODUCTION_TARGET_MEMORIES"] == "100000000"
    assert env["WAVEMIND_PRODUCTION_ENGINE"] == "qdrant-sharded-service"
    assert env["WAVEMIND_PRODUCTION_ADMISSION_ROOT"] == "/evidence"
    assert payload["operatorStatus"]["productionAdmission"]["enabled"] is True
    assert payload["operatorStatus"]["productionAdmission"]["configured"] is True
    assert payload["operatorStatus"]["productionAdmission"]["ready"] is True


def test_operator_reconcile_uses_capacity_target_for_statefulset_and_hpa():
    spec = WaveMindClusterSpec(
        name="wm-capacity",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=3,
        namespace_count=4096,
        autoscaling_enabled=True,
        autoscaling_min_replicas=3,
        autoscaling_max_replicas=24,
        autoscaling_target_memories=10_000_000,
        autoscaling_max_memories_per_node=1_000_000,
        autoscaling_headroom=0.70,
    )

    payload = operator_reconcile(spec.custom_resource())
    resources = {resource["kind"]: resource for resource in payload["items"]}
    statefulset = resources["StatefulSet"]
    hpa = resources["HorizontalPodAutoscaler"]
    configmap = resources["ConfigMap"]
    container = statefulset["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item.get("value") for item in container["env"]}
    annotations = statefulset["metadata"]["annotations"]
    rebalance_summary = json.loads(configmap["data"]["rebalance-summary.json"])
    rebalance_preview = json.loads(configmap["data"]["rebalance-batches-preview.json"])

    assert statefulset["spec"]["replicas"] >= 43
    assert hpa["spec"]["minReplicas"] == statefulset["spec"]["replicas"]
    assert hpa["spec"]["maxReplicas"] >= statefulset["spec"]["replicas"]
    assert annotations["memory.wavemind.ai/capacity-target-memories"] == "10000000"
    assert int(annotations["memory.wavemind.ai/capacity-required-replicas"]) == statefulset["spec"]["replicas"]
    assert int(annotations["memory.wavemind.ai/capacity-target-max-node-memories"]) <= 700_000
    assert env["WAVEMIND_REQUIRE_PRODUCTION_ADMISSION"] == "1"
    assert env["WAVEMIND_PRODUCTION_TARGET_MEMORIES"] == "10000000"
    assert env["WAVEMIND_PRODUCTION_ADMISSION_ROOT"] == "/evidence"
    assert configmap["metadata"]["name"] == "wm-capacity-rebalance-plan"
    assert configmap["metadata"]["annotations"]["memory.wavemind.ai/rebalance-status"] == "ready"
    assert configmap["metadata"]["annotations"]["memory.wavemind.ai/rebalance-full-plan"] == "true"
    assert rebalance_summary["status"] == "ready"
    assert rebalance_summary["full_plan"] is True
    assert rebalance_summary["batch_count"] >= 1
    assert rebalance_summary["move_count"] == spec.namespace_count
    assert rebalance_summary["write_quorum"] == 2
    assert rebalance_summary["preview_batches"] == len(rebalance_preview)
    assert payload["operatorStatus"]["ready"] is True
    assert payload["operatorStatus"]["capacity"]["requiredReplicas"] == statefulset["spec"]["replicas"]
    assert payload["operatorStatus"]["capacity"]["withinHeadroom"] is True
    assert payload["operatorStatus"]["rebalance"]["ready"] is True
    assert payload["operatorStatus"]["rebalance"]["fullPlan"] is True
    assert payload["operatorStatus"]["rebalance"]["batchCount"] >= 1
    assert payload["operatorStatus"]["rebalance"]["configMapName"] == "wm-capacity-rebalance-plan"
    assert {
        condition["type"] for condition in payload["operatorStatus"]["conditions"]
    } == {
        "ResourcesReady",
        "CapacityPlanned",
        "AutoscalingReady",
        "RebalancePlanned",
        "RepairScheduled",
        "MemoryOSReady",
        "ProductionAdmissionReady",
        "ControlPlaneReady",
    }
    assert payload["operatorStatus"]["memoryOs"]["enabled"] is False
    assert payload["operatorStatus"]["memoryOs"]["ready"] is True
    assert payload["operatorStatus"]["productionAdmission"]["enabled"] is True
    assert payload["operatorStatus"]["productionAdmission"]["required"] is True
    assert payload["operatorStatus"]["productionAdmission"]["ready"] is True
    assert payload["operatorStatus"]["productionAdmission"]["targetMemories"] == 10_000_000
    assert payload["operatorStatus"]["controlPlane"]["ready"] is True
    assert payload["operatorStatus"]["controlPlane"]["profile"]["minority_commit_blocked"] is True


def test_operator_status_reports_degraded_capacity_and_repair_actions():
    spec = WaveMindClusterSpec(
        name="wm-status",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=3,
        namespace_count=128,
        repair_enabled=False,
        autoscaling_enabled=True,
        autoscaling_min_replicas=3,
        autoscaling_max_replicas=3,
        autoscaling_target_memories=10_000_000,
        autoscaling_max_memories_per_node=1_000_000,
        autoscaling_headroom=0.70,
    )

    status = operator_status(
        spec.custom_resource(),
        observed={
            "readyReplicas": 2,
            "currentReplicas": 3,
            "currentMemories": 1_200_000,
            "degradedNodes": 1,
            "unavailableNodes": 1,
            "hpaDesiredReplicas": 3,
        },
    )
    conditions = {condition["type"]: condition for condition in status["conditions"]}

    assert status["ready"] is False
    assert status["phase"] == "Degraded"
    assert status["readyReplicas"] == 2
    assert status["degradedNodes"] == 1
    assert status["capacity"]["requiredReplicas"] <= status["autoscaling"]["maxReplicas"]
    assert conditions["ResourcesReady"]["status"] == "False"
    assert conditions["CapacityPlanned"]["status"] == "True"
    assert conditions["RebalancePlanned"]["status"] == "True"
    assert conditions["RepairScheduled"]["status"] == "False"
    assert conditions["ControlPlaneReady"]["status"] == "True"
    assert any("Run cluster-health" in action for action in status["actions"])
    assert any("Enable scheduled cluster repair" in action for action in status["actions"])


def test_operator_reconcile_renders_memory_os_cronjob_with_plan_gate():
    spec = WaveMindClusterSpec(
        name="wm-memory-os",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=2,
        namespace_count=8,
        redis_url="redis://redis.wavemind-system.svc.cluster.local:6379/0",
        memory_os_enabled=True,
        memory_os_schedule="*/5 * * * *",
        memory_os_namespace="tenant:ops",
        memory_os_cache_mode="auto",
        memory_os_target_memories=2_000_000,
        memory_os_lock_required=False,
        memory_os_run_on_all_replicas=False,
    )

    payload = operator_reconcile(spec.custom_resource())
    cronjobs = {
        resource["metadata"]["name"]: resource
        for resource in payload["items"]
        if resource["kind"] == "CronJob"
    }
    memory_os = cronjobs["wm-memory-os-memory-os"]
    container = memory_os["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    script = container["args"][0]

    assert memory_os["spec"]["schedule"] == "*/5 * * * *"
    assert "/memory-os/plan" in script
    assert "/memory-os/run" in script
    assert "plan_requires_lock" in script
    assert "spec.cache.redisUrl is not configured" in script
    assert '"namespace": "tenant:ops"' in script
    assert '"cache_mode": "auto"' in script
    assert '"target_memories": 2000000' in script
    assert "run_nodes = nodes if False else nodes[:1]" in script
    assert payload["operatorStatus"]["memoryOs"]["enabled"] is True
    assert payload["operatorStatus"]["memoryOs"]["ready"] is True
    assert payload["operatorStatus"]["memoryOs"]["redisRequired"] is True
    assert payload["operatorStatus"]["memoryOs"]["redisConfigured"] is True
    assert any(
        condition["type"] == "MemoryOSReady" and condition["status"] == "True"
        for condition in payload["operatorStatus"]["conditions"]
    )


def test_operator_status_blocks_memory_os_without_required_redis():
    spec = WaveMindClusterSpec(
        name="wm-memory-os-blocked",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=2,
        namespace_count=8,
        memory_os_enabled=True,
        memory_os_cache_mode="auto",
        memory_os_target_memories=2_000_000,
    )

    status = operator_status(spec.custom_resource())
    conditions = {condition["type"]: condition for condition in status["conditions"]}

    assert status["ready"] is False
    assert status["memoryOs"]["enabled"] is True
    assert status["memoryOs"]["ready"] is False
    assert status["memoryOs"]["redisRequired"] is True
    assert status["memoryOs"]["redisConfigured"] is False
    assert conditions["MemoryOSReady"]["status"] == "False"
    assert conditions["MemoryOSReady"]["reason"] == "MemoryOSRedisRequired"
    assert any("cache.redisUrl" in action for action in status["actions"])


def test_operator_status_marks_control_plane_disabled_as_not_ready():
    spec = WaveMindClusterSpec(
        name="wm-no-consensus",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=3,
        namespace_count=16,
        control_plane_consensus_enabled=False,
    )

    status = operator_status(spec.custom_resource())
    conditions = {condition["type"]: condition for condition in status["conditions"]}

    assert status["ready"] is False
    assert status["controlPlane"]["enabled"] is False
    assert status["controlPlane"]["ready"] is False
    assert conditions["ControlPlaneReady"]["status"] == "False"
    assert any("control-plane consensus" in action for action in status["actions"])


def test_operator_bundle_contains_crd_rbac_deployment_and_sample():
    bundle = operator_bundle(namespace="wavemind-system")
    kinds = [item["kind"] for item in bundle["items"]]

    assert bundle["kind"] == "List"
    assert "CustomResourceDefinition" in kinds
    assert "ServiceAccount" in kinds
    assert "ClusterRole" in kinds
    assert "ClusterRoleBinding" in kinds
    assert "Deployment" in kinds
    assert "WaveMindCluster" in kinds
    deployment = next(item for item in bundle["items"] if item["kind"] == "Deployment")
    role = next(item for item in bundle["items"] if item["kind"] == "ClusterRole")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    args = container["args"]
    assert container["command"] == ["wavemind"]
    assert deployment["spec"]["replicas"] == 2
    assert deployment["spec"]["strategy"]["rollingUpdate"] == {
        "maxUnavailable": 1,
        "maxSurge": 1,
    }
    assert args == [
        "operator-loop",
        "--namespace",
        "$(POD_NAMESPACE)",
        "--holder-identity",
        "$(POD_NAME)",
        "--interval-seconds",
        "30.0",
        "--lease-name",
        "wavemind-operator",
        "--lease-duration-seconds",
        "60",
    ]
    assert {item["name"] for item in container["env"]} == {"POD_NAME", "POD_NAMESPACE"}
    assert any(rule["apiGroups"] == [""] and rule["resources"] == ["services"] for rule in role["rules"])
    assert any(rule["apiGroups"] == [""] and rule["resources"] == ["configmaps"] for rule in role["rules"])
    assert any(rule["apiGroups"] == ["apps"] and rule["resources"] == ["statefulsets"] for rule in role["rules"])
    assert any(rule["apiGroups"] == ["batch"] and rule["resources"] == ["cronjobs"] for rule in role["rules"])
    assert any(
        rule["apiGroups"] == ["autoscaling"]
        and rule["resources"] == ["horizontalpodautoscalers"]
        for rule in role["rules"]
    )
    assert any(
        rule["apiGroups"] == ["memory.wavemind.ai"]
        and rule["resources"] == ["wavemindclusters/status"]
        for rule in role["rules"]
    )
    assert any(
        rule["apiGroups"] == ["coordination.k8s.io"]
        and rule["resources"] == ["leases"]
        and {"get", "create", "update"}.issubset(set(rule["verbs"]))
        for rule in role["rules"]
    )
    assert any(
        rule["apiGroups"] == ["policy"]
        and rule["resources"] == ["poddisruptionbudgets"]
        and {"get", "create", "update"}.issubset(set(rule["verbs"]))
        for rule in role["rules"]
    )


def test_operator_bundle_requires_redundant_operator_replicas():
    with pytest.raises(ValueError, match="at least 2"):
        operator_bundle(operator_replicas=1)


def test_kubernetes_resource_path_maps_supported_resources():
    service = {
        "kind": "Service",
        "metadata": {"name": "wm", "namespace": "ns"},
    }
    statefulset = {
        "kind": "StatefulSet",
        "metadata": {"name": "wm", "namespace": "ns"},
    }
    cronjob = {
        "kind": "CronJob",
        "metadata": {"name": "wm-repair", "namespace": "ns"},
    }
    hpa = {
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": "wm", "namespace": "ns"},
    }
    configmap = {
        "kind": "ConfigMap",
        "metadata": {"name": "wm-rebalance-plan", "namespace": "ns"},
    }
    lease = {
        "kind": "Lease",
        "metadata": {"name": "wavemind-operator", "namespace": "ns"},
    }
    pdb = {
        "kind": "PodDisruptionBudget",
        "metadata": {"name": "wm", "namespace": "ns"},
    }

    assert kubernetes_resource_path(service).api_path == "/api/v1/namespaces/ns/services/wm"
    assert kubernetes_resource_path(configmap).api_path == "/api/v1/namespaces/ns/configmaps/wm-rebalance-plan"
    assert kubernetes_resource_path(statefulset).api_path == "/apis/apps/v1/namespaces/ns/statefulsets/wm"
    assert kubernetes_resource_path(cronjob).api_path == "/apis/batch/v1/namespaces/ns/cronjobs/wm-repair"
    assert kubernetes_resource_path(hpa).api_path == "/apis/autoscaling/v2/namespaces/ns/horizontalpodautoscalers/wm"
    assert kubernetes_resource_path(lease).api_path == "/apis/coordination.k8s.io/v1/namespaces/ns/leases/wavemind-operator"
    assert kubernetes_resource_path(pdb).api_path == "/apis/policy/v1/namespaces/ns/poddisruptionbudgets/wm"
    with pytest.raises(ValueError, match="Unsupported"):
        kubernetes_resource_path({"kind": "Secret", "metadata": {"name": "wm"}})


def test_operator_loop_applies_reconciled_resources_once():
    spec = WaveMindClusterSpec(
        name="wm-loop",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=2,
        namespace_count=2,
    )
    client = RecordingKubernetesClient([spec.custom_resource()])

    report = operator_loop(
        namespace="wavemind-system",
        client=client,
        once=True,
    )

    assert report["clusters"] == 1
    assert report["applied_count"] == 5
    assert report["leaderElection"]["acquired"] is True
    assert report["leaderElection"]["backend"] == "kubernetes-lease-etcd"
    assert report["statuses"][0]["ready"] is True
    assert report["statuses"][0]["phase"] == "Ready"
    assert report["statuses"][0]["memoryOsReady"] is True
    assert report["statuses"][0]["memoryOsRedisRequired"] is False
    assert report["statuses"][0]["memoryOsRedisConfigured"] is False
    assert report["statuses"][0]["controlPlaneReady"] is True
    assert len(client.status_patches) == 1
    assert client.status_patches[0]["name"] == "wm-loop"
    assert client.status_patches[0]["status"]["ready"] is True
    assert client.status_patches[0]["status"]["operatorLeader"]["holderIdentity"] == "wavemind-operator"
    assert [resource["kind"] for resource in client.applied] == [
        "Service",
        "Service",
        "StatefulSet",
        "PodDisruptionBudget",
        "CronJob",
    ]


def test_operator_loop_follower_stays_read_only():
    spec = WaveMindClusterSpec(name="wm-follower", namespace="wavemind-system")
    client = RecordingKubernetesClient([spec.custom_resource()], leader=False)

    report = operator_loop(
        namespace="wavemind-system",
        client=client,
        holder_identity="operator-follower",
        once=True,
    )

    assert report["leaderElection"]["acquired"] is False
    assert report["leaderElection"]["currentHolder"] == "operator-other"
    assert report["clusters"] == 0
    assert report["applied_count"] == 0
    assert client.applied == []
    assert client.status_patches == []


def test_kubernetes_lease_create_renew_and_expired_takeover_are_cas_guarded():
    client = LeaseApiClient()
    started = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)

    first = client.acquire_or_renew_operator_lease(
        namespace="wavemind-system",
        lease_name="wavemind-operator",
        holder_identity="operator-a",
        lease_duration_seconds=60,
        now=started,
    )
    blocked = client.acquire_or_renew_operator_lease(
        namespace="wavemind-system",
        lease_name="wavemind-operator",
        holder_identity="operator-b",
        lease_duration_seconds=60,
        now=started + timedelta(seconds=10),
    )
    renewed = client.acquire_or_renew_operator_lease(
        namespace="wavemind-system",
        lease_name="wavemind-operator",
        holder_identity="operator-a",
        lease_duration_seconds=60,
        now=started + timedelta(seconds=20),
    )
    takeover = client.acquire_or_renew_operator_lease(
        namespace="wavemind-system",
        lease_name="wavemind-operator",
        holder_identity="operator-b",
        lease_duration_seconds=60,
        now=started + timedelta(seconds=81),
    )

    assert first.acquired is True
    assert first.resource_version == "1"
    assert blocked.acquired is False
    assert blocked.reason == "lease_held"
    assert renewed.acquired is True
    assert renewed.renewed is True
    assert renewed.resource_version == "2"
    assert takeover.acquired is True
    assert takeover.current_holder == "operator-b"
    assert takeover.lease_transitions == 1
    assert takeover.resource_version == "3"
    assert [method for method, *_ in client.requests].count("POST") == 1
    assert [method for method, *_ in client.requests].count("PUT") == 2


def test_operator_loop_reports_memory_os_redis_blocker_once():
    spec = WaveMindClusterSpec(
        name="wm-loop-os-blocked",
        namespace="wavemind-system",
        replicas=3,
        replication_factor=2,
        namespace_count=2,
        memory_os_enabled=True,
        memory_os_cache_mode="auto",
        memory_os_target_memories=2_000_000,
    )
    client = RecordingKubernetesClient([spec.custom_resource()])

    report = operator_loop(
        namespace="wavemind-system",
        client=client,
        once=True,
    )

    status = report["statuses"][0]
    assert status["ready"] is False
    assert status["phase"] == "Degraded"
    assert status["memoryOsReady"] is False
    assert status["memoryOsRedisRequired"] is True
    assert status["memoryOsRedisConfigured"] is False
    assert status["controlPlaneReady"] is True
    assert len(client.status_patches) == 1
    assert client.status_patches[0]["status"]["memoryOs"]["ready"] is False
    assert any(
        "cache.redisUrl" in action
        for action in client.status_patches[0]["status"]["actions"]
    )


def test_operator_cli_sample_bundle_and_reconcile(tmp_path):
    sample = run_cli(
        "operator-sample",
        "--name",
        "wm-cli",
        "--namespace",
        "wavemind-system",
        "--replicas",
        "3",
        "--replication-factor",
        "2",
        "--namespace-count",
        "2",
        "--autoscaling",
        "--autoscaling-max-replicas",
        "18",
        "--json",
    )
    sample_payload = json.loads(sample.stdout)
    sample_file = tmp_path / "wavemindcluster.json"
    sample_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    reconciled = json.loads(
        run_cli("operator-reconcile", "--file", str(sample_file), "--json").stdout
    )
    bundle = json.loads(
        run_cli("operator-bundle", "--namespace", "wavemind-system", "--json").stdout
    )

    assert sample_payload["kind"] == "WaveMindCluster"
    assert sample_payload["spec"]["controlPlane"]["consensus"]["enabled"] is True
    assert {item["kind"] for item in reconciled["items"]} == {
        "Service",
        "StatefulSet",
        "PodDisruptionBudget",
        "HorizontalPodAutoscaler",
        "CronJob",
    }
    assert sample_payload["spec"]["autoscaling"]["maxReplicas"] == 18
    assert any(item["kind"] == "CustomResourceDefinition" for item in bundle["items"])
    assert "operatorStatus" in reconciled

    memory_os_sample = json.loads(
        run_cli(
            "operator-sample",
            "--name",
            "wm-cli-os",
            "--namespace",
            "wavemind-system",
            "--redis-url",
            "redis://redis.wavemind-system.svc.cluster.local:6379/0",
            "--memory-os",
            "--memory-os-cache-mode",
            "auto",
            "--memory-os-target-memories",
            "2000000",
            "--memory-os-run-on-one-replica",
            "--json",
        ).stdout
    )
    assert memory_os_sample["spec"]["memoryOs"]["enabled"] is True
    assert memory_os_sample["spec"]["memoryOs"]["targetMemories"] == 2_000_000
    assert memory_os_sample["spec"]["memoryOs"]["runOnAllReplicas"] is False

    guarded_sample = json.loads(
        run_cli(
            "operator-sample",
            "--name",
            "wm-cli-guarded",
            "--namespace",
            "wavemind-system",
            "--production-admission",
            "--production-admission-target-memories",
            "100000000",
            "--production-admission-engine",
            "qdrant-sharded-service",
            "--production-admission-root",
            "/evidence",
            "--json",
        ).stdout
    )
    assert guarded_sample["spec"]["productionAdmission"] == {
        "enabled": True,
        "deployment": "production",
        "evidenceRoot": "/evidence",
        "targetMemories": 100_000_000,
        "engine": "qdrant-sharded-service",
    }


def test_operator_cli_status_renders_observed_conditions(tmp_path):
    sample = json.loads(
        run_cli(
            "operator-sample",
            "--name",
            "wm-status-cli",
            "--namespace",
            "wavemind-system",
            "--replicas",
            "3",
            "--replication-factor",
            "3",
            "--namespace-count",
            "4096",
            "--autoscaling",
            "--autoscaling-target-memories",
            "10000000",
            "--json",
        ).stdout
    )
    sample_file = tmp_path / "wavemindcluster-status.json"
    sample_file.write_text(json.dumps(sample), encoding="utf-8")

    status = json.loads(
        run_cli(
            "operator-status",
            "--file",
            str(sample_file),
            "--ready-replicas",
            "2",
            "--current-replicas",
            "3",
            "--degraded-nodes",
            "1",
            "--json",
        ).stdout
    )

    assert status["ready"] is False
    assert status["phase"] == "Degraded"
    assert status["desiredReplicas"] >= 3
    assert status["capacity"]["requiredReplicas"] == status["desiredReplicas"]
    assert any(condition["type"] == "ResourcesReady" for condition in status["conditions"])


def test_operator_reconcile_accepts_powershell_utf16_redirect_files(tmp_path):
    sample = json.loads(
        run_cli(
            "operator-sample",
            "--name",
            "wm-utf16",
            "--namespace",
            "wavemind-system",
            "--namespace-count",
            "1",
            "--json",
        ).stdout
    )
    sample_file = tmp_path / "wavemindcluster-utf16.json"
    sample_file.write_text(json.dumps(sample), encoding="utf-16")

    reconciled = json.loads(
        run_cli("operator-reconcile", "--file", str(sample_file), "--json").stdout
    )

    assert any(item["kind"] == "StatefulSet" for item in reconciled["items"])


def test_operator_cli_out_writes_utf8_json_files(tmp_path):
    sample_file = tmp_path / "sample.json"
    resources_file = tmp_path / "resources.json"

    run_cli(
        "operator-sample",
        "--name",
        "wm-out",
        "--namespace",
        "wavemind-system",
        "--namespace-count",
        "1",
        "--out",
        str(sample_file),
    )
    run_cli(
        "operator-reconcile",
        "--file",
        str(sample_file),
        "--out",
        str(resources_file),
    )

    assert sample_file.read_bytes().startswith(b"{")
    assert resources_file.read_bytes().startswith(b"{")
    assert json.loads(resources_file.read_text(encoding="utf-8"))["kind"] == "List"
