from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.scale_readiness_benchmark import run_sustained_http_cluster_workload
from wavemind import ClusterNode, HTTPNamespaceShardClient


def _node_spec_from_mapping(item: dict[str, Any]) -> tuple[str, str]:
    node_id = str(item.get("id") or item.get("name") or "").strip()
    address = str(item.get("url") or item.get("address") or "").strip()
    if not node_id or not address:
        raise ValueError("node manifest entries require id and url/address")
    return node_id, address


def load_node_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes_payload = payload.get("nodes")
    if not isinstance(nodes_payload, list) or not nodes_payload:
        raise ValueError("nodes-file must contain a non-empty nodes array")

    node_specs: list[str] = []
    zone_specs: list[str] = []
    for item in nodes_payload:
        if not isinstance(item, dict):
            raise ValueError("nodes-file nodes must be objects")
        node_id, address = _node_spec_from_mapping(item)
        node_specs.append(f"{node_id}={address}")
        zone = str(item.get("zone") or item.get("region") or "").strip()
        if zone:
            zone_specs.append(f"{node_id}={zone}")

    return {
        "schema": payload.get("schema", "wavemind.external_http_cluster.v1"),
        "node_specs": node_specs,
        "zone_specs": zone_specs,
        "deployment_id": payload.get("deployment_id"),
        "environment": payload.get("environment"),
        "source": payload.get("source"),
    }


