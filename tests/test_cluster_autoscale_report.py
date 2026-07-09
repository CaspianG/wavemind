import json
import subprocess
import sys
from pathlib import Path


def test_cluster_autoscale_report_generates_gate_artifacts(tmp_path):
    output = tmp_path / "cluster_autoscale_results.json"
    markdown_output = tmp_path / "CLUSTER_AUTOSCALE.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/cluster_autoscale_report.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")

    assert payload["schema"] == "wavemind.cluster_autoscale_report.v1"
    assert payload["source_file"] == "benchmarks/scale_readiness_results.json"
    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["passed_check_count"] == payload["summary"]["check_count"]
    assert payload["summary"]["simulated_memories"] == 1_000_000
    assert payload["summary"]["namespace_count"] == 4096
    assert payload["summary"]["planner_node_loss_min_availability"] == 1.0
    assert payload["summary"]["planner_zone_loss_min_availability"] == 1.0
    assert payload["summary"]["autoscaler_status"] == "scale_required"
    assert payload["summary"]["autoscaler_target_memories"] == 10_000_000
    assert payload["summary"]["autoscaler_required_nodes"] >= 50
    assert payload["summary"]["autoscaler_target_within_headroom"] is True
    assert payload["summary"]["operator_status_phase"] == "Ready"
    assert payload["summary"]["operator_status_ready"] is True
    assert payload["summary"]["operator_replicas"] == (
        payload["summary"]["operator_required_replicas"]
    )
    assert payload["summary"]["operator_controller_replicas"] >= 2
    assert payload["summary"]["operator_leader_election"] is True
    assert payload["summary"]["operator_lease_backend"] == "coordination.k8s.io/v1"
    assert payload["summary"]["operator_lease_rbac"] is True
    assert payload["summary"]["operator_cross_node_anti_affinity"] is True
    assert payload["summary"]["operator_memory_os_ready"] is True
    assert payload["summary"]["operator_memory_os_blocks_missing_redis"] is True
    assert payload["summary"]["control_plane_ok"] is True
    assert payload["summary"]["distributed_http_recalled_after_primary_loss"] is True
    assert payload["summary"]["distributed_http_recalled_after_repair"] is True
    assert (
        payload["summary"]["distributed_http_tombstone_suppressed_after_repair"]
        is True
    )
    assert payload["summary"]["distributed_http_concurrent_query_hit_rate"] == 1.0
    assert payload["summary"]["active_active_convergence_rate"] == 1.0
    assert payload["summary"]["active_active_delete_suppression_rate"] == 1.0
    assert payload["summary"]["http_active_active_success_rate"] == 1.0
    assert payload["summary"]["field_crdt_commutative_convergence"] is True
    assert payload["summary"]["field_crdt_tombstone_wins"] is True
    assert payload["summary"]["capacity_target_memories"] == 100_000_000
    assert payload["summary"]["capacity_node_count"] >= 128
    assert payload["summary"]["capacity_zones"] >= 8
    assert payload["summary"]["capacity_replication_factor"] >= 3
    assert payload["summary"]["capacity_valid_plan"] is True
    assert payload["summary"]["capacity_distinct_replica_rate"] == 1.0
    assert payload["summary"]["capacity_zone_spread_rate"] == 1.0
    assert payload["summary"]["capacity_node_loss_min_availability"] == 1.0
    assert payload["summary"]["capacity_zone_loss_min_availability"] == 1.0
    assert payload["summary"]["capacity_recommended_autoscaling_max_replicas"] >= 192
    assert len(payload["checks"]) >= 50
    assert all(check["pass"] for check in payload["checks"])
    assert "not a real 100M vector-query latency benchmark" in payload["claim_boundary"]
    assert "# WaveMind Cluster Autoscale Report" in markdown
    assert "Real 10M/50M/100M production latency" in markdown


def test_checked_in_cluster_autoscale_report_is_machine_readable():
    project_root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (project_root / "benchmarks/cluster_autoscale_results.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = (project_root / "benchmarks/CLUSTER_AUTOSCALE.md").read_text(
        encoding="utf-8"
    )

    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["passed_check_count"] == payload["summary"]["check_count"]
    assert payload["summary"]["operator_status_phase"] == "Ready"
    assert payload["summary"]["capacity_target_memories"] == 100_000_000
    assert payload["summary"]["capacity_valid_plan"] is True
    assert "managed Kubernetes production run" in payload["claim_boundary"]
    assert "Cluster Autoscale Report" in markdown
