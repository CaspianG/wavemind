import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "kubernetes_operator_smoke.py"
SPEC = importlib.util.spec_from_file_location("kubernetes_operator_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_kubernetes_operator_smoke_requires_every_failure_drill_check():
    payload = MODULE.evaluate_kubernetes_operator_smoke(
        {
            "node_count": 4,
            "operator_pod_count": 2,
            "operator_node_count": 2,
            "initial_holder": "operator-a",
            "next_holder": "operator-b",
            "lease_transitions_before": 0,
            "lease_transitions_after": 1,
            "desired_replicas_after_scale": 4,
            "ready_replicas_after_scale": 4,
            "cluster_status_holder": "operator-b",
            "data_pod_uid_changed": True,
            "api_healthy_after_recovery": True,
        }
    )

    assert payload["status"] == "pass"
    assert payload["summary"]["passed_checks"] == payload["summary"]["check_count"] == 9
    assert payload["environment"] == "kind-multinode-ci"
    assert "does not unlock remote production" in payload["claim_boundary"]


def test_kubernetes_operator_smoke_fails_without_lease_takeover():
    payload = MODULE.evaluate_kubernetes_operator_smoke(
        {
            "node_count": 4,
            "operator_pod_count": 2,
            "operator_node_count": 2,
            "initial_holder": "operator-a",
            "next_holder": "operator-a",
            "lease_transitions_before": 0,
            "lease_transitions_after": 0,
            "desired_replicas_after_scale": 4,
            "ready_replicas_after_scale": 4,
            "cluster_status_holder": "operator-a",
            "data_pod_uid_changed": True,
            "api_healthy_after_recovery": True,
        }
    )

    checks = {check["id"]: check for check in payload["checks"]}
    assert payload["status"] == "fail"
    assert checks["leader_failover"]["passed"] is False
    assert checks["lease_transition_recorded"]["passed"] is False


def test_kubernetes_operator_smoke_workflow_runs_real_kind_failure_drill():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "kubernetes-operator-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "kind create cluster" in workflow
    assert "KIND_SHA256: eb244cbafcc157dff60cf68693c14c9a75c4e6e6fedaf9cd71c58117cb93e3fa" in workflow
    assert "github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}" in workflow
    assert "kindest/node:v1.35.0@sha256:" in workflow
    assert "--operator-replicas 2" in workflow
    assert "--operator-interval-seconds 5" in workflow
    assert "--lease-duration-seconds 15" in workflow
    assert "kubernetes_operator_smoke.py" in workflow
    assert "kubernetes_operator_smoke_ci_results.json" in workflow
