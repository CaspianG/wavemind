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

    def list_wavemind_clusters(self, namespace):
        assert namespace == "wavemind-system"
        return self.clusters

    def apply(self, resource):
        self.applied.append(resource)
        return resource


def test_custom_resource_definition_declares_namespaced_wavemindcluster():
    crd = custom_resource_definition()

    assert crd["kind"] == "CustomResourceDefinition"
    assert crd["metadata"]["name"] == "wavemindclusters.memory.wavemind.ai"
    assert crd["spec"]["scope"] == "Namespaced"
    assert crd["spec"]["names"]["kind"] == "WaveMindCluster"


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

    assert kubernetes_resource_path(service).api_path == "/api/v1/namespaces/ns/services/wm"
    assert kubernetes_resource_path(statefulset).api_path == "/apis/apps/v1/namespaces/ns/statefulsets/wm"
    assert kubernetes_resource_path(cronjob).api_path == "/apis/batch/v1/namespaces/ns/cronjobs/wm-repair"
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
        "CronJob",
    }
    assert any(item["kind"] == "CustomResourceDefinition" for item in bundle["items"])


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
