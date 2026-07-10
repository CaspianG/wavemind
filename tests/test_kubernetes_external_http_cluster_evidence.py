import json
from pathlib import Path

from benchmarks.kubernetes_external_http_cluster_evidence import (
    canonical_payload_sha256,
    evaluate_kubernetes_external_http_cluster_evidence,
)
from wavemind.production_evidence import (
    _validate_external_cluster_payload,
    evaluate_production_evidence,
)
from wavemind.production_evidence_ingest import ingest_production_evidence_artifacts


SOURCE_REF = "a" * 40
WORKFLOW_RUN_ID = "123456789"


def _placement():
    zones = ("zone-a", "zone-b", "zone-c", "zone-a")
    workers = ("worker-a", "worker-b", "worker-c", "worker-a")
    return [
        {
            "id": f"wavemind-ci-{index}",
            "address": (
                f"http://wavemind-ci-{index}.wavemind-ci-headless."
                "wavemind-system.svc.cluster.local:8000"
            ),
            "zone": zones[index],
            "worker": workers[index],
            "uid": f"pod-uid-{index}",
        }
        for index in range(4)
    ]


def _network_payload():
    placement = _placement()
    return {
        "schema": "wavemind.kubernetes_cluster_network_smoke.v1",
        "status": "pass",
        "environment": "kind-multinode-network-ci",
        "evidence_source": "github-actions-kind-physical-node-pause",
        "source_ref": SOURCE_REF,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "workflow_run_url": (
            "https://github.com/CaspianG/wavemind/actions/runs/"
            f"{WORKFLOW_RUN_ID}"
        ),
        "checks": [
            {"id": f"network-check-{index}", "passed": True}
            for index in range(13)
        ],
        "observed": {
            "service_addresses": [item["address"] for item in placement],
            "zone_count": 3,
            "pod_placement": placement,
            "runner_pod": "wavemind-ci-1",
            "runner_worker": "worker-b",
            "runner_zone": "zone-b",
            "target_worker": "worker-c",
            "target_zone": "zone-c",
            "target_data_pods": ["wavemind-ci-2"],
            "failure_method": "docker-pause-kind-worker",
            "outage_duration_ms": 9500.0,
            "worker_unpaused": True,
            "node_ready_after_recovery": True,
            "pod_uids_preserved": True,
            "outage": {
                "status": "pass",
                "hit_rate": 1.0,
                "failed_nodes_seen": ["wavemind-ci-2"],
            },
            "recovered": {
                "status": "pass",
                "hit_rate": 1.0,
                "failed_nodes_seen": [],
            },
        },
    }


def _load_payload():
    placement = _placement()
    return {
        "scenario": {
            "name": "http_cluster_load",
            "node_count": 4,
            "node_ids": [item["id"] for item in placement],
            "node_addresses": [item["address"] for item in placement],
            "zones": ["zone-a", "zone-b", "zone-c"],
            "replication_factor": 3,
            "write_quorum": 2,
            "read_quorum": 1,
            "read_fanout": 1,
            "namespace_count": 32,
            "memories_per_namespace": 8,
            "batch_query_size": 24,
            "deployment_id": "github-actions-123456789-wavemind-ci",
            "environment": "kubernetes-kind-non-loopback-ci",
            "source": "kubernetes-pod-dns-physical-node-drill",
        },
        "results": [
            {
                "engine": "WaveMind external HTTP cluster load",
                "replication_factor": 3,
                "read_quorum": 1,
                "read_fanout": 1,
                "success_rate": 1.0,
                "write_success_rate": 1.0,
                "query_hit_rate": 1.0,
                "failover_hit_rate": 1.0,
                "delete_suppression_rate": 1.0,
                "repair_ok": True,
                "repair_repaired_total": 1,
                "p99_operation_ms": 120.0,
                "slo_pass": True,
                "batch_query": {
                    "success": True,
                    "individual_success": True,
                    "batch_success": True,
                    "batch_size": 24,
                    "individual_http_requests": 24,
                    "batch_http_requests": 1,
                    "request_reduction_ratio": 23 / 24,
                    "batch_p99_ms": 80.0,
                },
            }
        ],
    }


def _current_pods():
    return [
        {
            "id": item["id"],
            "uid": item["uid"],
            "worker": item["worker"],
            "ready": True,
        }
        for item in _placement()
    ]


def test_composed_kubernetes_evidence_passes_strict_validator():
    network = _network_payload()
    payload = evaluate_kubernetes_external_http_cluster_evidence(
        _load_payload(),
        network,
        current_pods=_current_pods(),
    )

    attestation = payload["scenario"]["kubernetes_attestation"]
    assert attestation["status"] == "pass"
    assert attestation["summary"]["passed_checks"] == 10
    assert attestation["network_evidence_sha256"] == canonical_payload_sha256(
        network
    )
    assert payload["results"][0]["physical_failure_slo_pass"] is True

    validation = _validate_external_cluster_payload(
        payload,
        require_remote=True,
        network_evidence_payload=network,
    )
    assert validation["status"] == "pass"
    assert validation["issues"] == []


def test_strict_validator_rejects_changed_linked_network_artifact():
    network = _network_payload()
    payload = evaluate_kubernetes_external_http_cluster_evidence(
        _load_payload(),
        network,
        current_pods=_current_pods(),
    )
    network["observed"]["outage"]["hit_rate"] = 0.5

    validation = _validate_external_cluster_payload(
        payload,
        require_remote=True,
        network_evidence_payload=network,
    )

    assert validation["status"] == "fail"
    assert any("SHA-256" in issue for issue in validation["issues"])
    assert any("100% recall during the outage" in issue for issue in validation["issues"])


def test_strict_gate_and_ingest_accept_linked_kubernetes_artifacts(tmp_path):
    network = _network_payload()
    payload = evaluate_kubernetes_external_http_cluster_evidence(
        _load_payload(),
        network,
        current_pods=_current_pods(),
    )
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "http_cluster_load_results.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    (artifact_dir / "kubernetes_cluster_network_smoke_results.json").write_text(
        json.dumps(network),
        encoding="utf-8",
    )

    manifest = ingest_production_evidence_artifacts(
        artifact_dir,
        output_root=tmp_path / "checkout",
    )
    strict = evaluate_production_evidence(tmp_path / "checkout")
    requirement = {
        item["id"]: item for item in strict["requirements"]
    }["external_http_cluster"]

    assert manifest["ingested"][0]["dependencies"] == [
        "kubernetes_cluster_network_smoke_results.json"
    ]
    assert (
        tmp_path
        / "checkout"
        / "benchmarks"
        / "kubernetes_cluster_network_smoke_results.json"
    ).exists()
    assert requirement["status"] == "pass"


def test_composition_rejects_different_load_and_failure_nodes():
    load = _load_payload()
    load["scenario"]["node_addresses"][0] = "http://different.svc.cluster.local:8000"

    payload = evaluate_kubernetes_external_http_cluster_evidence(
        load,
        _network_payload(),
        current_pods=_current_pods(),
    )
    checks = {
        item["id"]: item
        for item in payload["scenario"]["kubernetes_attestation"]["checks"]
    }

    assert payload["scenario"]["kubernetes_attestation"]["status"] == "fail"
    assert checks["same_service_nodes"]["passed"] is False


def test_kind_workflow_generates_strict_cluster_evidence_and_admission():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "kubernetes-operator-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "kubernetes_external_http_cluster_evidence.py" in workflow
    assert "benchmarks/http_cluster_load_results.json" in workflow
    assert "kubernetes_cluster_admission_ci_results.json" in workflow
    assert "--fail-on-blocked" in workflow
