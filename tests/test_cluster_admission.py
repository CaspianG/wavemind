import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence import (
    evaluate_cluster_admission,
    render_cluster_admission_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _remote_cluster_env() -> dict[str, str]:
    return {
        "WAVEMIND_CLUSTER_NODES": ",".join(
            [
                "node-a=https://wm-a.staging.internal",
                "node-b=https://wm-b.staging.internal",
                "node-c=https://wm-c.staging.internal",
                "node-d=https://wm-d.staging.internal",
            ]
        ),
        "WAVEMIND_API_KEY": "test-key",
    }


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "WAVEMIND_CLUSTER_NODES",
        "WAVEMIND_CLUSTER_NODES_MANIFEST_JSON",
    ):
        env.pop(key, None)
    return env


def _write_remote_cluster_artifact(
    root: Path,
    *,
    nodes: int = 4,
    namespaces: int = 32,
    memories_per_namespace: int = 8,
    replication_factor: int = 3,
    read_quorum: int = 1,
    read_fanout: int = 1,
    batch_query_size: int = 24,
    p99_ms: float = 500.0,
) -> Path:
    artifact = root / "benchmarks" / "http_cluster_load_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": {
            "name": "http_cluster_load",
            "node_count": nodes,
            "node_ids": [
                f"node-{chr(ord('a') + index)}" for index in range(nodes)
            ],
            "node_addresses": [
                f"https://wm-{chr(ord('a') + index)}.staging.internal"
                for index in range(nodes)
            ],
            "zones": ["zone-a", "zone-b", "zone-c"],
            "replication_factor": replication_factor,
            "write_quorum": 2,
            "read_quorum": read_quorum,
            "read_fanout": read_fanout,
            "namespace_prefix": "tenant:remote-cluster",
            "namespace_count": namespaces,
            "memories_per_namespace": memories_per_namespace,
            "workers": 8,
            "batch_query_size": batch_query_size,
            "deployment_id": "staging-cluster-001",
            "environment": "staging",
            "source": "github-actions-external-http-cluster-load",
            "source_ref": "a" * 40,
            "workflow_run_id": "123456789",
            "workflow_run_url": (
                "https://github.com/CaspianG/wavemind/actions/runs/123456789"
            ),
            "description": "External HTTP cluster-load runner executed against remote staging WaveMind API processes.",
        },
        "results": [
            {
                "engine": "WaveMind external HTTP cluster load",
                "nodes": nodes,
                "namespaces": namespaces,
                "memories_per_namespace": memories_per_namespace,
                "replication_factor": replication_factor,
                "write_quorum": 2,
                "read_quorum": read_quorum,
                "read_fanout": read_fanout,
                "workers": 8,
                "writes": namespaces * memories_per_namespace,
                "queries": namespaces * memories_per_namespace,
                "failover_queries": namespaces * memories_per_namespace,
                "forgets": namespaces,
                "failed_node": "node-b",
                "write_success_rate": 1.0,
                "query_hit_rate": 1.0,
                "failover_hit_rate": 1.0,
                "forget_success_rate": 1.0,
                "delete_suppression_rate": 1.0,
                "repair_missing_before": True,
                "repair_ok": True,
                "repair_repaired_total": 1,
                "repaired_replica": True,
                "success_rate": 1.0,
                "total_checks": 836,
                "errors": [],
                "error_count": 0,
                "avg_operation_ms": 120.0,
                "p95_operation_ms": 350.0,
                "p99_operation_ms": p99_ms,
                "batch_query": {
                    "namespace": "tenant:remote-cluster:batch-query",
                    "write_node_count": nodes,
                    "individual_node": "node-a",
                    "batch_node": "node-b",
                    "batch_size": batch_query_size,
                    "individual_http_requests": batch_query_size,
                    "batch_http_requests": 1,
                    "request_reduction_ratio": 1.0 - (1.0 / batch_query_size),
                    "individual_success": True,
                    "batch_success": True,
                    "success": True,
                    "individual_p99_ms": 30.0,
                    "batch_p99_ms": min(p99_ms, 450.0),
                },
                "slo_min_success_rate": 1.0,
                "slo_min_failover_hit_rate": 0.95,
                "slo_p99_ms": 1000.0,
                "slo_pass": True,
            }
        ],
    }
    artifact.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return artifact


