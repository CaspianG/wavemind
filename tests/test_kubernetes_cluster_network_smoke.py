import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "kubernetes_cluster_network_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("kubernetes_cluster_network_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _passing_observation():
    addresses = [
        f"http://wavemind-ci-{index}.wavemind-ci-headless."
        "wavemind-system.svc.cluster.local:8000"
        for index in range(4)
    ]
    return {
        "service_addresses": addresses,
        "zone_count": 3,
        "runner_worker": "wavemind-ci-worker2",
        "runner_zone": "zone-b",
        "target_worker": "wavemind-ci-worker",
        "target_zone": "zone-a",
        "target_data_pods": ["wavemind-ci-0"],
        "failure_method": "docker-pause-kind-worker",
        "worker_unpaused": True,
        "node_ready_after_recovery": True,
        "pod_uids_preserved": True,
        "seed": {
            "status": "pass",
            "written_memories": 256,
            "expected_memories": 256,
        },
        "outage": {
            "status": "pass",
            "hit_rate": 1.0,
            "failed_nodes_seen": ["wavemind-ci-0"],
        },
        "recovered": {
            "status": "pass",
            "hit_rate": 1.0,
            "failed_nodes_seen": [],
        },
    }


def test_network_smoke_requires_physical_non_loopback_failure(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CaspianG/wavemind")
    payload = MODULE.evaluate_kubernetes_cluster_network_smoke(_passing_observation())

    assert payload["status"] == "pass"
    assert payload["summary"]["passed_checks"] == payload["summary"]["check_count"] == 13
    assert payload["environment"] == "kind-multinode-network-ci"
    assert "not remote multi-region" in payload["claim_boundary"]
    assert payload["source_ref"] == "abc123"
    assert payload["workflow_run_url"] == "https://github.com/CaspianG/wavemind/actions/runs/789"


def test_network_smoke_rejects_loopback_or_simulated_failure():
    observed = _passing_observation()
    observed["service_addresses"][0] = "http://127.0.0.1:8000"
    observed["failure_method"] = "set_node_available"
    observed["outage"]["failed_nodes_seen"] = []

    payload = MODULE.evaluate_kubernetes_cluster_network_smoke(observed)
    checks = {check["id"]: check for check in payload["checks"]}

    assert payload["status"] == "fail"
    assert checks["non_loopback_pod_dns"]["passed"] is False
    assert checks["physical_worker_pause"]["passed"] is False
    assert checks["network_failure_observed"]["passed"] is False


def test_kind_workflow_runs_network_drill_across_labeled_zones():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "kubernetes-operator-smoke.yml").read_text(
        encoding="utf-8"
    )
    kind_config = (root / "deploy" / "kind" / "operator-smoke.yaml").read_text(
        encoding="utf-8"
    )

    assert "kubernetes_cluster_network_smoke.py" in workflow
    assert "kubernetes_cluster_network_smoke_ci_results.json" in workflow
    assert "docker ps -a" in workflow
    assert "topology.kubernetes.io/zone: zone-a" in kind_config
    assert "topology.kubernetes.io/zone: zone-b" in kind_config
    assert "topology.kubernetes.io/zone: zone-c" in kind_config
