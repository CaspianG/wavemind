import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import (
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
    def __init__(self, clusters):
        self.clusters = clusters
        self.applied = []
        self.status_patches = []

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


def test_custom_resource_definition_declares_namespaced_wavemindcluster():
    crd = custom_resource_definition()

    assert crd["kind"] == "CustomResourceDefinition"
    assert crd["metadata"]["name"] == "wavemindclusters.memory.wavemind.ai"
    assert crd["spec"]["scope"] == "Namespaced"
    assert crd["spec"]["names"]["kind"] == "WaveMindCluster"
    spec_props = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    assert "autoscaling" in spec_props
    status_props = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["status"]
    assert crd["spec"]["versions"][0]["subresources"] == {"status": {}}
    assert status_props["x-kubernetes-preserve-unknown-fields"] is True
    assert "maxReplicas" in spec_props["autoscaling"]["properties"]
    assert "targetMemories" in spec_props["autoscaling"]["properties"]
    assert "maxMemoriesPerNode" in spec_props["autoscaling"]["properties"]
    assert "headroom" in spec_props["autoscaling"]["properties"]


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
    container = resources["StatefulSet"]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/caspiang/wavemind:2.4.3"
    assert {"name": "WAVEMIND_REPLICATION_FACTOR", "value": "2"} in container["env"]
    assert resources["CronJob"]["metadata"]["name"] == "wm-prod-cluster-repair"
    repair_args = resources["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert repair_args.count("--namespace") == 4
    assert "wm-prod-0=http://wm-prod-0.wm-prod-headless.wavemind-system.svc.cluster.local:8000" in repair_args


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
    annotations = statefulset["metadata"]["annotations"]

    assert statefulset["spec"]["replicas"] >= 43
    assert hpa["spec"]["minReplicas"] == statefulset["spec"]["replicas"]
    assert hpa["spec"]["maxReplicas"] >= statefulset["spec"]["replicas"]
    assert annotations["memory.wavemind.ai/capacity-target-memories"] == "10000000"
    assert int(annotations["memory.wavemind.ai/capacity-required-replicas"]) == statefulset["spec"]["replicas"]
    assert int(annotations["memory.wavemind.ai/capacity-target-max-node-memories"]) <= 700_000
    assert payload["operatorStatus"]["ready"] is True
    assert payload["operatorStatus"]["capacity"]["requiredReplicas"] == statefulset["spec"]["replicas"]
    assert payload["operatorStatus"]["capacity"]["withinHeadroom"] is True
    assert {
        condition["type"] for condition in payload["operatorStatus"]["conditions"]
    } == {
        "ResourcesReady",
        "CapacityPlanned",
        "AutoscalingReady",
        "RepairScheduled",
    }


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
    assert conditions["RepairScheduled"]["status"] == "False"
    assert any("Run cluster-health" in action for action in status["actions"])
    assert any("Enable scheduled cluster repair" in action for action in status["actions"])


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
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args == ["operator-loop", "--namespace", "wavemind-system"]
    assert any(rule["apiGroups"] == [""] and rule["resources"] == ["services"] for rule in role["rules"])
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

    assert kubernetes_resource_path(service).api_path == "/api/v1/namespaces/ns/services/wm"
    assert kubernetes_resource_path(statefulset).api_path == "/apis/apps/v1/namespaces/ns/statefulsets/wm"
    assert kubernetes_resource_path(cronjob).api_path == "/apis/batch/v1/namespaces/ns/cronjobs/wm-repair"
    assert kubernetes_resource_path(hpa).api_path == "/apis/autoscaling/v2/namespaces/ns/horizontalpodautoscalers/wm"
    with pytest.raises(ValueError, match="Unsupported"):
        kubernetes_resource_path({"kind": "ConfigMap", "metadata": {"name": "wm"}})


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
    assert report["applied_count"] == 4
    assert report["statuses"][0]["ready"] is True
    assert report["statuses"][0]["phase"] == "Ready"
    assert len(client.status_patches) == 1
    assert client.status_patches[0]["name"] == "wm-loop"
    assert client.status_patches[0]["status"]["ready"] is True
    assert [resource["kind"] for resource in client.applied] == [
        "Service",
        "Service",
        "StatefulSet",
        "CronJob",
    ]


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
    assert {item["kind"] for item in reconciled["items"]} == {
        "Service",
        "StatefulSet",
        "HorizontalPodAutoscaler",
        "CronJob",
    }
    assert sample_payload["spec"]["autoscaling"]["maxReplicas"] == 18
    assert any(item["kind"] == "CustomResourceDefinition" for item in bundle["items"])
    assert "operatorStatus" in reconciled


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
