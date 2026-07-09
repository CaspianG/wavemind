import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "kubernetes_active_active_region_smoke.py"
)
SPEC = importlib.util.spec_from_file_location(
    "kubernetes_active_active_region_smoke", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _passing_observation():
    return {
        "region_addresses": [
            f"http://region-{letter}.wavemind-regions.svc.cluster.local:8000"
            for letter in "abc"
        ],
        "zone_count": 3,
        "all_regions_use_pvc": True,
        "runner_worker": "wavemind-ci-worker",
        "runner_zone": "zone-a",
        "target_region": "region-b",
        "target_worker": "wavemind-ci-worker2",
        "target_zone": "zone-b",
        "failure_method": "docker-pause-kind-worker",
        "worker_unpaused": True,
        "target_region_ready_after_recovery": True,
        "target_region_pod_uid_preserved": True,
        "seed": {
            "status": "pass",
            "verification": {"convergence_rate": 1.0},
        },
        "outage": {
            "status": "pass",
            "unavailable_regions": ["region-b"],
            "writes": 32,
            "verification": {
                "convergence_rate": 1.0,
                "delete_suppression_rate": 1.0,
            },
        },
        "recovered": {
            "status": "pass",
            "verification": {
                "convergence_rate": 1.0,
                "delete_suppression_rate": 1.0,
            },
            "sync": {
                "final_noop_records_imported": 0,
                "final_noop_tombstones_imported": 0,
                "final_noop_failed_pairs": 0,
            },
        },
    }


def test_active_active_region_smoke_requires_every_region_failure_check(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CaspianG/wavemind")
    payload = MODULE.evaluate_kubernetes_active_active_region_smoke(
        _passing_observation()
    )

    assert payload["status"] == "pass"
    assert payload["summary"]["passed_checks"] == payload["summary"]["check_count"] == 17
    assert payload["environment"] == "kind-multizone-active-active-ci"
    assert "not remote multi-region" in payload["claim_boundary"]
    assert payload["source_ref"] == "abc123"
    assert payload["workflow_run_url"] == "https://github.com/CaspianG/wavemind/actions/runs/999"


def test_active_active_region_smoke_rejects_simulated_or_incomplete_recovery():
    observed = _passing_observation()
    observed["failure_method"] = "set_node_available"
    observed["outage"]["unavailable_regions"] = []
    observed["recovered"]["verification"]["delete_suppression_rate"] = 0.5

    payload = MODULE.evaluate_kubernetes_active_active_region_smoke(observed)
    checks = {check["id"]: check for check in payload["checks"]}

    assert payload["status"] == "fail"
    assert checks["physical_region_worker_pause"]["passed"] is False
    assert checks["failed_region_detected"]["passed"] is False
    assert checks["recovered_delete_suppression"]["passed"] is False


def test_region_resources_pin_persistent_replicated_regions_to_three_zones():
    resources = MODULE.build_region_resources(
        namespace="wavemind-regions",
        image="wavemind:ci-upgrade",
    )
    services = [item for item in resources if item["kind"] == "Service"]
    statefulsets = [item for item in resources if item["kind"] == "StatefulSet"]

    assert len(services) == 3
    assert len(statefulsets) == 3
    assert {item["metadata"]["name"] for item in statefulsets} == {
        "region-a",
        "region-b",
        "region-c",
    }
    assert {
        item["spec"]["template"]["spec"]["nodeSelector"][
            "topology.kubernetes.io/zone"
        ]
        for item in statefulsets
    } == {"zone-a", "zone-b", "zone-c"}
    assert all(item["spec"]["volumeClaimTemplates"] for item in statefulsets)
    for item in statefulsets:
        args = item["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "--replicated-root" in args
        assert args.count("--replica-node") == 3
        assert "--replication-factor" in args


def test_kind_workflow_runs_active_active_region_failure_drill():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "kubernetes-operator-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "kubernetes_active_active_region_smoke.py" in workflow
    assert "kubernetes_active_active_region_smoke_ci_results.json" in workflow
    assert "--namespace wavemind-regions" in workflow
    assert "--image wavemind:ci-upgrade" in workflow