def test_cluster_admission_blocks_without_a_matching_target_configuration():
    payload = evaluate_cluster_admission(
        PROJECT_ROOT,
        allow_plan_only=False,
        env={},
    )

    assert payload["schema"] == "wavemind.cluster_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "external_http_cluster_evidence_required"
    assert payload["required_evidence"]["id"] == "external_http_cluster"
    assert payload["required_evidence"]["status"] == "pass"
    assert payload["required_evidence"]["artifact"] == (
        "benchmarks/http_cluster_load_results.json"
    )
    assert payload["requested_evidence"]["status"] == "pass"
    assert "WAVEMIND_CLUSTER_NODES" in payload["summary"]["missing_env"]
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["target_urls_match"] is False
    assert any("preflight is not ready" in item for item in payload["issues"])
    assert any("do not match" in item for item in payload["issues"])


def test_cluster_admission_admits_matching_remote_cluster_evidence(tmp_path):
    _write_remote_cluster_artifact(tmp_path)

    payload = evaluate_cluster_admission(
        tmp_path,
        min_nodes=4,
        namespace_count=32,
        memories_per_namespace=8,
        replication_factor=3,
        read_quorum=1,
        read_fanout=1,
        batch_query_size=24,
        p99_slo_ms=1000.0,
        env=_remote_cluster_env(),
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["requested_evidence"]["status"] == "pass"
    assert payload["requested_evidence"]["min_nodes"] == 4
    assert payload["requested_evidence"]["namespace_count"] == 32
    assert payload["requested_evidence"]["replication_factor"] == 3
    assert payload["requested_evidence"]["batch_query_size"] == 24
    assert payload["issues"] == []


def test_cluster_admission_blocks_when_artifact_is_too_small_for_rollout(tmp_path):
    _write_remote_cluster_artifact(tmp_path, nodes=4, namespaces=32, p99_ms=800.0)

    payload = evaluate_cluster_admission(
        tmp_path,
        min_nodes=8,
        namespace_count=64,
        p99_slo_ms=500.0,
        allow_plan_only=False,
        env=_remote_cluster_env(),
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "fail"
    assert payload["requested_evidence"]["status"] == "fail"
    assert "node_count must be >= 8" in payload["requested_evidence"]["issues"]
    assert "namespace_count must be >= 64" in payload["requested_evidence"]["issues"]
    assert "query_p99_ms above SLO" in payload["requested_evidence"]["issues"]


def test_cluster_admission_blocks_evidence_from_a_different_target(tmp_path):
    _write_remote_cluster_artifact(tmp_path)
    environment = _remote_cluster_env()
    environment["WAVEMIND_CLUSTER_NODES"] = environment[
        "WAVEMIND_CLUSTER_NODES"
    ].replace("wm-d.staging.internal", "wm-other.staging.internal")

    payload = evaluate_cluster_admission(tmp_path, env=environment)

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["summary"]["preflight_status"] == "ready"
    assert payload["summary"]["target_urls_match"] is False
    assert any("do not match" in issue for issue in payload["issues"])


def test_cluster_admission_allows_plan_only_reporting():
    payload = evaluate_cluster_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["strict_status"] == "pass"
    assert payload["summary"]["preflight_status"] == "action_required"
    assert payload["next_actions"]


def test_cluster_admission_markdown_documents_claim_boundary():
    payload = evaluate_cluster_admission(
        PROJECT_ROOT,
        allow_plan_only=True,
        env={},
    )
    markdown = render_cluster_admission_markdown(payload)

    assert "# WaveMind Cluster Admission" in markdown
    assert "non-loopback Kubernetes or external" in markdown
    assert "exact requested node" in markdown
    assert "benchmarks/http_cluster_load_results.json" in markdown
    assert "Local loopback" in markdown
    assert "Requested Evidence" in markdown


def test_cluster_admission_cli_writes_artifacts(tmp_path):
    output = tmp_path / "cluster.json"
    markdown_output = tmp_path / "cluster.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "cluster-admission",
            "--root",
            str(PROJECT_ROOT),
            "--allow-plan-only",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "plan_only"
    assert file_payload["schema"] == "wavemind.cluster_admission.v1"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Cluster Admission"
    )


def test_cluster_admission_cli_fail_on_blocked_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "cluster-admission",
            "--root",
            str(PROJECT_ROOT),
            "--fail-on-blocked",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_clean_env(),
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
