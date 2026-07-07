from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks import http_cluster_load_benchmark as external_runner
from benchmarks.local_http_cluster_smoke import LocalAPINode, start_api_node, stop_api_nodes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start real localhost WaveMind API processes, then run the external "
            "HTTP cluster-load benchmark against their node URLs. This produces "
            "the same artifact shape as a remote service-node run while staying "
            "CI-friendly."
        )
    )
    parser.add_argument("--nodes", type=int, default=4)
    parser.add_argument("--replication-factor", type=int, default=3)
    parser.add_argument("--write-quorum", type=int, default=None)
    parser.add_argument("--read-quorum", type=int, default=1)
    parser.add_argument("--read-fanout", type=int, default=1)
    parser.add_argument("--namespace-prefix", default=None)
    parser.add_argument("--namespace-count", type=int, default=32)
    parser.add_argument("--memories-per-namespace", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-query-size", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--readiness-timeout", type=float, default=20.0)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-failover-hit-rate", type=float, default=0.95)
    parser.add_argument("--p99-slo-ms", type=float, default=1000.0)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument("--deployment-id", default=None)
    parser.add_argument("--environment", default="local-loopback")
    parser.add_argument("--source", default="loopback-api-processes")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/http_cluster_load_results.json"),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.nodes < 2:
        raise ValueError("--nodes must be at least 2")
    if args.replication_factor <= 0:
        raise ValueError("--replication-factor must be positive")
    if args.replication_factor > args.nodes:
        raise ValueError("--replication-factor cannot exceed --nodes")
    if args.read_quorum <= 0:
        raise ValueError("--read-quorum must be positive")
    if args.read_fanout <= 0:
        raise ValueError("--read-fanout must be positive")
    if args.read_fanout < args.read_quorum:
        raise ValueError("--read-fanout cannot be smaller than --read-quorum")
    if args.read_fanout > args.replication_factor:
        raise ValueError("--read-fanout cannot exceed --replication-factor")
    if args.namespace_count <= 0:
        raise ValueError("--namespace-count must be positive")
    if args.memories_per_namespace < 2:
        raise ValueError("--memories-per-namespace must be at least 2")
    if args.workers <= 0:
        raise ValueError("--workers must be positive")
    if args.batch_query_size < 2:
        raise ValueError("--batch-query-size must be at least 2")


def _external_args(args: argparse.Namespace, nodes: list[LocalAPINode]) -> argparse.Namespace:
    deployment_id = args.deployment_id or f"loopback-{int(time.time())}"
    namespace_prefix = args.namespace_prefix or f"tenant:external-loopback:{deployment_id}"
    return argparse.Namespace(
        node=[f"{node.id}={node.address}" for node in nodes],
        nodes_file=None,
        zone=[f"{node.id}={node.zone}" for node in nodes],
        api_key=None,
        timeout=args.timeout,
        replication_factor=args.replication_factor,
        write_quorum=args.write_quorum,
        read_quorum=args.read_quorum,
        read_fanout=args.read_fanout,
        namespace_prefix=namespace_prefix,
        deployment_id=deployment_id,
        environment=args.environment,
        source=args.source,
        namespace_count=args.namespace_count,
        memories_per_namespace=args.memories_per_namespace,
        workers=args.workers,
        batch_query_size=args.batch_query_size,
        min_success_rate=args.min_success_rate,
        min_failover_hit_rate=args.min_failover_hit_rate,
        p99_slo_ms=args.p99_slo_ms,
        fail_on_slo=args.fail_on_slo,
        output=args.output,
    )


def run_from_args(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    started_at = time.time()
    nodes: list[LocalAPINode] = []

    with tempfile.TemporaryDirectory(prefix="wavemind-external-loopback-") as directory:
        root = Path(directory)
        try:
            for index in range(args.nodes):
                nodes.append(
                    start_api_node(
                        root,
                        f"node-{index:03d}",
                        readiness_timeout_seconds=args.readiness_timeout,
                        capture_output=False,
                    )
                )
            payload = external_runner.run_from_args(_external_args(args, nodes))
            scenario = payload["scenario"]
            scenario["started_api_processes"] = len(nodes)
            scenario["loopback_duration_ms"] = (time.time() - started_at) * 1000.0
            scenario["description"] = (
                "External HTTP cluster-load runner executed against real "
                "localhost WaveMind API processes. This proves the service-node "
                "transport, workload contract, SLO validation, repair, failover, "
                "and delete suppression path without requiring remote Kubernetes."
            )
            return payload
        finally:
            stop_api_nodes(nodes)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = run_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = payload["results"][0]
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    print(f"| external loopback HTTP cluster | nodes | {result['nodes']} |")
    print(f"| external loopback HTTP cluster | success_rate | {result['success_rate']:.3f} |")
    print(f"| external loopback HTTP cluster | failover_hit_rate | {result['failover_hit_rate']:.3f} |")
    print(f"| external loopback HTTP cluster | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
    print(f"| external loopback HTTP cluster | repair_repaired_total | {result['repair_repaired_total']} |")
    batch_query = result["batch_query"]
    print(f"| external loopback HTTP cluster | batch_query_success | {batch_query['success']} |")
    print(f"| external loopback HTTP cluster | batch_query_http_requests | {batch_query['individual_http_requests']} -> {batch_query['batch_http_requests']} |")
    print(f"| external loopback HTTP cluster | batch_query_p99_ms | {batch_query['batch_p99_ms']:.2f} |")
    print(f"| external loopback HTTP cluster | slo_pass | {result['slo_pass']} |")
    print(f"\nWrote {args.output}")
    if args.fail_on_slo and not result["slo_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
