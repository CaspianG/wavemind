from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.scale_readiness_benchmark import run_sustained_http_cluster_workload
from wavemind import ClusterNode, HTTPNamespaceShardClient


def parse_node_specs(specs: list[str], zones: list[str] | None = None) -> list[ClusterNode]:
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
        required=True,
        help="WaveMind API node as id=url or url. Repeat for every cluster node.",
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
    nodes = parse_node_specs(args.node, args.zone)
    if args.replication_factor > len(nodes):
        raise ValueError("replication_factor cannot exceed the number of nodes")
    namespace_prefix = args.namespace_prefix or f"tenant:http-load:{int(time.time())}"
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
            "description": (
                "External WaveMind API-node sustained cluster benchmark for "
                "production service deployments."
            ),
        },
        "results": [result],
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
