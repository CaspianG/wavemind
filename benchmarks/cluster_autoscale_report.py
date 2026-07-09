from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = "benchmarks/scale_readiness_results.json"

EXPECTED_OPERATOR_CONDITIONS = {
    "AutoscalingReady",
    "CapacityPlanned",
    "ControlPlaneReady",
    "MemoryOSReady",
    "RebalancePlanned",
    "RepairScheduled",
    "ResourcesReady",
}


def build_cluster_autoscale_report(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    source = _load_json(root / SOURCE_FILE)
    rows = {
        "planner": _engine_row(source, "WaveMind cluster planner"),
        "autoscaler": _engine_row(source, "WaveMind cluster autoscaler"),
        "control_plane": _engine_row(source, "WaveMind control-plane consensus"),
        "operator": _engine_row(source, "WaveMind Kubernetes operator"),
        "distributed_http": _engine_row(source, "WaveMind distributed HTTP sharding"),
        "active_active": _engine_row(source, "WaveMind sustained active-active sync"),
        "http_active_active": _engine_row(
            source, "WaveMind HTTP active-active service-region sync"
        ),
        "field_crdt": _engine_row(source, "WaveMind field-state CRDT"),
        "capacity_100m": _engine_row(source, "WaveMind 100M capacity envelope"),
    }
    checks = _checks(rows)
    passed = sum(1 for check in checks if check["pass"])
    summary = {
        "status": "pass" if checks and passed == len(checks) else "watch",
        "check_count": len(checks),
        "passed_check_count": passed,
        "source_generated_at": source.get("generated_at"),
        "simulated_memories": (source.get("scenario") or {}).get("simulated_memories"),
        "namespace_count": (source.get("scenario") or {}).get("namespace_count"),
        "planner_node_count": rows["planner"].get("nodes"),
        "planner_replication_factor": rows["planner"].get("replication_factor"),
        "planner_node_loss_min_availability": rows["planner"].get(
            "node_loss_min_availability"
        ),
        "planner_zone_loss_min_availability": rows["planner"].get(
            "zone_loss_min_availability"
        ),
        "autoscaler_status": rows["autoscaler"].get("status"),
        "autoscaler_target_memories": rows["autoscaler"].get("target_memories"),
        "autoscaler_required_nodes": rows["autoscaler"].get("required_nodes"),
        "autoscaler_additional_nodes": rows["autoscaler"].get("additional_nodes"),
        "autoscaler_target_within_headroom": rows["autoscaler"].get(
            "target_within_headroom"
        ),
        "autoscaler_rebalance_batches": rows["autoscaler"].get("rebalance_batches"),
        "autoscaler_rebalance_move_count": rows["autoscaler"].get(
            "rebalance_move_count"
        ),
        "operator_status_phase": rows["operator"].get("status_phase"),
        "operator_status_ready": rows["operator"].get("status_ready"),
        "operator_replicas": rows["operator"].get("statefulset_replicas"),
        "operator_controller_replicas": rows["operator"].get("operator_replicas"),
        "operator_leader_election": rows["operator"].get("operator_leader_election"),
        "operator_lease_backend": rows["operator"].get("operator_lease_backend"),
        "operator_lease_rbac": rows["operator"].get("operator_lease_rbac"),
        "operator_cross_node_anti_affinity": rows["operator"].get(
            "operator_cross_node_anti_affinity"
        ),
        "operator_required_replicas": rows["operator"].get("capacity_required_replicas"),
        "operator_rebalance_batches": rows["operator"].get("rebalance_batches"),
        "operator_rebalance_move_count": rows["operator"].get("rebalance_move_count"),
        "operator_conditions_true": rows["operator"].get("status_conditions_true", []),
        "operator_memory_os_ready": rows["operator"].get("status_memory_os_ready"),
        "operator_memory_os_blocks_missing_redis": rows["operator"].get(
            "memory_os_blocks_missing_redis"
        ),
        "control_plane_ok": rows["control_plane"].get("ok"),
        "control_plane_voters_after_membership": rows["control_plane"].get(
            "voters_after_membership"
        ),
        "distributed_http_recalled_after_primary_loss": rows["distributed_http"].get(
            "recalled_after_primary_loss"
        ),
        "distributed_http_recalled_after_repair": rows["distributed_http"].get(
            "recalled_after_repair"
        ),
        "distributed_http_tombstone_suppressed_after_repair": rows[
            "distributed_http"
        ].get("tombstone_suppressed_after_repair"),
        "distributed_http_concurrent_query_hit_rate": rows["distributed_http"].get(
            "concurrent_query_hit_rate"
        ),
        "active_active_convergence_rate": rows["active_active"].get("convergence_rate"),
        "active_active_delete_suppression_rate": rows["active_active"].get(
            "delete_suppression_rate"
        ),
        "http_active_active_success_rate": rows["http_active_active"].get(
            "success_rate"
        ),
        "field_crdt_commutative_convergence": rows["field_crdt"].get(
            "commutative_convergence"
        ),
        "field_crdt_tombstone_wins": rows["field_crdt"].get("tombstone_wins"),
        "capacity_target_memories": rows["capacity_100m"].get("target_memories"),
        "capacity_node_count": rows["capacity_100m"].get("node_count"),
        "capacity_zones": rows["capacity_100m"].get("zones"),
        "capacity_replication_factor": rows["capacity_100m"].get("replication_factor"),
        "capacity_valid_plan": rows["capacity_100m"].get("valid_capacity_plan"),
        "capacity_distinct_replica_rate": rows["capacity_100m"].get(
            "distinct_replica_rate"
        ),
        "capacity_zone_spread_rate": rows["capacity_100m"].get("zone_spread_rate"),
        "capacity_node_loss_min_availability": rows["capacity_100m"].get(
            "node_loss_min_availability"
        ),
        "capacity_zone_loss_min_availability": rows["capacity_100m"].get(
            "zone_loss_min_availability"
        ),
        "capacity_recommended_autoscaling_max_replicas": rows["capacity_100m"].get(
            "recommended_autoscaling_max_replicas"
        ),
        "capacity_scope": rows["capacity_100m"].get("scope"),
    }
    return {
        "schema": "wavemind.cluster_autoscale_report.v1",
        "generated_at": _generated_at(root),
        "source_ref": _source_ref(root),
        "source_file": SOURCE_FILE,
        "claim_boundary": (
            "Cluster autoscale evidence is extracted from the checked-in "
            "scale-readiness artifact. It proves deterministic shard placement, "
            "failure-domain availability, autoscale planning, rebalance planning, "
            "operator reconciliation, quorum safety, active-active convergence, "
            "field-state CRDT behavior, and the 100M capacity envelope on these "
            "fixtures. It is not a real 100M vector-query latency benchmark, "
            "managed Kubernetes production run, or independent multi-region SLO."
        ),
        "summary": summary,
        "checks": checks,
        "raw_metrics": rows,
    }


def render_cluster_autoscale_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    checks = payload.get("checks", [])
    return "\n".join(
        [
            "# WaveMind Cluster Autoscale Report",
            "",
            f"Generated: `{payload.get('generated_at', 'unknown')}`.",
            "",
            str(payload.get("claim_boundary", "")),
            "",
            "## Summary",
            "",
            f"- Status: `{summary.get('status', 'missing')}`.",
            f"- Checks: `{summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)}`.",
            f"- Simulated memories: `{summary.get('simulated_memories', 0)}`.",
            f"- Namespaces: `{summary.get('namespace_count', 0)}`.",
            f"- Autoscaler target: `{summary.get('autoscaler_target_memories', 0)}` memories.",
            f"- Autoscaler required nodes: `{summary.get('autoscaler_required_nodes', 0)}`.",
            f"- Operator replicas: `{summary.get('operator_replicas', 0)}`.",
            f"- Operator controller replicas: `{summary.get('operator_controller_replicas', 0)}`.",
            f"- Operator leader election: `{summary.get('operator_leader_election')}` via `{summary.get('operator_lease_backend', 'missing')}`.",
            f"- Rebalance moves: `{summary.get('operator_rebalance_move_count', 0)}`.",
            f"- 100M capacity nodes: `{summary.get('capacity_node_count', 0)}`.",
            f"- 100M capacity zones: `{summary.get('capacity_zones', 0)}`.",
            f"- 100M recommended max replicas: `{summary.get('capacity_recommended_autoscaling_max_replicas', 0)}`.",
            "",
            "## Gate Checks",
            "",
            "| check | status | value | target |",
            "|---|---|---:|---:|",
            *[_check_row(check) for check in checks],
            "",
            "## Coverage",
            "",
            "| area | evidence |",
            "|---|---|",
            (
                "| Placement | "
                f"`{summary.get('planner_node_count', 0)}` nodes, "
                f"replication `{summary.get('planner_replication_factor', 0)}`, "
                f"node-loss availability `{_fmt(summary.get('planner_node_loss_min_availability'))}`, "
                f"zone-loss availability `{_fmt(summary.get('planner_zone_loss_min_availability'))}`. |"
            ),
            (
                "| Autoscale | "
                f"status `{summary.get('autoscaler_status', 'missing')}`, "
                f"required nodes `{summary.get('autoscaler_required_nodes', 0)}`, "
                f"additional nodes `{summary.get('autoscaler_additional_nodes', 0)}`, "
                f"headroom ok `{summary.get('autoscaler_target_within_headroom')}`. |"
            ),
            (
                "| Rebalance | "
                f"`{summary.get('autoscaler_rebalance_move_count', 0)}` planner moves, "
                f"`{summary.get('autoscaler_rebalance_batches', 0)}` planner batches, "
                f"`{summary.get('operator_rebalance_move_count', 0)}` operator moves. |"
            ),
            (
                "| Operator | "
                f"phase `{summary.get('operator_status_phase', 'missing')}`, "
                f"replicas `{summary.get('operator_replicas', 0)}`, "
                f"controller replicas `{summary.get('operator_controller_replicas', 0)}`, "
                f"leader election `{summary.get('operator_leader_election')}`, "
                f"conditions `{', '.join(summary.get('operator_conditions_true', []))}`. |"
            ),
            (
                "| Runtime safety | "
                f"control plane ok `{summary.get('control_plane_ok')}`, "
                f"HTTP primary-loss recall `{summary.get('distributed_http_recalled_after_primary_loss')}`, "
                f"active-active convergence `{_fmt(summary.get('active_active_convergence_rate'))}`. |"
            ),
            (
                "| 100M envelope | "
                f"valid `{summary.get('capacity_valid_plan')}`, "
                f"nodes `{summary.get('capacity_node_count', 0)}`, "
                f"zones `{summary.get('capacity_zones', 0)}`, "
                f"replication `{summary.get('capacity_replication_factor', 0)}`, "
                f"zone spread `{_fmt(summary.get('capacity_zone_spread_rate'))}`. |"
            ),
            "",
            "## Production Boundary",
            "",
            "This report strengthens the cluster-scale foundation. Real 10M/50M/100M production latency, recall, and cost claims still require service-backed remote artifacts from the strict production-evidence gate.",
            "",
        ]
    )


def _checks(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    operator_conditions = set(rows["operator"].get("status_conditions_true", []) or [])
    return [
        _check("planner_node_loss_availability", rows["planner"].get("node_loss_min_availability"), 1.0, ">="),
        _check("planner_zone_loss_availability", rows["planner"].get("zone_loss_min_availability"), 1.0, ">="),
        _check("planner_replication_factor", rows["planner"].get("replication_factor"), 2, ">="),
        _check("planner_statefulset_manifest", rows["planner"].get("kubernetes_manifest_kind"), "StatefulSet", "=="),
        _check("autoscaler_has_scale_action", rows["autoscaler"].get("has_scale_action"), True, "is"),
        _check("autoscaler_target_within_headroom", rows["autoscaler"].get("target_within_headroom"), True, "is"),
        _check("autoscaler_required_nodes", rows["autoscaler"].get("required_nodes"), 50, ">="),
        _check("autoscaler_rebalance_ready", rows["autoscaler"].get("rebalance_status"), "ready", "=="),
        _check("autoscaler_rebalance_full_plan", rows["autoscaler"].get("rebalance_full_plan"), True, "is"),
        _check("autoscaler_rebalance_batches", rows["autoscaler"].get("rebalance_batches"), 1, ">="),
        _check("autoscaler_rebalance_move_count", rows["autoscaler"].get("rebalance_move_count"), 1, ">="),
        _check("autoscaler_batches_checkpointed", rows["autoscaler"].get("rebalance_all_batches_checkpointed"), True, "is"),
        _check("autoscaler_batches_repaired", rows["autoscaler"].get("rebalance_all_batches_repaired"), True, "is"),
        _check("autoscaler_batches_validated", rows["autoscaler"].get("rebalance_all_batches_validated"), True, "is"),
        _check("control_plane_ok", rows["control_plane"].get("ok"), True, "is"),
        _check("control_plane_stale_leader_blocked", rows["control_plane"].get("stale_leader_blocked"), True, "is"),
        _check("control_plane_stale_revision_blocked", rows["control_plane"].get("stale_revision_blocked"), True, "is"),
        _check("control_plane_minority_commit_blocked", rows["control_plane"].get("minority_commit_blocked"), True, "is"),
        _check("operator_status_ready", rows["operator"].get("status_ready"), True, "is"),
        _check("operator_phase_ready", rows["operator"].get("status_phase"), "Ready", "=="),
        _check("operator_has_service", rows["operator"].get("has_service"), True, "is"),
        _check("operator_has_statefulset", rows["operator"].get("has_statefulset"), True, "is"),
        _check("operator_has_hpa", rows["operator"].get("has_hpa"), True, "is"),
        _check("operator_has_repair_cronjob", rows["operator"].get("has_repair_cronjob"), True, "is"),
        _check("operator_has_memory_os_cronjob", rows["operator"].get("has_memory_os_cronjob"), True, "is"),
        _check("operator_controller_redundancy", rows["operator"].get("operator_replicas"), 2, ">="),
        _check("operator_leader_election", rows["operator"].get("operator_leader_election"), True, "is"),
        _check("operator_lease_rbac", rows["operator"].get("operator_lease_rbac"), True, "is"),
        _check("operator_cross_node_anti_affinity", rows["operator"].get("operator_cross_node_anti_affinity"), True, "is"),
        _check("operator_replicas_match_capacity", rows["operator"].get("statefulset_replicas"), rows["operator"].get("capacity_required_replicas"), "=="),
        _check("operator_capacity_within_headroom", rows["operator"].get("status_capacity_within_headroom"), True, "is"),
        _check("operator_rebalance_ready", rows["operator"].get("status_rebalance_ready"), True, "is"),
        _check("operator_rebalance_full_plan", rows["operator"].get("status_rebalance_full_plan"), True, "is"),
        _check("operator_rebalance_batches", rows["operator"].get("status_rebalance_batches"), 1, ">="),
        _check("operator_expected_conditions", EXPECTED_OPERATOR_CONDITIONS.issubset(operator_conditions), True, "is"),
        _check("operator_memory_os_ready", rows["operator"].get("status_memory_os_ready"), True, "is"),
        _check("operator_memory_os_blocks_missing_redis", rows["operator"].get("memory_os_blocks_missing_redis"), True, "is"),
        _check("distributed_http_primary_loss_recall", rows["distributed_http"].get("recalled_after_primary_loss"), True, "is"),
        _check("distributed_http_repair_recall", rows["distributed_http"].get("recalled_after_repair"), True, "is"),
        _check("distributed_http_tombstone_suppression", rows["distributed_http"].get("tombstone_suppressed_after_repair"), True, "is"),
        _check("distributed_http_concurrent_query_hit_rate", rows["distributed_http"].get("concurrent_query_hit_rate"), 1.0, ">="),
        _check("active_active_convergence_rate", rows["active_active"].get("convergence_rate"), 1.0, ">="),
        _check("active_active_delete_suppression_rate", rows["active_active"].get("delete_suppression_rate"), 1.0, ">="),
        _check("http_active_active_success_rate", rows["http_active_active"].get("success_rate"), 1.0, ">="),
        _check("field_crdt_commutative_convergence", rows["field_crdt"].get("commutative_convergence"), True, "is"),
        _check("field_crdt_idempotent_remerge", rows["field_crdt"].get("idempotent_remerge"), True, "is"),
        _check("field_crdt_tombstone_wins", rows["field_crdt"].get("tombstone_wins"), True, "is"),
        _check("capacity_valid_plan", rows["capacity_100m"].get("valid_capacity_plan"), True, "is"),
        _check("capacity_target_memories", rows["capacity_100m"].get("target_memories"), 100_000_000, ">="),
        _check("capacity_node_count", rows["capacity_100m"].get("node_count"), 128, ">="),
        _check("capacity_zone_count", rows["capacity_100m"].get("zones"), 8, ">="),
        _check("capacity_replication_factor", rows["capacity_100m"].get("replication_factor"), 3, ">="),
        _check("capacity_distinct_replica_rate", rows["capacity_100m"].get("distinct_replica_rate"), 1.0, ">="),
        _check("capacity_zone_spread_rate", rows["capacity_100m"].get("zone_spread_rate"), 1.0, ">="),
        _check("capacity_node_loss_availability", rows["capacity_100m"].get("node_loss_min_availability"), 1.0, ">="),
        _check("capacity_zone_loss_availability", rows["capacity_100m"].get("zone_loss_min_availability"), 1.0, ">="),
        _check("capacity_recommended_max_replicas", rows["capacity_100m"].get("recommended_autoscaling_max_replicas"), 192, ">="),
    ]


def _check(name: str, value: Any, target: Any, op: str) -> dict[str, Any]:
    passed = False
    if op in {">=", ">", "<=", "<"}:
        try:
            left = float(value)
            right = float(target)
            if op == ">=":
                passed = left >= right
            elif op == ">":
                passed = left > right
            elif op == "<=":
                passed = left <= right
            elif op == "<":
                passed = left < right
        except (TypeError, ValueError):
            passed = False
    elif op == "is":
        passed = value is target
    elif op == "==":
        passed = value == target
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": op,
        "pass": passed,
    }


def _check_row(check: dict[str, Any]) -> str:
    status = "pass" if check.get("pass") else "watch"
    target = f"{check.get('op')} {check.get('target')}"
    return (
        f"| {check.get('name')} | `{status}` | "
        f"`{_fmt(check.get('value'))}` | `{target}` |"
    )


def _engine_row(payload: dict[str, Any], engine: str) -> dict[str, Any]:
    for row in payload.get("results", []):
        if isinstance(row, dict) and row.get("engine") == engine:
            return row
    return {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _generated_at(root: Path) -> str:
    value = os.getenv("WAVEMIND_BENCHMARK_GENERATED_AT")
    if value:
        return value
    source = _load_json(root / SOURCE_FILE)
    if source.get("generated_at"):
        return str(source["generated_at"])
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str:
    value = os.getenv("GITHUB_SHA") or os.getenv("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value[:12]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/cluster_autoscale_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/CLUSTER_AUTOSCALE.md"),
    )
    args = parser.parse_args()
    payload = build_cluster_autoscale_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_cluster_autoscale_markdown(payload),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