def parse_node_specs(
    specs: list[str] | None,
    zones: list[str] | None = None,
) -> list[ClusterNode]:
    specs = specs or []
    if not specs:
        raise ValueError("at least one --node is required")
    zone_by_id: dict[str, str] = {}
    for zone_spec in zones or []:
        if "=" not in zone_spec:
            raise ValueError(f"--zone must use id=zone format, got {zone_spec!r}")
        node_id, zone = zone_spec.split("=", 1)
        if not node_id or not zone:
            raise ValueError(f"--zone must use id=zone format, got {zone_spec!r}")
        zone_by_id[node_id] = zone

    nodes: list[ClusterNode] = []
    seen: set[str] = set()
    for index, spec in enumerate(specs):
        if "=" in spec:
            node_id, address = spec.split("=", 1)
        else:
            node_id, address = f"node-{index:03d}", spec
        node_id = node_id.strip()
        address = address.strip()
        if not node_id or not address:
            raise ValueError(f"--node must use id=url or url format, got {spec!r}")
        if node_id in seen:
            raise ValueError(f"duplicate node id: {node_id}")
        seen.add(node_id)
        if not address.startswith(("http://", "https://")):
            raise ValueError(f"node address must start with http:// or https://, got {address!r}")
        nodes.append(
            ClusterNode(
                id=node_id,
                address=address.rstrip("/"),
                zone=zone_by_id.get(node_id, f"zone-{index % 3}"),
            )
        )
    return nodes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a sustained mixed workload against real WaveMind HTTP API nodes. "
            "The benchmark performs quorum writes, normal queries, simulated node "
            "failover queries, missing-replica repair, replicated forget, and "
            "delete-suppression checks."
        )
    )
    parser.add_argument(
        "--node",
        action="append",
        default=[],
        help="WaveMind API node as id=url or url. Repeat for every cluster node.",
    )
    parser.add_argument(
        "--nodes-file",
        type=Path,
        default=None,
        help="JSON node manifest with nodes[].id/url/zone for repeatable service runs.",
    )
    parser.add_argument(
        "--zone",
        action="append",
        default=[],
        help="Optional node zone as id=zone. Repeat as needed.",
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--replication-factor", type=int, default=3)
    parser.add_argument("--write-quorum", type=int, default=None)
    parser.add_argument("--read-quorum", type=int, default=1)
    parser.add_argument(
        "--read-fanout",
        type=int,
        default=None,
        help="Number of replicas queried per read. Defaults to all replicas.",
    )
    parser.add_argument("--namespace-prefix", default=None)
    parser.add_argument("--deployment-id", default=None)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--namespace-count", type=int, default=32)
    parser.add_argument("--memories-per-namespace", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-failover-hit-rate", type=float, default=0.95)
    parser.add_argument("--p99-slo-ms", type=float, default=1000.0)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/http_cluster_load_results.json"),
    )
    return parser


def run_from_args(args: argparse.Namespace) -> dict[str, object]:
    node_specs = list(args.node or [])
    zone_specs = list(args.zone or [])
    manifest: dict[str, Any] = {}
    if args.nodes_file:
        manifest = load_node_manifest(args.nodes_file)
        node_specs.extend(manifest["node_specs"])
        zone_specs.extend(manifest["zone_specs"])

    nodes = parse_node_specs(node_specs, zone_specs)
    if args.replication_factor > len(nodes):
        raise ValueError("replication_factor cannot exceed the number of nodes")
    namespace_prefix = args.namespace_prefix or f"tenant:http-load:{int(time.time())}"
    deployment_id = args.deployment_id or manifest.get("deployment_id")
    environment = args.environment or manifest.get("environment")
    source = args.source or manifest.get("source") or "manual"
    result = run_sustained_http_cluster_workload(
        nodes,
        client=HTTPNamespaceShardClient(
            api_key=args.api_key,
            timeout=args.timeout,
            trust_env=False,
        ),
        engine="WaveMind external HTTP cluster load",
        namespace_prefix=namespace_prefix,
        namespace_count=args.namespace_count,
        memories_per_namespace=args.memories_per_namespace,
        replication_factor=args.replication_factor,
        write_quorum=args.write_quorum,
        read_quorum=args.read_quorum,
        read_fanout=args.read_fanout,
        max_workers=args.workers,
    )
    result["slo_min_success_rate"] = args.min_success_rate
    result["slo_min_failover_hit_rate"] = args.min_failover_hit_rate
    result["slo_p99_ms"] = args.p99_slo_ms
    result["slo_pass"] = (
        float(result["success_rate"]) >= args.min_success_rate
        and float(result["failover_hit_rate"]) >= args.min_failover_hit_rate
        and float(result["p99_operation_ms"]) <= args.p99_slo_ms
    )
    return {
        "scenario": {
            "name": "http_cluster_load",
            "node_count": len(nodes),
            "node_ids": [node.id for node in nodes],
            "zones": sorted({node.zone for node in nodes}),
            "replication_factor": args.replication_factor,
            "write_quorum": args.write_quorum
            if args.write_quorum is not None
            else args.replication_factor // 2 + 1,
            "read_quorum": args.read_quorum,
            "read_fanout": args.read_fanout or args.replication_factor,
            "namespace_prefix": namespace_prefix,
            "namespace_count": args.namespace_count,
            "memories_per_namespace": args.memories_per_namespace,
            "workers": args.workers,
            "deployment_id": deployment_id,
            "environment": environment,
            "source": source,
            "description": (
                "External WaveMind API-node sustained cluster benchmark for "
                "production service deployments."
            ),
        },
        "results": [result],
    }


def validate_external_cluster_payload(
    payload: dict[str, Any] | None,
    *,
    min_nodes: int = 4,
    min_namespaces: int = 32,
    min_memories_per_namespace: int = 8,
    min_success_rate: float = 1.0,
    min_failover_hit_rate: float = 0.95,
    p99_slo_ms: float = 1000.0,
) -> dict[str, Any]:
    if not payload:
        return {
            "status": "action_required",
            "evidence": "no checked-in external HTTP cluster load result",
            "next_step": "Run external-http-cluster-load against real API nodes and upload or commit the resulting artifact.",
            "issues": ["missing artifact"],
        }

    scenario = payload.get("scenario", {})
    results = [
        result
        for result in payload.get("results", [])
        if result.get("engine") == "WaveMind external HTTP cluster load"
    ]
    result = results[0] if results else {}
    issues: list[str] = []

    def require(condition: bool, issue: str) -> None:
        if not condition:
            issues.append(issue)

    require(scenario.get("name") == "http_cluster_load", "scenario name must be http_cluster_load")
    require(int(scenario.get("node_count", 0)) >= min_nodes, f"node_count must be >= {min_nodes}")
    require(bool(scenario.get("deployment_id")), "deployment_id is required")
    require(bool(scenario.get("environment")), "environment is required")
    require(str(scenario.get("source") or "").lower() not in {"fixture", "sample"}, "source cannot be fixture/sample")
    require(int(scenario.get("namespace_count", 0)) >= min_namespaces, f"namespace_count must be >= {min_namespaces}")
    require(
        int(scenario.get("memories_per_namespace", 0)) >= min_memories_per_namespace,
        f"memories_per_namespace must be >= {min_memories_per_namespace}",
    )
    require(int(scenario.get("replication_factor", 0)) >= 3, "replication_factor must be >= 3")
    require(bool(result), "WaveMind external HTTP cluster load result is required")
    if result:
        require(float(result.get("success_rate", 0.0)) >= min_success_rate, "success_rate below SLO")
        require(float(result.get("write_success_rate", 0.0)) >= min_success_rate, "write_success_rate below SLO")
        require(float(result.get("query_hit_rate", 0.0)) >= min_success_rate, "query_hit_rate below SLO")
        require(
            float(result.get("failover_hit_rate", 0.0)) >= min_failover_hit_rate,
            "failover_hit_rate below SLO",
        )
        require(float(result.get("delete_suppression_rate", 0.0)) >= min_success_rate, "delete_suppression_rate below SLO")
        require(bool(result.get("repair_ok")), "repair_ok must be true")
        require(int(result.get("repair_repaired_total", 0)) >= 1, "repair_repaired_total must be >= 1")
        require(bool(result.get("slo_pass")), "slo_pass must be true")
        require(float(result.get("p99_operation_ms", float("inf"))) <= p99_slo_ms, "p99_operation_ms above SLO")

    status = "pass" if not issues else "fail"
    evidence = (
        f"nodes {scenario.get('node_count')}, "
        f"deployment {scenario.get('deployment_id')}, "
        f"environment {scenario.get('environment')}, "
        f"namespaces {scenario.get('namespace_count')}, "
        f"success {result.get('success_rate')}, "
        f"failover {result.get('failover_hit_rate')}, "
        f"p99 {result.get('p99_operation_ms')} ms"
        if result
        else "invalid external HTTP cluster load artifact"
    )
    return {
        "status": status,
        "evidence": evidence if not issues else f"{evidence}; issues: {', '.join(issues)}",
        "next_step": (
            "Keep the external service-node run current for release candidates."
            if status == "pass"
            else "Regenerate the artifact from a real external cluster run that meets the SLO contract."
        ),
        "issues": issues,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = run_from_args(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = payload["results"][0]
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    print(f"| external HTTP cluster | nodes | {result['nodes']} |")
    print(f"| external HTTP cluster | success_rate | {result['success_rate']:.3f} |")
    print(f"| external HTTP cluster | failover_hit_rate | {result['failover_hit_rate']:.3f} |")
    print(f"| external HTTP cluster | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
    print(f"| external HTTP cluster | repair_repaired_total | {result['repair_repaired_total']} |")
    print(f"| external HTTP cluster | slo_pass | {result['slo_pass']} |")
    print(f"\nWrote {args.output}")
    if args.fail_on_slo and not result["slo_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
